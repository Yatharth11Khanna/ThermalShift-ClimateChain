"""Server-side, idempotent report-hash anchoring on Ethereum Sepolia."""

import json
import os
import re
import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from eth_account import Account

NETWORK_NAME = "Ethereum Sepolia"
CHAIN_ID = 11155111
EXPLORER_TX_URL = "https://sepolia.etherscan.io/tx/"
REPORT_HASH_PATTERN = re.compile(r"^[0-9a-f]{64}$")
TRANSACTION_HASH_PATTERN = re.compile(r"^0x[0-9a-fA-F]{64}$")
DEFAULT_CONFIRMATIONS = 2
DEFAULT_RPC_TIMEOUT_SECONDS = 8
MAX_GAS_LIMIT = 100_000


class AnchorServiceError(Exception):
    """Base class for safe-to-report anchoring errors."""


class AnchorNotConfigured(AnchorServiceError):
    pass


class AnchorNotFound(AnchorServiceError):
    pass


class AnchorRPCUnavailable(AnchorServiceError):
    def __init__(self, method: str):
        super().__init__(f"Sepolia RPC request {method} could not be completed.")
        self.method = method


class AnchorRPCRejected(AnchorServiceError):
    def __init__(self, method: str, code: int | None, message: str):
        super().__init__(f"Sepolia RPC rejected {method}.")
        self.method = method
        self.code = code
        self.message = message


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _hex_int(value, method: str) -> int:
    if not isinstance(value, str) or not re.fullmatch(r"0x[0-9a-fA-F]+", value):
        raise AnchorRPCUnavailable(method)
    return int(value, 16)


def _hex_bytes(value: str) -> str:
    return "0x" + value.removeprefix("0x").lower()


class SepoliaAnchorService:
    """Store canonical hashes and verify their transaction calldata on Sepolia.

    Each transaction is a zero-value self-transfer whose 32-byte calldata is the
    report SHA-256. This requires no deployed contract and can be inspected on
    the public explorer. The private key is read only from the server process
    environment and is never persisted or returned.
    """

    def __init__(
        self,
        *,
        rpc_url: str | None = None,
        private_key: str | None = None,
        enabled: bool | None = None,
        db_path: str | Path | None = None,
        required_confirmations: int | None = None,
        rpc_timeout_seconds: int = DEFAULT_RPC_TIMEOUT_SECONDS,
        rpc_call=None,
    ):
        self.rpc_url = (
            rpc_url if rpc_url is not None else os.environ.get("SEPOLIA_RPC_URL", "")
        ).strip()
        self.private_key = (
            private_key
            if private_key is not None
            else os.environ.get("SEPOLIA_PRIVATE_KEY", "")
        ).strip()
        if enabled is None:
            enabled = os.environ.get("THERMALSHIFT_ANCHOR_ENABLED", "").lower() in {
                "1",
                "true",
                "yes",
            }
        self.enabled = bool(enabled)
        if required_confirmations is None:
            raw_confirmations = os.environ.get(
                "THERMALSHIFT_ANCHOR_CONFIRMATIONS", str(DEFAULT_CONFIRMATIONS)
            )
            try:
                required_confirmations = int(raw_confirmations)
            except (TypeError, ValueError):
                required_confirmations = DEFAULT_CONFIRMATIONS
        if not 1 <= required_confirmations <= 64:
            required_confirmations = DEFAULT_CONFIRMATIONS
        self.required_confirmations = required_confirmations
        self.rpc_timeout_seconds = rpc_timeout_seconds
        configured_db_path = db_path or os.environ.get("THERMALSHIFT_ANCHOR_DB_PATH")
        self.db_path = Path(
            configured_db_path
            or Path(__file__).with_name("thermalshift_anchors.sqlite3")
        )
        self._rpc_override = rpc_call
        self._lock = threading.RLock()

    def _connect(self):
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(str(self.db_path), timeout=15)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS report_anchors (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                network TEXT NOT NULL,
                chain_id INTEGER NOT NULL,
                report_hash TEXT NOT NULL UNIQUE,
                transaction_hash TEXT NOT NULL UNIQUE,
                signer_address TEXT NOT NULL,
                destination_address TEXT NOT NULL,
                nonce INTEGER NOT NULL,
                raw_transaction TEXT NOT NULL,
                status TEXT NOT NULL,
                confirmations INTEGER NOT NULL DEFAULT 0,
                confirmations_required INTEGER NOT NULL,
                block_number INTEGER,
                last_error TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """
        )
        return connection

    def _rpc(self, method: str, params: list):
        if self._rpc_override is not None:
            return self._rpc_override(method, params)
        if not self.rpc_url:
            raise AnchorNotConfigured("SEPOLIA_RPC_URL is not configured.")
        body = json.dumps(
            {"jsonrpc": "2.0", "id": 1, "method": method, "params": params}
        ).encode()
        request = Request(
            self.rpc_url,
            data=body,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urlopen(request, timeout=self.rpc_timeout_seconds) as response:
                payload = json.loads(response.read())
        except (HTTPError, URLError, TimeoutError, OSError, json.JSONDecodeError) as exc:
            raise AnchorRPCUnavailable(method) from exc
        if not isinstance(payload, dict):
            raise AnchorRPCUnavailable(method)
        if payload.get("error"):
            error = payload["error"]
            code = error.get("code") if isinstance(error, dict) else None
            message = error.get("message", "") if isinstance(error, dict) else ""
            raise AnchorRPCRejected(method, code, str(message))
        if "result" not in payload:
            raise AnchorRPCUnavailable(method)
        return payload["result"]

    def _account(self):
        missing = []
        if not self.enabled:
            missing.append("THERMALSHIFT_ANCHOR_ENABLED=true")
        if not self.rpc_url:
            missing.append("SEPOLIA_RPC_URL")
        if not self.private_key:
            missing.append("SEPOLIA_PRIVATE_KEY")
        if missing:
            raise AnchorNotConfigured(
                "Sepolia anchoring is not ready. Configure: " + ", ".join(missing)
            )
        try:
            return Account.from_key(self.private_key)
        except (TypeError, ValueError) as exc:
            raise AnchorNotConfigured(
                "SEPOLIA_PRIVATE_KEY is not a valid private key."
            ) from exc

    def status(self) -> dict:
        missing = []
        if not self.enabled:
            missing.append("THERMALSHIFT_ANCHOR_ENABLED=true")
        if not self.rpc_url:
            missing.append("SEPOLIA_RPC_URL")
        if not self.private_key:
            missing.append("SEPOLIA_PRIVATE_KEY")

        wallet_address = None
        configuration_error = None
        if self.private_key:
            try:
                wallet_address = Account.from_key(self.private_key).address
            except (TypeError, ValueError):
                configuration_error = "SEPOLIA_PRIVATE_KEY is not a valid private key."
                missing.append("A valid SEPOLIA_PRIVATE_KEY")

        network_available = None
        wallet_balance_wei = None
        rpc_error = None
        if not missing:
            try:
                actual_chain_id = _hex_int(self._rpc("eth_chainId", []), "eth_chainId")
                if actual_chain_id != CHAIN_ID:
                    rpc_error = "The configured RPC endpoint is not connected to Sepolia."
                else:
                    network_available = True
                    balance = _hex_int(
                        self._rpc("eth_getBalance", [wallet_address, "latest"]),
                        "eth_getBalance",
                    )
                    wallet_balance_wei = str(balance)
                    if balance == 0:
                        missing.append("Faucet-funded Sepolia test ETH")
            except (AnchorRPCUnavailable, AnchorRPCRejected, AnchorNotConfigured):
                network_available = False
                rpc_error = "The configured Sepolia RPC endpoint is unavailable."

        return {
            "network": NETWORK_NAME,
            "chain_id": CHAIN_ID,
            "explorer_base_url": "https://sepolia.etherscan.io",
            "enabled": self.enabled,
            "configured": not any(
                item in missing
                for item in (
                    "THERMALSHIFT_ANCHOR_ENABLED=true",
                    "SEPOLIA_RPC_URL",
                    "SEPOLIA_PRIVATE_KEY",
                    "A valid SEPOLIA_PRIVATE_KEY",
                )
            ),
            "ready": not missing and network_available is True,
            "network_available": network_available,
            "wallet_address": wallet_address,
            "wallet_balance_wei": wallet_balance_wei,
            "confirmations_required": self.required_confirmations,
            "missing_configuration": missing,
            "configuration_error": configuration_error,
            "status_error": rpc_error,
            "notice": (
                "Only the report hash is written on-chain. This does not authenticate "
                "inputs or validate the model or claimed savings."
            ),
        }

    def _get_by_report_hash(self, report_hash: str):
        connection = self._connect()
        try:
            row = connection.execute(
                "SELECT * FROM report_anchors WHERE report_hash = ?",
                (report_hash,),
            ).fetchone()
            return dict(row) if row else None
        finally:
            connection.close()

    def _get_by_transaction_hash(self, transaction_hash: str):
        connection = self._connect()
        try:
            row = connection.execute(
                "SELECT * FROM report_anchors WHERE transaction_hash = ?",
                (transaction_hash.lower(),),
            ).fetchone()
            return dict(row) if row else None
        finally:
            connection.close()

    @staticmethod
    def _public_record(record: dict) -> dict:
        return {
            "network": record["network"],
            "chain_id": record["chain_id"],
            "report_hash": record["report_hash"],
            "transaction_hash": record["transaction_hash"],
            "signer_address": record["signer_address"],
            "destination_address": record["destination_address"],
            "status": record["status"],
            "confirmations": record["confirmations"],
            "confirmations_required": record["confirmations_required"],
            "block_number": record["block_number"],
            "explorer_url": EXPLORER_TX_URL + record["transaction_hash"],
            "created_at": record["created_at"],
            "updated_at": record["updated_at"],
            "last_error": record["last_error"],
        }

    def get_by_report_hash(self, report_hash: str) -> dict | None:
        if not REPORT_HASH_PATTERN.fullmatch(report_hash):
            raise ValueError("report_hash must be a lowercase SHA-256 hex digest.")
        record = self._get_by_report_hash(report_hash)
        return self._public_record(record) if record else None

    def _update_record(self, transaction_hash: str, **fields):
        allowed = {
            "status",
            "confirmations",
            "block_number",
            "last_error",
        }
        if not fields or not set(fields).issubset(allowed):
            raise ValueError("Invalid anchor-record update.")
        assignments = ", ".join(f"{name} = ?" for name in fields)
        values = list(fields.values()) + [_utc_now(), transaction_hash.lower()]
        connection = self._connect()
        try:
            connection.execute(
                f"UPDATE report_anchors SET {assignments}, updated_at = ? "
                "WHERE transaction_hash = ?",
                values,
            )
            connection.commit()
        finally:
            connection.close()
        return self._get_by_transaction_hash(transaction_hash)

    def _broadcast(self, record: dict) -> dict:
        raw_transaction = record["raw_transaction"]
        try:
            returned_hash = self._rpc(
                "eth_sendRawTransaction", [raw_transaction]
            )
            if not isinstance(returned_hash, str) or (
                returned_hash.lower() != record["transaction_hash"].lower()
            ):
                record = self._update_record(
                    record["transaction_hash"],
                    status="submission_unknown",
                    last_error="RPC returned an unexpected transaction hash.",
                )
                return record
            record = self._update_record(
                record["transaction_hash"],
                status="submitted",
                last_error=None,
            )
        except AnchorRPCUnavailable:
            record = self._update_record(
                record["transaction_hash"],
                status="submission_unknown",
                last_error=(
                    "Submission response was unavailable; the transaction may have "
                    "reached the network. Verify before retrying."
                ),
            )
        except AnchorRPCRejected as exc:
            if "already known" in exc.message.lower() or "known transaction" in exc.message.lower():
                record = self._update_record(
                    record["transaction_hash"],
                    status="submitted",
                    last_error=None,
                )
            else:
                record = self._update_record(
                    record["transaction_hash"],
                    status="rejected",
                    last_error=f"RPC rejected the transaction (code {exc.code}).",
                )
        return self._refresh_record(record)

    def anchor_report(self, report_hash: str) -> dict:
        if not REPORT_HASH_PATTERN.fullmatch(report_hash):
            raise ValueError("report_hash must be a lowercase SHA-256 hex digest.")
        account = self._account()
        with self._lock:
            connection = self._connect()
            try:
                connection.execute("BEGIN IMMEDIATE")
                existing = connection.execute(
                    "SELECT * FROM report_anchors WHERE report_hash = ?",
                    (report_hash,),
                ).fetchone()
                if existing:
                    record = dict(existing)
                    connection.commit()
                else:
                    actual_chain_id = _hex_int(
                        self._rpc("eth_chainId", []), "eth_chainId"
                    )
                    if actual_chain_id != CHAIN_ID:
                        raise AnchorNotConfigured(
                            "Configured RPC endpoint is not connected to Ethereum Sepolia."
                        )

                    pending_nonce = _hex_int(
                        self._rpc(
                            "eth_getTransactionCount",
                            [account.address, "pending"],
                        ),
                        "eth_getTransactionCount",
                    )
                    reserved = connection.execute(
                        """
                        SELECT MAX(nonce) AS max_nonce
                        FROM report_anchors
                        WHERE chain_id = ? AND signer_address = ?
                        """,
                        (CHAIN_ID, account.address.lower()),
                    ).fetchone()["max_nonce"]
                    nonce = max(pending_nonce, (reserved + 1) if reserved is not None else 0)

                    calldata = bytes.fromhex(report_hash)
                    estimate = _hex_int(
                        self._rpc(
                            "eth_estimateGas",
                            [
                                {
                                    "from": account.address,
                                    "to": account.address,
                                    "value": "0x0",
                                    "data": "0x" + calldata.hex(),
                                }
                            ],
                        ),
                        "eth_estimateGas",
                    )
                    gas_limit = min(
                        MAX_GAS_LIMIT,
                        max(21_000, (estimate * 120 + 99) // 100),
                    )
                    gas_price = _hex_int(
                        self._rpc("eth_gasPrice", []),
                        "eth_gasPrice",
                    )
                    signed = account.sign_transaction(
                        {
                            "chainId": CHAIN_ID,
                            "nonce": nonce,
                            "gas": gas_limit,
                            "gasPrice": gas_price,
                            "to": account.address,
                            "value": 0,
                            "data": calldata,
                        }
                    )
                    transaction_hash = _hex_bytes(signed.hash.hex())
                    raw_transaction = _hex_bytes(signed.raw_transaction.hex())
                    created_at = _utc_now()
                    connection.execute(
                        """
                        INSERT INTO report_anchors (
                            network, chain_id, report_hash, transaction_hash,
                            signer_address, destination_address, nonce,
                            raw_transaction, status, confirmations,
                            confirmations_required, block_number, last_error,
                            created_at, updated_at
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            NETWORK_NAME,
                            CHAIN_ID,
                            report_hash,
                            transaction_hash.lower(),
                            account.address,
                            account.address,
                            nonce,
                            raw_transaction,
                            "prepared",
                            0,
                            self.required_confirmations,
                            None,
                            None,
                            created_at,
                            created_at,
                        ),
                    )
                    connection.commit()
                    record = dict(
                        connection.execute(
                            "SELECT * FROM report_anchors WHERE report_hash = ?",
                            (report_hash,),
                        ).fetchone()
                    )
            except Exception:
                connection.rollback()
                raise
            finally:
                connection.close()

        if record["status"] in {"confirmed", "failed", "mismatch"}:
            return self._public_record(record)
        return self._public_record(self._broadcast(record))

    def _refresh_record(self, record: dict) -> dict:
        transaction_hash = record["transaction_hash"]
        try:
            actual_chain_id = _hex_int(
                self._rpc("eth_chainId", []), "eth_chainId"
            )
            if actual_chain_id != CHAIN_ID:
                return {
                    **self._public_record(record),
                    "on_chain_transaction_matches": None,
                    "verification_error": (
                        "The configured RPC endpoint is not connected to Sepolia."
                    ),
                }
            transaction = self._rpc(
                "eth_getTransactionByHash", [transaction_hash]
            )
        except (AnchorRPCUnavailable, AnchorRPCRejected, AnchorNotConfigured):
            return {
                **self._public_record(record),
                "on_chain_transaction_matches": None,
                "verification_error": "Live Sepolia verification is temporarily unavailable.",
            }

        if transaction is None:
            if record["status"] == "confirmed":
                record = self._update_record(
                    transaction_hash,
                    status="pending",
                    confirmations=0,
                    block_number=None,
                    last_error="The transaction is not currently visible from the configured RPC.",
                )
            return {
                **self._public_record(record),
                "on_chain_transaction_matches": None,
            }

        tx_hash = str(transaction.get("hash", "")).lower()
        sender = str(transaction.get("from", "")).lower()
        destination = str(transaction.get("to", "")).lower()
        input_data = str(transaction.get("input", transaction.get("data", ""))).lower()
        tx_chain_id = transaction.get("chainId")
        chain_matches = (
            tx_chain_id is None or _hex_int(tx_chain_id, "transaction.chainId") == CHAIN_ID
        )
        transaction_matches = (
            tx_hash == transaction_hash.lower()
            and sender == record["signer_address"].lower()
            and destination == record["destination_address"].lower()
            and input_data == "0x" + record["report_hash"]
            and chain_matches
        )
        if not transaction_matches:
            record = self._update_record(
                transaction_hash,
                status="mismatch",
                confirmations=0,
                last_error="On-chain transaction fields do not match the stored anchor.",
            )
            return {
                **self._public_record(record),
                "on_chain_transaction_matches": False,
            }

        try:
            receipt = self._rpc("eth_getTransactionReceipt", [transaction_hash])
        except (AnchorRPCUnavailable, AnchorRPCRejected, AnchorNotConfigured):
            return {
                **self._public_record(record),
                "on_chain_transaction_matches": True,
                "verification_error": "Live Sepolia verification is temporarily unavailable.",
            }
        if receipt is None:
            record = self._update_record(
                transaction_hash,
                status="pending",
                confirmations=0,
                block_number=None,
                last_error=None,
            )
            return {
                **self._public_record(record),
                "on_chain_transaction_matches": True,
            }

        receipt_status = _hex_int(receipt.get("status", ""), "receipt.status")
        block_number = _hex_int(receipt.get("blockNumber", ""), "receipt.blockNumber")
        if receipt_status != 1:
            record = self._update_record(
                transaction_hash,
                status="failed",
                confirmations=0,
                block_number=block_number,
                last_error="The transaction was included but did not succeed.",
            )
            return {
                **self._public_record(record),
                "on_chain_transaction_matches": True,
            }

        try:
            latest_block = _hex_int(
                self._rpc("eth_blockNumber", []), "eth_blockNumber"
            )
        except (AnchorRPCUnavailable, AnchorRPCRejected, AnchorNotConfigured):
            return {
                **self._public_record(record),
                "on_chain_transaction_matches": True,
                "verification_error": "Live Sepolia verification is temporarily unavailable.",
            }
        confirmations = max(0, latest_block - block_number + 1)
        status = (
            "confirmed"
            if confirmations >= record["confirmations_required"]
            else "pending"
        )
        record = self._update_record(
            transaction_hash,
            status=status,
            confirmations=confirmations,
            block_number=block_number,
            last_error=None,
        )
        return {
            **self._public_record(record),
            "on_chain_transaction_matches": True,
        }

    def verify_anchor(self, transaction_hash: str, current_report_hash: str) -> dict:
        if not TRANSACTION_HASH_PATTERN.fullmatch(transaction_hash):
            raise ValueError("transaction_hash must be a 32-byte 0x-prefixed hash.")
        if not REPORT_HASH_PATTERN.fullmatch(current_report_hash):
            raise ValueError("The current report hash is invalid.")
        record = self._get_by_transaction_hash(transaction_hash)
        if record is None:
            raise AnchorNotFound("No local anchor record exists for that transaction.")

        report_matches = current_report_hash == record["report_hash"]
        refreshed = self._refresh_record(record)
        verification_error = refreshed.get("verification_error")
        transaction_matches = refreshed.get("on_chain_transaction_matches")
        confirmed = refreshed["status"] == "confirmed"
        if (
            not report_matches
            or transaction_matches is False
            or refreshed["status"] == "failed"
        ):
            valid = False
        elif verification_error or transaction_matches is not True or not confirmed:
            valid = None
        else:
            valid = True
        return {
            **refreshed,
            "valid": valid,
            "report_matches": report_matches,
            "on_chain_transaction_matches": transaction_matches,
            "verification_error": verification_error,
            "note": (
                "The current report hash, transaction calldata, destination, receipt, "
                "and confirmation count were checked against Sepolia."
                if valid is True
                else (
                    "The supplied report does not match the report hash stored for this anchor."
                    if not report_matches
                    else (
                        "The transaction is not yet confirmed. This is not a confirmed anchor."
                        if not verification_error and not confirmed
                        else (
                            verification_error
                            or "The transaction does not match the stored anchor record."
                        )
                    )
                )
            ),
        }
