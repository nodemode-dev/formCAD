import { el, q, setClass, setHidden, setText, stored, store as persist } from '../ui/dom';
import { t } from '../ui/i18n';
import { graphBus } from './bus';
import { curveDistance, GRID, snap } from './geometry';
import { NodeView, type WidgetHost } from './node-view';
import * as ops from './ops';
import { ContextMenu, ModsPopover } from './popups';
import { SearchPopup } from './search';
import type { GraphStore } from './store';
import { TipPopup, type TipContent } from './tip';
import type { CatalogueEntry, GraphRecord, GroupRecord, ModKey, NodeEdit, NodeRecord, PortRef, TreePage } from './types';
import { kindOfOutput, makeWireLayer, WireView } from './wires';

const SNAP_KEY = 'formCAD.graph.snap';
const Z_MIN = 0.15;
const Z_MAX = 2.5;
const FAR = 0.45;
const PAGE = 24;
const DRAG_PX = 4;
const GROUP_PAD = 14;

type Mode = 'idle' | 'pan' | 'box' | 'drag' | 'wire' | 'group';
interface Pt { x: number; y: number }
interface WireDrag { fromNode: string; fromPort: string; side: 'out' | 'in'; sx: number; sy: number; replacing: string }
interface GroupView { el: HTMLElement; label: HTMLElement; rec: GroupRecord; box: string }

let clipboard: ops.Clip | null = null;

export class GraphCanvas implements WidgetHost {
  readonly root: HTMLElement;
  readonly view: HTMLElement;
  private readonly world: HTMLElement;
  private readonly grid: HTMLElement;
  private gridSize = 0;
  private readonly groupsHost: HTMLElement;
  private readonly nodesHost: HTMLElement;
  private readonly wireLayer: SVGGElement;
  private readonly ghost: SVGPathElement;
  private readonly marquee: HTMLElement;
  private readonly note: HTMLElement;
  private readonly blank: HTMLElement;
  private readonly inline: HTMLInputElement;
  private readonly search: SearchPopup;
  private readonly tip: TipPopup;
  private readonly mods: ModsPopover;
  private readonly menu: ContextMenu;
  private readonly nodes = new Map<string, NodeView>();
  private readonly wires = new Map<string, WireView>();
  private readonly groups = new Map<string, GroupView>();
  private lastWires: readonly unknown[] | null = null;
  private lastGroups: readonly unknown[] | null = null;
  private lastNodes: readonly NodeRecord[] | null = null;
  private tx = 0;
  private ty = 0;
  private z = 1;
  private frame = 0;
  private rect = { left: 0, top: 0, width: 0, height: 0 };
  private mode: Mode = 'idle';
  private snapOn = stored(SNAP_KEY) === '1';
  private selNodes = new Set<string>();
  private selWires = new Set<string>();
  private selGroups = new Set<string>();
  private pointer: Pt = { x: 0, y: 0 };
  private downAt: Pt = { x: 0, y: 0 };
  private moved = false;
  private dragStart = new Map<string, Pt>();
  private dragWorld: Pt = { x: 0, y: 0 };
  private panStart = { tx: 0, ty: 0 };
  private wireDrag: WireDrag | null = null;
  private spaceDown = false;
  private hoverKey = '';
  private hoverTimer = 0;
  private tipTarget: { node: string; port: string; side: 'in' | 'out' } | null = null;
  private tipPage = 0;
  private tipPages: Map<number, TreePage> = new Map();
  private tipStamp = 0;
  private tipAt: Pt = { x: 0, y: 0 };
  private noteTimer = 0;
  private inlineDone: ((v: string | null) => void) | null = null;
  private suppressMenu = false;
  private lastSelKey = '';
  private nodeBoundsKey = '';

  constructor(parent: HTMLElement, private readonly data: GraphStore) {
    this.root = el(
      '<div class="gx-view" tabindex="0" role="application" aria-label="Graph canvas">' +
      '<div class="gx-grid"></div><div class="gx-world"><div class="gx-groups"></div><div class="gx-nodes"></div></div>' +
      '<div class="gx-marquee"></div><div class="gx-blank"></div><div class="gx-note" role="status"></div></div>',
    );
    this.view = this.root;
    this.world = q(this.root, '.gx-world');
    this.grid = q(this.root, '.gx-grid');
    this.groupsHost = q(this.root, '.gx-groups');
    this.nodesHost = q(this.root, '.gx-nodes');
    const layer = makeWireLayer();
    this.world.insertBefore(layer.svg, this.nodesHost);
    this.wireLayer = layer.layer;
    this.ghost = layer.ghost;
    this.marquee = q(this.root, '.gx-marquee');
    this.note = q(this.root, '.gx-note');
    this.blank = q(this.root, '.gx-blank');
    this.inline = el<HTMLInputElement>('<input class="gx-inline" type="text" spellcheck="false" autocomplete="off">');
    this.root.append(this.inline);
    this.search = new SearchPopup(this.root);
    this.tip = new TipPopup(this.root);
    this.mods = new ModsPopover(this.root);
    this.menu = new ContextMenu(this.root);
    parent.appendChild(this.root);
    this.root.style.setProperty('--gx-head', '26px');
    this.root.style.setProperty('--gx-row', '20px');
    this.root.style.setProperty('--gx-pad', '5px');
    this.wire();
    const ro = new ResizeObserver(() => { this.measure(); this.applyView(); });
    ro.observe(this.root);
    this.measure();
    this.applyView();
    data.onChange((what) => {
      if (what === 'graph') this.sync();
      else if (what === 'states') this.syncStates();
      else if (what === 'error') this.say(data.error, true);
      else if (what === 'open') { this.restoreView(); this.sync(); }
    });
    this.sync();
  }

  get snapping(): boolean { return this.snapOn; }
  get zoom(): number { return this.z; }
  selection(): { nodes: string[]; wires: string[]; groups: string[] } { return { nodes: [...this.selNodes], wires: [...this.selWires], groups: [...this.selGroups] }; }

  setSnap(on: boolean): void { this.snapOn = on; persist(SNAP_KEY, on ? '1' : '0'); }

  say(text: string, error = false): void {
    setText(this.note, text);
    setClass(this.note, 'is-error', error);
    setClass(this.note, 'is-shown', text !== '');
    window.clearTimeout(this.noteTimer);
    if (text) this.noteTimer = window.setTimeout(() => setClass(this.note, 'is-shown', false), 3200);
  }

  node(id: string): NodeRecord | undefined { return this.data.rec?.nodes.find((n) => n.id === id); }
  settingsOf(id: string): Record<string, unknown> { return this.node(id)?.settings ?? {}; }
  tree(id: string, port: string, page: number): Promise<TreePage> { return this.data.treePage(id, port, page); }

  edit(id: string, change: NodeEdit, live: boolean): void {
    this.data.apply((rec) => ops.patchNode(rec, id, (n) => {
      let next = n;
      if (change.settings) next = { ...next, settings: { ...next.settings, ...change.settings } };
      if (change.nickname !== undefined) next = { ...next, nickname: change.nickname };
      if (change.enabled !== undefined) next = { ...next, enabled: change.enabled };
      if (change.preview !== undefined) next = { ...next, preview: change.preview };
      if (change.persistent) {
        const port = change.persistent.port;
        next = { ...next, inputs: next.inputs.map((p) => (p.name === port ? { ...p, persistent: change.persistent?.tree } : p)) };
      }
      return next;
    }), { live });
    graphBus.emit('edit', { ids: [id] });
  }

  private measure(): void {
    const r = this.root.getBoundingClientRect();
    this.rect = { left: r.left, top: r.top, width: r.width, height: r.height };
  }

  private bounds(): { w: number; h: number } { return { w: this.rect.width, h: this.rect.height }; }

  toWorld(cx: number, cy: number): Pt {
    return { x: (cx - this.rect.left - this.tx) / this.z, y: (cy - this.rect.top - this.ty) / this.z };
  }

  centre(): Pt { return this.toWorld(this.rect.left + this.rect.width / 2, this.rect.top + this.rect.height / 2); }

  private applyView(): void {
    if (this.frame) return;
    this.frame = requestAnimationFrame(() => {
      this.frame = 0;
      this.world.style.transform = `translate(${this.tx}px,${this.ty}px) scale(${this.z})`;
      const g = GRID * this.z;
      if (g !== this.gridSize) {
        this.gridSize = g;
        this.grid.style.backgroundSize = `${g}px ${g}px`;
        this.grid.style.inset = `${-g}px`;
      }
      this.grid.style.transform = `translate(${this.tx % g}px,${this.ty % g}px)`;
      setClass(this.root, 'is-far', this.z < FAR);
    });
  }

  private emitView(): void {
    this.data.setView(this.tx, this.ty, this.z);
    graphBus.emit('view', { x: this.tx, y: this.ty, zoom: this.z });
  }

  private restoreView(): void {
    const v = this.data.viewOf();
    this.tx = v.x;
    this.ty = v.y;
    this.z = v.zoom;
    this.applyView();
  }

  zoomAt(factor: number, cx: number, cy: number): void {
    const nz = Math.min(Z_MAX, Math.max(Z_MIN, this.z * factor));
    const k = nz / this.z;
    const px = cx - this.rect.left, py = cy - this.rect.top;
    this.tx = px - (px - this.tx) * k;
    this.ty = py - (py - this.ty) * k;
    this.z = nz;
    this.applyView();
    this.emitView();
  }

  zoomBy(factor: number): void { this.zoomAt(factor, this.rect.left + this.rect.width / 2, this.rect.top + this.rect.height / 2); }

  fit(): void {
    this.measure();
    let x0 = Infinity, y0 = Infinity, x1 = -Infinity, y1 = -Infinity;
    const pick = this.selNodes.size > 0 ? [...this.selNodes].map((id) => this.nodes.get(id)).filter((v): v is NodeView => !!v) : [...this.nodes.values()];
    for (const v of pick) {
      x0 = Math.min(x0, v.rec.x); y0 = Math.min(y0, v.rec.y);
      x1 = Math.max(x1, v.rec.x + v.box.w); y1 = Math.max(y1, v.rec.y + v.box.h);
    }
    if (!Number.isFinite(x0)) { this.tx = this.rect.width / 2; this.ty = this.rect.height / 2; this.z = 1; this.applyView(); this.emitView(); return; }
    const pad = 48;
    const z = Math.min(1.2, Math.max(Z_MIN, Math.min((this.rect.width - pad * 2) / Math.max(1, x1 - x0), (this.rect.height - pad * 2) / Math.max(1, y1 - y0))));
    this.z = z;
    this.tx = this.rect.width / 2 - ((x0 + x1) / 2) * z;
    this.ty = this.rect.height / 2 - ((y0 + y1) / 2) * z;
    this.applyView();
    this.emitView();
  }

  reveal(ids: string[]): void {
    this.setSelection(ids, [], []);
  }

  setSelection(nodes: Iterable<string>, wires: Iterable<string>, groups: Iterable<string>): void {
    const n = new Set(nodes), w = new Set(wires), g = new Set(groups);
    for (const id of this.selNodes) if (!n.has(id)) this.nodes.get(id)?.setSelected(false);
    for (const id of n) if (!this.selNodes.has(id)) this.nodes.get(id)?.setSelected(true);
    for (const id of this.selWires) if (!w.has(id)) this.wireSel(id, false);
    for (const id of w) if (!this.selWires.has(id)) this.wireSel(id, true);
    for (const id of this.selGroups) if (!g.has(id)) setClass(this.groups.get(id)?.el ?? null, 'is-sel', false);
    for (const id of g) if (!this.selGroups.has(id)) setClass(this.groups.get(id)?.el ?? null, 'is-sel', true);
    this.selNodes = n; this.selWires = w; this.selGroups = g;
    const key = `${[...n].join(',')}|${[...w].join(',')}|${[...g].join(',')}`;
    if (key !== this.lastSelKey) {
      this.lastSelKey = key;
      graphBus.emit('selection', { nodes: [...n], wires: [...w], groups: [...g] });
    }
  }

  private wireSel(id: string, on: boolean): void {
    const wv = this.wires.get(id);
    if (wv) wv.paint(wv.currentKind, on, this.wireOff(wv), false);
  }

  private wireOff(wv: WireView): boolean {
    return !!wv.from && !wv.from.rec.enabled;
  }

  private entryOf(n: NodeRecord): CatalogueEntry | undefined { return this.data.entries.get(n.type); }

  sync(): void {
    const rec = this.data.rec;
    if (!rec) {
      for (const v of this.nodes.values()) v.dispose();
      for (const w of this.wires.values()) w.el.remove();
      for (const g of this.groups.values()) g.el.remove();
      this.nodes.clear(); this.wires.clear(); this.groups.clear();
      this.lastWires = null; this.lastGroups = null; this.lastNodes = null;
      this.selNodes.clear(); this.selWires.clear(); this.selGroups.clear();
      setText(this.blank, t('Open or create a graph to begin.'));
      setClass(this.blank, 'is-shown', true);
      return;
    }
    const dirty = new Set<string>();
    if (rec.nodes !== this.lastNodes) {
      this.lastNodes = rec.nodes;
      const seen = new Set<string>();
      for (const n of rec.nodes) {
        seen.add(n.id);
        let v = this.nodes.get(n.id);
        if (!v) {
          v = new NodeView(n, this.entryOf(n), this);
          const st = this.data.states.get(n.id);
          if (st) v.setState(st);
          this.nodes.set(n.id, v);
          this.nodesHost.appendChild(v.el);
          dirty.add(n.id);
          if (this.selNodes.has(n.id)) v.setSelected(true);
          graphBus.emit('node-added', { id: n.id, typeId: n.type });
        } else if (v.rec !== n) {
          v.patch(n, this.entryOf(n));
          dirty.add(n.id);
        }
      }
      for (const [id, v] of this.nodes) {
        if (seen.has(id)) continue;
        v.dispose();
        this.nodes.delete(id);
        this.selNodes.delete(id);
        graphBus.emit('node-removed', { id, typeId: v.rec.type });
      }
    }
    if (rec.wires !== this.lastWires) {
      this.lastWires = rec.wires;
      const seen = new Set<string>();
      for (const w of rec.wires) {
        seen.add(w.id);
        let wv = this.wires.get(w.id);
        if (!wv) {
          wv = new WireView(w);
          this.wires.set(w.id, wv);
          this.wireLayer.appendChild(wv.el);
          graphBus.emit('wire-added', { id: w.id, from: w.from, to: w.to });
        } else wv.rec = w;
      }
      for (const [id, wv] of this.wires) {
        if (seen.has(id)) continue;
        wv.el.remove();
        this.wires.delete(id);
        this.selWires.delete(id);
        graphBus.emit('wire-removed', { id });
      }
      this.linkDots();
      this.restyleWires(null);
    }
    for (const wv of this.wires.values()) {
      const f = this.nodes.get(wv.rec.from.node) ?? null, to = this.nodes.get(wv.rec.to.node) ?? null;
      if (wv.from !== f || wv.to !== to || dirty.has(wv.rec.from.node) || dirty.has(wv.rec.to.node)) {
        wv.from = f; wv.to = to;
        wv.route();
      } else if (wv.from === null) wv.route();
    }
    if (dirty.size && !this.wires.size) this.linkDots();
    this.syncGroups(rec, dirty);
    setClass(this.blank, 'is-shown', rec.nodes.length === 0);
    setText(this.blank, rec.nodes.length === 0 ? t('Double click to add a node.') : '');
    this.mods.sync(undefined);
  }

  private linkDots(): void {
    const ins = new Map<string, Set<string>>(), outs = new Map<string, Set<string>>();
    for (const wv of this.wires.values()) {
      let a = outs.get(wv.rec.from.node);
      if (!a) { a = new Set(); outs.set(wv.rec.from.node, a); }
      a.add(wv.rec.from.port);
      let b = ins.get(wv.rec.to.node);
      if (!b) { b = new Set(); ins.set(wv.rec.to.node, b); }
      b.add(wv.rec.to.port);
    }
    const none = new Set<string>();
    for (const [id, v] of this.nodes) v.setLinks(ins.get(id) ?? none, outs.get(id) ?? none);
  }

  private restyleWires(only: ReadonlySet<string> | null): void {
    for (const wv of this.wires.values()) {
      if (only && !only.has(wv.rec.from.node)) continue;
      const kind = kindOfOutput(this.data.states.get(wv.rec.from.node), wv.rec.from.port);
      wv.paint(kind, this.selWires.has(wv.rec.id), this.wireOff(wv), false);
    }
  }

  syncStates(): void {
    const changed = new Set<string>();
    for (const [id, v] of this.nodes) {
      const st = this.data.states.get(id);
      if (v.state !== st) { v.setState(st); changed.add(id); }
    }
    if (changed.size) this.restyleWires(changed);
    if (this.tip.isOpen && this.tipTarget) this.showTip(this.tipTarget.node, this.tipTarget.port, this.tipTarget.side, false);
  }

  private syncGroups(rec: GraphRecord, dirty: ReadonlySet<string>): void {
    if (rec.groups !== this.lastGroups) {
      this.lastGroups = rec.groups;
      const seen = new Set<string>();
      for (const g of rec.groups) {
        seen.add(g.id);
        let gv = this.groups.get(g.id);
        if (!gv) {
          const e = el('<div class="gx-group"><div class="gx-group-label"></div></div>');
          e.dataset.id = g.id;
          gv = { el: e, label: q(e, '.gx-group-label'), rec: g, box: '' };
          this.groups.set(g.id, gv);
          this.groupsHost.appendChild(e);
        }
        gv.rec = g;
        setText(gv.label, g.name || t('Group'));
        gv.el.style.setProperty('--gx-colour', g.colour);
        gv.box = '';
      }
      for (const [id, gv] of this.groups) if (!seen.has(id)) { gv.el.remove(); this.groups.delete(id); this.selGroups.delete(id); }
    }
    if (dirty.size === 0 && this.nodeBoundsKey === 'x' + this.groups.size) { if (!this.groups.size) return; }
    for (const gv of this.groups.values()) {
      let x0 = Infinity, y0 = Infinity, x1 = -Infinity, y1 = -Infinity;
      for (const m of gv.rec.members) {
        const v = this.nodes.get(m);
        if (!v) continue;
        x0 = Math.min(x0, v.rec.x); y0 = Math.min(y0, v.rec.y); x1 = Math.max(x1, v.rec.x + v.box.w); y1 = Math.max(y1, v.rec.y + v.box.h);
      }
      const hidden = !Number.isFinite(x0);
      setHidden(gv.el, hidden);
      if (hidden) continue;
      const key = `${x0},${y0},${x1},${y1}`;
      if (key === gv.box) continue;
      gv.box = key;
      gv.el.style.transform = `translate(${x0 - GROUP_PAD}px,${y0 - GROUP_PAD}px)`;
      gv.el.style.width = `${x1 - x0 + GROUP_PAD * 2}px`;
      gv.el.style.height = `${y1 - y0 + GROUP_PAD * 2}px`;
    }
    this.nodeBoundsKey = 'x' + this.groups.size;
  }

  private wire(): void {
    const r = this.root;
    r.addEventListener('pointerdown', (e) => this.onDown(e));
    r.addEventListener('pointermove', (e) => this.onMove(e));
    r.addEventListener('pointerup', (e) => this.onUp(e));
    r.addEventListener('pointercancel', (e) => this.onUp(e));
    r.addEventListener('wheel', (e) => {
      if (this.search.isOpen && (e.target as Element).closest('.gx-hits')) return;
      if ((e.target as Element).closest('.gx-tip')) return;
      e.preventDefault();
      this.tip.hide();
      this.zoomAt(Math.exp(-e.deltaY * (e.ctrlKey ? 0.01 : 0.0015)), e.clientX, e.clientY);
    }, { passive: false });
    r.addEventListener('dblclick', (e) => this.onDouble(e));
    r.addEventListener('contextmenu', (e) => this.onContext(e));
    r.addEventListener('click', (e) => this.onClick(e));
    r.addEventListener('keydown', (e) => this.onKey(e));
    r.addEventListener('keyup', (e) => { if (e.code === 'Space') { this.spaceDown = false; setClass(this.root, 'is-panning', false); } });
    r.addEventListener('pointerover', (e) => this.onOver(e));
    r.addEventListener('pointerout', (e) => this.onOut(e));
    r.addEventListener('dragover', (e) => { if (e.dataTransfer?.types.includes('application/x-formcad-node')) e.preventDefault(); });
    r.addEventListener('drop', (e) => {
      const id = e.dataTransfer?.getData('application/x-formcad-node');
      if (!id) return;
      e.preventDefault();
      this.measure();
      const p = this.toWorld(e.clientX, e.clientY);
      void this.addNodeAt(id, p.x, p.y);
    });
    this.inline.addEventListener('keydown', (e) => {
      e.stopPropagation();
      if (e.key === 'Enter') this.endInline(true);
      else if (e.key === 'Escape') this.endInline(false);
    });
    this.inline.addEventListener('blur', () => this.endInline(true));
    this.search.onClose = () => this.root.focus({ preventScroll: true });
  }

  private closePops(except?: string): void {
    if (except !== 'search') this.search.close();
    if (except !== 'mods') this.mods.close();
    this.menu.close();
    this.tip.hide();
    this.endInline(true);
  }

  private onDown(e: PointerEvent): void {
    const target = e.target as Element;
    this.measure();
    if (target.closest('.gx-pop')) return;
    this.closePops();
    this.root.focus({ preventScroll: true });
    this.pointer = { x: e.clientX, y: e.clientY };
    this.downAt = { x: e.clientX, y: e.clientY };
    this.moved = false;
    this.hoverKey = '';
    window.clearTimeout(this.hoverTimer);
    if (e.button === 1 || (e.button === 0 && this.spaceDown)) { this.beginPan(e); return; }
    if (e.button === 2) { this.suppressMenu = false; this.beginPan(e, true); return; }
    if (e.button !== 0) return;
    const dot = target.closest<HTMLElement>('.gx-dot');
    if (dot) { this.beginWire(e, dot); return; }
    if (target.closest('.gx-tog')) return;
    const nodeEl = target.closest<HTMLElement>('.gx-node');
    if (nodeEl) {
      if (target.closest('.gx-nb') && target.closest('input,button,select,textarea,[contenteditable],[data-gx-stop]')) return;
      if (target.closest('.gx-pl') && target.closest('.gx-pin')) return;
      this.beginDrag(e, nodeEl.dataset.id ?? '');
      return;
    }
    const groupLabel = target.closest<HTMLElement>('.gx-group-label');
    if (groupLabel) {
      const gid = groupLabel.parentElement?.dataset.id ?? '';
      this.beginGroupDrag(e, gid);
      return;
    }
    this.mode = 'box';
    this.root.setPointerCapture(e.pointerId);
    this.shiftBox = e.shiftKey;
  }

  private shiftBox = false;

  private beginPan(e: PointerEvent, right = false): void {
    this.mode = 'pan';
    this.panStart = { tx: this.tx, ty: this.ty };
    this.panRight = right;
    this.root.setPointerCapture(e.pointerId);
    if (!right) setClass(this.root, 'is-panning', true);
    e.preventDefault();
  }

  private panRight = false;

  private beginDrag(e: PointerEvent, id: string): void {
    if (!this.nodes.has(id)) return;
    if (e.shiftKey) {
      const next = new Set(this.selNodes);
      if (next.has(id)) next.delete(id); else next.add(id);
      this.setSelection(next, [], []);
    } else if (!this.selNodes.has(id)) this.setSelection([id], [], []);
    this.mode = 'drag';
    this.dragStart.clear();
    for (const sid of this.selNodes) { const v = this.nodes.get(sid); if (v) this.dragStart.set(sid, { x: v.rec.x, y: v.rec.y }); }
    this.dragWorld = this.toWorld(e.clientX, e.clientY);
    this.root.setPointerCapture(e.pointerId);
  }

  private beginGroupDrag(e: PointerEvent, gid: string): void {
    const g = this.groups.get(gid);
    if (!g) return;
    this.setSelection(g.rec.members, [], [gid]);
    this.mode = 'group';
    this.dragStart.clear();
    for (const sid of this.selNodes) { const v = this.nodes.get(sid); if (v) this.dragStart.set(sid, { x: v.rec.x, y: v.rec.y }); }
    this.dragWorld = this.toWorld(e.clientX, e.clientY);
    this.root.setPointerCapture(e.pointerId);
  }

  private beginWire(e: PointerEvent, dot: HTMLElement): void {
    const nodeId = dot.closest<HTMLElement>('.gx-node')?.dataset.id ?? '';
    const port = dot.dataset.port ?? '';
    const side = dot.dataset.side === 'in' ? 'in' : 'out';
    const view = this.nodes.get(nodeId);
    if (!view) return;
    let drag: WireDrag;
    if (side === 'out') {
      const i = view.rec.outputs.findIndex((p) => p.name === port);
      const p = view.outPoint(i);
      drag = { fromNode: nodeId, fromPort: port, side: 'out', sx: p.x, sy: p.y, replacing: '' };
    } else {
      const existing = this.data.rec?.wires.filter((w) => w.to.node === nodeId && w.to.port === port).sort((a, b) => b.order - a.order)[0];
      if (existing && !e.shiftKey) {
        const src = this.nodes.get(existing.from.node);
        const i = src ? src.rec.outputs.findIndex((p) => p.name === existing.from.port) : -1;
        if (!src || i < 0) return;
        const p = src.outPoint(i);
        drag = { fromNode: existing.from.node, fromPort: existing.from.port, side: 'out', sx: p.x, sy: p.y, replacing: existing.id };
      } else {
        const i = view.rec.inputs.findIndex((p) => p.name === port);
        const p = view.inPoint(i);
        drag = { fromNode: nodeId, fromPort: port, side: 'in', sx: p.x, sy: p.y, replacing: '' };
      }
    }
    this.wireDrag = drag;
    this.mode = 'wire';
    setClass(this.root, 'is-wiring', true);
    this.ghost.style.display = '';
    this.root.setPointerCapture(e.pointerId);
    e.preventDefault();
    this.drawGhost(e.clientX, e.clientY);
  }

  private drawGhost(cx: number, cy: number): void {
    const d = this.wireDrag;
    if (!d) return;
    const p = this.toWorld(cx, cy);
    const path = d.side === 'out' ? `M${d.sx} ${d.sy}C${d.sx + 60} ${d.sy} ${p.x - 60} ${p.y} ${p.x} ${p.y}` : `M${p.x} ${p.y}C${p.x + 60} ${p.y} ${d.sx - 60} ${d.sy} ${d.sx} ${d.sy}`;
    this.ghost.setAttribute('d', path);
  }

  private onMove(e: PointerEvent): void {
    this.pointer = { x: e.clientX, y: e.clientY };
    if (this.mode === 'idle') return;
    if (!this.moved && Math.hypot(e.clientX - this.downAt.x, e.clientY - this.downAt.y) < DRAG_PX) return;
    this.moved = true;
    if (this.mode === 'pan') {
      this.tx = this.panStart.tx + (e.clientX - this.downAt.x);
      this.ty = this.panStart.ty + (e.clientY - this.downAt.y);
      if (this.panRight) this.suppressMenu = true;
      this.applyView();
      return;
    }
    if (this.mode === 'box') { this.drawBox(e); return; }
    if (this.mode === 'drag' || this.mode === 'group') {
      const w = this.toWorld(e.clientX, e.clientY);
      const dx = w.x - this.dragWorld.x, dy = w.y - this.dragWorld.y;
      const moves = new Map<string, Pt>();
      for (const [id, s] of this.dragStart) moves.set(id, { x: snap(s.x + dx, this.snapOn), y: snap(s.y + dy, this.snapOn) });
      this.data.apply((rec) => ops.moveNodes(rec, moves), { send: false });
      return;
    }
    if (this.mode === 'wire') {
      this.drawGhost(e.clientX, e.clientY);
      this.markTarget(e.clientX, e.clientY);
    }
  }

  private lastDot: HTMLElement | null = null;

  private markTarget(cx: number, cy: number): void {
    const hit = document.elementFromPoint(cx, cy)?.closest<HTMLElement>('.gx-dot') ?? null;
    if (hit === this.lastDot) return;
    if (this.lastDot) { this.lastDot.classList.remove('is-ok', 'is-no'); }
    this.lastDot = hit;
    const d = this.wireDrag;
    if (!hit || !d) return;
    const verdict = this.checkTarget(d, hit);
    hit.classList.add(verdict.ok ? 'is-ok' : 'is-no');
  }

  private checkTarget(d: WireDrag, dot: HTMLElement): { ok: boolean; from?: PortRef; to?: PortRef; why: string } {
    const nodeId = dot.closest<HTMLElement>('.gx-node')?.dataset.id ?? '';
    const port = dot.dataset.port ?? '';
    const side = dot.dataset.side === 'in' ? 'in' : 'out';
    if (side === d.side) return { ok: false, why: t('A wire joins an output to an input.') };
    const from: PortRef = d.side === 'out' ? { node: d.fromNode, port: d.fromPort } : { node: nodeId, port };
    const to: PortRef = d.side === 'out' ? { node: nodeId, port } : { node: d.fromNode, port: d.fromPort };
    if (from.node === to.node) return { ok: false, why: t('A node cannot feed itself.') };
    const rec = this.data.rec;
    if (!rec) return { ok: false, why: '' };
    const fk = this.kindOf(rec.nodes.find((n) => n.id === from.node), from.port, 'out');
    const tk = this.kindOf(rec.nodes.find((n) => n.id === to.node), to.port, 'in');
    if (!ops.kindsMeet(fk, tk)) return { ok: false, why: t('Those two ports hold different kinds of data.') };
    if (this.loops(rec, from.node, to.node)) return { ok: false, why: t('That wire would make a loop.') };
    return { ok: true, from, to, why: '' };
  }

  private kindOf(n: NodeRecord | undefined, port: string, side: 'in' | 'out'): string {
    if (!n) return 'any';
    const e = this.entryOf(n);
    return (side === 'in' ? e?.inputs : e?.outputs)?.find((p) => p.name === port)?.kind ?? 'any';
  }

  private loops(rec: GraphRecord, from: string, to: string): boolean {
    const succ = new Map<string, string[]>();
    for (const w of rec.wires) {
      const a = succ.get(w.from.node);
      if (a) a.push(w.to.node); else succ.set(w.from.node, [w.to.node]);
    }
    const seen = new Set<string>();
    const stack = [to];
    while (stack.length) {
      const cur = stack.pop() as string;
      if (cur === from) return true;
      if (seen.has(cur)) continue;
      seen.add(cur);
      for (const nx of succ.get(cur) ?? []) stack.push(nx);
    }
    return false;
  }

  private drawBox(e: PointerEvent): void {
    const x0 = Math.min(e.clientX, this.downAt.x) - this.rect.left, y0 = Math.min(e.clientY, this.downAt.y) - this.rect.top;
    const w = Math.abs(e.clientX - this.downAt.x), h = Math.abs(e.clientY - this.downAt.y);
    const m = this.marquee;
    m.style.display = 'block';
    m.style.transform = `translate(${x0}px,${y0}px)`;
    m.style.width = `${w}px`;
    m.style.height = `${h}px`;
  }

  private onUp(e: PointerEvent): void {
    const mode = this.mode;
    this.mode = 'idle';
    if (this.root.hasPointerCapture(e.pointerId)) this.root.releasePointerCapture(e.pointerId);
    setClass(this.root, 'is-panning', false);
    if (mode === 'box') {
      this.marquee.style.display = 'none';
      if (this.moved) this.finishBox(e);
      else this.pickAt(e);
    } else if (mode === 'drag' || mode === 'group') {
      if (this.moved) this.data.commit();
    } else if (mode === 'wire') {
      this.finishWire(e);
    } else if (mode === 'pan') {
      if (this.moved) this.emitView();
      if (this.moved && this.panRight) window.setTimeout(() => { this.suppressMenu = false; }, 0);
    }
  }

  private finishBox(e: PointerEvent): void {
    const a = this.toWorld(this.downAt.x, this.downAt.y), b = this.toWorld(e.clientX, e.clientY);
    const x0 = Math.min(a.x, b.x), x1 = Math.max(a.x, b.x), y0 = Math.min(a.y, b.y), y1 = Math.max(a.y, b.y);
    const hit = new Set<string>(this.shiftBox ? this.selNodes : []);
    for (const [id, v] of this.nodes) {
      if (v.rec.x < x1 && v.rec.x + v.box.w > x0 && v.rec.y < y1 && v.rec.y + v.box.h > y0) hit.add(id);
    }
    const wires = new Set<string>();
    if (this.shiftBox) for (const id of this.selWires) wires.add(id);
    for (const wv of this.wires.values()) {
      const ends = wv.ends();
      if (ends && ends.ax >= x0 && ends.ax <= x1 && ends.bx >= x0 && ends.bx <= x1 && ends.ay >= y0 && ends.ay <= y1 && ends.by >= y0 && ends.by <= y1) wires.add(wv.rec.id);
    }
    this.setSelection(hit, wires, []);
  }

  private pickAt(e: PointerEvent): void {
    const p = this.toWorld(e.clientX, e.clientY);
    const tol = 6 / this.z;
    let best: WireView | null = null, bd = tol;
    for (const wv of this.wires.values()) {
      const ends = wv.ends();
      if (!ends) continue;
      const minx = Math.min(ends.ax, ends.bx) - 240 - tol, maxx = Math.max(ends.ax, ends.bx) + 240 + tol;
      if (p.x < minx || p.x > maxx) continue;
      const d = curveDistance(ends.ax, ends.ay, ends.bx, ends.by, p.x, p.y);
      if (d < bd) { bd = d; best = wv; }
    }
    if (best) {
      const next = e.shiftKey ? new Set(this.selWires) : new Set<string>();
      next.add(best.rec.id);
      this.setSelection(e.shiftKey ? this.selNodes : [], next, []);
    } else if (!e.shiftKey) this.setSelection([], [], []);
  }

  private finishWire(e: PointerEvent): void {
    const d = this.wireDrag;
    this.wireDrag = null;
    this.ghost.style.display = 'none';
    setClass(this.root, 'is-wiring', false);
    if (this.lastDot) { this.lastDot.classList.remove('is-ok', 'is-no'); this.lastDot = null; }
    if (!d) return;
    const hit = document.elementFromPoint(e.clientX, e.clientY)?.closest<HTMLElement>('.gx-dot') ?? null;
    if (hit) {
      const verdict = this.checkTarget(d, hit);
      if (!verdict.ok || !verdict.from || !verdict.to) {
        if (verdict.why) this.say(verdict.why, true);
        return;
      }
      const from = verdict.from, to = verdict.to;
      const add = e.shiftKey || (d.replacing !== '' && false);
      this.data.apply((rec) => {
        let next = rec;
        if (d.replacing) next = ops.disconnect(next, d.replacing);
        return ops.connect(next, from, to, add);
      });
      return;
    }
    if (d.replacing) {
      this.data.apply((rec) => ops.disconnect(rec, d.replacing));
      return;
    }
    if (this.moved && d.side === 'out') this.openSearch(e.clientX, e.clientY, d);
  }

  private openSearch(cx: number, cy: number, from: WireDrag | null): void {
    this.measure();
    const w = this.toWorld(cx, cy);
    const src = from ? this.kindOf(this.data.rec?.nodes.find((n) => n.id === from.fromNode), from.fromPort, 'out') : '';
    const accept = from ? (en: CatalogueEntry): boolean => en.inputs.some((p) => ops.kindsMeet(src, p.kind)) : undefined;
    this.search.open(cx - this.rect.left, cy - this.rect.top, this.bounds(), this.data.catalogue, (entry) => {
      void this.addNodeAt(entry.id, w.x, w.y).then((id) => {
        if (!id || !from) return;
        const rec = this.data.rec;
        const n = rec?.nodes.find((x) => x.id === id);
        const ent = this.data.entries.get(entry.id);
        if (!n || !ent) return;
        const target = ent.inputs.find((p) => ops.kindsMeet(src, p.kind));
        if (!target) return;
        this.data.apply((r) => ops.connect(r, { node: from.fromNode, port: from.fromPort }, { node: id, port: target.name }, false));
      });
    }, accept);
  }

  async addNodeAt(typeId: string, wx: number, wy: number): Promise<string> {
    const entry = this.data.entries.get(typeId);
    if (!entry || !this.data.rec) return '';
    const node = ops.makeNode(entry, snap(wx - 20, this.snapOn), snap(wy - 12, this.snapOn));
    this.data.apply((rec) => ops.addNode(rec, node));
    this.setSelection([node.id], [], []);
    return node.id;
  }

  private onDouble(e: MouseEvent): void {
    const target = document.elementFromPoint(e.clientX, e.clientY) ?? (e.target as Element);
    if (target.closest('.gx-pop')) return;
    this.measure();
    const head = target.closest<HTMLElement>('.gx-nt');
    if (head) {
      const id = head.closest<HTMLElement>('.gx-node')?.dataset.id ?? '';
      const v = this.nodes.get(id);
      if (v) this.rename(head, v.rec.nickname, (val) => { if (val !== null) this.data.apply((r) => ops.patchNode(r, id, (n) => ({ ...n, nickname: val.trim() }))); });
      return;
    }
    const label = target.closest<HTMLElement>('.gx-group-label');
    if (label) {
      const gid = label.parentElement?.dataset.id ?? '';
      const g = this.groups.get(gid);
      if (g) this.rename(label, g.rec.name, (val) => { if (val !== null) this.data.apply((r) => ops.patchGroup(r, gid, (x) => ({ ...x, name: val.trim() }))); });
      return;
    }
    if (target.closest('.gx-node') || target.closest('.gx-dot')) return;
    this.openSearch(e.clientX, e.clientY, null);
  }

  private rename(anchor: HTMLElement, current: string, done: (v: string | null) => void): void {
    const r = anchor.getBoundingClientRect();
    const i = this.inline;
    i.style.transform = `translate(${r.left - this.rect.left}px,${r.top - this.rect.top}px)`;
    i.style.width = `${Math.max(120, r.width)}px`;
    i.value = current;
    i.classList.add('is-open');
    this.inlineDone = done;
    i.focus();
    i.select();
  }

  private endInline(commit: boolean): void {
    if (!this.inline.classList.contains('is-open')) return;
    const fn = this.inlineDone;
    this.inlineDone = null;
    this.inline.classList.remove('is-open');
    fn?.(commit ? this.inline.value : null);
    this.root.focus({ preventScroll: true });
  }

  private onClick(e: MouseEvent): void {
    const target = e.target as Element;
    const tog = target.closest<HTMLElement>('.gx-tog');
    if (tog) {
      const id = tog.closest<HTMLElement>('.gx-node')?.dataset.id ?? '';
      const n = this.node(id);
      if (!n) return;
      if (tog.dataset.act === 'preview') this.data.apply((r) => ops.patchNode(r, id, (x) => ({ ...x, preview: !x.preview })));
      else this.data.apply((r) => ops.patchNode(r, id, (x) => ({ ...x, enabled: !x.enabled })));
      return;
    }
    const label = target.closest<HTMLElement>('.gx-pl');
    if (label && label.dataset.side === 'in' && !this.moved) {
      const id = label.closest<HTMLElement>('.gx-node')?.dataset.id ?? '';
      const n = this.node(id);
      const port = label.dataset.port ?? '';
      const p = n?.inputs.find((x) => x.name === port);
      if (!n || !p) return;
      this.tip.hide();
      const r = label.getBoundingClientRect();
      this.mods.open(id, port, `${n.nickname || this.entryOf(n)?.name || n.type} · ${port}`, p.mods, r.left - this.rect.left, r.bottom - this.rect.top + 4, this.bounds());
      this.mods.onToggle = (node, pt, key, value) => this.data.apply((rec) => ops.setMod(rec, node, pt, key as ModKey, value));
      this.mods.onExpression = (node, pt, text) => this.data.apply((rec) => ops.setMod(rec, node, pt, 'expression', text));
    }
  }

  private onContext(e: MouseEvent): void {
    e.preventDefault();
    if (this.suppressMenu) { this.suppressMenu = false; return; }
    const target = document.elementFromPoint(e.clientX, e.clientY) ?? (e.target as Element);
    if (target.closest('.gx-pop')) return;
    this.measure();
    this.closePops();
    const px = e.clientX - this.rect.left, py = e.clientY - this.rect.top;
    const world = this.toWorld(e.clientX, e.clientY);
    const nodeEl = target.closest<HTMLElement>('.gx-node');
    const labelEl = target.closest<HTMLElement>('.gx-group-label');
    if (nodeEl) {
      const id = nodeEl.dataset.id ?? '';
      if (!this.selNodes.has(id)) this.setSelection([id], [], []);
      const n = this.node(id);
      graphBus.emit('context', { x: e.clientX, y: e.clientY, wx: world.x, wy: world.y, target: 'node', id });
      this.menu.open([
        { id: 'copy', label: t('Copy') }, { id: 'cut', label: t('Cut') }, { id: 'duplicate', label: t('Duplicate') },
        { id: 'enable', label: n?.enabled ? t('Disable') : t('Enable') }, { id: 'preview', label: n?.preview ? t('Preview off') : t('Preview on') },
        { id: 'rename', label: t('Rename') }, { id: 'group', label: t('Group') }, { id: 'delete', label: t('Delete') },
      ], px, py, this.bounds(), (a) => this.menuAction(a, id, world));
      return;
    }
    if (labelEl) {
      const gid = labelEl.parentElement?.dataset.id ?? '';
      const g = this.groups.get(gid);
      if (!g) return;
      this.setSelection(g.rec.members, [], [gid]);
      graphBus.emit('context', { x: e.clientX, y: e.clientY, wx: world.x, wy: world.y, target: 'group', id: gid });
      this.menu.open([{ id: 'grename', label: t('Rename group') }, { id: 'ungroup', label: t('Ungroup') }], px, py, this.bounds(), (a) => this.menuAction(a, gid, world), {
        current: g.rec.colour,
        pick: (c) => this.data.apply((r) => ops.patchGroup(r, gid, (x) => ({ ...x, colour: c }))),
      });
      return;
    }
    graphBus.emit('context', { x: e.clientX, y: e.clientY, wx: world.x, wy: world.y, target: 'canvas', id: '' });
    this.menu.open([
      { id: 'add', label: t('Add node') }, { id: 'paste', label: t('Paste') }, { id: 'all', label: t('Select all') }, { id: 'fit', label: t('Zoom to fit') },
    ], px, py, this.bounds(), (a) => this.menuAction(a, '', world, e.clientX, e.clientY));
  }

  private menuAction(a: string, id: string, world: Pt, cx = 0, cy = 0): void {
    switch (a) {
      case 'copy': this.copy(); break;
      case 'cut': this.copy(); this.removeSelection(); break;
      case 'duplicate': this.copy(); this.pasteAt(null, 30); break;
      case 'enable': this.data.apply((r) => ops.patchNode(r, id, (n) => ({ ...n, enabled: !n.enabled }))); break;
      case 'preview': this.data.apply((r) => ops.patchNode(r, id, (n) => ({ ...n, preview: !n.preview }))); break;
      case 'rename': {
        const v = this.nodes.get(id);
        const anchor = v?.el.querySelector<HTMLElement>('.gx-nt');
        if (v && anchor) this.rename(anchor, v.rec.nickname, (val) => { if (val !== null) this.data.apply((r) => ops.patchNode(r, id, (n) => ({ ...n, nickname: val.trim() }))); });
        break;
      }
      case 'group': this.groupSelection(); break;
      case 'delete': this.removeSelection(); break;
      case 'grename': {
        const g = this.groups.get(id);
        if (g) this.rename(g.label, g.rec.name, (val) => { if (val !== null) this.data.apply((r) => ops.patchGroup(r, id, (x) => ({ ...x, name: val.trim() }))); });
        break;
      }
      case 'ungroup': this.ungroup(id); break;
      case 'add': this.openSearch(cx, cy, null); break;
      case 'paste': this.pasteAt(world, 0); break;
      case 'all': this.selectAll(); break;
      case 'fit': this.fit(); break;
      default: break;
    }
  }

  selectAll(): void {
    const rec = this.data.rec;
    if (rec) this.setSelection(rec.nodes.map((n) => n.id), [], []);
  }

  copy(): void {
    const rec = this.data.rec;
    if (!rec || this.selNodes.size === 0) return;
    clipboard = ops.copyOf(rec, this.selNodes);
  }

  pasteAt(world: Pt | null, offset: number): void {
    const rec = this.data.rec;
    if (!rec || !clipboard) return;
    let dx = offset, dy = offset;
    if (world) {
      const x0 = Math.min(...clipboard.nodes.map((n) => n.x)), y0 = Math.min(...clipboard.nodes.map((n) => n.y));
      dx = snap(world.x - x0, this.snapOn); dy = snap(world.y - y0, this.snapOn);
    }
    const clip = clipboard;
    let ids: string[] = [];
    this.data.apply((r) => { const out = ops.paste(r, clip, dx, dy); ids = out.ids; return out.rec; });
    this.setSelection(ids, [], []);
  }

  removeSelection(): void {
    if (this.selNodes.size + this.selWires.size + this.selGroups.size === 0) return;
    const n = new Set(this.selNodes), w = new Set(this.selWires), g = new Set(this.selGroups);
    const onlyGroups = n.size === 0 && w.size === 0;
    this.data.apply((r) => ops.removeItems(r, onlyGroups ? new Set() : n, w, g));
    this.setSelection([], [], []);
  }

  groupSelection(): void {
    if (this.selNodes.size === 0) return;
    const ids = [...this.selNodes];
    const colour = ops.GROUP_COLOURS[(this.data.rec?.groups.length ?? 0) % ops.GROUP_COLOURS.length];
    this.data.apply((r) => ops.groupNodes(r, ids, t('Group'), colour));
  }

  ungroup(gid: string): void {
    this.data.apply((r) => ops.removeItems(r, new Set(), new Set(), new Set([gid])));
    this.setSelection([], [], []);
  }

  private onKey(e: KeyboardEvent): void {
    if (e.target !== this.root) return;
    const mod = e.ctrlKey || e.metaKey;
    const k = e.key.toLowerCase();
    if (e.code === 'Space') { this.spaceDown = true; setClass(this.root, 'is-panning', true); e.preventDefault(); return; }
    if (e.key === 'Delete' || e.key === 'Backspace') { this.removeSelection(); e.preventDefault(); return; }
    if (e.key === 'Escape') { this.setSelection([], [], []); this.closePops(); e.preventDefault(); return; }
    if (mod && k === 'c') { this.copy(); e.preventDefault(); return; }
    if (mod && k === 'x') { this.copy(); this.removeSelection(); e.preventDefault(); return; }
    if (mod && k === 'v') { this.measure(); this.pasteAt(this.toWorld(this.pointer.x, this.pointer.y), 0); e.preventDefault(); return; }
    if (mod && k === 'd') { this.copy(); this.pasteAt(null, 30); e.preventDefault(); return; }
    if (mod && k === 'a') { this.selectAll(); e.preventDefault(); return; }
    if (mod && k === 'g') { this.groupSelection(); e.preventDefault(); return; }
    if (!mod && k === 'f') { this.fit(); e.preventDefault(); return; }
    if (!mod && (e.key === '=' || e.key === '+')) { this.zoomBy(1.2); e.preventDefault(); return; }
    if (!mod && e.key === '-') { this.zoomBy(1 / 1.2); e.preventDefault(); return; }
    if (e.key === 'F5') { void this.data.solve(e.shiftKey); e.preventDefault(); }
  }

  private onOver(e: PointerEvent): void {
    if (this.mode !== 'idle') return;
    const target = e.target as Element;
    const port = target.closest<HTMLElement>('.gx-dot, .gx-pl');
    const msg = target.closest<HTMLElement>('.gx-nm');
    const hit = port ?? msg;
    if (!hit) return;
    const nodeId = hit.closest<HTMLElement>('.gx-node')?.dataset.id ?? '';
    const side = (hit.dataset.side === 'in' ? 'in' : 'out') as 'in' | 'out';
    const name = port ? port.dataset.port ?? '' : '';
    const key = `${nodeId}|${side}|${name}|${msg ? 'm' : 'p'}`;
    if (key === this.hoverKey) return;
    this.hoverKey = key;
    window.clearTimeout(this.hoverTimer);
    this.hoverTimer = window.setTimeout(() => {
      this.tipPage = 0;
      this.tipPages.clear();
      this.showTip(nodeId, name, side, true, hit);
    }, 280);
  }

  private onOut(e: PointerEvent): void {
    const to = e.relatedTarget as Element | null;
    const from = e.target as Element;
    if (!from.closest('.gx-dot, .gx-pl, .gx-nm')) return;
    if (to && to.closest('.gx-dot, .gx-pl, .gx-nm') === from.closest('.gx-dot, .gx-pl, .gx-nm')) return;
    window.clearTimeout(this.hoverTimer);
    this.hoverKey = '';
    this.tipTarget = null;
    this.tip.hideSoon();
  }

  private showTip(nodeId: string, port: string, side: 'in' | 'out', fresh: boolean, anchor?: HTMLElement): void {
    const n = this.node(nodeId);
    if (!n) { this.tip.hide(); return; }
    const entry = this.entryOf(n);
    const state = this.data.states.get(nodeId);
    const title = n.nickname || entry?.name || n.type;
    this.tipTarget = { node: nodeId, port, side };
    this.tip.onPage = (delta) => { this.tipPage = Math.max(0, this.tipPage + delta); this.showTip(nodeId, port, side, false); };
    let content: TipContent;
    if (port === '') {
      content = { title, sub: t('Messages'), messages: state?.messages ?? [], rows: [], page: 0, pages: 1, empty: '' };
    } else {
      let srcNode = nodeId, srcPort = port;
      let linked = side === 'out';
      if (side === 'in') {
        const w = this.data.rec?.wires.filter((x) => x.to.node === nodeId && x.to.port === port).sort((a, b) => a.order - b.order)[0];
        if (w) { srcNode = w.from.node; srcPort = w.from.port; linked = true; }
      }
      const summary = this.data.states.get(srcNode)?.outputs[srcPort];
      const portMsgs = (state?.messages ?? []).filter((m) => m.port === port);
      const kind = this.kindOf(n, port, side);
      const sub = !linked ? t('Not connected') : !summary ? t('No data yet') : `${summary.items} ${t('items')} · ${summary.count} ${t('branches')} · ${kind}`;
      if (fresh) this.tipStamp++;
      const pages = summary ? Math.max(1, Math.ceil(summary.count / PAGE)) : 1;
      if (this.tipPage >= pages) this.tipPage = pages - 1;
      let rows: Array<{ path: string; value: string }> = [];
      if (summary && summary.count > 0) {
        const cached = this.tipPages.get(this.tipPage);
        if (cached) rows = cached.branches.map((b) => ({ path: b.path, value: `[${b.count}] ${b.items.slice(0, 6).join(', ')}` }));
        else {
          const page = this.tipPage;
          const stamp = this.tipStamp;
          void this.data.treePage(srcNode, srcPort, page).then((p) => {
            this.tipPages.set(page, p);
            if (stamp === this.tipStamp && this.tipTarget && this.tipTarget.node === nodeId && this.tipPage === page) this.showTip(nodeId, port, side, false);
          }).catch(() => undefined);
        }
      }
      content = { title: `${title} · ${port}`, sub, messages: portMsgs, rows, page: this.tipPage, pages, empty: summary ? t('Loading') : t('Nothing to show') };
    }
    graphBus.emit('hover-port', { node: nodeId, port, tree: this.data.states.get(nodeId)?.outputs[port] ?? null });
    this.measure();
    const nv = this.nodes.get(nodeId);
    const nr = nv?.el.getBoundingClientRect();
    const place = port === '' ? 'below' : side === 'in' ? 'left' : 'right';
    if (anchor) {
      const r = anchor.getBoundingClientRect();
      this.tipAt = { x: 0, y: r.top - this.rect.top };
      if (nr) this.tipAt.x = place === 'left' ? nr.left - this.rect.left - 8 : place === 'right' ? nr.right - this.rect.left + 8 : nr.left - this.rect.left;
      if (place === 'below' && nr) this.tipAt.y = nr.bottom - this.rect.top + 8;
    }
    this.tip.show(content, this.tipAt.x, this.tipAt.y, this.bounds(), place === 'left' ? 'left' : 'right');
  }

  dispose(): void {
    window.clearTimeout(this.hoverTimer);
    window.clearTimeout(this.noteTimer);
    cancelAnimationFrame(this.frame);
  }
}
