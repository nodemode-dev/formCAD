import type { Access, GraphRecord, GroupRecord, MessageLevel, NodeRecord, NodeState, NodeStateName, PortRecord, RuntimeMessage, TreeSummary, WireRecord } from './types';

type Dict = Record<string, unknown>;
const isObj = (v: unknown): v is Dict => !!v && typeof v === 'object' && !Array.isArray(v);
const str = (v: unknown, d = ''): string => (typeof v === 'string' ? v : d);
const num = (v: unknown, d = 0): number => (typeof v === 'number' && Number.isFinite(v) ? v : d);

const NODE_KNOWN = new Set(['id', 'type', 'nickname', 'enabled', 'preview', 'matching', 'x', 'y', 'ports', 'settings']);
const PORT_KNOWN = new Set(['id', 'name', 'access', 'mods', 'persistent']);
const GRAPH_KNOWN = new Set(['id', 'name', 'nodes', 'wires', 'groups']);

function pick(raw: Dict, known: Set<string>): Dict {
  const out: Dict = {};
  for (const [k, v] of Object.entries(raw)) if (!known.has(k)) out[k] = v;
  return out;
}

function decodePort(raw: unknown): PortRecord | null {
  if (!isObj(raw) || typeof raw.name !== 'string') return null;
  const access = raw.access === 'list' || raw.access === 'tree' ? raw.access : 'item';
  return { id: str(raw.id, raw.name), name: raw.name, access: access as Access, mods: isObj(raw.mods) ? (raw.mods as PortRecord['mods']) : {}, persistent: raw.persistent, keep: pick(raw, PORT_KNOWN) };
}

export function decodeGraph(def: Dict, fallbackId = ''): GraphRecord {
  const nodes: NodeRecord[] = [];
  const portOwner = new Map<string, { node: string; port: string; side: 'in' | 'out' }>();
  for (const raw of Array.isArray(def.nodes) ? def.nodes : []) {
    if (!isObj(raw) || typeof raw.id !== 'string') continue;
    const ports = isObj(raw.ports) ? raw.ports : {};
    const ins = (Array.isArray(ports.in) ? ports.in : []).map(decodePort).filter((p): p is PortRecord => !!p);
    const outs = (Array.isArray(ports.out) ? ports.out : []).map(decodePort).filter((p): p is PortRecord => !!p);
    for (const p of ins) portOwner.set(p.id, { node: raw.id, port: p.name, side: 'in' });
    for (const p of outs) portOwner.set(p.id, { node: raw.id, port: p.name, side: 'out' });
    nodes.push({
      id: raw.id,
      type: str(raw.type),
      nickname: str(raw.nickname),
      enabled: raw.enabled !== false,
      preview: raw.preview !== false,
      matching: str(raw.matching, 'longest'),
      inputs: ins,
      outputs: outs,
      settings: isObj(raw.settings) ? raw.settings : {},
      x: num(raw.x),
      y: num(raw.y),
      keep: pick(raw, NODE_KNOWN),
    });
  }
  const wires: WireRecord[] = [];
  for (const raw of Array.isArray(def.wires) ? def.wires : []) {
    if (!isObj(raw)) continue;
    const a = portOwner.get(str(raw.from));
    const b = portOwner.get(str(raw.to));
    if (!a || !b || a.side !== 'out' || b.side !== 'in') continue;
    wires.push({ id: str(raw.id), from: { node: a.node, port: a.port }, to: { node: b.node, port: b.port }, order: num(raw.order), keep: pick(raw, new Set(['id', 'from', 'to', 'order'])) });
  }
  const groups: GroupRecord[] = [];
  for (const raw of Array.isArray(def.groups) ? def.groups : []) {
    if (!isObj(raw)) continue;
    groups.push({ id: str(raw.id), name: str(raw.name), colour: str(raw.colour, '#8a8f98'), members: (Array.isArray(raw.members) ? raw.members : []).filter((m): m is string => typeof m === 'string'), keep: pick(raw, new Set(['id', 'name', 'colour', 'members'])) });
  }
  return { id: str(def.id, fallbackId), name: str(def.name), nodes, wires, groups, extra: pick(def, GRAPH_KNOWN) };
}

function encodePort(p: PortRecord): Dict {
  const out: Dict = { ...(p.keep ?? {}), id: p.id, name: p.name, access: p.access ?? 'item' };
  if (p.mods && Object.keys(p.mods).length) out.mods = p.mods;
  if (p.persistent !== undefined && p.persistent !== null) out.persistent = p.persistent;
  return out;
}

export function encodeGraph(rec: GraphRecord): Dict {
  const portId = (node: string, side: 'in' | 'out', name: string): string => {
    const n = rec.nodes.find((x) => x.id === node);
    return (side === 'in' ? n?.inputs : n?.outputs)?.find((p) => p.name === name)?.id ?? '';
  };
  return {
    ...rec.extra,
    id: rec.id,
    name: rec.name,
    nodes: rec.nodes.map((n) => ({
      ...(n.keep ?? {}),
      id: n.id,
      type: n.type,
      nickname: n.nickname,
      enabled: n.enabled,
      preview: n.preview,
      matching: n.matching ?? 'longest',
      x: n.x,
      y: n.y,
      settings: n.settings,
      ports: { in: n.inputs.map(encodePort), out: n.outputs.map(encodePort) },
    })),
    wires: rec.wires.map((w) => ({ ...(w.keep ?? {}), id: w.id, from: portId(w.from.node, 'out', w.from.port), to: portId(w.to.node, 'in', w.to.port), order: w.order })),
    groups: rec.groups.map((g) => ({ ...(g.keep ?? {}), id: g.id, name: g.name, colour: g.colour, members: g.members })),
  };
}

const LEVELS = new Set<string>(['remark', 'warning', 'error']);

function decodeTree(raw: unknown): TreeSummary {
  if (!isObj(raw)) return { count: 0, items: 0, first: [] };
  return { count: num(raw.branches), items: num(raw.items), first: (Array.isArray(raw.first) ? raw.first : []).map((v) => (typeof v === 'string' ? v : JSON.stringify(v))) };
}

export function decodeTreePage(raw: unknown): import('./types').TreePage {
  const r = isObj(raw) ? raw : {};
  const page = (Array.isArray(r.page) ? r.page : []).filter(isObj).map((b) => ({
    path: str(b.path),
    count: num(b.count),
    items: (Array.isArray(b.items) ? b.items : []).map((v) => (typeof v === 'string' ? v : JSON.stringify(v))),
  }));
  return { branches: page, offset: num(r.offset), total: num(r.branches), items: num(r.items) };
}

export function decodeState(raw: unknown, enabled: boolean): NodeState {
  const r = isObj(raw) ? raw : {};
  const messages: RuntimeMessage[] = (Array.isArray(r.messages) ? r.messages : []).filter(isObj).filter((m) => LEVELS.has(str(m.level))).map((m) => ({ level: m.level as MessageLevel, text: str(m.text), port: str(m.port) || undefined }));
  const outputs: Record<string, TreeSummary> = {};
  if (isObj(r.outputs)) for (const [k, v] of Object.entries(r.outputs)) outputs[k] = decodeTree(v);
  const s = str(r.state, 'blank');
  let state: NodeStateName = 'blank';
  if (!enabled || s === 'skipped') state = 'disabled';
  else if (s === 'failed' || messages.some((m) => m.level === 'error')) state = 'error';
  else if (s === 'computed') state = messages.some((m) => m.level === 'warning') ? 'warning' : 'computed';
  else if (s === 'collecting' || s === 'computing') state = 'busy';
  return { state, messages, outputs, ms: typeof r.ms === 'number' ? r.ms : undefined };
}
