import type { CanvasApi, Pt } from '../canvas/types';
import { el, patchList, q, setClass, setHidden, setText, setTitle } from '../ui/dom';
import { t } from '../ui/i18n';
import { icon } from '../ui/icons';
import type { ViewInfo } from './api';
import type { drawStore as Store } from './store';

const NS = 'http://www.w3.org/2000/svg';
const svgEl = <T extends SVGElement>(name: string, cls: string): T => {
  const n = document.createElementNS(NS, name) as T;
  n.setAttribute('class', cls);
  return n;
};

export type Side = 'top' | 'bottom' | 'left' | 'right';
export const SIDES: Side[] = ['top', 'bottom', 'left', 'right'];

export interface OverlayHooks {
  badge(v: ViewInfo): void;
  tag(v: ViewInfo): void;
  handleDown(kind: Side | 'move', v: ViewInfo, e: PointerEvent): void;
}

export class DrawOverlay {
  readonly root: HTMLElement;
  readonly bar: HTMLElement;
  private readonly svg: SVGSVGElement;
  private readonly tags: HTMLElement;
  private readonly frame: SVGRectElement;
  private readonly handles = new Map<string, SVGElement>();
  private readonly ghostLine: SVGPolylineElement;
  private readonly ghostFill: SVGPolygonElement;
  private readonly ghostCircle: SVGCircleElement;
  private readonly ghostRect: SVGRectElement;
  private readonly ghostArrows: SVGPathElement;
  private readonly ghostHot: SVGPolylineElement;
  private readonly cross: SVGPathElement;
  private ghost: { line: Pt[]; closed: boolean; circle: [Pt, number] | null; rect: [Pt, Pt] | null; arrows: Array<[Pt, Pt]>; cross: Pt | null; hot: Pt[] } = { line: [], closed: false, circle: null, rect: null, arrows: [], cross: null, hot: [] };
  private raf = 0;
  hooks: OverlayHooks | null = null;

  constructor(private readonly host: HTMLElement, private readonly canvas: CanvasApi, private readonly store: typeof Store) {
    this.root = el(
      '<div class="dw-layer" aria-hidden="false">' +
      '<svg class="dw-svg" width="100%" height="100%"></svg>' +
      '<div class="dw-tags"></div>' +
      '<div class="dw-bar dw-ui" hidden></div>' +
      '</div>',
    );
    this.svg = q<SVGSVGElement>(this.root, 'svg');
    this.tags = q(this.root, '.dw-tags');
    this.bar = q(this.root, '.dw-bar');
    this.frame = svgEl<SVGRectElement>('rect', 'dw-frame');
    this.ghostFill = svgEl<SVGPolygonElement>('polygon', 'dw-ghost-fill');
    this.ghostRect = svgEl<SVGRectElement>('rect', 'dw-ghost-rect');
    this.ghostCircle = svgEl<SVGCircleElement>('circle', 'dw-ghost-circle');
    this.ghostLine = svgEl<SVGPolylineElement>('polyline', 'dw-ghost-line');
    this.ghostArrows = svgEl<SVGPathElement>('path', 'dw-ghost-arrows');
    this.ghostHot = svgEl<SVGPolylineElement>('polyline', 'dw-ghost-hot');
    this.cross = svgEl<SVGPathElement>('path', 'dw-cross');
    this.svg.append(this.frame, this.ghostFill, this.ghostRect, this.ghostCircle, this.ghostLine, this.ghostArrows, this.ghostHot, this.cross);
    for (const k of ['top', 'bottom', 'left', 'right', 'move']) {
      const g = svgEl<SVGGElement>('g', `dw-handle dw-ui is-${k}`);
      g.dataset.kind = k;
      const c = svgEl<SVGCircleElement>('circle', 'dw-handle-dot');
      c.setAttribute('r', '9');
      const a = svgEl<SVGPathElement>('path', 'dw-handle-mark');
      g.append(c, a);
      g.addEventListener('pointerdown', (e) => {
        const v = this.store.selected;
        if (!v || e.button !== 0) return;
        e.preventDefault();
        e.stopPropagation();
        this.hooks?.handleDown(k as Side | 'move', v, e);
      });
      this.handles.set(k, g);
      this.svg.appendChild(g);
    }
    host.appendChild(this.root);
    this.canvas.on('view', () => this.schedule());
    this.canvas.on('display', () => this.schedule());
    this.store.onChange(() => this.schedule());
    new ResizeObserver(() => this.schedule()).observe(host);
    this.tags.addEventListener('click', (e) => {
      const b = (e.target as HTMLElement).closest<HTMLElement>('[data-act]');
      const key = (e.target as HTMLElement).closest<HTMLElement>('[data-key]')?.dataset.key;
      const v = key ? this.store.find(Number(key)) : undefined;
      if (!v || !b) return;
      e.stopPropagation();
      if (b.dataset.act === 'badge') this.hooks?.badge(v);
      else this.hooks?.tag(v);
    });
    this.tags.addEventListener('pointerdown', (e) => { e.stopPropagation(); });
  }

  schedule(): void {
    if (this.raf) return;
    this.raf = requestAnimationFrame(() => { this.raf = 0; this.paint(); });
  }

  private px(p: Pt): Pt {
    return this.canvas.screenFromWorld(p[0], p[1]);
  }

  setGhost(g: Partial<typeof this.ghost>): void {
    this.ghost = { line: [], closed: false, circle: null, rect: null, arrows: [], cross: null, hot: [], ...g };
    this.schedule();
  }

  clearGhost(): void {
    this.setGhost({});
  }

  private paint(): void {
    const on = this.store.inLayout;
    setHidden(this.root, !on);
    if (!on) return;
    this.paintTags();
    this.paintSelection();
    this.paintGhost();
  }

  private paintTags(): void {
    patchList(this.tags, this.store.views, {
      key: (v) => String(v.handle),
      create: () => {
        const n = el('<div class="dw-tag dw-ui"><button class="dw-tag-name" type="button" data-act="tag"></button><button class="dw-badge" type="button" data-act="badge"></button></div>');
        return n;
      },
      update: (n, v) => {
        const [x0, , , y1] = v.bounds;
        const [sx, sy] = this.px([x0, y1]);
        const tf = `translate(${Math.round(sx)}px, ${Math.round(sy) - 22}px)`;
        if (n.style.transform !== tf) n.style.transform = tf;
        const name = q(n, '.dw-tag-name');
        setText(name, v.name);
        const sel = this.store.selected?.handle === v.handle;
        setClass(n, 'is-selected', sel);
        const st = v.state.status;
        setClass(n, 'is-stale', st === 'stale');
        setClass(n, 'is-error', st === 'error');
        const badge = q(n, '.dw-badge');
        setHidden(badge, st !== 'stale' && st !== 'error');
        const label = st === 'stale' ? t('Out of date') : t('Error');
        setText(badge, label);
        setTitle(badge, st === 'stale' ? t('Update this view') : v.state.message || t('The view could not be built'));
        setTitle(name, `${v.name} ${v.label}`.trim());
      },
    });
  }

  private paintSelection(): void {
    const v = this.store.selected;
    const frameOn = !!v;
    setAttr(this.frame, 'visibility', frameOn ? 'visible' : 'hidden');
    for (const g of this.handles.values()) setAttr(g, 'visibility', frameOn ? 'visible' : 'hidden');
    if (!v) return;
    const [x0, y0, x1, y1] = v.bounds;
    const [ax, ay] = this.px([x0, y1]);
    const [bx, by] = this.px([x1, y0]);
    const w = Math.max(1, bx - ax);
    const h = Math.max(1, by - ay);
    setAttr(this.frame, 'x', String(Math.round(ax)));
    setAttr(this.frame, 'y', String(Math.round(ay)));
    setAttr(this.frame, 'width', String(Math.round(w)));
    setAttr(this.frame, 'height', String(Math.round(h)));
    const gap = 18;
    const cx = ax + w / 2;
    const cy = ay + h / 2;
    const at: Record<string, Pt> = { top: [cx, ay - gap], bottom: [cx, ay + h + gap], left: [ax - gap, cy], right: [ax + w + gap, cy], move: [cx, cy] };
    const marks: Record<string, string> = {
      top: 'M-4 2 L0 -3 L4 2', bottom: 'M-4 -2 L0 3 L4 -2', left: 'M2 -4 L-3 0 L2 4', right: 'M-2 -4 L3 0 L-2 4',
      move: 'M0 -5 V5 M-5 0 H5 M-2 -3 L0 -5 L2 -3 M-2 3 L0 5 L2 3 M-3 -2 L-5 0 L-3 2 M3 -2 L5 0 L3 2',
    };
    for (const [k, g] of this.handles) {
      const [x, y] = at[k];
      setAttr(g, 'transform', `translate(${Math.round(x)} ${Math.round(y)})`);
      setAttr(g.lastChild as SVGElement, 'd', marks[k]);
      setClass(g as unknown as HTMLElement, 'is-off', k !== 'move' && (v.vtype === 'detail'));
    }
  }

  private paintGhost(): void {
    const g = this.ghost;
    const pts = g.line.map((p) => this.px(p));
    const list = pts.map((p) => `${p[0].toFixed(1)},${p[1].toFixed(1)}`).join(' ');
    setAttr(this.ghostLine, 'points', g.closed ? `${list} ${pts[0] ? `${pts[0][0].toFixed(1)},${pts[0][1].toFixed(1)}` : ''}` : list);
    setAttr(this.ghostFill, 'points', g.closed ? list : '');
    setAttr(this.ghostLine, 'visibility', pts.length ? 'visible' : 'hidden');
    setAttr(this.ghostFill, 'visibility', g.closed && pts.length > 2 ? 'visible' : 'hidden');
    const hot = g.hot.map((p) => this.px(p)).map((p) => `${p[0].toFixed(1)},${p[1].toFixed(1)}`).join(' ');
    setAttr(this.ghostHot, 'points', hot);
    setAttr(this.ghostHot, 'visibility', g.hot.length ? 'visible' : 'hidden');
    if (g.circle) {
      const [cx, cy] = this.px(g.circle[0]);
      const [ex] = this.px([g.circle[0][0] + g.circle[1], g.circle[0][1]]);
      setAttr(this.ghostCircle, 'cx', cx.toFixed(1));
      setAttr(this.ghostCircle, 'cy', cy.toFixed(1));
      setAttr(this.ghostCircle, 'r', Math.max(1, Math.abs(ex - cx)).toFixed(1));
    }
    setAttr(this.ghostCircle, 'visibility', g.circle ? 'visible' : 'hidden');
    if (g.rect) {
      const a = this.px(g.rect[0]);
      const b = this.px(g.rect[1]);
      setAttr(this.ghostRect, 'x', Math.min(a[0], b[0]).toFixed(1));
      setAttr(this.ghostRect, 'y', Math.min(a[1], b[1]).toFixed(1));
      setAttr(this.ghostRect, 'width', Math.abs(a[0] - b[0]).toFixed(1));
      setAttr(this.ghostRect, 'height', Math.abs(a[1] - b[1]).toFixed(1));
    }
    setAttr(this.ghostRect, 'visibility', g.rect ? 'visible' : 'hidden');
    let arrows = '';
    for (const [from, to] of g.arrows) {
      const a = this.px(from);
      const b = this.px(to);
      const dx = b[0] - a[0];
      const dy = b[1] - a[1];
      const len = Math.hypot(dx, dy) || 1;
      const ux = dx / len;
      const uy = dy / len;
      arrows += `M${a[0].toFixed(1)} ${a[1].toFixed(1)} L${b[0].toFixed(1)} ${b[1].toFixed(1)} M${b[0].toFixed(1)} ${b[1].toFixed(1)} L${(b[0] - 8 * ux + 4 * uy).toFixed(1)} ${(b[1] - 8 * uy - 4 * ux).toFixed(1)} M${b[0].toFixed(1)} ${b[1].toFixed(1)} L${(b[0] - 8 * ux - 4 * uy).toFixed(1)} ${(b[1] - 8 * uy + 4 * ux).toFixed(1)} `;
    }
    setAttr(this.ghostArrows, 'd', arrows);
    if (g.cross) {
      const [x, y] = this.px(g.cross);
      setAttr(this.cross, 'd', `M${(x - 10).toFixed(1)} ${y.toFixed(1)} H${(x + 10).toFixed(1)} M${x.toFixed(1)} ${(y - 10).toFixed(1)} V${(y + 10).toFixed(1)}`);
    }
    setAttr(this.cross, 'visibility', g.cross ? 'visible' : 'hidden');
  }

  showBar(on: boolean): void {
    setHidden(this.bar, !on);
    setClass(this.root, 'is-tool', on);
  }

  iconNode(name: string): string {
    return icon(name, 14);
  }
}

function setAttr(n: Element, name: string, value: string): void {
  if (n.getAttribute(name) !== value) n.setAttribute(name, value);
}
