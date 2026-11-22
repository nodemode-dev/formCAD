import { el, q, setClass, setHidden, setStyleVar, setText, store, stored } from './dom';
import { icon } from './icons';
import { onLanguage, t } from './i18n';

export interface DockPanel {
  id: string;
  label: string;
  icon: string;
  order?: number;
  grow?: boolean;
  build: (body: HTMLElement) => { show?: () => void } | void;
}

export interface DockDeps {
  width: () => number;
  preview: (px: number) => void;
  commit: (px: number) => void;
}

interface Group {
  panel: DockPanel;
  root: HTMLElement;
  head: HTMLButtonElement;
  body: HTMLElement;
  api: { show?: () => void } | void;
  strip: HTMLButtonElement;
}

export const DOCK_MIN = 240;
export const DOCK_MAX = 560;
const STATE_KEY = 'formCAD.dockGroups';
const COLLAPSE_KEY = 'formCAD.dockCollapsed';
const ORDER_KEY = 'formCAD.dockOrder';
const HEIGHT_KEY = 'formCAD.dockHeights';
const GROUP_MIN = 96;
const DRAG_START = 6;

function loadOrder(): string[] {
  try {
    const v: unknown = JSON.parse(stored(ORDER_KEY) ?? '[]');
    return Array.isArray(v) ? v.filter((x): x is string => typeof x === 'string') : [];
  } catch {
    return [];
  }
}

function loadHeights(): Record<string, number> {
  try {
    const v: unknown = JSON.parse(stored(HEIGHT_KEY) ?? '{}');
    if (!v || typeof v !== 'object') return {};
    const out: Record<string, number> = {};
    for (const [k, px] of Object.entries(v as Record<string, unknown>)) if (typeof px === 'number' && Number.isFinite(px) && px >= GROUP_MIN) out[k] = Math.round(px);
    return out;
  } catch {
    return {};
  }
}

const pending: DockPanel[] = [];
let live: Dock | null = null;

export function registerDockPanel(panel: DockPanel): void {
  if (live) live.add(panel);
  else if (!pending.some((p) => p.id === panel.id)) pending.push(panel);
}

function loadState(): Record<string, boolean> {
  try {
    const v: unknown = JSON.parse(stored(STATE_KEY) ?? '{}');
    if (!v || typeof v !== 'object') return {};
    const out: Record<string, boolean> = {};
    for (const [k, folded] of Object.entries(v as Record<string, unknown>)) if (typeof folded === 'boolean') out[k] = folded;
    return out;
  } catch {
    return {};
  }
}

const clampWidth = (n: number): number => Math.min(DOCK_MAX, Math.max(DOCK_MIN, Math.round(n)));

export class Dock {
  private readonly groups = new Map<string, Group>();
  private readonly column: HTMLElement;
  private readonly grip: HTMLElement;
  private folded: Record<string, boolean> = loadState();
  private readonly strip: HTMLElement;
  private readonly fly: HTMLElement;
  private readonly collapseBtn: HTMLButtonElement;
  private flyOpen: { g: Group; mark: Comment } | null = null;
  private order: string[] = loadOrder();
  private heights: Record<string, number> = loadHeights();
  private readonly dropLine: HTMLElement;
  private justMoved = false;

  constructor(private readonly host: HTMLElement, private readonly deps: DockDeps) {
    this.grip = el('<div class="cv-dock-grip" role="separator" aria-orientation="vertical" aria-label="Resize panels" tabindex="0"></div>');
    this.column = el('<div class="cv-dock-column"></div>');
    this.dropLine = el('<div class="cv-drop-line" aria-hidden="true"></div>');
    this.column.appendChild(this.dropLine);
    this.strip = el('<div class="cv-dock-strip" role="toolbar" aria-orientation="vertical"></div>');
    const expand = el<HTMLButtonElement>(`<button class="cv-strip-btn cv-strip-expand" type="button">${icon('collapseLeft', 16)}</button>`);
    this.strip.append(expand);
    this.fly = el('<div class="cv-dock-fly" hidden></div>');
    this.collapseBtn = el<HTMLButtonElement>(`<button class="cv-group-collapse" type="button">${icon('collapseRight', 14)}</button>`);
    const paintTitles = (): void => {
      for (const [b, text] of [[expand, t('Expand panels')], [this.collapseBtn, t('Collapse to icons')]] as const) { b.title = text; if (b.getAttribute('aria-label') !== text) b.setAttribute('aria-label', text); }
    };
    paintTitles();
    onLanguage(paintTitles);
    expand.addEventListener('click', () => this.setCollapsed(false));
    this.collapseBtn.addEventListener('click', () => this.setCollapsed(true));
    setClass(host, 'is-collapsed', stored(COLLAPSE_KEY) === '1');
    host.append(this.grip, this.strip, this.column);
    (document.getElementById('overlay-root') ?? document.body).append(this.fly);
    document.addEventListener('pointerdown', (e) => { if (this.flyOpen && !this.fly.contains(e.target as Node) && !this.strip.contains(e.target as Node)) this.closeFly(); }, true);
    document.addEventListener('keydown', (e) => { if (this.flyOpen && e.key === 'Escape') this.closeFly(); });
    this.bindGrip();
    live = this;
    for (const p of pending.splice(0)) this.add(p);
  }

  add(panel: DockPanel): void {
    if (this.groups.has(panel.id)) return;
    const root = el(`<section class="cv-group" data-panel="${panel.id}"><button class="cv-group-head" type="button" aria-expanded="true"><span class="cv-group-grip" aria-hidden="true">${icon('grip', 14)}</span><span class="cv-group-icon">${icon(panel.icon, 16)}</span><span class="cv-group-label"></span><span class="cv-group-chev">${icon('chevronDown', 12)}</span></button><div class="cv-group-body"></div><div class="cv-dock-split" role="separator" aria-orientation="horizontal" tabindex="0"></div></section>`);
    const head = q<HTMLButtonElement>(root, '.cv-group-head');
    const body = q(root, '.cv-group-body');
    const label = q(root, '.cv-group-label');
    const strip = el<HTMLButtonElement>(`<button class="cv-strip-btn" type="button" data-strip="${panel.id}">${icon(panel.icon, 18)}</button>`);
    const split = q(root, '.cv-dock-split');
    const paint = (): void => {
      setText(label, t(panel.label));
      head.title = t(panel.label);
      strip.title = t(panel.label);
      if (strip.getAttribute('aria-label') !== t(panel.label)) strip.setAttribute('aria-label', t(panel.label));
      const resize = `${t('Resize')} ${t(panel.label)}`;
      if (split.getAttribute('aria-label') !== resize) split.setAttribute('aria-label', resize);
    };
    paint();
    onLanguage(paint);
    setClass(root, 'is-grow', !!panel.grow);
    const group: Group = { panel, root, head, body, api: undefined, strip };
    this.groups.set(panel.id, group);
    group.api = panel.build(body);
    head.addEventListener('click', (e) => {
      if (this.justMoved) { this.justMoved = false; e.preventDefault(); return; }
      this.fold(panel.id);
    });
    strip.addEventListener('click', () => this.toggleFly(group));
    this.bindMove(group, q(root, '.cv-group-grip'));
    this.bindSplit(group, split);
    this.place(group);
    this.paint(group);
  }

  private rank(g: Group): number {
    const at = this.order.indexOf(g.panel.id);
    return at >= 0 ? at : 10000 + (g.panel.order ?? 100);
  }

  private sized(g: Group): number {
    return this.heights[g.panel.id] ?? 0;
  }

  private setHeight(g: Group, px: number, save: boolean): void {
    const next = px > 0 ? Math.max(GROUP_MIN, Math.round(px)) : 0;
    if (next) this.heights = { ...this.heights, [g.panel.id]: next };
    else { const { [g.panel.id]: _gone, ...rest } = this.heights; this.heights = rest; }
    if (save) store(HEIGHT_KEY, JSON.stringify(this.heights));
    this.paint(g);
  }

  private bindSplit(g: Group, split: HTMLElement): void {
    split.addEventListener('pointerdown', (e) => {
      if (e.button !== 0) return;
      e.preventDefault();
      const y0 = e.clientY, h0 = g.root.getBoundingClientRect().height;
      let last = h0;
      split.setPointerCapture(e.pointerId);
      setClass(split, 'is-dragging', true);
      const move = (ev: PointerEvent): void => {
        last = Math.min(this.column.clientHeight, h0 + (ev.clientY - y0));
        this.setHeight(g, last, false);
      };
      const up = (): void => {
        split.removeEventListener('pointermove', move);
        split.removeEventListener('pointerup', up);
        split.removeEventListener('pointercancel', up);
        setClass(split, 'is-dragging', false);
        this.setHeight(g, last, true);
      };
      split.addEventListener('pointermove', move);
      split.addEventListener('pointerup', up);
      split.addEventListener('pointercancel', up);
    });
    split.addEventListener('keydown', (e) => {
      const step = e.key === 'ArrowUp' ? -16 : e.key === 'ArrowDown' ? 16 : 0;
      if (!step) return;
      e.preventDefault();
      this.setHeight(g, (this.sized(g) || g.root.getBoundingClientRect().height) + step, true);
    });
    split.addEventListener('dblclick', () => this.setHeight(g, 0, true));
  }

  private slotAt(y: number, moving: Group): { before: Group | null; top: number } {
    const rest = Array.from(this.groups.values()).filter((g) => g !== moving && g.root.parentElement === this.column).sort((a, b) => this.rank(a) - this.rank(b));
    const base = this.column.getBoundingClientRect().top - this.column.scrollTop;
    for (const g of rest) {
      const r = g.root.getBoundingClientRect();
      if (y < r.top + r.height / 2) return { before: g, top: r.top - base };
    }
    const end = rest[rest.length - 1]?.root.getBoundingClientRect();
    return { before: null, top: end ? end.bottom - base : 0 };
  }

  private bindMove(g: Group, grip: HTMLElement): void {
    grip.addEventListener('pointerdown', (e) => {
      if (e.button !== 0 || this.isCollapsed()) return;
      const y0 = e.clientY;
      let moving = false, slot: { before: Group | null; top: number } | null = null;
      const move = (ev: PointerEvent): void => {
        if (!moving && Math.abs(ev.clientY - y0) < DRAG_START) return;
        if (!moving) { moving = true; setClass(g.root, 'is-moving', true); setClass(this.column, 'is-arranging', true); }
        slot = this.slotAt(ev.clientY, g);
        this.dropLine.style.transform = `translateY(${Math.round(slot.top)}px)`;
        setClass(this.dropLine, 'is-shown', true);
      };
      const up = (ev: PointerEvent): void => {
        document.removeEventListener('pointermove', move, true);
        document.removeEventListener('pointerup', up, true);
        document.removeEventListener('pointercancel', up, true);
        setClass(this.dropLine, 'is-shown', false);
        setClass(g.root, 'is-moving', false);
        setClass(this.column, 'is-arranging', false);
        if (!moving) return;
        this.justMoved = true;
        window.setTimeout(() => { this.justMoved = false; }, 0);
        if (ev.type === 'pointercancel' || !slot) return;
        this.moveBefore(g, slot.before);
      };
      document.addEventListener('pointermove', move, true);
      document.addEventListener('pointerup', up, true);
      document.addEventListener('pointercancel', up, true);
    });
  }

  private moveBefore(g: Group, before: Group | null): void {
    const ids = Array.from(this.groups.values()).filter((x) => x !== g).sort((a, b) => this.rank(a) - this.rank(b)).map((x) => x.panel.id);
    const at = before ? ids.indexOf(before.panel.id) : ids.length;
    ids.splice(at < 0 ? ids.length : at, 0, g.panel.id);
    if (ids.join('|') === Array.from(this.groups.values()).sort((a, b) => this.rank(a) - this.rank(b)).map((x) => x.panel.id).join('|')) return;
    this.order = ids;
    store(ORDER_KEY, JSON.stringify(ids));
    this.place(g);
  }

  has(id: string): boolean {
    return this.groups.has(id);
  }

  ids(): string[] {
    return Array.from(this.groups.keys());
  }

  isFolded(id: string): boolean {
    return !!this.folded[id];
  }

  fold(id: string, folded?: boolean): void {
    const g = this.groups.get(id);
    if (!g) return;
    this.folded = { ...this.folded, [id]: folded ?? !this.folded[id] };
    store(STATE_KEY, JSON.stringify(this.folded));
    this.paint(g);
  }

  reveal(id: string): void {
    const g = this.groups.get(id);
    if (!g) return;
    if (this.isCollapsed()) this.setCollapsed(false);
    this.fold(id, false);
    g.root.scrollIntoView({ block: 'nearest' });
  }

  resetLayout(): void {
    this.folded = {};
    this.order = [];
    this.heights = {};
    store(STATE_KEY, '{}');
    store(ORDER_KEY, '[]');
    store(HEIGHT_KEY, '{}');
    for (const g of Array.from(this.groups.values()).sort((a, b) => this.rank(a) - this.rank(b))) { this.place(g); this.paint(g); }
    this.deps.commit(300);
  }

  private place(group: Group): void {
    const rank = this.rank(group);
    const next = Array.from(this.groups.values()).filter((g) => g !== group && this.rank(g) > rank).sort((a, b) => this.rank(a) - this.rank(b))[0];
    const rootAt = next ? next.root : this.dropLine;
    const stripAt = next ? next.strip : null;
    if (group.root.nextElementSibling !== rootAt || group.root.parentElement !== this.column) this.column.insertBefore(group.root, rootAt);
    if (group.strip.nextElementSibling !== stripAt || group.strip.parentElement !== this.strip) this.strip.insertBefore(group.strip, stripAt);
    const first = this.column.firstElementChild;
    if (first && this.collapseBtn.parentElement !== first) first.appendChild(this.collapseBtn);
  }

  isCollapsed(): boolean {
    return this.host.classList.contains('is-collapsed');
  }

  setCollapsed(on: boolean): void {
    this.closeFly();
    store(COLLAPSE_KEY, on ? '1' : '0');
    setClass(this.host, 'is-collapsed', on);
  }

  private toggleFly(g: Group): void {
    const same = this.flyOpen?.g === g;
    this.closeFly();
    if (same) return;
    const mark = document.createComment(g.panel.id);
    g.root.replaceWith(mark);
    this.fly.appendChild(g.root);
    this.fly.style.visibility = 'hidden';
    setHidden(this.fly, false);
    this.flyOpen = { g, mark };
    setClass(g.strip, 'is-on', true);
    const r = g.strip.getBoundingClientRect(), st = this.strip.getBoundingClientRect();
    this.fly.style.right = `${Math.round(window.innerWidth - st.left + 6)}px`;
    this.fly.style.top = `${Math.round(Math.max(8, Math.min(r.top, window.innerHeight - this.fly.offsetHeight - 8)))}px`;
    this.fly.style.visibility = '';
    if (g.api && g.api.show) g.api.show();
  }

  private closeFly(): void {
    const o = this.flyOpen;
    if (!o) return;
    this.flyOpen = null;
    o.mark.replaceWith(o.g.root);
    setClass(o.g.strip, 'is-on', false);
    setHidden(this.fly, true);
  }

  private paint(g: Group): void {
    const folded = !!this.folded[g.panel.id];
    const h = folded ? 0 : this.sized(g);
    setClass(g.root, 'is-folded', folded);
    setClass(g.root, 'is-sized', h > 0);
    setStyleVar(g.root, '--group-h', h > 0 ? `${h}px` : '');
    setHidden(g.body, folded);
    g.head.setAttribute('aria-expanded', String(!folded));
    if (!folded && g.api && g.api.show) g.api.show();
  }

  private bindGrip(): void {
    this.grip.addEventListener('pointerdown', (e) => {
      if (e.button !== 0) return;
      e.preventDefault();
      const x0 = e.clientX, w0 = this.deps.width();
      let last = w0;
      this.grip.setPointerCapture(e.pointerId);
      setClass(this.grip, 'is-dragging', true);
      const move = (ev: PointerEvent): void => {
        last = clampWidth(w0 + (x0 - ev.clientX));
        this.deps.preview(last);
      };
      const up = (): void => {
        this.grip.removeEventListener('pointermove', move);
        this.grip.removeEventListener('pointerup', up);
        this.grip.removeEventListener('pointercancel', up);
        setClass(this.grip, 'is-dragging', false);
        this.deps.commit(last);
      };
      this.grip.addEventListener('pointermove', move);
      this.grip.addEventListener('pointerup', up);
      this.grip.addEventListener('pointercancel', up);
    });
    this.grip.addEventListener('keydown', (e) => {
      const step = e.key === 'ArrowLeft' ? 16 : e.key === 'ArrowRight' ? -16 : 0;
      if (!step) return;
      e.preventDefault();
      const next = clampWidth(this.deps.width() + step);
      this.deps.preview(next);
      this.deps.commit(next);
    });
    this.grip.addEventListener('dblclick', () => this.deps.commit(288));
  }
}
