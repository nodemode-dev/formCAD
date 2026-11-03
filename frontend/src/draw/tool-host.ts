import type { CanvasApi, Pt } from '../canvas/types';
import { el, q, setHidden, setText } from '../ui/dom';
import { t } from '../ui/i18n';
import { toast } from '../ui/toast';
import type { ViewInfo } from './api';
import type { DrawOverlay } from './overlay';
import type { drawStore } from './store';

export interface Tool {
  id: string;
  title: string;
  hint(): string;
  opts?: HTMLElement;
  finishLabel?: string;
  move?(p: Pt, e: PointerEvent): void;
  click?(p: Pt, e: PointerEvent): void | Promise<void>;
  drag?(from: Pt, to: Pt, end: boolean, e: PointerEvent): void | Promise<void>;
  dblclick?(p: Pt): void | Promise<void>;
  finish?(): void | Promise<void>;
  back?(): void;
  enter?(): void;
  leave?(): void;
}

export interface ToolEnv {
  canvas: CanvasApi;
  overlay: DrawOverlay;
  store: typeof drawStore;
  host: HTMLElement;
}

export const toLocal = (v: ViewInfo, p: Pt): Pt => {
  const k = v.scale / (v.unitMm || 1);
  return [(p[0] - v.position[0]) / k, (p[1] - v.position[1]) / k];
};

export const toPaper = (v: ViewInfo, p: Pt): Pt => {
  const k = v.scale / (v.unitMm || 1);
  return [v.position[0] + p[0] * k, v.position[1] + p[1] * k];
};

export const lengthOf = (a: Pt, b: Pt): number => Math.hypot(b[0] - a[0], b[1] - a[1]);

export class ToolHost {
  active: Tool | null = null;
  private readonly title: HTMLElement;
  private readonly hintNode: HTMLElement;
  private readonly optsNode: HTMLElement;
  private readonly finishBtn: HTMLButtonElement;
  private down: { p: Pt; px: number; py: number; moved: boolean; button: number } | null = null;
  private last: Pt | null = null;
  private readonly listeners = new Set<() => void>();

  constructor(readonly env: ToolEnv) {
    const bar = env.overlay.bar;
    bar.append(
      el('<span class="dw-bar-title"></span>'),
      el('<span class="dw-bar-hint"></span>'),
      el('<span class="dw-bar-opts"></span>'),
      el<HTMLButtonElement>('<button class="dw-bar-btn" type="button" data-act="finish"></button>'),
      el<HTMLButtonElement>('<button class="dw-bar-btn" type="button" data-act="cancel"></button>'),
    );
    this.title = q(bar, '.dw-bar-title');
    this.hintNode = q(bar, '.dw-bar-hint');
    this.optsNode = q(bar, '.dw-bar-opts');
    this.finishBtn = q<HTMLButtonElement>(bar, '[data-act=finish]');
    setText(q(bar, '[data-act=cancel]'), t('Cancel'));
    bar.addEventListener('click', (e) => {
      const act = (e.target as HTMLElement).closest<HTMLElement>('[data-act]')?.dataset.act;
      if (act === 'cancel') this.cancel();
      else if (act === 'finish') void this.active?.finish?.();
    });
    bar.addEventListener('pointerdown', (e) => { e.stopPropagation(); });
    const h = env.host;
    h.addEventListener('pointerdown', (e) => this.onDown(e), true);
    h.addEventListener('pointermove', (e) => this.onMove(e), true);
    h.addEventListener('pointerup', (e) => this.onUp(e), true);
    h.addEventListener('dblclick', (e) => this.onDouble(e), true);
    h.addEventListener('contextmenu', (e) => this.onContext(e), true);
    window.addEventListener('keydown', (e) => this.onKey(e), true);
  }

  onChange(fn: () => void): () => void {
    this.listeners.add(fn);
    return () => { this.listeners.delete(fn); };
  }

  private emit(): void {
    for (const fn of this.listeners) fn();
  }

  arm(tool: Tool): void {
    if (!this.env.store.inLayout) { toast(t('Switch to a layout tab first.')); return; }
    this.disarm(false);
    this.active = tool;
    if (tool.opts && tool.opts.parentElement !== this.optsNode) this.optsNode.appendChild(tool.opts);
    for (const n of Array.from(this.optsNode.children)) setHidden(n as HTMLElement, n !== tool.opts);
    setHidden(this.optsNode, !tool.opts);
    this.finishBtn.hidden = !tool.finish;
    setText(this.finishBtn, t(tool.finishLabel ?? 'Finish'));
    this.env.overlay.showBar(true);
    this.env.host.classList.add('is-draw-tool');
    tool.enter?.();
    this.paintHint();
    this.emit();
  }

  paintHint(): void {
    const tool = this.active;
    if (!tool) return;
    setText(this.title, t(tool.title));
    setText(this.hintNode, t(tool.hint()));
  }

  disarm(announce = true): void {
    const tool = this.active;
    if (!tool) return;
    this.active = null;
    this.down = null;
    this.last = null;
    tool.leave?.();
    this.env.overlay.clearGhost();
    this.env.overlay.showBar(false);
    this.env.host.classList.remove('is-draw-tool');
    if (announce) this.emit();
  }

  cancel(): void {
    this.disarm();
  }

  private point(e: MouseEvent): Pt {
    const r = this.env.host.getBoundingClientRect();
    const w = this.env.canvas.worldFromScreen(e.clientX - r.left, e.clientY - r.top);
    return [w[0], w[1]];
  }

  private mine(e: Event): boolean {
    return !!this.active && !(e.target as Element).closest?.('.dw-ui');
  }

  private onDown(e: PointerEvent): void {
    if (!this.mine(e) || e.button !== 0) return;
    e.stopPropagation();
    e.preventDefault();
    const r = this.env.host.getBoundingClientRect();
    this.down = { p: this.point(e), px: e.clientX - r.left, py: e.clientY - r.top, moved: false, button: e.button };
  }

  private onMove(e: PointerEvent): void {
    const tool = this.active;
    if (!tool || (e.target as Element).closest?.('.dw-ui')) return;
    const p = this.point(e);
    this.last = p;
    const d = this.down;
    if (d) {
      const r = this.env.host.getBoundingClientRect();
      if (!d.moved && Math.hypot(e.clientX - r.left - d.px, e.clientY - r.top - d.py) > 5) d.moved = true;
      if (d.moved && tool.drag) { void tool.drag(d.p, p, false, e); return; }
    }
    tool.move?.(p, e);
  }

  private onUp(e: PointerEvent): void {
    const tool = this.active;
    const d = this.down;
    if (!tool || !d || e.button !== 0) return;
    this.down = null;
    e.stopPropagation();
    const p = this.point(e);
    if (d.moved && tool.drag) { void tool.drag(d.p, p, true, e); return; }
    if (tool.click) void tool.click(d.p, e);
  }

  private onDouble(e: MouseEvent): void {
    if (!this.mine(e)) return;
    e.stopPropagation();
    e.preventDefault();
    void this.active?.dblclick?.(this.point(e));
  }

  private onContext(e: MouseEvent): void {
    if (!this.mine(e)) return;
    e.stopPropagation();
    e.preventDefault();
    if (this.active?.finish) void this.active.finish();
    else this.cancel();
  }

  private onKey(e: KeyboardEvent): void {
    const tool = this.active;
    if (!tool) return;
    const typing = e.target instanceof HTMLElement && (e.target.isContentEditable || /^(INPUT|TEXTAREA|SELECT)$/.test(e.target.tagName));
    if (e.key === 'Escape') {
      e.stopImmediatePropagation();
      e.preventDefault();
      this.cancel();
    } else if (typing) {
      return;
    } else if (e.key === 'Enter' && tool.finish) {
      e.stopImmediatePropagation();
      e.preventDefault();
      void tool.finish();
    } else if (e.key === 'Backspace' && tool.back) {
      e.stopImmediatePropagation();
      e.preventDefault();
      tool.back();
    }
  }

  pointer(): Pt | null {
    return this.last;
  }
}
