import type { CatalogueEntry, GraphRecord, GroupRecord, ModKey, NodeRecord, PortMods, PortRef, WireRecord } from './types';

export const uid = (prefix: string): string => `${prefix}_${Math.random().toString(16).slice(2, 10)}`;

const GROUP_TOKENS = ['--accent-color', '--ok', '--canvas-axis-z', '--sm-bend-up', '--warn', '--danger'];

export function groupColours(): string[] {
  const style = getComputedStyle(document.documentElement);
  return GROUP_TOKENS.map((t) => style.getPropertyValue(t).trim()).filter((v) => /^#[0-9a-f]{6}$/i.test(v));
}

export function makeNode(entry: CatalogueEntry, x: number, y: number): NodeRecord {
  return {
    id: uid('n'),
    type: entry.id,
    nickname: '',
    enabled: true,
    preview: true,
    matching: 'longest',
    inputs: entry.inputs.map((p) => ({ id: uid('p'), name: p.name, access: p.access ?? 'item', mods: {} })),
    outputs: entry.outputs.map((p) => ({ id: uid('p'), name: p.name, access: p.access ?? 'item', mods: {} })),
    settings: structuredClone(entry.settings ?? {}),
    x,
    y,
  };
}

const sameRef = (a: PortRef, b: PortRef): boolean => a.node === b.node && a.port === b.port;

export function addNode(rec: GraphRecord, node: NodeRecord): GraphRecord {
  return { ...rec, nodes: [...rec.nodes, node] };
}

export function patchNode(rec: GraphRecord, id: string, fn: (n: NodeRecord) => NodeRecord): GraphRecord {
  let hit = false;
  const nodes = rec.nodes.map((n) => {
    if (n.id !== id) return n;
    hit = true;
    return fn(n);
  });
  return hit ? { ...rec, nodes } : rec;
}

export function removeItems(rec: GraphRecord, nodeIds: ReadonlySet<string>, wireIds: ReadonlySet<string>, groupIds: ReadonlySet<string>): GraphRecord {
  const nodes = rec.nodes.filter((n) => !nodeIds.has(n.id));
  const wires = rec.wires.filter((w) => !wireIds.has(w.id) && !nodeIds.has(w.from.node) && !nodeIds.has(w.to.node));
  const groups: GroupRecord[] = [];
  for (const g of rec.groups) {
    if (groupIds.has(g.id)) continue;
    const members = g.members.filter((m) => !nodeIds.has(m));
    if (members.length === 0) continue;
    groups.push(members.length === g.members.length ? g : { ...g, members });
  }
  return { ...rec, nodes, wires, groups };
}

export function moveNodes(rec: GraphRecord, moves: ReadonlyMap<string, { x: number; y: number }>): GraphRecord {
  if (moves.size === 0) return rec;
  return { ...rec, nodes: rec.nodes.map((n) => { const m = moves.get(n.id); return m && (m.x !== n.x || m.y !== n.y) ? { ...n, x: m.x, y: m.y } : n; }) };
}

export function connect(rec: GraphRecord, from: PortRef, to: PortRef, add: boolean): GraphRecord {
  if (from.node === to.node) return rec;
  if (rec.wires.some((w) => sameRef(w.from, from) && sameRef(w.to, to))) return rec;
  const kept = add ? rec.wires : rec.wires.filter((w) => !sameRef(w.to, to));
  const order = kept.filter((w) => sameRef(w.to, to)).length;
  const wire: WireRecord = { id: uid('w'), from, to, order };
  return { ...rec, wires: [...kept, wire] };
}

export function disconnect(rec: GraphRecord, wireId: string): GraphRecord {
  return { ...rec, wires: rec.wires.filter((w) => w.id !== wireId) };
}

export function setMod(rec: GraphRecord, nodeId: string, port: string, key: ModKey | 'expression', value: boolean | string | null): GraphRecord {
  return patchNode(rec, nodeId, (n) => ({
    ...n,
    inputs: n.inputs.map((p) => {
      if (p.name !== port) return p;
      const mods: PortMods = { ...(p.mods ?? {}) };
      if (key === 'expression') mods.expression = typeof value === 'string' && value.trim() ? value : null;
      else mods[key] = value === true;
      return { ...p, mods };
    }),
  }));
}

export function groupNodes(rec: GraphRecord, ids: string[], name: string, colour: string): GraphRecord {
  const members = ids.filter((id) => rec.nodes.some((n) => n.id === id));
  if (members.length === 0) return rec;
  const set = new Set(members);
  const groups = rec.groups.map((g) => (g.members.some((m) => set.has(m)) ? { ...g, members: g.members.filter((m) => !set.has(m)) } : g)).filter((g) => g.members.length > 0);
  return { ...rec, groups: [...groups, { id: uid('g'), name, colour, members }] };
}

export function patchGroup(rec: GraphRecord, id: string, fn: (g: GroupRecord) => GroupRecord): GraphRecord {
  return { ...rec, groups: rec.groups.map((g) => (g.id === id ? fn(g) : g)) };
}

export interface Clip { nodes: NodeRecord[]; wires: WireRecord[]; groups: GroupRecord[] }

export function copyOf(rec: GraphRecord, ids: ReadonlySet<string>): Clip {
  const nodes = rec.nodes.filter((n) => ids.has(n.id));
  const wires = rec.wires.filter((w) => ids.has(w.from.node) && ids.has(w.to.node));
  const groups = rec.groups.map((g) => ({ ...g, members: g.members.filter((m) => ids.has(m)) })).filter((g) => g.members.length > 1);
  return { nodes: structuredClone(nodes), wires: structuredClone(wires), groups: structuredClone(groups) };
}

export function paste(rec: GraphRecord, clip: Clip, dx: number, dy: number): { rec: GraphRecord; ids: string[] } {
  const map = new Map<string, string>();
  const nodes = clip.nodes.map((n) => {
    const id = uid('n');
    map.set(n.id, id);
    const copy = structuredClone(n);
    return { ...copy, id, x: n.x + dx, y: n.y + dy, inputs: copy.inputs.map((p) => ({ ...p, id: uid('p') })), outputs: copy.outputs.map((p) => ({ ...p, id: uid('p') })) };
  });
  const wires = clip.wires.map((w) => ({ id: uid('w'), from: { node: map.get(w.from.node) ?? '', port: w.from.port }, to: { node: map.get(w.to.node) ?? '', port: w.to.port }, order: w.order }));
  const groups = clip.groups.map((g) => ({ ...g, id: uid('g'), members: g.members.map((m) => map.get(m) ?? '').filter(Boolean) }));
  return { rec: { ...rec, nodes: [...rec.nodes, ...nodes], wires: [...rec.wires, ...wires], groups: [...rec.groups, ...groups] }, ids: nodes.map((n) => n.id) };
}

export function kindsMeet(from: string, to: string): boolean {
  if (from === to || from === 'any' || to === 'any') return true;
  const geometry = new Set(['point', 'curve', 'surface', 'brep', 'mesh', 'geometry', 'vector', 'plane']);
  if (to === 'geometry' && geometry.has(from)) return true;
  if (from === 'geometry' && geometry.has(to)) return true;
  const numeric = new Set(['number', 'integer', 'boolean']);
  if (numeric.has(from) && numeric.has(to)) return true;
  if (from === 'point' && to === 'vector') return true;
  if (from === 'vector' && to === 'point') return true;
  if (from === 'number' && to === 'domain') return true;
  if (from === 'integer' && to === 'domain') return true;
  if (to === 'text') return true;
  if (from === 'surface' && to === 'brep') return true;
  if (from === 'brep' && to === 'surface') return true;
  return false;
}
