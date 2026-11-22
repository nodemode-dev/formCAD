import { call } from '../io/api';
import type { Vec3 } from './types';

const enc = encodeURIComponent;

export interface CurveRow {
  handle: number;
  name: string;
  degree: number;
  periodic: boolean;
  domain: [number, number];
  poles: Vec3[];
  weights: number[];
  knots: number[];
  mults: number[];
  samples: Vec3[];
  edit_points: Vec3[];
  audit?: Record<string, unknown>;
  error?: string;
}

export interface SeamReport {
  level: string;
  g0: boolean;
  g1: boolean;
  g2: boolean;
  max_gap: number;
  max_gap_at?: Vec3;
  max_angle: number;
  max_angle_deg?: number;
  max_curvature_gap: number;
  tolerance?: { length: number; angle: number; curvature: number; curvature_relative?: number };
  hair?: Array<{ p: Vec3; gap: number; angle: number; curv?: number }>;
  bodies?: number[];
}

export interface InvalidShape { statuses?: string[]; [key: string]: unknown }

export interface ArgumentReport {
  id: string;
  valid: boolean;
  invalid: InvalidShape[];
  small_edges: unknown[];
  naked_edges: { count: number; polylines: Vec3[][] } | Vec3[][];
}

export interface BoolReport {
  op?: string;
  tol?: number;
  fuzzy?: number;
  fuzzy_used?: number;
  repaired?: boolean;
  ok?: boolean;
  message?: string;
  warnings?: string[];
  arguments?: ArgumentReport[];
  ladder?: Array<{ step: string; fuzzy: number; has_errors: boolean; has_warnings: boolean; alerts: { errors: string[]; warnings: string[] } }>;
  analysis?: { self_intersections: Array<{ status: string; faulty_first?: number; faulty_second?: number; max_distance?: number }>; small_edges: unknown[]; other: unknown[] };
  result?: { invalid?: InvalidShape[]; small_edges?: unknown[]; naked_edges?: { count: number; polylines: Vec3[][] } | Vec3[][]; valid?: boolean };
}

export interface NakedResult {
  naked_edges: { count: number; polylines: Vec3[][] } | Vec3[][];
  small_edges?: unknown[];
  check?: { valid?: boolean; invalid?: InvalidShape[] };
}

export interface LastSurface {
  seq: number;
  report: (SeamReport & BoolReport) | null;
  naked: NakedResult | null;
  mm_per_unit: number;
}

export interface ModelTolerance {
  absolute_mm: number;
  absolute_units: number;
  angular: number;
  absolute_source: string;
  angular_source: string;
  mm_per_unit: number;
}

export const fetchCurves = (doc: string, perSpan = 16): Promise<{ curves: CurveRow[] }> => call('GET', `/api/docs/${enc(doc)}/curves?per_span=${perSpan}`);
export const previewCurve = (doc: string, handle: number, grip: string, to: [number, number], perSpan = 16): Promise<{ handle: number; poles: Vec3[]; samples: Vec3[] }> => call('POST', `/api/docs/${enc(doc)}/curves/${handle}/preview`, { grip, to, per_span: perSpan });
export interface SurfaceNet {
  handle: number;
  name: string;
  version: number;
  blob: string;
  degree: [number, number];
  count: [number, number];
  poles: Vec3[];
  weights: number[];
  uknots: number[];
  vknots: number[];
  trimmed: boolean;
  reversed: boolean;
  grid: { u: number[]; v: number[]; mask: number[] };
}

export const fetchNet = (doc: string, handle: number): Promise<SurfaceNet> => call('GET', `/api/docs/${enc(doc)}/surfaces/${handle}/net`);
export const fetchLast =(doc: string): Promise<LastSurface> => call('GET', `/api/docs/${enc(doc)}/surface-last`);
export const fetchTolerance = (doc: string): Promise<ModelTolerance> => call('GET', `/api/docs/${enc(doc)}/model-tolerance`);

export const polylinesOf = (n: { count: number; polylines: Vec3[][] } | Vec3[][] | undefined | null): Vec3[][] => (!n ? [] : Array.isArray(n) ? n : n.polylines);
export const countOf = (n: { count: number; polylines: Vec3[][] } | Vec3[][] | undefined | null): number => (!n ? 0 : Array.isArray(n) ? n.length : n.count);
