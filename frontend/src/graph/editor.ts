import { docStore } from '../ui/doc-store';
import { el, q, setClass, setDisabled, setText, setTitle } from '../ui/dom';
import { onLanguage, t } from '../ui/i18n';
import { icon } from '../ui/icons';
import { toast } from '../ui/toast';
import { graphBus } from './bus';
import { GraphCanvas } from './canvas';
import { GraphStore } from './store';
import type { CatalogueEntry, GraphRecord } from './types';

class GraphEditor {
  readonly store = new GraphStore();
  canvas: GraphCanvas | null = null;
  private stage: HTMLElement | null = null;
  private root: HTMLElement | null = null;
  private picker!: HTMLSelectElement;
  private stat!: HTMLElement;
  private btns = new Map<string, HTMLButtonElement>();
  private opened = false;

  mount(stage: HTMLElement): void {
    this.stage = stage;
    const root = el(
      '<section class="gx-root" aria-label="Graph editor"><div class="gx-head">' +
      `<button class="gx-btn" type="button" data-a="close">${icon('chevronLeft', 16)}<span></span></button><span class="gx-sep"></span>` +
      `<span class="gx-ico">${icon('graph', 16)}</span><select class="gx-select" aria-label="Graph"></select>` +
      `<button class="gx-btn" type="button" data-a="new">${icon('add', 16)}</button>` +
      `<button class="gx-btn" type="button" data-a="delete">${icon('delete', 16)}</button><span class="gx-sep"></span>` +
      `<button class="gx-btn" type="button" data-a="fit">${icon('fitView', 16)}</button>` +
      `<button class="gx-btn" type="button" data-a="zoomOut">${icon('zoomOut', 16)}</button>` +
      `<button class="gx-btn" type="button" data-a="zoomIn">${icon('zoomIn', 16)}</button>` +
      `<button class="gx-btn" type="button" data-a="snap">${icon('grid', 16)}</button><span class="gx-sep"></span>` +
      `<button class="gx-btn" type="button" data-a="solve">${icon('refresh', 16)}<span></span></button>` +
      `<button class="gx-btn" type="button" data-a="recompute"><span></span></button>` +
      '<span class="gx-grow"></span><span class="gx-stat"></span></div></section>',
    );
    this.root = root;
    stage.appendChild(root);
    this.picker = q<HTMLSelectElement>(root, '.gx-select');
    this.stat = q(root, '.gx-stat');
    for (const b of Array.from(root.querySelectorAll<HTMLButtonElement>('.gx-head [data-a]'))) this.btns.set(b.dataset.a ?? '', b);
    this.canvas = new GraphCanvas(root, this.store);
    root.addEventListener('click', (e) => {
      const b = (e.target as Element).closest<HTMLButtonElement>('.gx-head [data-a]');
      if (b) this.act(b.dataset.a ?? '');
    });
    this.picker.addEventListener('change', () => { void this.store.open(this.picker.value); });
    this.words();
    onLanguage(() => this.words());
    this.store.onChange((what) => {
      if (what === 'list' || what === 'open') this.paintList();
      if (what === 'graph' || what === 'states' || what === 'busy' || what === 'open') this.paintStat();
      if (what === 'error' && this.store.error) toast(this.store.error, 'error');
    });
    graphBus.on('selection', () => this.paintStat());
    this.paintList();
    this.paintStat();
  }

  private words(): void {
    const label = (a: string, text: string): void => {
      const b = this.btns.get(a);
      if (!b) return;
      setTitle(b, text);
      b.setAttribute('aria-label', text);
    };
    label('new', t('New graph'));
    label('delete', t('Delete graph'));
    label('fit', t('Zoom to fit'));
    label('zoomOut', t('Zoom out'));
    label('zoomIn', t('Zoom in'));
    label('snap', t('Snap to grid'));
    label('close', t('Back to the drawing'));
    label('solve', t('Solve'));
    label('recompute', t('Recompute everything'));
    const set = (a: string, text: string): void => { const s = this.btns.get(a)?.querySelector('span:not(.icon)'); if (s) setText(s, text); };
    set('close', t('Drawing'));
    set('solve', t('Solve'));
    set('recompute', t('Recompute'));
  }

  private act(a: string): void {
    const c = this.canvas;
    if (!c) return;
    switch (a) {
      case 'close': this.hide(); break;
      case 'new': void this.store.create(`${t('Graph')} ${this.store.list.length + 1}`); break;
      case 'delete': void this.store.remove(); break;
      case 'fit': c.fit(); break;
      case 'zoomIn': c.zoomBy(1.25); break;
      case 'zoomOut': c.zoomBy(0.8); break;
      case 'snap': c.setSnap(!c.snapping); this.paintStat(); break;
      case 'solve': void this.store.solve(false); break;
      case 'recompute': void this.store.solve(true); break;
      default: break;
    }
  }

  private paintList(): void {
    const sel = this.picker;
    const want = this.store.list;
    const have = Array.from(sel.options);
    if (have.length !== want.length || have.some((o, i) => o.value !== want[i].id || o.textContent !== want[i].name)) {
      sel.replaceChildren(...want.map((g) => { const o = document.createElement('option'); o.value = g.id; o.textContent = g.name; return o; }));
    }
    if (sel.value !== this.store.gid && this.store.gid) sel.value = this.store.gid;
    setDisabled(sel, want.length === 0);
    setDisabled(this.btns.get('delete') as HTMLButtonElement, !this.store.gid);
  }

  private paintStat(): void {
    const rec = this.store.rec;
    const parts = rec ? [`${rec.nodes.length} ${t('nodes')}`, `${rec.wires.length} ${t('wires')}`] : [];
    if (rec) parts.push(this.store.busy ? t('Solving') : `${this.store.lastMs.toFixed(0)} ms`);
    setText(this.stat, parts.join(' · '));
    const c = this.canvas;
    setClass(this.btns.get('snap') ?? null, 'is-on', !!c?.snapping);
    setClass(this.btns.get('solve') ?? null, 'is-on', this.store.busy);
    for (const k of ['solve', 'recompute', 'fit']) setDisabled(this.btns.get(k) as HTMLButtonElement, !rec);
  }

  isOpen(): boolean { return this.stage?.classList.contains('is-graph') ?? false; }

  async show(): Promise<void> {
    if (!this.stage) return;
    if (!docStore.activeId) { toast(t('Open a drawing first.')); return; }
    setClass(this.stage, 'is-graph', true);
    this.canvas?.view.focus({ preventScroll: true });
    document.dispatchEvent(new CustomEvent('formcad:graph-workspace', { detail: { open: true } }));
    if (!this.opened || this.store.docId !== docStore.activeId) {
      this.opened = true;
      await this.store.enter();
      if (this.store.docId === docStore.activeId && this.store.list.length === 0 && !this.store.error) await this.store.create(`${t('Graph')} 1`);
    }
    this.canvas?.fit();
    graphBus.emit('open', { gid: this.store.gid || null });
  }

  hide(): void {
    if (!this.stage) return;
    setClass(this.stage, 'is-graph', false);
    document.dispatchEvent(new CustomEvent('formcad:graph-workspace', { detail: { open: false } }));
    graphBus.emit('open', { gid: null });
  }

  gid(): string { return this.store.gid; }
  record(): GraphRecord | null { return this.store.rec; }
  catalogue(): CatalogueEntry[] { return this.store.catalogue; }
  selected(): string[] { return this.canvas?.selection().nodes ?? []; }
  select(ids: string[]): void { this.canvas?.setSelection(ids, [], []); }
  fit(): void { this.canvas?.fit(); }
  solve(opts: { all?: boolean } = {}): Promise<void> { return this.store.solve(opts.all === true); }
  open(gid: string): Promise<void> { return this.store.open(gid); }
  screenToWorld(x: number, y: number): { x: number; y: number } { return this.canvas?.toWorld(x, y) ?? { x, y }; }
  centre(): { x: number; y: number } { return this.canvas?.centre() ?? { x: 0, y: 0 }; }

  async addNode(typeId: string, wx?: number, wy?: number): Promise<string> {
    const c = this.canvas;
    if (!c) return '';
    const p = wx === undefined || wy === undefined ? c.centre() : { x: wx, y: wy };
    return c.addNodeAt(typeId, p.x, p.y);
  }
}

export const graphEditor = new GraphEditor();
