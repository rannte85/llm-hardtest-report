// main.ts — deterministic reproduction scenario
import { Cache } from "./cache";
import { Worker } from "./worker";
import { RetryQueue } from "./retry";
import { Scheduler } from "./scheduler";
import { Metrics } from "./metrics";
import { handleRead, handleWrite } from "./request";

const cache = new Cache();
cache.seed("user:42", "v1-result", 1);
const sched = new Scheduler(cache, new Worker(), new RetryQueue());
const metrics = new Metrics();

// t1: read arrives (cache hit; background refresh; first worker attempt fails; retry scheduled)
handleRead(sched, metrics, { key: "user:42", expectedValue: "v2-result" });
// t3: external write arrives and updates the value to v2
handleWrite(sched, "user:42", "v2-result", 2);
// t4: drain queue — run/commit retry, then deliver the read callback
sched.drain(); // <- CONSISTENCY VIOLATION occurs here
