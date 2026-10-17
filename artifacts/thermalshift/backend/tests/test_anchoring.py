import json
import sqlite3
from hashlib import sha256

import pytest
from eth_account import Account
from eth_utils import keccak
from fastapi.testclient import TestClient

import main
from anchoring import (
    AnchorNotConfigured,
    AnchorRPCUnavailable,
    SepoliaAnchorService,
)

TEST_PRIVATE_KEY = "0x" + "12" * 32


class FakeSepoliaRPC:
    def __init__(self):
        self.chain_id = 11155111
        self.pending_nonce = 0
        self.gas_price = 1_000_000_000
        self.gas_estimate = 25_000
        self.balance = 1_000_000_000_000_000
        self.latest_block = 100
        self.receipt = None
        self.fail_method = None
        self.transaction_template = None
        self.transactions = {}
        self.sent_raw_transactions = []

    def __call__(self, method, params):
        if method == self.fail_method:
            raise AnchorRPCUnavailable(method)
        if method == "eth_chainId":
            return hex(self.chain_id)
        if method == "eth_getTransactionCount":
            return hex(self.pending_nonce)
        if method == "eth_estimateGas":
            self.transaction_template = params[0]
            return hex(self.gas_estimate)
        if method == "eth_gasPrice":
            return hex(self.gas_price)
        if method == "eth_getBalance":
            return hex(self.balance)
        if method == "eth_sendRawTransaction":
            raw = params[0]
            self.sent_raw_transactions.append(raw)
            digest = keccak(bytes.fromhex(raw.removeprefix("0x"))).hex()
            tx_hash = digest if digest.startswith("0x") else "0x" + digest
            self.transactions[tx_hash.lower()] = {
                "hash": tx_hash,
                "from": self.transaction_template["from"],
                "to": self.transaction_template["to"],
                "input": self.transaction_template["data"],
                "chainId": hex(self.chain_id),
            }
            return tx_hash
        if method == "eth_getTransactionByHash":
            return self.transactions.get(params[0].lower())
        if method == "eth_getTransactionReceipt":
            return self.receipt
        if method == "eth_blockNumber":
            return hex(self.latest_block)
        raise AssertionError(f"Unexpected JSON-RPC method: {method}")


def make_service(tmp_path, fake_rpc, confirmations=2):
    return SepoliaAnchorService(
        rpc_url="https://rpc.invalid",
        private_key=TEST_PRIVATE_KEY,
        enabled=True,
        db_path=tmp_path / "anchors.sqlite3",
        required_confirmations=confirmations,
        rpc_call=fake_rpc,
    )


def count_anchor_rows(database_path):
    with sqlite3.connect(database_path) as connection:
        return connection.execute("SELECT COUNT(*) FROM report_anchors").fetchone()[0]


def test_anchor_is_idempotent_and_waits_for_required_confirmations(tmp_path):
    rpc = FakeSepoliaRPC()
    service = make_service(tmp_path, rpc, confirmations=2)
    report_hash = sha256(b"canonical report").hexdigest()

    first = service.anchor_report(report_hash)
    duplicate = service.anchor_report(report_hash)

    assert first["status"] == "pending"
    assert first["transaction_hash"] == duplicate["transaction_hash"]
    assert first["destination_address"] == Account.from_key(TEST_PRIVATE_KEY).address
    assert first["report_hash"] == report_hash
    assert first["network"] == "Ethereum Sepolia"
    assert first["confirmations"] == 0
    assert len(rpc.sent_raw_transactions) == 2
    assert rpc.sent_raw_transactions[0] == rpc.sent_raw_transactions[1]
    assert count_anchor_rows(service.db_path) == 1

    rpc.receipt = {"status": "0x1", "blockNumber": "0x64"}
    one_confirmation = service.verify_anchor(first["transaction_hash"], report_hash)
    assert one_confirmation["status"] == "pending"
    assert one_confirmation["valid"] is None
    assert one_confirmation["confirmations"] == 1

    rpc.latest_block = 101
    verified = service.verify_anchor(first["transaction_hash"], report_hash)
    assert verified["status"] == "confirmed"
    assert verified["valid"] is True
    assert verified["report_matches"] is True
    assert verified["on_chain_transaction_matches"] is True
    assert verified["confirmations"] == 2


def test_anchor_verification_detects_changed_report_and_transaction_data(tmp_path):
    rpc = FakeSepoliaRPC()
    service = make_service(tmp_path, rpc, confirmations=1)
    report_hash = sha256(b"canonical report").hexdigest()
    record = service.anchor_report(report_hash)
    rpc.receipt = {"status": "0x1", "blockNumber": "0x64"}

    changed_report = service.verify_anchor(
        record["transaction_hash"],
        sha256(b"altered report").hexdigest(),
    )
    assert changed_report["valid"] is False
    assert changed_report["report_matches"] is False

    rpc.transactions[record["transaction_hash"]]["input"] = "0x" + "f" * 64
    changed_transaction = service.verify_anchor(
        record["transaction_hash"],
        report_hash,
    )
    assert changed_transaction["valid"] is False
    assert changed_transaction["on_chain_transaction_matches"] is False
    assert changed_transaction["status"] == "mismatch"


def test_failed_on_chain_receipt_is_never_reported_as_valid(tmp_path):
    rpc = FakeSepoliaRPC()
    service = make_service(tmp_path, rpc, confirmations=1)
    report_hash = sha256(b"canonical report").hexdigest()
    record = service.anchor_report(report_hash)
    rpc.receipt = {"status": "0x0", "blockNumber": "0x64"}

    verification = service.verify_anchor(record["transaction_hash"], report_hash)

    assert verification["status"] == "failed"
    assert verification["valid"] is False
    assert verification["on_chain_transaction_matches"] is True


def test_rpc_submission_failure_is_not_claimed_as_confirmed_and_can_retry(tmp_path):
    rpc = FakeSepoliaRPC()
    rpc.fail_method = "eth_sendRawTransaction"
    service = make_service(tmp_path, rpc)
    report_hash = sha256(b"canonical report").hexdigest()

    unknown = service.anchor_report(report_hash)
    assert unknown["status"] == "submission_unknown"
    assert unknown["confirmations"] == 0
    assert unknown["last_error"]
    assert count_anchor_rows(service.db_path) == 1

    rpc.fail_method = "eth_getTransactionByHash"
    uncertain_verification = service.verify_anchor(
        unknown["transaction_hash"],
        report_hash,
    )
    assert uncertain_verification["valid"] is None
    assert uncertain_verification["verification_error"]

    rpc.fail_method = None
    retried = service.anchor_report(report_hash)
    assert retried["transaction_hash"] == unknown["transaction_hash"]
    assert retried["status"] == "pending"
    assert count_anchor_rows(service.db_path) == 1


def test_wrong_rpc_network_is_rejected_before_creating_an_anchor(tmp_path):
    rpc = FakeSepoliaRPC()
    rpc.chain_id = 1
    service = make_service(tmp_path, rpc)

    with pytest.raises(AnchorNotConfigured, match="not connected to Ethereum Sepolia"):
        service.anchor_report(sha256(b"canonical report").hexdigest())

    assert count_anchor_rows(service.db_path) == 0


def test_status_reports_missing_configuration_without_exposing_secrets(tmp_path):
    service = SepoliaAnchorService(
        enabled=False,
        db_path=tmp_path / "anchors.sqlite3",
    )

    status = service.status()

    assert status["network"] == "Ethereum Sepolia"
    assert status["chain_id"] == 11155111
    assert status["ready"] is False
    assert status["write_enabled"] is False
    assert "SEPOLIA_RPC_URL" in status["missing_configuration"]
    assert "SEPOLIA_PRIVATE_KEY" in status["missing_configuration"]
    assert "THERMALSHIFT_ANCHOR_ENABLED=true" in status["missing_configuration"]
    assert "private_key" not in status
    assert TEST_PRIVATE_KEY not in json.dumps(status)


def test_anchor_service_is_disabled_by_default(tmp_path, monkeypatch):
    monkeypatch.delenv("THERMALSHIFT_ANCHOR_ENABLED", raising=False)
    monkeypatch.delenv("SEPOLIA_RPC_URL", raising=False)
    monkeypatch.delenv("SEPOLIA_PRIVATE_KEY", raising=False)

    status = SepoliaAnchorService(
        db_path=tmp_path / "anchors.sqlite3",
    ).status()

    assert status["enabled"] is False
    assert status["write_enabled"] is False
    assert status["ready"] is False
    assert "THERMALSHIFT_ANCHOR_ENABLED=true" in status["missing_configuration"]


def test_api_rejects_altered_report_hash_before_attempting_submission(monkeypatch):
    client = TestClient(main.app)
    scenario = main.demo_scenario()
    optimized = client.post(
        "/api/optimize",
        json={"scenario": scenario.model_dump()},
    )
    assert optimized.status_code == 200
    full_report = optimized.json()

    altered = {
        **full_report,
        "scenario": "changed after report hashing",
    }
    response = client.post(
        "/api/anchor",
        json={
            "report": altered,
            "report_hash": full_report["evidence"]["report_hash"],
        },
    )

    assert response.status_code == 409
    assert "does not match" in response.json()["detail"]


def test_api_reports_anchor_setup_requirements_without_live_network():
    client = TestClient(main.app)

    status = client.get("/api/anchor/status")

    assert status.status_code == 200
    assert status.json()["network"] == "Ethereum Sepolia"
    assert status.json()["ready"] is False
    assert status.json()["write_enabled"] is False


def test_anchor_lookup_and_verification_routes_remain_available(tmp_path, monkeypatch):
    rpc = FakeSepoliaRPC()
    service = make_service(tmp_path, rpc)
    report = {"scenario": "test fixture"}
    report_hash = main.canonical_report_hash(report)
    record = service.anchor_report(report_hash)
    monkeypatch.setattr(main, "anchor_service", service)
    client = TestClient(main.app)

    lookup = client.get(f"/api/anchor/report/{report_hash}")
    verification = client.post(
        "/api/anchor/verify",
        json={"report": report, "transaction_hash": record["transaction_hash"]},
    )

    assert lookup.status_code == 200
    assert lookup.json()["transaction_hash"] == record["transaction_hash"]
    assert verification.status_code == 200
    assert verification.json()["on_chain_transaction_matches"] is True


def test_api_anchor_route_is_disabled_without_configuration():
    client = TestClient(main.app)
    scenario = main.demo_scenario()
    optimized = client.post(
        "/api/optimize",
        json={"scenario": scenario.model_dump()},
    )
    report = optimized.json()
    payload = {
        key: value
        for key, value in report.items()
        if key != "evidence"
    }

    response = client.post(
        "/api/anchor",
        json={
            "report": report,
            "report_hash": report["evidence"]["report_hash"],
        },
    )

    assert response.status_code == 503
    assert response.json()["detail"] == (
        "Public anchoring writes are disabled; status and verification remain available."
    )
    assert main.canonical_report_hash(payload) == report["evidence"]["report_hash"]


def test_public_anchor_write_is_disabled_even_when_server_is_configured(
    tmp_path, monkeypatch
):
    rpc = FakeSepoliaRPC()
    service = make_service(tmp_path, rpc)
    monkeypatch.setattr(main, "anchor_service", service)
    status = service.status()
    assert status["ready"] is True
    assert status["write_enabled"] is False
    assert TEST_PRIVATE_KEY not in json.dumps(status)
    assert "rpc.invalid" not in json.dumps(status)
    client = TestClient(main.app)
    report = {"scenario": "caller supplied"}
    report_hash = main.canonical_report_hash(report)

    response = client.post(
        "/api/anchor",
        json={"report": report, "report_hash": report_hash},
    )

    assert response.status_code == 503
    assert response.json()["detail"] == (
        "Public anchoring writes are disabled; status and verification remain available."
    )
    assert TEST_PRIVATE_KEY not in response.text
    assert "rpc.invalid" not in response.text
    assert rpc.sent_raw_transactions == []
    assert not service.db_path.exists()
