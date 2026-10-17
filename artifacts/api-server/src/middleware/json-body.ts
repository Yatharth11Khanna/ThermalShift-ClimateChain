import express, { type ErrorRequestHandler } from "express";

export const JSON_BODY_LIMIT_BYTES = 256 * 1024;
export const jsonBodyParser = express.json({ limit: JSON_BODY_LIMIT_BYTES });

export const handleRequestBodyErrors: ErrorRequestHandler = (
  error,
  _req,
  res,
  next,
) => {
  if (
    error &&
    typeof error === "object" &&
    "type" in error &&
    error.type === "entity.too.large"
  ) {
    res.status(413).json({
      detail: `Request body exceeds the ${JSON_BODY_LIMIT_BYTES / 1024} KiB limit.`,
    });
    return;
  }
  next(error);
};
