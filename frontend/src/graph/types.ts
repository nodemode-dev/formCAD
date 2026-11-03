export type Access = 'item' | 'list' | 'tree';
export type NodeStateName = 'blank' | 'busy' | 'computed' | 'warning' | 'error' | 'disabled';
export type MessageLevel = 'remark' | 'warning' | 'error';
export type ModKey = 'reverse' | 'flatten' | 'graft' | 'simplify' | 'principal' | 'invert';

export interface PortMods {
  reverse?: boolean;
  flatten?: boolean;
  graft?: boolean;
  simplify?: boolean;
  principal?: boolean;
  invert?: boolean;
  expression?: string | null;
}

export interface PortRecord {
  id: string;
  name: string;
  access?: Access;
  mods?: PortMods;
  persistent?: unknown;
  keep?: Record<string, unknown>;
}

export interface NodeRecord {
  id: string;
  type: string;
  nickname: string;
  enabled: boolean;
  preview: boolean;
  matching?: string;
  inputs: PortRecord[];
  outputs: PortRecord[];
  settings: Record<string, unknown>;
  x: number;
  y: number;
  keep?: Record<string, unknown>;
}

export interface PortRef { node: string; port: string }
export interface WireRecord { id: string; from: PortRef; to: PortRef; order: number; keep?: Record<string, unknown> }
export interface GroupRecord { id: string; name: string; colour: string; members: string[]; keep?: Record<string, unknown> }

export interface GraphRecord {
  id: string;
  name: string;
  nodes: NodeRecord[];
  wires: WireRecord[];
  groups: GroupRecord[];
  extra: Record<string, unknown>;
}

export interface GraphListItem { id: string; name: string; nodes?: number }

export interface CataloguePort { name: string; nick?: string; kind: string; access?: Access; description?: string; optional?: boolean }
export interface CatalogueEntry {
  id: string;
  name: string;
  nick?: string;
  category: string;
  group?: string;
  description?: string;
  inputs: CataloguePort[];
  outputs: CataloguePort[];
  widget?: string;
  icon?: string;
  obsolete?: boolean;
  settings?: Record<string, unknown>;
}

export interface RuntimeMessage { level: MessageLevel; text: string; port?: string }
export interface TreeSummary { count: number; items: number; first: string[] }

export interface NodeState {
  state: NodeStateName;
  messages: RuntimeMessage[];
  outputs: Record<string, TreeSummary>;
  ms?: number;
}

export interface TreeBranch { path: string; count: number; items: string[] }
export interface TreePage { branches: TreeBranch[]; offset: number; total: number; items: number }

export interface NodeEdit {
  settings?: Record<string, unknown>;
  persistent?: { port: string; tree: unknown };
  nickname?: string;
  enabled?: boolean;
  preview?: boolean;
}

export const MOD_KEYS: ModKey[] = ['reverse', 'flatten', 'graft', 'simplify', 'principal', 'invert'];

export const sameState = (a: NodeState | undefined, b: NodeState | undefined): boolean => {
  if (a === b) return true;
  if (!a || !b) return false;
  return a.state === b.state && JSON.stringify(a.messages) === JSON.stringify(b.messages) && JSON.stringify(a.outputs) === JSON.stringify(b.outputs);
};
