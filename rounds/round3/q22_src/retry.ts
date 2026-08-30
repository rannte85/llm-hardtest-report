// retry.ts — retries failed refreshes and commits them later
import { Cache } from "./cache";
import { Worker } from "./worker";

interface PendingRetry { key: string; payload: { key: string; metaSchema: number }; genSnapshot: number; }
interface PendingCommit { key: string; result: string; genSnapshot: number; }

export class RetryQueue {
  private retries: PendingRetry[] = [];
  private commits: PendingCommit[] = [];

  scheduleRetry(key: string, payload: { key: string; metaSchema: number }, genSnapshot: number): void {
    this.retries.push({ key, payload, genSnapshot });
  }

  commitLater(key: string, result: string, genSnapshot: number): void {
    this.commits.push({ key, result, genSnapshot });
  }

  flush(cache: Cache, worker: Worker): void {
    for (const r of this.retries) {
      const result = worker.process(r.payload); // second attempt; transient failure is gone
      cache.commitRefresh(r.key, result, r.genSnapshot);
    }
    this.retries.length = 0;
    for (const c of this.commits) {
      cache.commitRefresh(c.key, c.result, c.genSnapshot);
    }
    this.commits.length = 0;
  }
}
