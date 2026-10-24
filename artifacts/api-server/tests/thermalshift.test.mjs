import assert from "node:assert/strict";
import { once } from "node:events";
import { request as httpRequest } from "node:http";
import { after, before, test } from "node:test";
import express from "express";
import { handleRequestBodyErrors, jsonBodyParser } from "../src/middleware/json-body.ts";
import thermalShiftRouter from "../src/routes/thermalshift.ts";

const app = express();
app.use(jsonBodyParser);
app.use(express.urlencoded({ extended: true }));
app.use("/api", thermalShiftRouter);
app.use(handleRequestBodyErrors);

let server;
let port;

before(async () => {
  server = app.listen(0, "127.0.0.1");
  await once(server, "listening");
  port = server.address().port;
});

after(async () => {
  await new Promise((resolve, reject) => {
    server.close((error) => (error ? reject(error) : resolve()));
  });
});

function csvAtMaximumSize() {
  const timestamps = Array.from({ length: 24 }, (_, hour) =>
    new Date(Date.UTC(2025, 0, 1, hour)).toISOString(),
  );
  const rows = [
    "hour,tariff_timestamp,baseline_kwh,tariff_per_kwh,grid_emissions_timestamp,grid_kgco2_per_kwh,ambient_heat_gain_c,ignored",
    ...timestamps.map(
      (timestamp, hour) =>
        `${hour},${timestamp},0.5,1.0,${timestamp},0.4,0.1,`,
    ),
  ];
  const withoutPadding = `${rows.join("\r\n")}\r\n`;
  const paddingBytes = 100_000 - Buffer.byteLength(withoutPadding);
  assert.ok(paddingBytes >= 0);
  rows[1] += "x".repeat(paddingBytes);
  const csv = `${rows.join("\r\n")}\r\n`;
  assert.equal(Buffer.byteLength(csv), 100_000);
  return csv;
}

function postJson(path, body) {
  return new Promise((resolve, reject) => {
    const request = httpRequest(
      {
        host: "127.0.0.1",
        port,
        path,
        method: "POST",
        headers: { "content-type": "application/json" },
      },
      (incoming) => {
        let responseBody = "";
        incoming.setEncoding("utf8");
        incoming.on("data", (chunk) => {
          responseBody += chunk;
        });
        incoming.on("end", () => {
          const parsedBody = responseBody ? JSON.parse(responseBody) : null;
          resolve({
            status: incoming.statusCode,
            contentType: incoming.headers["content-type"],
            body: parsedBody,
          });
        });
      },
    );
    request.on("error", reject);
    request.end(JSON.stringify(body));
  });
}

test("anchor proxy rejects public writes without contacting the backend", async () => {
  const originalFetch = globalThis.fetch;
  let upstreamRequests = 0;
  globalThis.fetch = async () => {
    upstreamRequests += 1;
    throw new Error("The disabled anchor route must not contact the backend.");
  };

  try {
    const response = await postJson("/api/anchor", {
      report: { arbitrary: "content" },
    });

    assert.equal(response.status, 503);
    assert.deepEqual(response.body, {
      detail:
        "Public anchoring writes are disabled; status and verification remain available.",
    });
    assert.equal(upstreamRequests, 0);
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test("maximum-size CSV upload passes through the API proxy", async () => {
  const originalFetch = globalThis.fetch;
  let forwardedRequest;
  globalThis.fetch = async (input, init) => {
    forwardedRequest = {
      url: String(input),
      method: init.method,
      body: JSON.parse(init.body),
    };
    return new Response(JSON.stringify({ record_count: 24 }), {
      status: 200,
      headers: { "content-type": "application/json" },
    });
  };

  try {
    const csv = csvAtMaximumSize();
    const response = await postJson("/api/import-csv", {
      csv_text: csv,
      metadata: {
        timezone: "UTC",
        tariff_unit: "USD/kWh",
        tariff_source: "Synthetic proxy test",
        grid_emissions_unit: "kgCO2/kWh",
        grid_emissions_source: "Synthetic proxy test",
      },
      scenario: {},
    });

    assert.equal(response.status, 200);
    assert.equal(response.body.record_count, 24);
    assert.equal(forwardedRequest.url, "http://127.0.0.1:8000/api/import-csv");
    assert.equal(forwardedRequest.method, "POST");
    assert.equal(forwardedRequest.body.csv_text, csv);
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test("scenario comparison passes through the API proxy", async () => {
  const originalFetch = globalThis.fetch;
  let forwardedRequest;
  globalThis.fetch = async (input, init) => {
    forwardedRequest = {
      url: String(input),
      method: init.method,
      body: JSON.parse(init.body),
    };
    return new Response(JSON.stringify({ scenarios: {} }), {
      status: 200,
      headers: { "content-type": "application/json" },
    });
  };

  try {
    const payload = { scenario: { name: "comparison fixture" } };
    const response = await postJson("/api/compare-scenarios", payload);

    assert.equal(response.status, 200);
    assert.equal(forwardedRequest.url, "http://127.0.0.1:8000/api/compare-scenarios");
    assert.equal(forwardedRequest.method, "POST");
    assert.deepEqual(forwardedRequest.body, payload);
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test("request larger than the bounded JSON limit gets a safe 413 response", async () => {
  const originalFetch = globalThis.fetch;
  let upstreamRequests = 0;
  globalThis.fetch = async () => {
    upstreamRequests += 1;
    throw new Error("Oversized requests must not be forwarded.");
  };

  try {
    const response = await postJson("/api/import-csv", {
      csv_text: "x".repeat(300_000),
    });

    assert.equal(response.status, 413);
    assert.match(response.contentType, /^application\/json/);
    assert.deepEqual(response.body, {
      detail: "Request body exceeds the 256 KiB limit.",
    });
    assert.equal(upstreamRequests, 0);
  } finally {
    globalThis.fetch = originalFetch;
  }
});
