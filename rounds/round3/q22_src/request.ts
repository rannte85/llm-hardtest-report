// request.ts — request entry point
import { Scheduler } from "./scheduler";
import { Metrics } from "./metrics";

export interface UserRequest {
  key: string;
  expectedValue: string; // value expected after the client's latest write; harness-only
}

export function handleRead(sched: Scheduler, metrics: Metrics, req: UserRequest): void {
  sched.submitRead(req.key, (value: string) => {
    metrics.recordDelivery(req.key, value, req.expectedValue);
  });
}

export function handleWrite(sched: Scheduler, key: string, value: string, metaSchema: number): void {
  sched.submitWrite(key, value, metaSchema);
}
