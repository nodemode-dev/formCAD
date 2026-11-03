import type { NodeEdit, NodeRecord, NodeState, TreePage } from './types';

export interface NodeWidgetContext {
  nodeId: string;
  typeId: string;
  host: HTMLElement;
  node(): NodeRecord;
  settings(): Record<string, unknown>;
  persistent(port?: string): unknown;
  edit(change: NodeEdit, opts?: { live?: boolean }): void;
  tree(port: string, page?: number): Promise<TreePage>;
  emit(type: string, detail?: unknown): void;
}

export interface NodeWidget {
  size: { w: number; h: number };
  update(node: NodeRecord, state: NodeState): void;
  dispose?(): void;
}

export type NodeWidgetFactory = (ctx: NodeWidgetContext) => NodeWidget;

const factories = new Map<string, NodeWidgetFactory>();
const watchers = new Set<(kind: string) => void>();

export function registerNodeWidget(kind: string, factory: NodeWidgetFactory): void {
  factories.set(kind, factory);
  for (const fn of watchers) fn(kind);
}

export const widgetFactory = (kind: string): NodeWidgetFactory | undefined => factories.get(kind);

export function onWidgetRegistered(fn: (kind: string) => void): () => void {
  watchers.add(fn);
  return () => { watchers.delete(fn); };
}

const iconTable = new Map<string, string>();

export function registerNodeIcons(map: Record<string, string>): void {
  for (const [k, v] of Object.entries(map)) iconTable.set(k, v);
}

export const nodeIconName = (typeId: string, category: string): string | undefined => iconTable.get(typeId) ?? iconTable.get(category);
