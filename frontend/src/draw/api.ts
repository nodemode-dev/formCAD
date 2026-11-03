import { api, call } from '../io/api';

const enc = encodeURIComponent;
const base = (id: string): string => `/api/docs/${enc(id)}/drawviews`;

export type Pt2 = [number, number];
export type ViewType = 'base' | 'projected' | 'auxiliary' | 'section' | 'detail' | 'broken' | 'crop';
export type Status = 'ok' | 'stale' | 'error' | 'empty';

export interface ViewState {
  status: Status;
  message: string;
  sig: string;
  ms: number;
  mode_used?: string;
  built_rev?: number;
  stats?: { faces?: number; hlr_ms?: number; attr_ms?: number; total_ms?: number; section_kind?: string; attributed?: number };
}

export interface BreakSpec { axis: 'x' | 'y'; lo: number; hi: number; gap: number; style: 'zigzag' | 'straight' }

export interface ViewInfo {
  handle: number;
  name: string;
  label: string;
  vtype: ViewType;
  layout: string;
  source: { doc: string; component: string; config: string };
  vnormal: number[];
  vup: number[];
  scale: number;
  scaleText: string;
  position: Pt2;
  origin: number[];
  parent: number;
  align: string | number[];
  section: { kind?: string; line?: Pt2[]; flip?: boolean; letter?: string };
  detail: { center?: Pt2; radius?: number; letter?: string };
  broken: { breaks?: BreakSpec[] };
  crop: { polygon?: Pt2[] };
  show: { hidden: boolean; tangent: boolean; silhouette: boolean; seam: boolean; hatch: boolean; label: boolean };
  style: Record<string, unknown>;
  mode: 'exact' | 'draft' | 'auto';
  auto: boolean;
  state: ViewState;
  bounds: [number, number, number, number];
  counts: Record<string, number>;
  unitMm: number;
}

export interface ViewListing { views: ViewInfo[]; projection: Record<string, 'first' | 'third'> }

export const dv = {
  list: (id: string, layout = ''): Promise<ViewListing> => call('GET', `${base(id)}${layout ? `?layout=${enc(layout)}` : ''}`),
  create: (id: string, body: Record<string, unknown>): Promise<ViewInfo> => call('POST', base(id), body),
  patch: (id: string, handle: number, body: Record<string, unknown>): Promise<ViewInfo> => call('PATCH', `${base(id)}/${handle}`, body),
  remove: (id: string, handle: number, cascade = false): Promise<{ deleted: number[] }> => call('DELETE', `${base(id)}/${handle}?cascade=${cascade}`),
  update: (id: string, handle: number): Promise<ViewInfo> => call('POST', `${base(id)}/${handle}/update`, {}),
  updateAll: (id: string, all: boolean): Promise<{ updated: number[] }> => call('POST', `${base(id)}/update`, { all }),
  projection: (id: string, layout: string, system: 'first' | 'third'): Promise<{ layout: string; projection: string }> => call('PUT', `${base(id)}/projection`, { layout, system }),
  run: (id: string, command: string, args: Record<string, unknown>): Promise<unknown> => api.runCommand(id, command, args),
};

export const messageOf = (e: unknown): string => (e instanceof Error ? e.message : 'The engine did not answer');
