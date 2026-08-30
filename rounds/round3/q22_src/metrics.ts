// metrics.ts — records delivery results and checks consistency
export class Metrics {
  public deliveries: Array<{ key: string; value: string }> = [];

  recordDelivery(key: string, value: string, expected: string): void {
    this.deliveries.push({ key, value });
    if (value !== expected) {
      throw new Error(`CONSISTENCY VIOLATION: ${key} delivered "${value}" but last write was "${expected}"`);
    }
  }
}
