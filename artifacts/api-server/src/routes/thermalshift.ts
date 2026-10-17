import { Router, type IRouter, type Request, type Response } from "express";

const router: IRouter = Router();
const backendUrl =
  process.env.THERMALSHIFT_API_URL ?? "http://127.0.0.1:8000";

async function forwardToThermalShift(
  req: Request,
  res: Response,
  endpoint: string,
) {
  try {
    const upstream = await fetch(`${backendUrl}/api/${endpoint}`, {
      method: req.method,
      headers:
        req.method === "POST" ? { "Content-Type": "application/json" } : {},
      body: req.method === "POST" ? JSON.stringify(req.body) : undefined,
    });
    const contentType =
      upstream.headers.get("content-type") ?? "application/json";
    const body = await upstream.text();
    res.status(upstream.status).type(contentType).send(body);
  } catch (err) {
    req.log.error({ err, endpoint }, "ThermalShift backend request failed");
    res.status(502).json({
      detail: "ThermalShift optimization service is unavailable.",
    });
  }
}

router.get("/health", (req, res) =>
  forwardToThermalShift(req, res, "health"),
);
router.get("/demo", (req, res) => forwardToThermalShift(req, res, "demo"));
router.post("/optimize", (req, res) =>
  forwardToThermalShift(req, res, "optimize"),
);
router.post("/verify-hash", (req, res) =>
  forwardToThermalShift(req, res, "verify-hash"),
);
router.post("/import-csv", (req, res) =>
  forwardToThermalShift(req, res, "import-csv"),
);
router.get("/anchor/status", (req, res) =>
  forwardToThermalShift(req, res, "anchor/status"),
);
router.get("/anchor/report/:reportHash", (req, res) => {
  const rawReportHash = req.params.reportHash;
  const reportHash = Array.isArray(rawReportHash)
    ? rawReportHash[0]
    : rawReportHash;
  return forwardToThermalShift(
    req,
    res,
    `anchor/report/${encodeURIComponent(reportHash ?? "")}`,
  );
});
router.post("/anchor", (_req, res) =>
  res.status(503).json({
    detail:
      "Public anchoring writes are disabled; status and verification remain available.",
  }),
);
router.post("/anchor/verify", (req, res) =>
  forwardToThermalShift(req, res, "anchor/verify"),
);

export default router;
