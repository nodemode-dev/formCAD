import type { NodeRecord } from './types';

export const NODE_W = 192;
export const HEAD_H = 26;
export const ROW_H = 20;
export const PORT_PAD = 5;
export const BODY_PAD = 4;
export const GRID = 20;
export const PORT_INSET = 9;

export interface Box { w: number; h: number }

export const portsHeight = (n: NodeRecord): number => Math.max(n.inputs.length, n.outputs.length, 1) * ROW_H + PORT_PAD * 2;

export function nodeBox(n: NodeRecord, widget: Box | null): Box {
  const body = widget ? widget.h + BODY_PAD * 2 : 0;
  return { w: Math.max(NODE_W, widget ? widget.w + BODY_PAD * 2 : 0), h: HEAD_H + portsHeight(n) + body };
}

export function portPoint(n: NodeRecord, side: 'in' | 'out', index: number, box: Box): { x: number; y: number } {
  return { x: n.x + (side === 'in' ? 0 : box.w), y: n.y + HEAD_H + PORT_PAD + index * ROW_H + ROW_H / 2 };
}

export function curve(ax: number, ay: number, bx: number, by: number): string {
  const dx = Math.max(40, Math.min(240, Math.abs(bx - ax) * 0.5 + Math.abs(by - ay) * 0.12));
  return `M${ax} ${ay}C${ax + dx} ${ay} ${bx - dx} ${by} ${bx} ${by}`;
}

export function curveDistance(ax: number, ay: number, bx: number, by: number, px: number, py: number): number {
  const dx = Math.max(40, Math.min(240, Math.abs(bx - ax) * 0.5 + Math.abs(by - ay) * 0.12));
  const x1 = ax + dx, x2 = bx - dx;
  let best = Infinity;
  let lx = ax, ly = ay;
  for (let i = 1; i <= 20; i++) {
    const t = i / 20, u = 1 - t;
    const x = u * u * u * ax + 3 * u * u * t * x1 + 3 * u * t * t * x2 + t * t * t * bx;
    const y = u * u * u * ay + 3 * u * u * t * ay + 3 * u * t * t * by + t * t * t * by;
    const vx = x - lx, vy = y - ly;
    const len = vx * vx + vy * vy;
    const s = len === 0 ? 0 : Math.max(0, Math.min(1, ((px - lx) * vx + (py - ly) * vy) / len));
    const d = Math.hypot(lx + vx * s - px, ly + vy * s - py);
    if (d < best) best = d;
    lx = x; ly = y;
  }
  return best;
}

export const snap = (v: number, on: boolean): number => (on ? Math.round(v / GRID) * GRID : v);
