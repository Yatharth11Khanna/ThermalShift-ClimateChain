import { Router, type IRouter } from "express";
import healthRouter from "./health";
import thermalShiftRouter from "./thermalshift";

const router: IRouter = Router();

router.use(healthRouter);
router.use(thermalShiftRouter);

export default router;
