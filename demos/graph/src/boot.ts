import recording from '../recordings/graph.json';
import { installReplay, type Recording, type ReplayRequest } from '../../../demo/src/shim/replay';
import { decodeGraph, encodeGraph } from '../../../frontend/src/graph/codec';

type Dict = Record<string, unknown>;

const rec = recording as unknown as Recording;

const bodyOf = (path: RegExp): string | null => {
  let found: string | null = null;
  for (const e of rec.exchanges) if (e.method === 'GET' && path.test(e.path) && e.response !== null && e.status === 200) found = rec.responses[e.response];
  return found;
};

const bytesOf = (path: RegExp): Uint8Array<ArrayBuffer> | null => {
  let found: { raw: string; b64: boolean } | null = null;
  for (const e of rec.exchanges) if (e.method === 'GET' && path.test(e.path) && e.response !== null && e.status === 200) found = { raw: rec.responses[e.response], b64: e.encoding === 'base64' };
  if (!found) return null;
  const bin = found.b64 ? atob(found.raw) : found.raw;
  const out = new Uint8Array(new ArrayBuffer(bin.length));
  for (let i = 0; i < bin.length; i++) out[i] = bin.charCodeAt(i) & 0xff;
  return out;
};

const shape = (def: Dict): string => {
  const enc = encodeGraph(decodeGraph(def));
  const nodes = (Array.isArray(enc.nodes) ? (enc.nodes as Dict[]) : []).map(({ x: _x, y: _y, ...rest }) => rest);
  const { view: _view, nodes: _nodes, ...restOf } = enc;
  return JSON.stringify({ ...restOf, nodes });
};

const graphPath = /^\/api\/docs\/[^/]+\/graphs\/([^/]+)$/;
const statePath = /^\/api\/docs\/[^/]+\/graphs\/[^/]+\/state$/;
const previewPath = /^\/api\/docs\/[^/]+\/graphs\/[^/]+\/preview$/;

const graphs = new Map<string, Dict>();
const recorded = (gid: string): Dict | null => {
  const held = graphs.get(gid);
  if (held) return held;
  const raw = bodyOf(new RegExp(`/graphs/${gid}$`));
  if (!raw) return null;
  const res = JSON.parse(raw) as Dict;
  graphs.set(gid, res);
  return res;
};

const lastState = bodyOf(statePath);
const preview = bytesOf(previewPath);

const local = (req: ReplayRequest): unknown => {
  const path = decodeURIComponent(req.path);
  const g = graphPath.exec(path);
  if (g && req.method === 'GET') return recorded(g[1]) ?? undefined;
  if (g && req.method === 'PUT') {
    const held = recorded(g[1]);
    let ask: Dict = {};
    try { ask = JSON.parse(req.body ?? '{}') as Dict; } catch { return undefined; }
    const next = ask.definition as Dict | undefined;
    if (!held || !next || shape(next) !== shape(held.definition as Dict)) return undefined;
    graphs.set(g[1], { ...held, definition: next });
    return { expired: [], busy: false };
  }
  if (req.method === 'GET' && statePath.test(path) && lastState) return new Response(lastState, { status: 200, headers: { 'Content-Type': 'application/json' } });
  if (req.method === 'GET' && previewPath.test(path) && preview) return new Response(preview, { status: 200, headers: { 'Content-Type': 'application/octet-stream' } });
  return undefined;
};

const handle = installReplay(rec, { local, frames: 'boot' });

Object.assign(window, { formcadReplay: { document: rec.document, misses: handle.misses } });
