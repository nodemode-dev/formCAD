import { el, q, setClass, setHidden, setText, store, stored } from './dom';
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

  constructor(private readonly host: HTMLElement, private readonly deps: DockDeps) {
    this.grip = el('<div class="cv-dock-grip" role="separator" aria-orientation="vertical" aria-label="Resize panels" tabindex="0"></div>');
    this.column = el('<div class="cv-dock-column"></div>');
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
    const root = el(`<section class="cv-group" data-panel="${panel.id}"><button class="cv-group-head" type="button" aria-expanded="true"><span class="cv-group-icon">${icon(panel.icon, 16)}</span><span class="cv-group-label"></span><span class="cv-group-chev">${icon('chevronDown', 12)}</span></button><div class="cv-group-body"></div></section>`);
    const head = q<HTMLButtonElement>(root, '.cv-group-head');
    const body = q(root, '.cv-group-body');
    const label = q(root, '.cv-group-label');
    const strip = el<HTMLButtonElement>(`<button class="cv-strip-btn" type="button" data-strip="${panel.id}">${icon(panel.icon, 18)}</button>`);
    const paint = (): void => {
      setText(label, t(panel.label));
      head.title = t(panel.label);
      strip.title = t(panel.label);
      if (strip.getAttribute('aria-label') !== t(panel.label)) strip.setAttribute('aria-label', t(panel.label));
    };
    paint();
    onLanguage(paint);
    setClass(root, 'is-grow', !!panel.grow);
    const group: Group = { panel, root, head, body, api: undefined, strip };
    this.groups.set(panel.id, group);
    group.api = panel.build(body);
    head.addEventListener('click', () => this.fold(panel.id));
    strip.addEventListener('click', () => this.toggleFly(group));
    this.place(group);
    this.paint(group);
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
    store(STATE_KEY, '{}');
    for (const g of this.groups.values()) this.paint(g);
    this.deps.commit(300);
  }

  private place(group: Group): void {
    const order = group.panel.order ?? 100;
    const next = Array.from(this.groups.values()).filter((g) => g !== group && (g.panel.order ?? 100) > order).sort((a, b) => (a.panel.order ?? 100) - (b.panel.order ?? 100))[0];
    if (next) { this.column.insertBefore(group.root, next.root); this.strip.insertBefore(group.strip, next.strip); }
    else { this.column.appendChild(group.root); this.strip.appendChild(group.strip); }
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
    setClass(g.root, 'is-folded', folded);
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
