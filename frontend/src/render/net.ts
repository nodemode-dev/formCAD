import { req, buffer, docUrl } from '../u8/net';
import { token } from '../io/api';

export interface RenderSettings {
  name?: string;
  environment: { id: string; resolution: '1k' | '2k' | '4k'; rotation: number; intensity: number; show_background: boolean; background_color: string; blur: number };
  ground: { mode: 'none' | 'floor'; color: string; roughness: number };
  quality: { samples: number; bounces: number; transmissive_bounces: number; filter_glossy: number; tiles: number; denoise: boolean; exposure: number; tone_mapping: 'neutral' | 'aces' | 'agx' | 'linear' };
  output: { width: number; height: number; transparent: boolean };
  camera: { fov: number | null; aperture: number; focus_distance: number | null };
}

export interface Limits { max_edge: number; min_edge: number; max_pixels: number; max_samples: number; max_tiles: number; limited_caller: boolean }

export interface Appearance {
  name: string;
  category: string;
  base_color: string;
  metallic: number;
  roughness: number;
  ior: number;
  transmission: number;
  thickness: number;
  clearcoat: number;
  clearcoat_roughness: number;
  sheen: number;
  sheen_roughness: number;
  sheen_color: string;
  emissive: string;
  emissive_intensity: number;
  opacity: number;
  attenuation_color: string;
  attenuation_distance: number;
  provenance: string;
  sources: Record<string, string>;
  origin?: 'shipped' | 'user';
}

export interface SourceRef { title: string; url: string; licence: string; retrieved: string }
export interface Library { sources: Record<string, SourceRef>; material_map: Record<string, { appearance: string; note: string }>; default: string; appearances: Appearance[] }

export interface EnvFile { resolution: '1k' | '2k' | '4k'; size: number; md5: string; url: string; shipped: boolean; present: boolean }
export interface EnvEntry { id: string; name: string; author: string; page: string; category: string; files: EnvFile[] }
export interface EnvListing { licence: { id: string; url: string; note: string }; shipped_resolution: string; download_hosts: string[]; environments: EnvEntry[] }

export interface RenderBodyRow {
  id: number;
  key: string;
  instance_key: string;
  name: string;
  material: string;
  appearance: Appearance;
  from: 'assigned' | 'material' | 'body colour' | 'default';
  assigned: string;
}

export interface Decal {
  name: string;
  label: string;
  body: string;
  position: [number, number, number];
  normal: [number, number, number];
  up: [number, number, number];
  size: [number, number];
  depth: number;
  kind: 'color' | 'image';
  color: string;
  image: string;
  opacity: number;
  roughness: number;
  rotation: number;
  visible: boolean;
}

export interface JobBrief {
  id: string;
  document: string;
  backend: 'page' | 'window' | 'headless';
  state: 'queued' | 'running' | 'done' | 'failed' | 'cancelled';
  message: string;
  done: number;
  total: number;
  phase: string;
  out: string;
  stats: Record<string, unknown>;
  elapsed: number;
  width: number;
  height: number;
  samples: number;
}

export interface JobSpec {
  id: string;
  document: string;
  backend: string;
  settings: Omit<RenderSettings, 'name'>;
  view: Record<string, unknown> | null;
  engine: 'path' | 'raster';
  state: string;
}

export const library = (): Promise<Library> => req('GET', '/api/render/library');
export const environments = (): Promise<EnvListing> => req('GET', '/api/render/environments');
export const limits = (): Promise<Limits> => req('GET', '/api/render/limits');
export const envBytes = (id: string, res: string): Promise<ArrayBuffer | null> => buffer(`/api/render/environments/${encodeURIComponent(id)}/${encodeURIComponent(res)}`);
export const downloadEnv = (id: string, res: string): Promise<{ downloaded: boolean; size: number }> => req('POST', `/api/render/environments/${encodeURIComponent(id)}/${encodeURIComponent(res)}/download`);
export const getSettings = (doc: string): Promise<{ settings: RenderSettings; limits: Limits }> => req('GET', docUrl(doc, 'render/settings'));
export const putSettings = (doc: string, patch: Record<string, unknown>): Promise<{ settings: RenderSettings; limits: Limits }> => req('PUT', docUrl(doc, 'render/settings'), patch);
export const renderBodies = (doc: string): Promise<{ bodies: RenderBodyRow[]; assignments: Record<string, string> }> => req('GET', docUrl(doc, 'render/bodies'));
export const assign = (doc: string, keys: string[], appearance: string | null): Promise<{ assigned: number }> => req('PUT', docUrl(doc, 'render/assign'), { keys, appearance });
export const decals = (doc: string): Promise<{ decals: Decal[] }> => req('GET', docUrl(doc, 'render/decals'));
export const addDecal = (doc: string, d: Partial<Decal> & { name: string }): Promise<Decal> => req('POST', docUrl(doc, 'render/decals'), d);
export const editDecal = (doc: string, name: string, d: Partial<Decal>): Promise<Decal> => req('PUT', docUrl(doc, `render/decals/${encodeURIComponent(name)}`), d);
export const removeDecal = (doc: string, name: string): Promise<{ removed: string }> => req('DELETE', docUrl(doc, `render/decals/${encodeURIComponent(name)}`));
export const createJob = (doc: string, body: Record<string, unknown>): Promise<JobBrief> => req('POST', docUrl(doc, 'renderjobs'), body);
export const getJob = (id: string, spec = false): Promise<JobBrief & { spec?: JobSpec }> => req('GET', `/api/render/jobs/${encodeURIComponent(id)}${spec ? '?spec=true' : ''}`);
export const jobProgress = (id: string, body: Record<string, unknown>): Promise<{ state: string; cancel: boolean }> => req('POST', `/api/render/jobs/${encodeURIComponent(id)}/progress`, body);
export const cancelJob = (id: string): Promise<JobBrief> => req('POST', `/api/render/jobs/${encodeURIComponent(id)}/cancel`);

export async function postResult(id: string, png: Blob, stats: Record<string, unknown>): Promise<JobBrief & { path: string }> {
  const headers: Record<string, string> = { 'Content-Type': 'image/png' };
  const tok = token();
  if (tok) headers['X-FormCAD-Token'] = tok;
  const res = await fetch(`/api/render/jobs/${encodeURIComponent(id)}/result?stats=${encodeURIComponent(JSON.stringify(stats))}`, { method: 'POST', headers, body: png });
  if (!res.ok) {
    let msg = res.statusText;
    try { msg = String(((await res.json()) as { detail?: unknown }).detail ?? msg); } catch { /* keep the status text */ }
    throw new Error(msg);
  }
  return await res.json() as JobBrief & { path: string };
}

export async function sceneBuffer(doc: string): Promise<ArrayBuffer> {
  const buf = await buffer(docUrl(doc, 'scene?since=0'));
  if (!buf) throw new Error('The document has no 3D data.');
  return buf;
}
