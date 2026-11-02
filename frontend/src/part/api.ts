import { ApiError, call, token } from '../io/api';
import { parseScene } from '../view3d/scene-format';
import type { SceneModel } from '../view3d/types';
import type { RefItem } from '../view3d/refgeo';

const enc = encodeURIComponent;
const base = (id: string): string => `/api/docs/${enc(id)}`;

export type FeatureStatus = 'ok' | 'warning' | 'error' | 'suppressed' | 'stale' | 'rolled';

export interface FeatureState {
  status: FeatureStatus;
  message: string;
  warnings: string[];
  ms: number;
  failed: Record<string, unknown>;
}

export interface RefRecord {
  kind: string;
  key?: string;
  id?: string;
  pid?: number | null;
  ctx?: string | null;
  sig?: Record<string, unknown>;
  [k: string]: unknown;
}

export interface Feature {
  id: string;
  type: string;
  label: string;
  group: string;
  index: number;
  suppressed: boolean;
  params: Record<string, unknown>;
  refs: Record<string, RefRecord | RefRecord[]>;
  state: FeatureState;
  parents: string[];
  children: string[];
  rolled: boolean;
}

export interface PartTree {
  workspace: string;
  rollback: string | null;
  auto: boolean;
  body: number;
  built: string;
  features: Feature[];
  rev: number;
}

export interface ParamSchema { name: string; kind: string; default: unknown; min: number | null; max: number | null; choices: unknown[] | null; label: string; unit: string }
export interface RefSchema { name: string; kind: string; multi: boolean; required: boolean; label: string }
export interface TypeSchema { type: string; label: string; group: string; needs_body: boolean; sketch: boolean; params: ParamSchema[]; refs: RefSchema[]; roles: string[] }

export interface PreviewInfo { id: string; status: FeatureStatus; message: string; warnings: string[]; failed: Record<string, unknown> }
export interface PreviewResult { model: SceneModel; info: PreviewInfo }

export interface PreviewAsk {
  type?: string;
  id?: string;
  params: Record<string, unknown>;
  refs: Record<string, unknown>;
  after?: string | null;
  hold?: string | null;
}

export interface RefGeoItem extends RefItem { method: string; params: Record<string, unknown>; message?: string; seq: number }
export interface RefGeoList { items: RefGeoItem[]; methods: Record<string, string[]> }

export interface ConfigRow { name: string; description: string; values: Record<string, string>; suppress: Record<string, string>; materials: Record<string, string>; seq: number; default: boolean }
export interface ConfigList { active: string; configs: ConfigRow[]; suppression: Record<string, unknown>; materials_in_use: string[] }

export interface TableColumn { id: string; kind: string; key: string; label: string }
export interface TableRow { name: string; description: string; cells: Record<string, string> }
export interface DesignTable { active: string; columns: TableColumn[]; rows: TableRow[] }

export interface MaterialRow {
  name: string;
  grade?: string;
  density: number;
  youngs_modulus: number;
  poissons_ratio: number;
  provenance: string;
  single_source_fields?: string[];
  single_source?: boolean;
  origin: string;
}
export interface MaterialList { units: Record<string, string>; materials: MaterialRow[] }

export interface BodyRow {
  handle: number;
  name: string;
  material: string | null;
  summary: { valid?: boolean; closed?: boolean; solids?: number };
  visible: boolean;
}

export interface MassBody { handle: number; name: string; material: string | null; density: number | null; volume: number | null; area: number; mass: number | null; closed: boolean; valid: boolean }
export interface MassResult {
  bodies: MassBody[];
  count: number;
  cs: string;
  units: Record<string, string>;
  area: number;
  notes: string[];
  volume?: number;
  mass?: number;
  mass_basis?: string;
  centroid?: [number, number, number];
  inertia?: number[][];
  principal?: number[];
  axes?: number[][];
  inertia_cs?: number[][];
  centroid_cs?: [number, number, number];
}

export interface HoleRow { id: string; standard: string; nominal: number; pitch: number | null; source: string; status: string; note?: string; origin: string }
export interface HoleTable { notice: string; sections: { thread_series: HoleRow[] } & Record<string, unknown[]>; empty: string[]; rules: string[]; kinds: string[]; fits: string[] }

export const part = {
  tree: (id: string): Promise<PartTree> => call('GET', `${base(id)}/part`),
  types: async (id: string): Promise<TypeSchema[]> => (await call<{ types: TypeSchema[] }>('GET', `${base(id)}/part/types`)).types,
  add: (id: string, body: { type: string; params?: Record<string, unknown>; refs?: Record<string, unknown>; label?: string; after?: string | null }): Promise<Feature> => call('POST', `${base(id)}/part/features`, body),
  edit: (id: string, fid: string, body: { label?: string; params?: Record<string, unknown>; refs?: Record<string, unknown>; suppressed?: boolean }): Promise<Feature> => call('PATCH', `${base(id)}/part/features/${enc(fid)}`, body),
  remove: (id: string, fid: string, cascade: boolean, sketch = false): Promise<unknown> => call('DELETE', `${base(id)}/part/features/${enc(fid)}?cascade=${cascade ? 1 : 0}&sketch=${sketch ? 1 : 0}`),
  suppress: (id: string, fid: string, suppressed: boolean): Promise<unknown> => call('POST', `${base(id)}/part/features/${enc(fid)}/suppress`, { suppressed }),
  rollback: (id: string, to: string | null): Promise<unknown> => call('POST', `${base(id)}/part/rollback`, { to }),
  reorder: (id: string, fid: string, after: string | null): Promise<unknown> => call('POST', `${base(id)}/part/reorder`, { id: fid, after }),
  canMove: (id: string, fid: string, after: string): Promise<{ ok: boolean; message: string }> => call('GET', `${base(id)}/part/features/${enc(fid)}/canmove?after=${enc(after)}`),
  rebuild: (id: string, force = false): Promise<unknown> => call('POST', `${base(id)}/part/rebuild`, { force }),
  workspace: (id: string, workspace: string): Promise<unknown> => call('PUT', `${base(id)}/part/workspace`, { workspace }),
  sketch: (id: string, body: { name?: string; plane?: string; offset?: number; face?: Record<string, unknown>; source?: Record<string, unknown>; after?: string | null }): Promise<Feature> => call('POST', `${base(id)}/part/sketch`, body),
  enter: (id: string, fid: string): Promise<unknown> => call('POST', `${base(id)}/part/sketch/${enc(fid)}/enter`),
  exit: (id: string): Promise<unknown> => call('POST', `${base(id)}/part/sketch/exit`),
  refgeo: (id: string): Promise<RefGeoList> => call('GET', `${base(id)}/refgeo`),
  refgeoAdd: (id: string, body: Record<string, unknown>): Promise<unknown> => call('POST', `${base(id)}/refgeo`, body),
  refgeoEdit: (id: string, name: string, body: Record<string, unknown>): Promise<unknown> => call('PUT', `${base(id)}/refgeo/${enc(name)}`, body),
  refgeoRemove: (id: string, name: string): Promise<unknown> => call('DELETE', `${base(id)}/refgeo/${enc(name)}`),
  bodies: async (id: string): Promise<BodyRow[]> => (await call<{ bodies: BodyRow[] }>('GET', `${base(id)}/bodies`)).bodies,
  configs: (id: string): Promise<ConfigList> => call('GET', `${base(id)}/configs`),
  configAdd: (id: string, body: Record<string, unknown>): Promise<unknown> => call('POST', `${base(id)}/configs`, body),
  configRemove: (id: string, name: string): Promise<unknown> => call('DELETE', `${base(id)}/configs/${enc(name)}`),
  configActivate: (id: string, name: string): Promise<unknown> => call('POST', `${base(id)}/configs/${enc(name)}/activate`),
  table: (id: string): Promise<DesignTable> => call('GET', `${base(id)}/designtable`),
  tableSave: (id: string, rows: TableRow[]): Promise<unknown> => call('PUT', `${base(id)}/designtable`, { rows }),
  materials: (id: string): Promise<MaterialList> => call('GET', `${base(id)}/materials`),
  assignMaterial: (id: string, handle: number, material: string | null): Promise<unknown> => call('PUT', `${base(id)}/bodies/${handle}/material`, { material: material ?? '', refresh: true }),
  mass: (id: string, body: { handles: number[]; cs: unknown; density?: number }): Promise<MassResult> => call('POST', `${base(id)}/bodies/massprops`, body),
  holes: (): Promise<HoleTable> => call('GET', '/api/holes/table'),
};

export async function previewFeature(id: string, ask: PreviewAsk, signal: AbortSignal): Promise<PreviewResult> {
  const headers: Record<string, string> = { 'Content-Type': 'application/json' };
  const tok = token();
  if (tok) headers['X-FormCAD-Token'] = tok;
  let res: Response;
  try {
    res = await fetch(`${base(id)}/part/preview`, { method: 'POST', headers, body: JSON.stringify(ask), signal });
  } catch (e) {
    if (e instanceof DOMException && e.name === 'AbortError') throw e;
    throw new ApiError(0, 'The engine is not reachable');
  }
  if (!res.ok) {
    let message = res.statusText || `Request failed (${res.status})`;
    try {
      const data = await res.json() as { detail?: unknown };
      if (typeof data.detail === 'string') message = data.detail;
    } catch {
      message = res.statusText || message;
    }
    throw new ApiError(res.status, message);
  }
  const raw = res.headers.get('X-FormCAD-Preview') ?? '{}';
  const info = JSON.parse(decodeURIComponent(raw)) as PreviewInfo;
  const parsed = parseScene(await res.arrayBuffer());
  return { model: { rev: parsed.rev, bodies: parsed.bodies, snaps: parsed.bodies.flatMap((b) => b.snaps) }, info };
}
