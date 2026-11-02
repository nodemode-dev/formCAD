import { css, luminance } from './color';
import { tipBox } from './overlay';
import type { Theme } from './theme';
import type { CursorMode } from './types';

export type ChromePart = 'top' | 'home' | 'ring' | 'wcs' | 'ucs' | 'menu' | null;

export interface MenuRow { id: string; label: string; checked?: boolean }

interface Menu { x: number; y: number; w: number; rows: MenuRow[]; hover: number; owner: 'cube' | 'ucs' }

const CUBE_RIGHT = 92;
const CUBE_TOP = 82;
const RING_R = 58;
const RING_W = 9;
const FACE = 44;
const PILL_W = 56;
const PILL_H = 16;
const PILL_DY = 84;
const UCS_LEFT = 36;
const UCS_BOTTOM = 34;
const UCS_ARM = 60;
const ROW_H = 24;

export const TIPS: Record<string, string> = {
  top: 'Top view: zoom to extents',
  home: 'Zoom to the drawing extents',
  ring: 'View rotation is not available in the plan view',
  wcs: 'Coordinate system',
  ucs: 'Coordinate system',
};

export class Chrome {
  cube = true;
  ucs = true;
  hover: ChromePart = null;
  private menu: Menu | null = null;
  private width = 1;
  private height = 1;

  resize(w: number, h: number): void {
    this.width = w;
    this.height = h;
  }

  private cubeCentre(): [number, number] { return [this.width - CUBE_RIGHT, CUBE_TOP]; }

  private homeCentre(): [number, number] {
    const [cx, cy] = this.cubeCentre();
    return [cx - RING_R * Math.SQRT1_2, cy - RING_R * Math.SQRT1_2];
  }

  private pillRect(): [number, number, number, number] {
    const [cx, cy] = this.cubeCentre();
    return [cx - PILL_W / 2, cy + PILL_DY - PILL_H / 2, PILL_W, PILL_H];
  }

  private ucsOrigin(): [number, number] { return [UCS_LEFT, this.height - UCS_BOTTOM]; }

  hit(px: number, py: number): ChromePart {
    if (this.menu) {
      const m = this.menu;
      if (px >= m.x && px <= m.x + m.w && py >= m.y && py <= m.y + m.rows.length * ROW_H) return 'menu';
    }
    if (this.cube && this.width > 320 && this.height > 240) {
      const [cx, cy] = this.cubeCentre();
      const [hx, hy] = this.homeCentre();
      if (Math.hypot(px - hx, py - hy) <= 11) return 'home';
      if (Math.abs(px - cx) <= FACE / 2 && Math.abs(py - cy) <= FACE / 2) return 'top';
      const d = Math.hypot(px - cx, py - cy);
      if (d >= RING_R - RING_W / 2 - 1 && d <= RING_R + RING_W / 2 + 1) return 'ring';
      const [rx, ry, rw, rh] = this.pillRect();
      if (px >= rx && px <= rx + rw && py >= ry && py <= ry + rh) return 'wcs';
    }
    if (this.ucs && this.height > 160) {
      const [ox, oy] = this.ucsOrigin();
      const nearX = px >= ox - 6 && px <= ox + UCS_ARM + 14 && Math.abs(py - oy) <= 8;
      const nearY = py <= oy + 6 && py >= oy - UCS_ARM - 14 && Math.abs(px - ox) <= 8;
      if (nearX || nearY) return 'ucs';
    }
    return null;
  }

  openMenu(owner: 'cube' | 'ucs', px: number, py: number, rows: MenuRow[]): void {
    const w = 168;
    this.menu = { x: Math.min(px, this.width - w - 4), y: Math.min(py, this.height - rows.length * ROW_H - 4), w, rows, hover: -1, owner };
  }

  closeMenu(): boolean {
    const was = this.menu !== null;
    this.menu = null;
    return was;
  }

  get menuOpen(): boolean { return this.menu !== null; }

  menuHover(px: number, py: number): void {
    const m = this.menu;
    if (!m) return;
    const i = Math.floor((py - m.y) / ROW_H);
    m.hover = px >= m.x && px <= m.x + m.w && i >= 0 && i < m.rows.length ? i : -1;
  }

  menuPick(px: number, py: number): string | null {
    const m = this.menu;
    if (!m) return null;
    const i = Math.floor((py - m.y) / ROW_H);
    if (px < m.x || px > m.x + m.w || i < 0 || i >= m.rows.length) return null;
    return m.rows[i].id;
  }

  draw(ctx: CanvasRenderingContext2D, th: Theme, pointer: { px: number; py: number } | null): void {
    const ink = luminance(th.bg) < 0.5 ? 'rgba(232,232,236,' : 'rgba(30,32,38,';
    if (this.cube && this.width > 320 && this.height > 240) this.drawCube(ctx, ink);
    if (this.ucs && this.height > 160) this.drawUcs(ctx, th, ink);
    if (this.menu) this.drawMenu(ctx, th);
    else if (this.hover && this.hover !== 'menu' && pointer) tipBox(ctx, pointer.px + 14, pointer.py + 16, TIPS[this.hover], 'rgb(236,236,240)', 'rgb(40,40,48)');
  }

  private drawCube(ctx: CanvasRenderingContext2D, ink: string): void {
    const [cx, cy] = this.cubeCentre();
    const hv = this.hover;
    ctx.setLineDash([]);
    ctx.lineWidth = 1;
    ctx.beginPath();
    ctx.arc(cx, cy, RING_R + RING_W / 2, 0, Math.PI * 2);
    ctx.strokeStyle = `${ink}0.35)`;
    ctx.stroke();
    ctx.beginPath();
    ctx.arc(cx, cy, RING_R, 0, Math.PI * 2);
    ctx.lineWidth = RING_W;
    ctx.strokeStyle = `${ink}${hv === 'ring' ? 0.28 : 0.14})`;
    ctx.stroke();
    ctx.lineWidth = 1;
    ctx.font = '600 10px Inter, system-ui, sans-serif';
    ctx.textAlign = 'center';
    ctx.textBaseline = 'middle';
    ctx.fillStyle = `${ink}0.85)`;
    ctx.fillText('N', cx, cy - RING_R);
    ctx.fillText('E', cx + RING_R, cy);
    ctx.fillText('S', cx, cy + RING_R);
    ctx.fillText('W', cx - RING_R, cy);
    ctx.fillStyle = `${ink}${hv === 'top' ? 0.3 : 0.16})`;
    ctx.strokeStyle = `${ink}0.55)`;
    ctx.fillRect(cx - FACE / 2, cy - FACE / 2, FACE, FACE);
    ctx.strokeRect(cx - FACE / 2 + 0.5, cy - FACE / 2 + 0.5, FACE - 1, FACE - 1);
    ctx.fillStyle = `${ink}0.9)`;
    ctx.fillText('TOP', cx, cy);
    const [hx, hy] = this.homeCentre();
    ctx.fillStyle = `${ink}${hv === 'home' ? 0.3 : 0.16})`;
    ctx.beginPath();
    ctx.arc(hx, hy, 10, 0, Math.PI * 2);
    ctx.fill();
    ctx.strokeStyle = `${ink}0.9)`;
    ctx.lineWidth = 1.4;
    ctx.beginPath();
    ctx.moveTo(hx - 5, hy);
    ctx.lineTo(hx, hy - 5);
    ctx.lineTo(hx + 5, hy);
    ctx.moveTo(hx - 3.5, hy - 0.5);
    ctx.lineTo(hx - 3.5, hy + 4.5);
    ctx.lineTo(hx + 3.5, hy + 4.5);
    ctx.lineTo(hx + 3.5, hy - 0.5);
    ctx.stroke();
    const [rx, ry, rw, rh] = this.pillRect();
    ctx.fillStyle = `${ink}${hv === 'wcs' ? 0.28 : 0.14})`;
    ctx.beginPath();
    ctx.roundRect(rx, ry, rw, rh, rh / 2);
    ctx.fill();
    ctx.fillStyle = `${ink}0.9)`;
    ctx.font = '600 9px Inter, system-ui, sans-serif';
    ctx.textAlign = 'left';
    ctx.fillText('WCS', rx + 9, ry + rh / 2 + 0.5);
    ctx.strokeStyle = `${ink}0.9)`;
    ctx.lineWidth = 1.2;
    ctx.beginPath();
    ctx.moveTo(rx + rw - 14, ry + rh / 2 - 1.5);
    ctx.lineTo(rx + rw - 10.5, ry + rh / 2 + 1.5);
    ctx.lineTo(rx + rw - 7, ry + rh / 2 - 1.5);
    ctx.stroke();
    ctx.textAlign = 'start';
  }

  private drawUcs(ctx: CanvasRenderingContext2D, th: Theme, ink: string): void {
    const [ox, oy] = this.ucsOrigin();
    const hot = this.hover === 'ucs';
    ctx.setLineDash([]);
    ctx.lineWidth = hot ? 2 : 1;
    ctx.strokeStyle = css(th.axisX);
    ctx.beginPath();
    ctx.moveTo(ox, oy + 0.5);
    ctx.lineTo(ox + UCS_ARM, oy + 0.5);
    ctx.stroke();
    ctx.strokeStyle = css(th.axisY);
    ctx.beginPath();
    ctx.moveTo(ox + 0.5, oy);
    ctx.lineTo(ox + 0.5, oy - UCS_ARM);
    ctx.stroke();
    ctx.lineWidth = 1;
    ctx.strokeStyle = `${ink}0.8)`;
    ctx.strokeRect(ox + 0.5, oy - 8.5, 9, 9);
    ctx.font = '600 10px Inter, system-ui, sans-serif';
    ctx.fillStyle = `${ink}0.9)`;
    ctx.textBaseline = 'middle';
    ctx.textAlign = 'center';
    ctx.fillText('X', ox + UCS_ARM + 9, oy);
    ctx.fillText('Y', ox, oy - UCS_ARM - 9);
    ctx.textAlign = 'start';
  }

  private drawMenu(ctx: CanvasRenderingContext2D, th: Theme): void {
    const m = this.menu;
    if (!m) return;
    ctx.setLineDash([]);
    ctx.fillStyle = css(th.panel);
    ctx.strokeStyle = css(th.line);
    ctx.lineWidth = 1;
    ctx.beginPath();
    ctx.roundRect(m.x + 0.5, m.y + 0.5, m.w, m.rows.length * ROW_H, 6);
    ctx.fill();
    ctx.stroke();
    ctx.font = '12px Inter, system-ui, sans-serif';
    ctx.textBaseline = 'middle';
    m.rows.forEach((r, i) => {
      const y = m.y + i * ROW_H;
      if (i === m.hover) {
        ctx.fillStyle = css(th.accent, 0.22);
        ctx.fillRect(m.x + 3, y + 2, m.w - 5, ROW_H - 3);
      }
      ctx.fillStyle = css(th.text);
      if (r.checked) {
        ctx.beginPath();
        ctx.arc(m.x + 12, y + ROW_H / 2, 3, 0, Math.PI * 2);
        ctx.fill();
      }
      ctx.fillText(r.label, m.x + 24, y + ROW_H / 2 + 0.5);
    });
  }
}

export interface CursorOptions {
  sizePct: number;
  pickbox: number;
  mode: CursorMode;
  dark: boolean;
  x: number;
  y: number;
  width: number;
  height: number;
  iso?: number[] | null;
}

export function drawCursor(ctx: CanvasRenderingContext2D, o: CursorOptions): void {
  if (o.mode === 'none') return;
  if (o.iso && o.mode !== 'pick') {
    const r = Math.max(12, (o.sizePct / 100) * o.height);
    ctx.setLineDash([]);
    ctx.lineWidth = 1;
    ctx.strokeStyle = o.dark ? 'rgb(232,232,232)' : 'rgb(32,32,32)';
    ctx.beginPath();
    for (const a of o.iso) {
      const dx = Math.cos((a * Math.PI) / 180) * r;
      const dy = -Math.sin((a * Math.PI) / 180) * r;
      ctx.moveTo(o.x - dx, o.y - dy);
      ctx.lineTo(o.x + dx, o.y + dy);
    }
    ctx.stroke();
    return;
  }
  const arm = Math.max(12, (o.sizePct / 100) * o.height);
  const half = o.mode === 'pick' ? o.pickbox * 1.5 : 0;
  const x = Math.round(o.x) + 0.5;
  const y = Math.round(o.y) + 0.5;
  ctx.setLineDash([]);
  ctx.lineWidth = 1;
  ctx.strokeStyle = o.dark ? 'rgb(232,232,232)' : 'rgb(32,32,32)';
  ctx.beginPath();
  if (half >= 1) {
    ctx.moveTo(x - arm, y);
    ctx.lineTo(x - half, y);
    ctx.moveTo(x + half, y);
    ctx.lineTo(x + arm, y);
    ctx.moveTo(x, y - arm);
    ctx.lineTo(x, y - half);
    ctx.moveTo(x, y + half);
    ctx.lineTo(x, y + arm);
    ctx.rect(x - half, y - half, half * 2, half * 2);
  } else {
    ctx.moveTo(x - arm, y);
    ctx.lineTo(x + arm, y);
    ctx.moveTo(x, y - arm);
    ctx.lineTo(x, y + arm);
  }
  ctx.stroke();
}
