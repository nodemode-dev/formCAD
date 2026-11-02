import { call } from './api';

const enc = encodeURIComponent;
const d = (id: string): string => `/api/docs/${enc(id)}`;

export interface LayerRow {
  name: string;
  on: boolean;
  frozen: boolean;
  locked: boolean;
  plot: boolean;
  color: number | string;
  linetype: string;
  lineweight: number;
  transparency: number;
  description: string;
  plot_style: string;
  new_vp_freeze: boolean;
  current: boolean;
  objects: number;
  used: boolean;
  xref: boolean;
  protected: boolean;
  colorText: string;
  lineweightText: string;
  vp_freeze?: boolean;
  vp_color?: number | string | null;
  [key: string]: unknown;
}

export interface LayerFilterInfo { name: string; kind: string; parent: string; count: number }
export interface LayerStateInfo { name: string; description: string; layers: number; current: string }
export interface LayerListing {
  layers: LayerRow[];
  total: number;
  shown: number;
  current: string;
  filter: string;
  filters: LayerFilterInfo[];
  states: LayerStateInfo[];
  viewport: number | null;
  results?: unknown[];
  skipped?: Array<{ name?: string; reason?: string; op?: string } | string>;
}
export interface LayerQuery { filter?: string; search?: string; sort?: string; desc?: boolean; viewport?: number | null }

export interface ViewRow { name: string; layout: string; space: string; center: number[]; width: number; height: number; twist: number; layerState: string }
export interface TileInfo { index: number; lowerLeft: number[]; upperRight: number[]; center: number[]; height: number; aspect: number; current: boolean }

export interface LayoutRow { name: string; order: number; paper: string; width: number; height: number; landscape: boolean; viewports: number; objects: number; current: boolean }
export interface LayoutSummary { tab: string; current: string; viewport: number; maximized: number; layouts: LayoutRow[]; rev: number; result?: Record<string, unknown> }
export interface ViewportInfo { h: number; id: number; layer: string; scale: number; scaleText: string; locked: boolean; on: boolean; clipped: boolean; annoScale: string; viewCenter: number[]; viewHeight: number; [key: string]: unknown }

export interface BlockRow { name: string; base: number[]; description: string; references: number; objects: number; attributes: number; anonymous: boolean; xref: boolean; explodable: boolean; annotative: boolean; insunits: number; uses?: string[] }
export interface AttribValue { tag: string; value: string; prompt?: string; invisible?: boolean; constant?: boolean; [key: string]: unknown }
export interface XrefRow { name: string; status: string; type: string; path: string; references?: number; found?: string; [key: string]: unknown }

const qs = (o: Record<string, unknown>): string => {
  const p = Object.entries(o).filter(([, v]) => v !== undefined && v !== null && v !== '' && v !== false).map(([k, v]) => `${k}=${enc(String(v))}`);
  return p.length ? `?${p.join('&')}` : '';
};

export const cad = {
  layers: (id: string, q: LayerQuery = {}): Promise<LayerListing> => call('GET', `${d(id)}/layers${qs({ filter: q.filter, search: q.search, sort: q.sort, desc: q.desc, viewport: q.viewport })}`),
  layerOps: (id: string, ops: Array<Record<string, unknown>>, q: LayerQuery = {}): Promise<LayerListing> => call('PUT', `${d(id)}/layers${qs({ filter: q.filter, search: q.search, sort: q.sort, desc: q.desc, viewport: q.viewport })}`, { ops }),
  layerStates: (id: string, body: Record<string, unknown>): Promise<Record<string, unknown>> => call('POST', `${d(id)}/layers/states`, body),
  layerFilters: (id: string, ops: Array<Record<string, unknown>>): Promise<Record<string, unknown>> => call('PUT', `${d(id)}/layers/filters`, { ops }),

  views: (id: string): Promise<{ views: ViewRow[]; snapshot: boolean; space: string }> => call('GET', `${d(id)}/views`),
  viewAction: (id: string, body: Record<string, unknown>): Promise<{ views: ViewRow[]; snapshot: boolean; space: string; result?: Record<string, unknown> }> => call('POST', `${d(id)}/views`, body),
  vports: (id: string): Promise<{ tiles: TileInfo[]; current: number; configs: string[] }> => call('GET', `${d(id)}/vports`),
  vportAction: (id: string, body: Record<string, unknown>): Promise<{ tiles: TileInfo[]; current: number; configs: string[] }> => call('POST', `${d(id)}/vports`, body),

  layouts: (id: string): Promise<LayoutSummary> => call('GET', `${d(id)}/layouts`),
  layoutAction: (id: string, body: Record<string, unknown>): Promise<LayoutSummary> => call('POST', `${d(id)}/layouts`, body),
  viewports: (id: string, layout?: string): Promise<{ layout: string; viewports: ViewportInfo[] }> => call('GET', `${d(id)}/viewports${qs({ layout })}`),
  setViewport: (id: string, handle: number, body: Record<string, unknown>): Promise<ViewportInfo> => call('PUT', `${d(id)}/viewports/${handle}`, body),
  space: (id: string, body: { tab?: string; viewport?: number; maximize?: boolean }): Promise<LayoutSummary> => call('POST', `${d(id)}/space`, body),
  papers: (id: string): Promise<Record<string, unknown>> => call('GET', `${d(id)}/papers`),

  blocks: (id: string, anonymous = false): Promise<{ blocks: BlockRow[] }> => call('GET', `${d(id)}/blocks${qs({ anonymous })}`),
  block: (id: string, name: string): Promise<Record<string, unknown>> => call('GET', `${d(id)}/blocks/${enc(name)}`),
  insertAttribs: (id: string, handle: number): Promise<Record<string, unknown>> => call('GET', `${d(id)}/inserts/${handle}/attributes`),
  setInsertAttribs: (id: string, handle: number, body: Record<string, unknown>): Promise<Record<string, unknown>> => call('PUT', `${d(id)}/inserts/${handle}/attributes`, body),
  blockAttribs: (id: string, name: string): Promise<Record<string, unknown>> => call('GET', `${d(id)}/blocks/${enc(name)}/attributes`),
  editBlockAttribs: (id: string, name: string, body: Record<string, unknown>): Promise<Record<string, unknown>> => call('POST', `${d(id)}/blocks/${enc(name)}/attributes`, body),

  xrefs: (id: string): Promise<{ xrefs: XrefRow[]; total: number; notes: string[] }> => call('GET', `${d(id)}/xrefs`),
  xrefAction: (id: string, body: Record<string, unknown>): Promise<Record<string, unknown>> => call('POST', `${d(id)}/xrefs`, body),
  blockEditor: (id: string): Promise<Record<string, unknown>> => call('GET', `${d(id)}/blockedit`),
};
