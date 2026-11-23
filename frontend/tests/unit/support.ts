import { vi } from 'vitest';
import type { DisplayItem, Geom, Rect } from '../../src/canvas/types';

export function seeded(seed: number): () => number {
  let a = seed >>> 0;
  return () => {
    a = (a + 0x6d2b79f5) >>> 0;
    let t = a;
    t = Math.imul(t ^ (t >>> 15), t | 1);
    t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

function inert(): unknown {
  const fn = function (): void { return undefined; };
  const proxy: unknown = new Proxy(fn, {
    get: (_t, key) => {
      if (key === 'measureText') return () => ({ width: 1, actualBoundingBoxAscent: 1, actualBoundingBoxDescent: 0 });
      if (key === 'getImageData') return () => ({ data: new Uint8ClampedArray(4) });
      if (key === 'createLinearGradient' || key === 'createRadialGradient' || key === 'createPattern') return () => ({ addColorStop: () => undefined });
      return proxy;
    },
    apply: () => undefined,
    set: () => true,
  });
  return proxy;
}

export interface TestCanvas {
  pickAt(px: number, py: number, aperturePx?: number): Array<{ handle: string | number; dist: number }>;
  boxQuery(rect: Rect, crossing: boolean): Array<string | number>;
  setView(cx: number, cy: number, height: number): void;
  worldFromScreen(px: number, py: number): [number, number];
  screenFromWorld(x: number, y: number): [number, number];
  cam: { setSize(w: number, h: number): void; scale: number };
  store: { apply(p: unknown): void };
}

export async function drawingCanvas(width: number, height: number): Promise<TestCanvas> {
  const ctx = inert();
  vi.spyOn(HTMLCanvasElement.prototype, 'getContext').mockImplementation(((kind: string) => (kind === '2d' ? ctx : null)) as never);
  const { mountCanvas } = await import('../../src/canvas/index');
  const host = document.createElement('div');
  document.body.append(host);
  const deps = {
    fetchDisplay: async () => ({ rev: 0, full: true, removed: [], items: [] }),
    fetchPicture: async () => new Blob(),
    sysvar: (_n: string, fallback: number) => fallback,
    sysvarVec: () => null,
    onSysvar: () => () => undefined,
    markerSize: () => 5,
    systemCursor: () => false,
    notify: () => undefined,
    store: () => undefined,
    stored: () => null,
  };
  const c = mountCanvas(host, deps) as unknown as TestCanvas;
  c.cam.setSize(width, height);
  return c;
}

export function item(h: string, geom: Geom, bounds: Rect, layer = '0', order = 1): DisplayItem {
  return { h, kind: geom.type, layer, color: [255, 255, 255], lw: 0, lt: null, tr: 0, order, geom, bounds };
}

export const line = (h: string, x0: number, y0: number, x1: number, y1: number, layer = '0'): DisplayItem =>
  item(h, { type: 'line', p1: [x0, y0], p2: [x1, y1] }, [Math.min(x0, x1), Math.min(y0, y1), Math.max(x0, x1), Math.max(y0, y1)], layer);

export const circle = (h: string, cx: number, cy: number, r: number): DisplayItem =>
  item(h, { type: 'circle', c: [cx, cy], r }, [cx - r, cy - r, cx + r, cy + r]);

export function show(c: TestCanvas, items: DisplayItem[], layers?: Record<string, { on?: boolean }>): void {
  c.store.apply({ rev: 1, full: true, removed: [], items, ...(layers ? { layers } : {}) });
}

export function segDist(px: number, py: number, ax: number, ay: number, bx: number, by: number): number {
  const dx = bx - ax;
  const dy = by - ay;
  const l2 = dx * dx + dy * dy;
  const t = l2 === 0 ? 0 : Math.max(0, Math.min(1, ((px - ax) * dx + (py - ay) * dy) / l2));
  return Math.hypot(px - (ax + t * dx), py - (ay + t * dy));
}

export function jsonResponse(status: number, body: unknown, statusText = ''): Response {
  return new Response(body === undefined ? null : JSON.stringify(body), { status, statusText, headers: { 'Content-Type': 'application/json' } });
}

export interface Sent { method: string; url: string; headers: Record<string, string>; body: unknown }

export function engine(answer: (method: string, url: string, body: unknown) => Response | Promise<Response>): Sent[] {
  const sent: Sent[] = [];
  vi.stubGlobal('fetch', vi.fn(async (url: string, init: RequestInit = {}) => {
    const method = (init.method ?? 'GET').toUpperCase();
    const body = typeof init.body === 'string' ? JSON.parse(init.body) : undefined;
    sent.push({ method, url: String(url), headers: { ...(init.headers as Record<string, string> | undefined) }, body });
    return answer(method, String(url), body);
  }));
  return sent;
}
