import type { Rgb } from './types';

export type Rgba = [number, number, number, number];

export function parseCss(value: string, fallback: Rgba = [0, 0, 0, 1]): Rgba {
  const v = value.trim();
  if (v.startsWith('#')) {
    const h = v.slice(1);
    if (h.length === 3 || h.length === 4) {
      const n = [...h].map((c) => parseInt(c + c, 16));
      return [n[0], n[1], n[2], h.length === 4 ? n[3] / 255 : 1];
    }
    if (h.length === 6 || h.length === 8) {
      const n = parseInt(h, 16);
      return h.length === 6 ? [(n >> 16) & 255, (n >> 8) & 255, n & 255, 1] : [(n >>> 24) & 255, (n >> 16) & 255, (n >> 8) & 255, (n & 255) / 255];
    }
    return fallback;
  }
  const cs = /^color\(\s*srgb\s+([^)]+)\)/i.exec(v);
  if (cs) {
    const parts = cs[1].split(/[\s/]+/).filter(Boolean).map((s) => (s.endsWith('%') ? parseFloat(s) / 100 : parseFloat(s)));
    if (parts.length < 3 || parts.some((n) => !Number.isFinite(n))) return fallback;
    return [parts[0] * 255, parts[1] * 255, parts[2] * 255, parts.length > 3 ? parts[3] : 1];
  }
  const m = /^rgba?\(([^)]+)\)/i.exec(v);
  if (!m) return fallback;
  const parts = m[1].split(/[\s,/]+/).filter(Boolean).map((s) => (s.endsWith('%') ? (parseFloat(s) / 100) : parseFloat(s)));
  if (parts.length < 3 || parts.some((n) => !Number.isFinite(n))) return fallback;
  return [parts[0], parts[1], parts[2], parts.length > 3 ? parts[3] : 1];
}

export const luminance = (c: Rgb | Rgba): number => (0.2126 * c[0] + 0.7152 * c[1] + 0.0722 * c[2]) / 255;

export const isDark = (c: Rgb | Rgba): boolean => luminance(c) < 0.5;

export function opacityOf(tr: number, enabled: boolean): number {
  if (!enabled) return 255;
  const t = Math.max(0, Math.min(90, Math.round(tr * 100)));
  return Math.floor((255 * (100 - t) + 50) / 100);
}

export function pack(r: number, g: number, b: number, a: number): number {
  const k = a / 255;
  return ((a & 255) << 24 | (Math.round(b * k) & 255) << 16 | (Math.round(g * k) & 255) << 8 | (Math.round(r * k) & 255)) >>> 0;
}

export function packRaw(r: number, g: number, b: number, a: number): number {
  return ((a & 255) << 24 | (b & 255) << 16 | (g & 255) << 8 | (r & 255)) >>> 0;
}

export function css(c: Rgba | Rgb, alpha?: number): string {
  const a = alpha ?? (c.length > 3 ? (c as Rgba)[3] : 1);
  return `rgba(${Math.round(c[0])},${Math.round(c[1])},${Math.round(c[2])},${+a.toFixed(3)})`;
}
