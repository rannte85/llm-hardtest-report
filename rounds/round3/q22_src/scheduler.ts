// scheduler.ts — tick-based deterministic event queue:
//   t1 read (cache hit + refresh) -> t2 first worker attempt -> t3 write -> t4 retry/commit
import { Cache } from "./cache";
import { Worker } from "./worker";
import { RetryQueue } from "./retry";

export class Scheduler {
  private pendingCallbacks: Array<() => void> = [];

  constructor(
    private cache: Cache,
    private worker: Worker,
    private retry: RetryQueue,
  ) {}

  submitRead(key: string, onDeliver: (v: string) => void): void {
    const entry = this.cache.lookup(key);
    if (entry !== undefined) {
      // stale-while-revalidate: schedule cached delivery plus background refresh
      const genSnapshot = entry.generation;
      const refreshPayload = { key, metaSchema: entry.metaSchema };
      this.dispatchRefresh(key, refreshPayload, genSnapshot);
      this.pendingCallbacks.push(() => onDeliver(this.cache.lookup(key)!.value));
      return;
    }
    // Cache-miss path; not reached in this scenario.
    this.worker.process({ key, metaSchema: 0 });
  }

  submitWrite(key: string, value: string, metaSchema: number): void {
    this.cache.update(key, value, metaSchema);
  }

  private dispatchRefresh(key: string, payload: { key: string; metaSchema: number }, genSnapshot: number): void {
    try {
      const result = this.worker.process(payload);
      this.retry.commitLater(key, result, genSnapshot); // commit on the next tick
    } catch (e) {
      this.retry.scheduleRetry(key, payload, genSnapshot);
    }
  }

  drain(): void {
    this.retry.flush(this.cache, this.worker);
    for (const cb of this.pendingCallbacks) cb();
    this.pendingCallbacks.length = 0;
  }
}
