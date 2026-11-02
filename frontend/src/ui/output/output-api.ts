import { ApiError, call, token, type DocSummary } from '../../io/api';

const enc = encodeURIComponent;

export interface PlotDevice { name: string; description: string; output: 'pdf' | 'png' | 'svg'; resolution: number; orientation: string; paper: string; builtin: boolean; file: string; papers: number }
export interface PaperSize { name: string; short: string; width: number; height: number }
export interface PlotDefaults {
  layout: string; model: boolean; device: string; output: 'pdf' | 'png' | 'svg'; resolution: number; paper: string;
  width: number; height: number; landscape: boolean; margins: number[]; printable: number[];
  area: string; window: number[] | null; fit: boolean; scale: number; scaleText: string; center: boolean; offset: number[];
  lineweights: boolean; transparency: boolean; displayStyles: boolean; styleTable: string; unit: string; layouts: string[]; pageSetup: PageSetupRecord | null;
}
export interface PageSetupRecord {
  device: string; paper: string; width: number; height: number; margins: number[]; landscape: boolean; plot_area: string; window: number[];
  fit: boolean; scale: number; scale_text: string; style_table: string; center: boolean; plot_lineweights: boolean; display_styles: boolean;
  transparency: boolean; offset: number[]; sheet?: number[]; printable?: number[];
}
export interface PlotJob {
  id: string; doc: string; kind: string; state: 'queued' | 'running' | 'done' | 'failed'; message: string; created: number; finished: number | null;
  output?: string; mime?: string; size?: number; path?: string; pages?: Array<{ name: string; width: number; height: number; empty: boolean }>;
}
export interface StyleTableInfo { name: string; kind: 'color' | 'named'; description: string; builtin: boolean; stored: boolean; file: string; count: number }
export interface PlotStyle {
  name: string; description: string; color: number[] | null; grayscale: boolean; screening: number; linetype: string | null; lineweight: number | null;
  cap: string; join: string; fill: string;
}
export interface StyleTable extends StyleTableInfo { styles: PlotStyle[] }
export interface LayoutList { current: string; tab: string; layouts: Array<{ name: string; paper: string; width: number; height: number; landscape: boolean; current: boolean }> }
export interface PreviewImage { url: string; width: number; height: number; dpi: number; sheet: string; sheetMm: number[]; printableMm: number[] }
export interface DwgStatus { enabled: boolean; converterPath: string; converter: string; converterKind: string; detected: { oda: string; libredwgRead: string; libredwgWrite: string }; usable: boolean; writeExperimental: boolean; message: string }
export interface FormatList { read: Array<{ ext: string; name: string }>; write: Array<{ ext: string; name: string }>; versions: string[] }
export interface Notes { notes: string[]; warnings: string[]; counts: Record<string, number>; dropped: Record<string, number>; converted: Record<string, number> }

const LONG_MS = 330000;

async function slow<T>(method: string, path: string, body: unknown): Promise<T> {
  const headers: Record<string, string> = { 'Content-Type': 'application/json' };
  const tok = token();
  if (tok) headers['X-FormCAD-Token'] = tok;
  const ctl = new AbortController();
  const timer = window.setTimeout(() => ctl.abort(), LONG_MS);
  let res: Response;
  try {
    res = await fetch(path, { method, headers, body: JSON.stringify(body), signal: ctl.signal });
  } catch (e) {
    throw new ApiError(0, e instanceof DOMException && e.name === 'AbortError' ? 'The engine did not answer in time' : 'The engine is not reachable');
  } finally {
    window.clearTimeout(timer);
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
  return await res.json() as T;
}

export const out = {
  devices: (): Promise<{ devices: PlotDevice[] }> => call('GET', '/api/plot/devices'),
  deviceDetail: (name: string): Promise<PlotDevice & { paperList: unknown[] }> => call('GET', `/api/plot/devices/${enc(name)}`),
  addDevice: (body: Record<string, unknown>): Promise<{ path: string }> => call('POST', '/api/plot/devices', body),
  papers: (): Promise<{ papers: PaperSize[]; maxSide: number }> => call('GET', '/api/plot/papers'),
  defaults: (id: string, layout: string, device = ''): Promise<PlotDefaults> => call('GET', `/api/docs/${enc(id)}/plot/defaults?layout=${enc(layout)}${device ? `&device=${enc(device)}` : ''}`),
  plot: (id: string, request: Record<string, unknown>, kind: string, wait = false): Promise<PlotJob> => call('POST', `/api/docs/${enc(id)}/plot`, { request, kind, wait }),
  job: (jobId: string): Promise<PlotJob> => call('GET', `/api/plot/jobs/${enc(jobId)}`),
  layouts: (id: string): Promise<LayoutList> => call('GET', `/api/docs/${enc(id)}/layouts`),
  pageSetup: (id: string, layout: string): Promise<PageSetupRecord> => call('GET', `/api/docs/${enc(id)}/layouts/${enc(layout)}/pagesetup`),
  setPageSetup: (id: string, layout: string, changes: Record<string, unknown>): Promise<PageSetupRecord> => call('PUT', `/api/docs/${enc(id)}/layouts/${enc(layout)}/pagesetup`, changes),
  styles: (id: string): Promise<{ tables: StyleTableInfo[] }> => call('GET', `/api/docs/${enc(id)}/plot/styles`),
  style: (id: string, name: string): Promise<StyleTable> => call('GET', `/api/docs/${enc(id)}/plot/styles/${enc(name)}`),
  styleAction: <T = Record<string, unknown>>(id: string, action: string, args: Record<string, unknown>): Promise<T> => call('POST', `/api/docs/${enc(id)}/plot/styles`, { action, args }),
  formats: (): Promise<FormatList> => call('GET', '/api/interchange/formats'),
  dwg: (): Promise<DwgStatus> => call('GET', '/api/interchange/dwg'),
  setDwg: (body: { enabled?: boolean; converter?: string }): Promise<DwgStatus> => call('PUT', '/api/interchange/dwg', body),
  openForeign: (path: string, recover = false): Promise<DocSummary & { notes?: Notes }> => slow('POST', '/api/interchange/open', { path, recover }),
  saveAs: (id: string, path: string, version = '', binary = false): Promise<DocSummary & { notes?: Notes }> => slow('POST', `/api/docs/${enc(id)}/interchange/saveas`, { path, version, binary }),
  exportFile: (id: string, path: string, version = '', binary = false): Promise<{ path: string; notes: Notes }> => slow('POST', `/api/docs/${enc(id)}/interchange/export`, { path, version, binary }),
  importFile: (id: string, path: string, recover = false): Promise<{ added: Record<string, number>; report: Notes; summary: string }> => slow('POST', `/api/docs/${enc(id)}/interchange/import`, { path, recover }),
};

export async function previewImage(id: string, request: Record<string, unknown>, signal?: AbortSignal): Promise<PreviewImage> {
  const headers: Record<string, string> = { 'Content-Type': 'application/json' };
  const tok = token();
  if (tok) headers['X-FormCAD-Token'] = tok;
  let res: Response;
  try {
    res = await fetch(`/api/docs/${enc(id)}/plot/preview`, { method: 'POST', headers, body: JSON.stringify(request), signal });
  } catch (e) {
    if (e instanceof DOMException && e.name === 'AbortError') throw e;
    throw new ApiError(0, 'The engine is not reachable');
  }
  if (!res.ok) {
    let message = res.statusText;
    try { const data = await res.json() as { detail?: unknown }; if (typeof data.detail === 'string') message = data.detail; } catch { message = res.statusText; }
    throw new ApiError(res.status, message || 'The preview failed');
  }
  const nums = (h: string | null): number[] => (h ?? '').split(',').map(Number).filter((n) => Number.isFinite(n));
  const blob = await res.blob();
  return {
    url: URL.createObjectURL(blob),
    width: Number(res.headers.get('X-Preview-Width')) || 0,
    height: Number(res.headers.get('X-Preview-Height')) || 0,
    dpi: Number(res.headers.get('X-Preview-Dpi')) || 0,
    sheet: res.headers.get('X-Sheet-Name') ?? '',
    sheetMm: nums(res.headers.get('X-Sheet-Mm')),
    printableMm: nums(res.headers.get('X-Printable-Mm')),
  };
}

export const failure = (e: unknown): string => (e instanceof ApiError || e instanceof Error ? e.message : 'The engine did not answer');
