import { call } from '../io/api';

const enc = encodeURIComponent;
const base = (id: string): string => `/api/docs/${enc(id)}/sheetmetal`;

export type Pt2 = [number, number];

export type FlatSeg =
  | { t: 'line'; a: Pt2; b: Pt2 }
  | { t: 'arc'; c: Pt2; r: number; a0: number; a1: number; ccw: boolean; a: Pt2; b: Pt2 }
  | { t: 'circle'; c: Pt2; r: number; ccw: boolean }
  | { t: 'poly'; pts: Pt2[] };

export interface FlatLoop { outer: boolean; area: number; length: number; segs: FlatSeg[] }

export interface FlatBend {
  id: string;
  key: number | string;
  record: string | null;
  direction: 'up' | 'down';
  angle: number;
  angle_deg: number;
  radius: number;
  k: number;
  ba: number;
  bd: number | null;
  method: string;
  length: number;
  a: Pt2;
  b: Pt2;
  warnings: string[];
}

export interface FlatData {
  thickness: number;
  loops: FlatLoop[];
  bends: FlatBend[];
  bbox: [number, number, number, number];
  blank_area: number;
  cut_outer: number;
  cut_inner: number;
  cutouts: number;
  length: number;
  width: number;
  handle: number;
  material: string;
  warnings: string[];
}

export interface FlatState { on: boolean; flip: boolean; fixed_face: number | null; align: string; rule: Record<string, unknown> | null }
export interface FlatReply { state: FlatState; flat?: FlatData }

export interface CutBend { id: string; record: string | null; direction: string; angle: number; radius: number; k: number; ba: number; bd: number | null; length: number }
export interface CutList {
  thickness: number;
  material: string;
  bbox_length: number;
  bbox_width: number;
  blank_area: number;
  cutting_length_outside: number;
  cutting_length_inside: number;
  num_bends: number;
  num_cutouts: number;
  bends: CutBend[];
}

export interface TableSet { thickness?: number; radius?: number; points: Array<[number, number]> }
export interface BendTable {
  id?: string;
  name: string;
  mode: 'k' | 'ba' | 'bd';
  axis: 'angle' | 'ratio';
  tolerance?: number;
  source: string;
  origin?: string;
  sets: TableSet[];
}
export interface TableRow { id: string; name: string; mode: string; axis: string; sets: number; origin: string; source: string }

export interface BendRecord {
  id: string;
  feature: string;
  type: string;
  radius: number;
  thickness: number;
  angle: number;
  direction: string;
  k: number;
  ba: number;
  bd: number | null;
  method: string;
  warnings: string[];
}

export interface FlatExportBody { path: string; profile: 'cutting' | 'bending'; version: string; notes: boolean; handle?: number }
export interface FlatExportResult { path: string; profile: string; version: string; layers: string[]; outer_loops: number; inner_loops: number; bend_lines: number; units: string }

export const sheet = {
  flat: (id: string, data = true): Promise<FlatReply> => call('GET', `${base(id)}/flat?data=${data}`),
  setFlat: (id: string, body: Record<string, unknown>): Promise<FlatReply> => call('PUT', `${base(id)}/flat`, body),
  props: (id: string): Promise<CutList> => call('GET', `${base(id)}/flat/props`),
  exportFlat: (id: string, body: FlatExportBody): Promise<FlatExportResult> => call('POST', `${base(id)}/flat/export`, body),
  bends: (id: string): Promise<BendRecord[] | { bends: BendRecord[] }> => call('GET', `${base(id)}/bends`),
  rule: (id: string): Promise<Record<string, unknown> | null> => call('GET', `${base(id)}/rule`),
  tables: (id: string): Promise<TableRow[] | { tables: TableRow[] }> => call('GET', `${base(id)}/tables`),
  table: (id: string, tid: string): Promise<BendTable> => call('GET', `${base(id)}/tables/${enc(tid)}`),
  putTable: (id: string, tid: string, table: BendTable): Promise<BendTable> => call('PUT', `${base(id)}/tables/${enc(tid)}`, table),
  removeTable: (id: string, tid: string): Promise<unknown> => call('DELETE', `${base(id)}/tables/${enc(tid)}`),
};
