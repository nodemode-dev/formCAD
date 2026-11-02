import { cad, type LayerRow } from '../../io/api-cad';
import { Dialog } from '../dialogs';
import { docStore } from '../doc-store';
import { el, patchList, q, setClass, setDisabled, setHidden, setText, setTitle, setValue } from '../dom';
import { icon } from '../icons';
import { t } from '../i18n';
import { toast } from '../toast';
import { managerFeed as layerFeed } from './layer-data';
import { colorHex, lineweightLabel, pickColor, pickLinetype, pickLineweight } from './layer-pickers';
import { Popover } from './popover';

const COLS: Array<[string, string]> = [
  ['status', 'Status'], ['name', 'Name'], ['on', 'On'], ['frozen', 'Freeze'], ['locked', 'Lock'], ['plot', 'Plot'], ['color', 'Color'],
  ['linetype', 'Linetype'], ['lineweight', 'Lineweight'], ['transparency', 'Transparency'], ['vp_freeze', 'VP Freeze'], ['vp_color', 'VP Color'],
  ['new_vp_freeze', 'New VP Freeze'], ['description', 'Description'],
];
const SORTABLE = new Set(['name', 'color', 'linetype', 'lineweight', 'transparency', 'description']);

const rowHtml = (): string =>
  '<div class="lm-c lm-c-status" data-act="status"></div>' +
  '<div class="lm-c lm-c-name" data-act="name"><span class="lm-name"></span></div>' +
  `<button class="lm-c lm-c-on lm-ic" type="button" data-act="on">${icon('bulbOn', 16)}</button>` +
  `<button class="lm-c lm-c-frozen lm-ic" type="button" data-act="frozen">${icon('sun', 16)}</button>` +
  `<button class="lm-c lm-c-locked lm-ic" type="button" data-act="locked">${icon('unlock', 16)}</button>` +
  `<button class="lm-c lm-c-plot lm-ic" type="button" data-act="plot">${icon('print', 16)}</button>` +
  '<button class="lm-c lm-c-color lm-pick" type="button" data-act="color"><i class="lm-sw"></i><span></span></button>' +
  '<button class="lm-c lm-c-linetype lm-pick" type="button" data-act="linetype"><i class="lm-line"></i><span></span></button>' +
  '<button class="lm-c lm-c-lineweight lm-pick" type="button" data-act="lineweight"><i class="lm-bar"></i><span></span></button>' +
  '<input class="lm-c lm-c-transparency cv-input" type="number" min="0" max="90" step="1" data-act="transparency">' +
  `<button class="lm-c lm-c-vp_freeze lm-ic" type="button" data-act="vp_freeze">${icon('sun', 16)}</button>` +
  '<span class="lm-c lm-c-vp_color"><button class="lm-pick" type="button" data-act="vp_color"><i class="lm-sw"></i><span></span></button><button class="lm-x" type="button" data-act="vp_clear">x</button></span>' +
  `<button class="lm-c lm-c-new_vp_freeze lm-ic" type="button" data-act="new_vp_freeze">${icon('vpFreeze', 16)}</button>` +
  '<div class="lm-c lm-c-description" data-act="description"><span></span></div>';

export class LayerManager extends Dialog {
  private readonly rows: HTMLElement;
  private readonly head: HTMLElement;
  private readonly info: HTMLElement;
  private readonly search: HTMLInputElement;
  private readonly stateSel: HTMLSelectElement;
  private readonly stateName: HTMLInputElement;
  private readonly stateRestore: HTMLButtonElement;
  private readonly stateDelete: HTMLButtonElement;
  private readonly stateSave: HTMLButtonElement;
  private readonly filters: HTMLElement;
  private readonly btnNew: HTMLButtonElement;
  private readonly btnDel: HTMLButtonElement;
  private readonly btnCur: HTMLButtonElement;
  private readonly menu: Popover;
  private readonly selected = new Set<string>();
  private anchor = '';
  private editing = false;
  private rename = '';
  private data: LayerRow[] = [];
  private current = '';
  private viewport: number | null = null;
  private sort = 'name';
  private desc = false;
  private stateChosen = '';
  private off: (() => void) | null = null;
  private lastFilterKey = '';

  constructor() {
    super('Layer Properties Manager', 1180);
    this.scrim.classList.add('cv-scrim-through');
    this.body.appendChild(el(
      '<div class="lm">' +
      '<div class="lm-tools"></div>' +
      '<div class="lm-main"><div class="lm-filters" role="tree"></div>' +
      '<div class="lm-table"><div class="lm-head lm-grid" role="row"></div><div class="lm-rows" role="rowgroup"></div></div></div>' +
      '<div class="lm-info" aria-live="off"></div></div>'));
    const tools = q(this.body, '.lm-tools');
    const ib = (name: string, title: string, run: () => void): HTMLButtonElement => {
      const b = el<HTMLButtonElement>(`<button class="cv-icon-btn lm-tool" type="button">${icon(name, 16)}</button>`);
      b.title = t(title);
      b.setAttribute('aria-label', t(title));
      b.addEventListener('click', run);
      tools.appendChild(b);
      return b;
    };
    this.btnNew = ib('plus', 'New Layer', () => void this.newLayer());
    this.btnDel = ib('delete', 'Delete Layer', () => void this.deleteSelected());
    this.btnCur = ib('check', 'Set Current', () => void this.makeCurrent(this.pickedName()));
    tools.appendChild(el('<span class="lm-sep"></span>'));
    this.stateSel = el<HTMLSelectElement>('<select class="cv-input lm-state" aria-label="Layer State"></select>');
    tools.appendChild(this.stateSel);
    const sb = (label: string, run: () => void): HTMLButtonElement => {
      const b = el<HTMLButtonElement>('<button class="cv-btn lm-btn" type="button"></button>');
      setText(b, t(label));
      b.addEventListener('click', run);
      tools.appendChild(b);
      return b;
    };
    this.stateRestore = sb('Restore', () => void this.stateAct('restore'));
    this.stateDelete = sb('Delete', () => void this.stateAct('delete'));
    this.stateName = el<HTMLInputElement>('<input class="cv-input lm-state-name" type="text" spellcheck="false" autocomplete="off">');
    this.stateName.placeholder = t('New state name');
    tools.appendChild(this.stateName);
    this.stateSave = sb('Save State', () => void this.stateAct('save'));
    this.search = el<HTMLInputElement>('<input class="cv-input lm-search" type="search" spellcheck="false" autocomplete="off">');
    this.search.placeholder = t('Search for layer');
    this.search.setAttribute('aria-label', t('Search for layer'));
    tools.appendChild(this.search);

    this.filters = q(this.body, '.lm-filters');
    this.head = q(this.body, '.lm-head');
    this.rows = q(this.body, '.lm-rows');
    this.info = q(this.body, '.lm-info');
    this.head.innerHTML = COLS.map(([k, label]) => `<div class="lm-h lm-c-${k}${SORTABLE.has(k) ? ' is-sort' : ''}" data-sort="${k}"><span>${t(label)}</span><i class="lm-arrow"></i></div>`).join('');
    this.menu = new Popover('lm-pop-menu', 180);
    this.menu.root.innerHTML = `<button type="button" data-m="current">${t('Set Current')}</button><button type="button" data-m="rename">${t('Rename Layer')}</button><button type="button" data-m="delete">${t('Delete Layer')}</button>`;
    this.menu.root.addEventListener('click', (e) => {
      const m = (e.target as HTMLElement).closest<HTMLElement>('[data-m]')?.dataset.m;
      this.menu.hide();
      if (m === 'current') void this.makeCurrent(this.pickedName());
      else if (m === 'rename') this.startRename(this.pickedName());
      else if (m === 'delete') void this.deleteSelected();
    });
    this.button('Close', 'primary', () => this.close());
    this.wire();
    this.onClose = () => { this.off?.(); this.off = null; layerFeed.setActive(false); this.menu.hide(); };
    docStore.onChange(() => { if (this.isOpen) this.syncViewport(); });
  }

  private pickedName(): string {
    return this.anchor || Array.from(this.selected)[0] || '';
  }

  private nameOf(node: HTMLElement): string {
    return node.closest<HTMLElement>('.lm-row')?.dataset.key ?? '';
  }

  private rowOf(name: string): LayerRow | undefined {
    return this.data.find((r) => r.name === name);
  }

  private targets(name: string): string[] {
    return this.selected.has(name) ? Array.from(this.selected) : [name];
  }

  async show(): Promise<void> {
    if (!docStore.activeId) return;
    this.syncViewport();
    layerFeed.setQuery({ viewport: this.viewport, sort: this.sort, desc: this.desc });
    layerFeed.setActive(true);
    this.off = layerFeed.onChange(() => this.paint());
    this.paint();
    layerFeed.schedule();
    this.open(this.search);
  }

  private syncViewport(): void {
    const d = docStore.current() as (typeof docStore.docs)[number] & { viewport?: number; tab?: string } | null;
    const vp = d && d.tab && d.tab !== 'model' && d.viewport ? d.viewport : null;
    if (vp === this.viewport) return;
    this.viewport = vp;
    setClass(this.scrim, 'is-vp', !!vp);
    this.setTitle(vp ? 'Layer Properties Manager - current viewport' : 'Layer Properties Manager');
    layerFeed.setQuery({ viewport: vp });
  }

  private async newLayer(): Promise<void> {
    const l = await layerFeed.ops([{ op: 'new', props: {} }]);
    const made = (l?.results?.[0] as { name?: string } | undefined)?.name;
    if (made) { this.selected.clear(); this.selected.add(made); this.anchor = made; this.rename = made; layerFeed.schedule(); }
  }

  private async deleteSelected(): Promise<void> {
    const names = Array.from(this.selected).filter((n) => !this.rowOf(n)?.protected);
    if (!names.length) return;
    await layerFeed.ops([{ op: 'delete', names }]);
    for (const n of names) this.selected.delete(n);
  }

  private async makeCurrent(name: string): Promise<void> {
    if (name) await layerFeed.ops([{ op: 'current', name }]);
  }

  private startRename(name: string): void {
    const r = this.rowOf(name);
    if (!r || r.protected) return;
    this.rename = name;
    this.beginEdit();
  }

  private beginEdit(): void {
    const name = this.rename;
    if (!name) return;
    const node = this.rows.querySelector<HTMLElement>(`.lm-row[data-key="${CSS.escape(name)}"] .lm-c-name`);
    if (!node || this.editing) return;
    this.editing = true;
    this.rename = '';
    this.inplace(node, name, async (v) => { if (v && v !== name) await layerFeed.ops([{ op: 'rename', name, to: v }]); });
  }

  private inplace(host: HTMLElement, value: string, commit: (v: string) => Promise<void> | void): void {
    const span = host.querySelector('span') as HTMLElement;
    const input = el<HTMLInputElement>('<input class="cv-input lm-edit" type="text" spellcheck="false" autocomplete="off">');
    input.value = value;
    span.hidden = true;
    host.appendChild(input);
    input.focus();
    input.select();
    let done = false;
    const end = (ok: boolean): void => {
      if (done) return;
      done = true;
      const v = input.value.trim();
      input.remove();
      span.hidden = false;
      this.editing = false;
      if (ok && v !== value) void commit(v);
    };
    input.addEventListener('keydown', (e) => {
      e.stopPropagation();
      if (e.key === 'Enter') { e.preventDefault(); end(true); } else if (e.key === 'Escape') { e.preventDefault(); end(false); }
    });
    input.addEventListener('blur', () => end(true));
  }

  private async stateAct(action: 'save' | 'restore' | 'delete'): Promise<void> {
    const id = docStore.activeId;
    if (!id) return;
    const name = action === 'save' ? this.stateName.value.trim() : this.stateSel.value;
    if (!name) return;
    try {
      await cad.layerStates(id, action === 'save' ? { action, name, overwrite: true } : { action, name });
      if (action === 'save') { this.stateChosen = name; this.stateName.value = ''; }
      if (action === 'delete') this.stateChosen = '';
      layerFeed.schedule();
    } catch (e) {
      toast(e instanceof Error ? e.message : 'The layer state could not be changed', 'error');
    }
  }

  private wire(): void {
    this.search.addEventListener('input', () => layerFeed.setQuery({ search: this.search.value.trim() }));
    this.stateName.addEventListener('input', () => this.gateStates());
    this.stateSel.addEventListener('change', () => { this.stateChosen = this.stateSel.value; this.gateStates(); });
    this.stateName.addEventListener('keydown', (e) => { if (e.key === 'Enter' && !this.stateSave.disabled) { e.preventDefault(); this.stateSave.click(); } });
    this.head.addEventListener('click', (e) => {
      const k = (e.target as HTMLElement).closest<HTMLElement>('[data-sort]')?.dataset.sort;
      if (!k || !SORTABLE.has(k)) return;
      if (this.sort === k) this.desc = !this.desc; else { this.sort = k; this.desc = false; }
      layerFeed.setQuery({ sort: this.sort, desc: this.desc });
      this.paintHead();
    });
    this.filters.addEventListener('click', (e) => {
      const n = (e.target as HTMLElement).closest<HTMLElement>('[data-filter]')?.dataset.filter;
      if (n) layerFeed.setQuery({ filter: n });
    });
    this.rows.addEventListener('click', (e) => this.onClick(e));
    this.rows.addEventListener('dblclick', (e) => this.onDouble(e));
    this.rows.addEventListener('contextmenu', (e) => {
      const name = this.nameOf(e.target as HTMLElement);
      if (!name) return;
      e.preventDefault();
      if (!this.selected.has(name)) { this.selected.clear(); this.selected.add(name); this.paintSelection(); }
      this.anchor = name;
      this.menu.root.style.setProperty('--lm-x', '0');
      const ghost = el<HTMLElement>('<span style="position:fixed;width:1px;height:1px"></span>');
      ghost.style.left = `${e.clientX}px`;
      ghost.style.top = `${e.clientY}px`;
      document.body.appendChild(ghost);
      this.menu.show(ghost);
      ghost.remove();
      setDisabled(q<HTMLButtonElement>(this.menu.root, '[data-m="rename"]'), !!this.rowOf(name)?.protected);
    });
    this.rows.addEventListener('change', (e) => {
      const tg = e.target as HTMLInputElement;
      if (tg.dataset.act !== 'transparency') return;
      const name = this.nameOf(tg);
      const v = Math.max(0, Math.min(90, Math.round(Number(tg.value) || 0)));
      void layerFeed.ops([{ op: 'set', names: this.targets(name), props: { transparency: v } }]);
    });
  }

  private onClick(e: MouseEvent): void {
    const target = e.target as HTMLElement;
    const act = target.closest<HTMLElement>('[data-act]');
    const name = this.nameOf(target);
    if (!act || !name || this.editing) return;
    const kind = act.dataset.act ?? '';
    const row = this.rowOf(name);
    if (!row) return;
    const names = this.targets(name);
    const set = (props: Record<string, unknown>): void => { void layerFeed.ops([{ op: 'set', names, props }]); };
    const vpSet = (vp: Record<string, unknown>): void => { void layerFeed.ops([{ op: 'set', names, viewport: this.viewport, vp }]); };
    switch (kind) {
      case 'on': set({ on: !row.on }); return;
      case 'frozen': set({ frozen: !row.frozen }); return;
      case 'locked': set({ locked: !row.locked }); return;
      case 'plot': set({ plot: !row.plot }); return;
      case 'new_vp_freeze': set({ new_vp_freeze: !row.new_vp_freeze }); return;
      case 'vp_freeze': vpSet({ freeze: !row.vp_freeze }); return;
      case 'vp_clear': vpSet({ clear: true }); return;
      case 'color': pickColor(act, row.color, (v) => set({ color: v })); return;
      case 'vp_color': pickColor(act, row.vp_color ?? row.color, (v) => vpSet({ color: v })); return;
      case 'linetype': void pickLinetype(act, row.linetype, (v) => set({ linetype: v })); return;
      case 'lineweight': pickLineweight(act, row.lineweight, (v) => set({ lineweight: v })); return;
      case 'transparency': return;
      default: break;
    }
    if (kind === 'name' || kind === 'status' || kind === 'description') {
      if (e.ctrlKey || e.metaKey) { if (!this.selected.delete(name)) this.selected.add(name); }
      else if (e.shiftKey && this.anchor) {
        const names2 = this.data.map((r) => r.name);
        const a = names2.indexOf(this.anchor), b = names2.indexOf(name);
        this.selected.clear();
        for (let i = Math.min(a, b); i <= Math.max(a, b); i++) this.selected.add(names2[i]);
      } else { this.selected.clear(); this.selected.add(name); }
      if (!e.shiftKey) this.anchor = name;
      this.paintSelection();
    }
  }

  private onDouble(e: MouseEvent): void {
    const target = e.target as HTMLElement;
    const act = target.closest<HTMLElement>('[data-act]')?.dataset.act;
    const name = this.nameOf(target);
    if (!name) return;
    if (act === 'status') void this.makeCurrent(name);
    else if (act === 'name') this.startRename(name);
    else if (act === 'description') {
      const host = target.closest<HTMLElement>('.lm-c-description');
      const row = this.rowOf(name);
      if (host && row && !this.editing) {
        this.editing = true;
        this.inplace(host, row.description, (v) => void layerFeed.ops([{ op: 'set', name, props: { description: v } }]));
      }
    }
  }

  private gateStates(): void {
    setDisabled(this.stateSave, !this.stateName.value.trim());
    setDisabled(this.stateRestore, !this.stateSel.value);
    setDisabled(this.stateDelete, !this.stateSel.value);
  }

  private paintHead(): void {
    for (const h of Array.from(this.head.querySelectorAll<HTMLElement>('[data-sort]'))) {
      const on = h.dataset.sort === this.sort;
      setClass(h, 'is-on', on);
      setClass(h, 'is-desc', on && this.desc);
    }
  }

  private paintSelection(): void {
    for (const n of Array.from(this.rows.children) as HTMLElement[]) setClass(n, 'is-selected', this.selected.has(n.dataset.key ?? ''));
    const picked = this.pickedName();
    const r = this.rowOf(picked);
    setDisabled(this.btnDel, !this.selected.size || Array.from(this.selected).every((n) => this.rowOf(n)?.protected));
    setDisabled(this.btnCur, !r || r.frozen || r.xref);
  }

  private paintFilters(l: NonNullable<typeof layerFeed.data>): void {
    const key = JSON.stringify(l.filters.map((f) => [f.name, f.parent, f.count])) + l.filter;
    if (key === this.lastFilterKey) return;
    this.lastFilterKey = key;
    patchList(this.filters, l.filters, {
      key: (f) => f.name,
      create: (f) => {
        const b = el<HTMLButtonElement>(`<button class="lm-filter" type="button" role="treeitem">${icon('layers', 14)}<b class="lm-filter-name"></b><em></em></button>`);
        b.dataset.filter = f.name;
        return b;
      },
      update: (n, f) => {
        setText(n.querySelector('.lm-filter-name'), f.name);
        setText(n.querySelector('em'), String(f.count));
        setClass(n, 'is-on', f.name === l.filter);
        n.style.setProperty('--depth', f.parent ? '1' : '0');
      },
    });
  }

  private paintStates(l: NonNullable<typeof layerFeed.data>): void {
    const names = l.states.map((s) => s.name);
    const sel = this.stateSel;
    const key = names.join('\u0001');
    if (sel.dataset.key !== key) {
      sel.dataset.key = key;
      const opts = [`<option value="">${t(names.length ? 'Unsaved Layer State' : 'No saved layer states')}</option>`, ...names.map((n) => `<option value="${n.replace(/"/g, '&quot;')}"></option>`)];
      sel.innerHTML = opts.join('');
      names.forEach((n, i) => { sel.options[i + 1].textContent = n; });
    }
    setValue(sel, names.includes(this.stateChosen) ? this.stateChosen : '');
    this.gateStates();
  }

  private paint(): void {
    const l = layerFeed.data;
    if (!l || !this.isOpen) return;
    this.data = l.layers;
    this.current = l.current;
    const names = new Set(l.layers.map((r) => r.name));
    for (const n of Array.from(this.selected)) if (!names.has(n)) this.selected.delete(n);
    if (!this.selected.size && l.layers.length && !this.anchor) { this.anchor = l.current; this.selected.add(l.current); }
    setClass(this.scrim, 'is-vp', !!this.viewport);
    this.paintHead();
    this.paintFilters(l);
    this.paintStates(l);
    patchList(this.rows, l.layers, {
      key: (r) => r.name,
      create: (r) => {
        const n = el<HTMLElement>(`<div class="lm-row lm-grid" role="row">${rowHtml()}</div>`);
        this.fill(n, r);
        return n;
      },
      update: (n, r) => this.fill(n, r),
    });
    setText(this.info, `${t('Layers displayed')}: ${l.shown} ${t('of')} ${l.total}.   ${t('Current layer')}: ${l.current}`);
    this.paintSelection();
    if (this.rename) this.beginEdit();
  }

  private fill(n: HTMLElement, r: LayerRow): void {
    setClass(n, 'is-current', r.current);
    setClass(n, 'is-selected', this.selected.has(r.name));
    setClass(n, 'is-off', !r.on);
    setClass(n, 'is-xref', r.xref);
    const status = q(n, '.lm-c-status');
    const sKey = r.current ? 'c' : r.used ? 'u' : 'e';
    if (status.dataset.k !== sKey) {
      status.dataset.k = sKey;
      status.innerHTML = icon(r.current ? 'check' : r.used ? 'sheetFull' : 'sheet', 16);
    }
    setTitle(status, t(r.current ? 'Current layer' : r.used ? 'Layer contains objects (double-click to make current)' : 'Layer is empty (double-click to make current)'));
    setText(q(n, '.lm-name'), r.name);
    const tog = (sel: string, on: boolean, a: string, b: string, tip: string): void => {
      const btn = q<HTMLButtonElement>(n, sel);
      setClass(btn, 'is-off', !on);
      if (btn.dataset.s !== (on ? '1' : '0')) {
        btn.dataset.s = on ? '1' : '0';
        btn.innerHTML = icon(on ? a : b, 16);
      }
      setTitle(btn, tip);
    };
    tog('.lm-c-on', r.on, 'bulbOn', 'bulbOff', t(r.on ? 'On (click: turn off)' : 'Off (click: turn on)'));
    tog('.lm-c-frozen', !r.frozen, 'sun', 'snow', t(r.frozen ? 'Frozen in all viewports (click: thaw)' : 'Thawed (click: freeze in all viewports)'));
    tog('.lm-c-locked', !r.locked, 'unlock', 'lock', t(r.locked ? 'Locked (click: unlock)' : 'Unlocked (click: lock)'));
    tog('.lm-c-plot', r.plot, 'print', 'printOff', t(r.plot ? 'Plot (click: do not plot)' : 'Do not plot (click: plot)'));
    const colorBtn = q(n, '.lm-c-color');
    q(colorBtn, '.lm-sw').style.setProperty('--c', colorHex(r.color));
    setText(q(colorBtn, 'span'), r.colorText);
    const ltBtn = q(n, '.lm-c-linetype');
    setText(q(ltBtn, 'span'), r.linetype);
    const lwBtn = q(n, '.lm-c-lineweight');
    q(lwBtn, '.lm-bar').style.setProperty('--h', `${r.lineweight < 0 ? 1 : Math.max(1, Math.min(6, r.lineweight / 30))}px`);
    setText(q(lwBtn, 'span'), t(lineweightLabel(r.lineweight)));
    const tr = q<HTMLInputElement>(n, '.lm-c-transparency');
    setValue(tr, String(r.transparency));
    const vf = q<HTMLButtonElement>(n, '.lm-c-vp_freeze');
    const vfOn = !!r.vp_freeze;
    setClass(vf, 'is-off', vfOn);
    if (vf.dataset.s !== (vfOn ? '1' : '0')) { vf.dataset.s = vfOn ? '1' : '0'; vf.innerHTML = icon(vfOn ? 'snow' : 'sun', 16); }
    const vc = q(n, '.lm-c-vp_color');
    const has = r.vp_color !== null && r.vp_color !== undefined;
    q(vc, '.lm-sw').style.setProperty('--c', colorHex((has ? r.vp_color : r.color) as number | string));
    setText(q(vc, 'span'), has ? String(r.vp_color) : 'ByLayer');
    setHidden(q(vc, '.lm-x'), !has);
    setTitle(q(vc, '.lm-x'), t('Remove the viewport override'));
    const nv = q<HTMLButtonElement>(n, '.lm-c-new_vp_freeze');
    setClass(nv, 'is-off', !r.new_vp_freeze);
    setTitle(nv, t('Freeze in new viewports'));
    const desc = q(n, '.lm-c-description span');
    setText(desc, r.description || '-');
    setTitle(q(n, '.lm-c-description'), t('Double-click to edit the description'));
  }
}

let manager: LayerManager | null = null;

export function openLayerManager(): boolean {
  if (!docStore.activeId) return true;
  manager ??= new LayerManager();
  void manager.show();
  return true;
}
