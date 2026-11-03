export type GraphEventType =
  | 'open' | 'selection' | 'node-added' | 'node-removed' | 'wire-added' | 'wire-removed'
  | 'edit' | 'solved' | 'view' | 'hover-port' | 'context' | (string & {});

type Handler = (detail: Record<string, unknown>) => void;

class GraphBus {
  private readonly map = new Map<string, Set<Handler>>();

  on(type: GraphEventType, fn: Handler): () => void {
    let set = this.map.get(type);
    if (!set) { set = new Set(); this.map.set(type, set); }
    set.add(fn);
    return () => { set.delete(fn); };
  }

  emit(type: GraphEventType, detail: Record<string, unknown> = {}): void {
    for (const fn of this.map.get(type) ?? []) fn(detail);
    document.dispatchEvent(new CustomEvent('formcad:graph', { detail: { type, ...detail } }));
  }
}

export const graphBus = new GraphBus();
