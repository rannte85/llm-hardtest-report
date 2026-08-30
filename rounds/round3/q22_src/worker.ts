// worker.ts — performs the refresh. The first call fails with transient I/O.
export class Worker {
  private callCount = 0;

  process(payload: { key: string; metaSchema: number }): string {
    this.callCount += 1;
    if (this.callCount === 1) {
      throw new Error(`worker: transient I/O failure while refreshing ${payload.key}`);
    }
    return `refreshed(schema=${payload.metaSchema})`;
  }
}
