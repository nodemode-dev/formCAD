import { afterEach, describe, expect, it, vi } from 'vitest';
import { decodeGraph, encodeGraph } from '../../src/graph/codec';
import { connect, copyOf, kindsMeet, paste, removeItems } from '../../src/graph/ops';
import type { GraphRecord, NodeRecord } from '../../src/graph/types';
import { engine, jsonResponse } from './support';

const node = (id: string, ins: string[], outs: string[], x = 0): NodeRecord => ({
  id, type: 'math.add', nickname: '', enabled: true, preview: true, matching: 'longest',
  inputs: ins.map((n) => ({ id: `${id}.${n}`, name: n, access: 'item', mods: {} })),
  outputs: outs.map((n) => ({ id: `${id}.${n}`, name: n, access: 'item', mods: {} })),
  settings: {}, x, y: 0,
});

const graph = (): GraphRecord => ({
  id: 'G1', name: 'G1', extra: {},
  nodes: [node('a', [], ['r']), node('b', ['x', 'y'], ['r'], 100), node('c', ['x'], ['r'], 200)],
  wires: [], groups: [],
});

describe('connecting ports in the graph editor', () => {
  it.each([
    ['number', 'number'], ['integer', 'number'], ['boolean', 'integer'], ['curve', 'geometry'], ['geometry', 'brep'],
    ['point', 'vector'], ['number', 'domain'], ['mesh', 'any'], ['any', 'plane'], ['brep', 'text'],
  ])('accepts a wire from a %s output to a %s input', (from, to) => {
    expect(kindsMeet(from, to)).toBe(true);
  });

  it.each([
    ['curve', 'number'], ['text', 'number'], ['mesh', 'plane'], ['boolean', 'curve'], ['colour', 'transform'], ['docref', 'point'],
  ])('refuses a wire from a %s output to a %s input', (from, to) => {
    expect(kindsMeet(from, to)).toBe(false);
  });

  it('a new wire into an input replaces the one already there unless it is added alongside', () => {
    let g = connect(graph(), { node: 'a', port: 'r' }, { node: 'b', port: 'x' }, false);
    g = connect(g, { node: 'c', port: 'r' }, { node: 'b', port: 'x' }, false);
    expect(g.wires.map((w) => [w.from.node, w.to.node, w.to.port])).toEqual([['c', 'b', 'x']]);
    g = connect(g, { node: 'a', port: 'r' }, { node: 'b', port: 'x' }, true);
    expect(g.wires.map((w) => [w.from.node, w.order])).toEqual([['c', 0], ['a', 1]]);
  });

  it('refuses a wire from a node to itself and a second identical wire', () => {
    const start = connect(graph(), { node: 'a', port: 'r' }, { node: 'b', port: 'y' }, false);
    expect(connect(start, { node: 'b', port: 'r' }, { node: 'b', port: 'x' }, true)).toBe(start);
    expect(connect(start, { node: 'a', port: 'r' }, { node: 'b', port: 'y' }, true)).toBe(start);
  });

  it('an edit leaves the earlier graph unchanged so undo can return to it', () => {
    const before = graph();
    const snapshot = JSON.stringify(before);
    const after = connect(before, { node: 'a', port: 'r' }, { node: 'b', port: 'x' }, false);
    expect(after.wires).toHaveLength(1);
    expect(JSON.stringify(before)).toBe(snapshot);
  });
});

describe('deleting and copying nodes', () => {
  it('deleting a node removes every wire into or out of it and takes it out of its group', () => {
    let g = connect(graph(), { node: 'a', port: 'r' }, { node: 'b', port: 'x' }, false);
    g = connect(g, { node: 'b', port: 'r' }, { node: 'c', port: 'x' }, false);
    g = connect(g, { node: 'a', port: 'r' }, { node: 'c', port: 'x' }, true);
    g = { ...g, groups: [{ id: 'g1', name: 'Pair', colour: '#112233', members: ['a', 'b'] }, { id: 'g2', name: 'Solo', colour: '#445566', members: ['b'] }] };
    const out = removeItems(g, new Set(['b']), new Set(), new Set());
    expect(out.nodes.map((n) => n.id)).toEqual(['a', 'c']);
    expect(out.wires.map((w) => `${w.from.node}>${w.to.node}`)).toEqual(['a>c']);
    expect(out.groups).toEqual([{ id: 'g1', name: 'Pair', colour: '#112233', members: ['a'] }]);
  });

  it('pasting a copy makes new nodes at the offset with the copied wires joined between the copies', () => {
    let g = connect(graph(), { node: 'a', port: 'r' }, { node: 'b', port: 'x' }, false);
    g = connect(g, { node: 'b', port: 'r' }, { node: 'c', port: 'x' }, false);
    const clip = copyOf(g, new Set(['a', 'b']));
    expect(clip.wires).toHaveLength(1);
    const { rec, ids } = paste(g, clip, 30, 40);
    expect(rec.nodes).toHaveLength(5);
    expect(new Set(ids).size).toBe(2);
    expect(ids.some((id) => ['a', 'b', 'c'].includes(id))).toBe(false);
    const copies = rec.nodes.filter((n) => ids.includes(n.id));
    expect(copies.map((n) => [n.x, n.y])).toEqual([[30, 40], [130, 40]]);
    const added = rec.wires.slice(2);
    expect(added).toHaveLength(1);
    expect(added[0].from.node).toBe(copies[0].id);
    expect(added[0].to).toEqual({ node: copies[1].id, port: 'x' });
  });
});

describe('the graph file codec', () => {
  const def = {
    version: '1.0.0', min_reader: '1.0.0', settings: { seed: 0, tolerance: 0.001 }, meta: { author: 'me' }, notes: [{ id: 'k1', text: 'hi', x: 1, y: 2 }],
    id: 'G1', name: 'Plate',
    nodes: [
      { id: 'n_1', type: 'math.add', guid: '7f0c', type_name: 'Add', library: '', node_version: 1, nickname: '', enabled: true, preview: true, matching: 'cross', x: 120, y: 80,
        ports: { in: [{ id: 'p_01', name: 'a', access: 'item', mods: { flatten: true, expression: 'x*2' }, persistent: { type: 'number', tree: { '{0}': [1.5] } }, extra_flag: 3 }], out: [{ id: 'p_03', name: 'r', access: 'list' }] }, settings: { k: 1 } },
      { id: 'n_2', type: 'math.add', nickname: 'B', enabled: false, preview: true, matching: 'longest', x: 300, y: 80,
        ports: { in: [{ id: 'p_04', name: 'a', access: 'item' }], out: [{ id: 'p_05', name: 'r', access: 'item' }] }, settings: {} },
    ],
    wires: [{ id: 'w1', from: 'p_03', to: 'p_04', order: 0, colour: 'red' }],
    groups: [{ id: 'g1', name: 'Both', colour: '#aabbcc', members: ['n_1', 'n_2'], locked: true }],
  };

  it('keeps every field it does not know at the top level and in nodes, ports, wires and groups on a round trip', () => {
    const back = encodeGraph(decodeGraph(structuredClone(def)));
    expect(back).toEqual(def);
  });

  it('reads a wire as joining the node and port names that own the two port ids', () => {
    const g = decodeGraph(structuredClone(def));
    expect(g.wires).toEqual([{ id: 'w1', from: { node: 'n_1', port: 'r' }, to: { node: 'n_2', port: 'a' }, order: 0, keep: { colour: 'red' } }]);
  });

  it('drops a wire that runs from an input port to an output port', () => {
    const bad = { ...structuredClone(def), wires: [{ id: 'w2', from: 'p_04', to: 'p_03', order: 0 }] };
    expect(decodeGraph(bad).wires).toEqual([]);
  });
});

describe('the graph store', () => {
  afterEach(() => { vi.unstubAllGlobals(); vi.useRealTimers(); });

  async function opened(readonly: boolean, putFails: boolean) {
    vi.useFakeTimers();
    vi.resetModules();
    const { docStore } = await import('../../src/ui/doc-store');
    const { GraphStore } = await import('../../src/graph/store');
    docStore.activeId = 'D1';
    const sent = engine((method, url) => {
      if (url === '/api/graph/catalogue') return jsonResponse(200, { revision: 1, nodes: [] });
      if (url === '/api/docs/D1/graphs') return jsonResponse(200, { graphs: [{ id: 'G1', label: 'Plate', nodes: 2 }] });
      if (method === 'GET' && url === '/api/docs/D1/graphs/G1') return jsonResponse(200, { id: 'G1', label: 'Plate', definition: structuredClone(def), readonly, problems: [], busy: true });
      if (url.startsWith('/api/docs/D1/graphs/G1/state')) return jsonResponse(200, { nodes: {}, busy: false, error: '', report: null, problems: [] });
      if (method === 'PUT') return putFails ? jsonResponse(409, { detail: 'That wire would make a loop: n_1, n_2' }) : jsonResponse(200, { expired: [], busy: false });
      return jsonResponse(404, { detail: url });
    });
    const store = new GraphStore();
    await store.enter();
    return { store, sent };
  }
  const def = { id: 'G1', name: 'Plate', nodes: [
    { id: 'n_1', type: 't', x: 0, y: 0, ports: { in: [], out: [{ id: 'p1', name: 'r' }] }, settings: {} },
    { id: 'n_2', type: 't', x: 9, y: 0, ports: { in: [{ id: 'p2', name: 'a' }], out: [] }, settings: {} },
  ], wires: [], groups: [] };

  it('a graph written by a newer version refuses every edit', async () => {
    const { store, sent } = await opened(true, false);
    const before = store.rec;
    expect(store.apply((r) => connect(r, { node: 'n_1', port: 'r' }, { node: 'n_2', port: 'a' }, false))).toBe(false);
    expect(store.rec).toBe(before);
    await vi.advanceTimersByTimeAsync(100);
    expect(sent.some((s) => s.method === 'PUT')).toBe(false);
  });

  it('an edit is sent to the engine as the whole definition with the new wire', async () => {
    const { store, sent } = await opened(false, false);
    expect(store.apply((r) => connect(r, { node: 'n_1', port: 'r' }, { node: 'n_2', port: 'a' }, false))).toBe(true);
    await vi.advanceTimersByTimeAsync(10);
    const put = sent.find((s) => s.method === 'PUT');
    expect(put?.url).toBe('/api/docs/D1/graphs/G1');
    const wires = (put?.body as { definition: { wires: Array<{ from: string; to: string }> } }).definition.wires;
    expect(wires.map((w) => [w.from, w.to])).toEqual([['p1', 'p2']]);
  });

  it('an edit the engine refuses is rolled back to the engine copy and the reason is shown', async () => {
    const { store } = await opened(false, true);
    store.apply((r) => connect(r, { node: 'n_1', port: 'r' }, { node: 'n_2', port: 'a' }, false));
    expect(store.rec?.wires).toHaveLength(1);
    await vi.advanceTimersByTimeAsync(10);
    expect(store.rec?.wires).toEqual([]);
    expect(store.error).toBe('That wire would make a loop: n_1, n_2');
  });
});
