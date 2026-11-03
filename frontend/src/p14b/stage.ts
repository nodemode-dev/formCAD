import { commands } from '../ui/commands';
import { docStore } from '../ui/doc-store';
import { el, q, setClass, setDisabled, setText } from '../ui/dom';
import { t } from '../ui/i18n';
import { PcbEditor, type PcbTool } from './pcb-view';
import { SchEditor, type SchTool } from './sch-view';
import { ec, type Tab } from './store';
import type { BoardLayer } from './board-layer';
import type { Viewport3D } from '../view3d/viewport';

const SCH_TOOLS: Array<[SchTool, string, string]> = [
  ['select', 'Select', 'V'], ['place', 'Place', 'P'], ['wire', 'Wire', 'W'], ['bus', 'Bus', 'B'], ['entry', 'Entry', ''], ['label', 'Label', 'L'], ['glabel', 'Global', 'G'],
  ['power', 'Power', ''], ['junction', 'Dot', 'J'], ['noconn', 'NC', 'N'], ['delete', 'Delete', 'X'],
];
const PCB_TOOLS: Array<[PcbTool, string, string]> = [
  ['select', 'Select', 'S'], ['track', 'Track', 'X'], ['via', 'Via', 'U'], ['zone', 'Zone', 'Z'], ['keepout', 'Keepout', 'K'], ['delete', 'Delete', 'D'],
];

class EcadStage {
  sch!: SchEditor;
  pcb!: PcbEditor;
  layer: BoardLayer | null = null;
  vp: Viewport3D | null = null;
  tab: Tab = 'sch';
  stage: HTMLElement | null = null;
  root: HTMLElement | null = null;
  private stat!: HTMLElement;
  private tabBtns = new Map<string, HTMLButtonElement>();
  private toolBtns = new Map<string, HTMLButtonElement>();
  private sheetSel!: HTMLSelectElement;
  private layerSel!: HTMLSelectElement;
  private turned3d = false;
  private fitted = new Set<string>();
  private subs = new Set<() => void>();

  onChange(fn: () => void): void { this.subs.add(fn); }
  private emit(): void { for (const f of this.subs) f(); }

  mount(stage: HTMLElement): void {
    this.stage = stage;
    const root = el(
      '<section class="ec-root" aria-label="Electronics"><div class="ec-head">' +
      '<div class="ec-tabs" role="tablist"></div><span class="ec-sep"></span>' +
      '<span class="ec-wrap ec-wrap-sch"><select class="ec-select ec-sheet" aria-label="Sheet"></select></span>' +
      '<div class="ec-tools ec-tools-sch"></div>' +
      '<span class="ec-wrap ec-wrap-pcb"><select class="ec-select ec-layer" aria-label="Active layer"><option value="F.Cu">F.Cu</option><option value="B.Cu">B.Cu</option></select></span>' +
      '<div class="ec-tools ec-tools-pcb"></div><span class="ec-grow"></span>' +
      '<button class="ec-btn" type="button" data-a="undo"></button><button class="ec-btn" type="button" data-a="redo"></button>' +
      '<button class="ec-btn" type="button" data-a="fit"></button><button class="ec-btn" type="button" data-a="zin">+</button><button class="ec-btn" type="button" data-a="zout">-</button>' +
      '<span class="ec-stat"></span></div>' +
      '<div class="ec-body"><div class="ec-host ec-host-sch"></div><div class="ec-host ec-host-pcb"></div></div></section>',
    );
    this.root = root;
    stage.appendChild(root);
    this.stat = q(root, '.ec-stat');
    this.sheetSel = q<HTMLSelectElement>(root, '.ec-sheet');
    this.layerSel = q<HTMLSelectElement>(root, '.ec-layer');
    const tabs = q(root, '.ec-tabs');
    for (const [id, label] of [['sch', 'Schematic'], ['pcb', 'Board'], ['b3d', '3D board']] as const) {
      const b = el<HTMLButtonElement>('<button class="ec-tab" type="button" role="tab"></button>');
      b.dataset.tab = id;
      setText(b, t(label));
      b.addEventListener('click', () => void this.setTab(id));
      tabs.appendChild(b);
      this.tabBtns.set(id, b);
    }
    const mk = (host: HTMLElement, list: Array<[string, string, string]>, kind: 'sch' | 'pcb'): void => {
      for (const [id, label, key] of list) {
        const b = el<HTMLButtonElement>('<button class="ec-btn ec-tool" type="button"></button>');
        setText(b, t(label));
        b.title = key ? `${t(label)} (${key})` : t(label);
        b.dataset.tool = `${kind}:${id}`;
        b.addEventListener('click', () => { if (kind === 'sch') this.sch.setTool(id as SchTool); else this.pcb.setTool(id as PcbTool); });
        host.appendChild(b);
        this.toolBtns.set(`${kind}:${id}`, b);
      }
    };
    this.sch = new SchEditor(q(root, '.ec-host-sch'));
    this.pcb = new PcbEditor(q(root, '.ec-host-pcb'));
    mk(q(root, '.ec-tools-sch'), SCH_TOOLS, 'sch');
    mk(q(root, '.ec-tools-pcb'), PCB_TOOLS, 'pcb');
    const labelOf = (a: string, text: string): void => { const b = q(root, `[data-a="${a}"]`); if (a === 'zin' || a === 'zout') { b.title = text; return; } setText(b, text); };
    labelOf('undo', t('Undo')); labelOf('redo', t('Redo')); labelOf('fit', t('Fit')); labelOf('zin', t('Zoom in')); labelOf('zout', t('Zoom out'));
    root.addEventListener('click', (e) => {
      const b = (e.target as Element).closest<HTMLButtonElement>('[data-a]');
      if (!b) return;
      const a = b.dataset.a;
      if (a === 'undo') void ec.undo(); else if (a === 'redo') void ec.redo();
      else if (a === 'fit') this.fit();
      else if (a === 'zin') this.active()?.view.zoomBy(1.25);
      else if (a === 'zout') this.active()?.view.zoomBy(0.8);
    });
    this.sheetSel.addEventListener('change', () => { void ec.setSheet(this.sheetSel.value); });
    this.layerSel.addEventListener('change', () => this.pcb.setActive(this.layerSel.value));
    this.sch.onState = () => { this.paint(); this.emit(); };
    this.pcb.onState = () => { this.paint(); this.emit(); };
    ec.onChange(() => { this.sch.dataChanged(); this.pcb.dataChanged(); this.paint(); void this.maybeReload(); });
    this.paint();
  }

  active(): SchEditor | PcbEditor | null { return this.tab === 'sch' ? this.sch : this.tab === 'pcb' ? this.pcb : null; }

  isOpen(): boolean { return this.stage?.classList.contains('is-ecad') ?? false; }

  fit(): void {
    if (this.tab === 'sch') this.sch.fit();
    else if (this.tab === 'pcb') this.pcb.fit();
    else this.vp?.fitLayers();
  }

  async show(): Promise<void> {
    if (!this.stage || !ec.isEcad()) return;
    ec.switchDoc();
    setClass(this.stage, 'is-ecad', true);
    if (!ec.loaded) await ec.refresh();
    await this.setTab(this.tab, true);
  }

  async hide(): Promise<void> {
    if (!this.stage) return;
    if (this.tab === 'b3d') await this.leave3d();
    setClass(this.stage, 'is-ecad', false);
  }

  async setTab(tab: Tab, force = false): Promise<void> {
    if (!this.root || (tab === this.tab && !force)) return;
    if (this.tab === 'b3d' && tab !== 'b3d') await this.leave3d();
    this.tab = tab;
    ec.tab = tab;
    this.paint();
    if (tab === 'b3d') await this.enter3d();
    else {
      const key = `${ec.docId}:${tab}`;
      requestAnimationFrame(() => {
        this.sch.view.size(); this.pcb.view.size();
        if (!this.fitted.has(key) && ec.loaded) { this.fitted.add(key); this.fit(); }
        this.active()?.view.canvas.focus({ preventScroll: true });
      });
    }
    this.emit();
  }

  private async enter3d(): Promise<void> {
    const toggle = commands.get('v3-toggle');
    const on = this.stage?.classList.contains('is-3d') ?? false;
    if (!on) { this.turned3d = true; commands.run('v3-toggle'); await new Promise((r) => setTimeout(r, 400)); }
    this.layer?.setShown(true);
    await this.layer?.load(true);
    this.vp?.fitLayers();
    this.paint();
    void toggle;
  }

  private async leave3d(): Promise<void> {
    this.layer?.setShown(false);
    if (this.turned3d && (this.stage?.classList.contains('is-3d') ?? false)) commands.run('v3-toggle');
    this.turned3d = false;
  }

  private async maybeReload(): Promise<void> {
    if (this.tab === 'b3d' && this.isOpen()) { await this.layer?.load(); this.vp?.fitLayers(); }
    if (this.isOpen() && ec.loaded && this.tab !== 'b3d') {
      const key = `${ec.docId}:${this.tab}`;
      if (!this.fitted.has(key)) { this.fitted.add(key); this.fit(); }
    }
  }

  private paint(): void {
    const root = this.root;
    if (!root) return;
    for (const [id, b] of this.tabBtns) { setClass(b, 'is-on', id === this.tab); b.setAttribute('aria-selected', String(id === this.tab)); }
    root.dataset.tab = this.tab;
    setClass(root, 'is-b3d', this.tab === 'b3d');
    for (const [k, b] of this.toolBtns) {
      const [kind, id] = k.split(':');
      setClass(b, 'is-on', kind === 'sch' ? this.sch.tool === id : this.pcb.tool === id);
    }
    const sheets = ((ec.sum?.sheets ?? []) as Array<{ id: string; name: string }>);
    const sig = sheets.map((s) => `${s.id}|${s.name}`).join(',');
    if (this.sheetSel.dataset.sig !== sig) {
      this.sheetSel.dataset.sig = sig;
      this.sheetSel.replaceChildren(...sheets.map((s) => { const o = document.createElement('option'); o.value = s.id; o.textContent = s.name || s.id; return o; }));
    }
    if (this.sheetSel.value !== ec.sheetId && ec.sheetId) this.sheetSel.value = ec.sheetId;
    if (this.layerSel.value !== this.pcb.active) this.layerSel.value = this.pcb.active;
    setDisabled(this.layerSel, false);
    const sch = this.tab === 'sch';
    setClass(q(root, '.ec-wrap-sch'), 'is-off', !sch);
    setClass(q(root, '.ec-tools-sch'), 'is-off', !sch);
    setClass(q(root, '.ec-wrap-pcb'), 'is-off', this.tab !== 'pcb');
    setClass(q(root, '.ec-tools-pcb'), 'is-off', this.tab !== 'pcb');
    const parts: string[] = [];
    if (this.tab === 'sch') {
      parts.push(`${((ec.sum?.parts ?? []) as unknown[]).length} ${t('parts')}`);
      const s = ec.erc?.summary;
      if (s) parts.push(`ERC ${s.error ?? 0}/${s.warning ?? 0}`);
    } else if (this.tab === 'pcb') {
      const c = ec.pcb?.counts;
      if (c) parts.push(`${c.parts} ${t('parts')}`, `${c.tracks} ${t('tracks')}`, `${c.vias} ${t('vias')}`);
      if (ec.rat.length) parts.push(`${ec.rat.length} ${t('unrouted')}`);
    } else {
      parts.push(`${this.layer?.stats.board ?? 0} ${t('triangles')}`);
    }
    setText(this.stat, parts.join(' · '));
  }
}

export const ecStage = new EcadStage();
export const hasEcad = (): boolean => !!docStore.current() && ec.isEcad();
