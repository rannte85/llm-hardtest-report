// cache.ts — generation-based invalidation cache
export interface Entry {
  value: string;
  metaSchema: number;
  generation: number; // must increase whenever the value changes
}

export class Cache {
  private entries = new Map<string, Entry>();

  seed(key: string, value: string, metaSchema: number): void {
    this.entries.set(key, { value, metaSchema, generation: 1 });
  }

  lookup(key: string): Entry | undefined {
    return this.entries.get(key);
  }

  // External write path: update both the value and schema.
  update(key: string, value: string, metaSchema: number): void {
    const e = this.entries.get(key);
    if (e === undefined) return;
    e.value = value;
    e.metaSchema = metaSchema;
  }

  // Commit a refresh only when the snapshot generation is still current.
  commitRefresh(key: string, value: string, genSnapshot: number): boolean {
    const e = this.entries.get(key);
    if (e === undefined) return false;
    if (e.generation !== genSnapshot) return false; // concurrent update: discard stale refresh
    e.value = value;
    return true;
  }
}
