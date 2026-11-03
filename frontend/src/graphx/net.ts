import { call, token } from '../io/api';
import { docStore } from '../ui/doc-store';

type Dict = Record<string, unknown>;

const enc = encodeURIComponent;

export const docBase = (): string => `/api/docs/${enc(docStore.activeId ?? '')}`;
export const graphBase = (gid: string): string => `${docBase()}/graphs/${enc(gid)}`;

export interface BakeOptions { layer: string; colour: string; byLayer: boolean; name: string }
export interface BakeResult { baked?: number; replaced?: number; skipped?: string[]; message?: string }

export const bake = (gid: string, nodes: string[], options: BakeOptions): Promise<BakeResult> =>
  call<BakeResult>('POST', `${graphBase(gid)}/bake`, { nodes, options: { layer: options.layer, colour: options.byLayer ? null : options.colour, name: options.name } });

export interface LayerRow { name: string; colorText?: string }
export const layers = (): Promise<{ layers: LayerRow[]; current: string }> => call('GET', `${docBase()}/layers`);

export interface OptimizeRequest {
  genes: string[];
  fitness_node: string;
  fitness_port: string;
  direction: 'minimise' | 'maximise';
  method: 'evolution' | 'annealing';
  population: number;
  generations: number;
  seed: number;
  commit: boolean;
}
export interface OptimizeStatus {
  id: string;
  state: string;
  generation: number;
  evaluations: number;
  best: number | null;
  history: number[];
  genome: Record<string, number>;
  message: string;
}

const num = (v: unknown, d = 0): number => (typeof v === 'number' && Number.isFinite(v) ? v : d);

export function statusOf(raw: Dict): OptimizeStatus {
  const prog = (raw.progress && typeof raw.progress === 'object' ? raw.progress : {}) as Dict;
  const result = (raw.result && typeof raw.result === 'object' ? raw.result : null) as Dict | null;
  const hist = result && Array.isArray(result.history) ? (result.history as Dict[]).map((h) => (typeof h.best === 'number' ? h.best : NaN)).filter((h) => Number.isFinite(h)) : [];
  const genome: Record<string, number> = {};
  if (result && Array.isArray(result.best)) for (const g of result.best as Dict[]) if (typeof g.node === 'string' && typeof g.value === 'number') genome[g.node] = g.value;
  const best = typeof prog.best === 'number' ? prog.best : result && typeof result.best_value === 'number' ? result.best_value : null;
  return {
    id: typeof raw.id === 'string' ? raw.id : '',
    state: typeof raw.state === 'string' ? raw.state : 'idle',
    generation: num(prog.generation, result ? num(result.generations) : 0),
    evaluations: num(prog.evaluations, result ? num(result.evaluations) : 0),
    best,
    history: hist,
    genome,
    message: typeof raw.message === 'string' ? raw.message : '',
  };
}

export const optimizeStart = (gid: string, req: OptimizeRequest): Promise<OptimizeStatus> => call<Dict>('POST', `${graphBase(gid)}/optimize`, req).then(statusOf);
export const optimizeStatus = (gid: string, job: string): Promise<OptimizeStatus> => call<Dict>('GET', `${graphBase(gid)}/optimize/${enc(job)}`).then(statusOf);
export const optimizeCancel = (gid: string, job: string): Promise<unknown> => call('POST', `${graphBase(gid)}/optimize/${enc(job)}/cancel`, {});

export interface RunRequest { graph?: Dict; graph_path?: string; inputs: Dict }
export interface RunOutput { name: string; branches: number; items: number; first: string[] }
export interface RunResult { rows: RunOutput[]; ok: boolean; digest: string; problems: string[] }

export async function runHeadless(req: RunRequest): Promise<RunResult> {
  const res = await call<Dict>('POST', '/api/graph/run', req);
  const outs = (res.outputs ?? {}) as Dict;
  const problems = (Array.isArray(res.messages) ? (res.messages as Dict[]) : []).filter((m) => m.level === 'error').map((m) => String(m.text ?? m.message ?? ''));
  const rows: RunOutput[] = [];
  for (const [name, raw] of Object.entries(outs)) {
    if (!raw || typeof raw !== 'object') continue;
    const tree = raw as Dict;
    const branches = Array.isArray(tree.branches) ? (tree.branches as Dict[]) : Object.entries((tree.tree ?? tree) as Dict).map(([path, items]) => ({ path, items }));
    let items = 0;
    const first: string[] = [];
    for (const b of branches) {
      const list = Array.isArray(b.items) ? (b.items as unknown[]) : [];
      items += list.length;
      for (const it of list) if (first.length < 6) first.push(typeof it === 'string' ? it : JSON.stringify(it));
    }
    rows.push({ name, branches: branches.length, items, first });
  }
  return { rows, ok: res.ok !== false, digest: typeof res.digest === 'string' ? res.digest : '', problems };
}

export const definitionOf = (gid: string): Promise<Dict> => call<{ definition: Dict }>('GET', graphBase(gid)).then((r) => r.definition);

export const importGraph =(path: string): Promise<{ id: string }> => call('POST', `${docBase()}/graphs/import`, { path, solve: true });
export const exportGraph = (gid: string, path: string): Promise<{ path: string; bytes: number }> => call('POST', `${graphBase(gid)}/export`, { path });

export async function previewScene(gid: string): Promise<ArrayBuffer | null> {
  const headers: Record<string, string> = {};
  const tok = token();
  if (tok) headers['X-FormCAD-Token'] = tok;
  const res = await fetch(`${graphBase(gid)}/preview`, { headers });
  if (res.status === 404 || res.status === 501 || res.status === 204) return null;
  if (!res.ok) throw new Error(res.statusText || `The graph preview request failed (${res.status})`);
  const buf = await res.arrayBuffer();
  return buf.byteLength ? buf : null;
}

export interface PluginNodeType { id: string; plugin: string; name: string; category: string; description: string }

export async function pluginNodeTypes(): Promise<PluginNodeType[]> {
  const res = await call<{ nodes: Dict[] }>('GET', '/api/graph/catalogue');
  const out: PluginNodeType[] = [];
  for (const n of res.nodes ?? []) {
    const id = String(n.id);
    const at = id.indexOf('/');
    if (at <= 0) continue;
    out.push({ id, plugin: id.slice(0, at), name: String(n.name ?? id.slice(at + 1)), category: String(n.category ?? ''), description: String(n.description ?? '') });
  }
  return out;
}
