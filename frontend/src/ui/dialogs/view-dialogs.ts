import { cad, type TileBox, type ViewRow } from '../../io/api-cad';
import { api, ApiError } from '../../io/api';
import { Dialog } from '../dialogs';
import { docStore } from '../doc-store';
import { el, patchList, q, setChecked, setClass, setDisabled, setText } from '../dom';
import { t } from '../i18n';
import { layoutState } from '../layout-state';
import { toast } from '../toast';
const feed = async (...words: string[]): Promise<void> => {
  const id = docStore.activeId;
  if (!id) return;
  try {
    let state = null;
    for (const w of words) state = await api.sendInput(id, w);
    document.dispatchEvent(new CustomEvent('formcad:command-state', { detail: { doc: id, state } }));
  } catch (e) { toast(text(e), 'error'); }
};

const text = (e: unknown): string => (e instanceof ApiError || e instanceof Error ? e.message : 'The engine did not answer');

const row = (key: string): HTMLElement => {
  const n = el<HTMLElement>('<button class="cv-list-row u3-row" type="button" role="option"><span></span><span class="u3-row-name"></span><span class="cv-list-meta"></span></button>');
  n.dataset.key = key;
  return n;
};

export class ViewManager extends Dialog {
  private views: ViewRow[] = [];
  private selected = '';
  private snapshot = true;
  private readonly list: HTMLElement;
  private readonly name: HTMLInputElement;
  private readonly snap: HTMLInputElement;
  private readonly detail: HTMLElement;
  private readonly bRestore: HTMLButtonElement;
  private readonly bSave: HTMLButtonElement;
  private readonly bDelete: HTMLButtonElement;
  private readonly bWindow: HTMLButtonElement;
  private openedFor = '';

  constructor() {
    super('View Manager', 560);
    this.scrim.classList.add('cv-scrim-through');
    this.body.appendChild(el(
      '<div class="u3-vm"><div class="u3-vm-left"><div class="cv-list u3-list" role="listbox"></div></div>' +
      '<div class="u3-vm-right"><div class="u3-detail"></div>' +
      '<input class="cv-input u3-name" type="text" spellcheck="false" autocomplete="off">' +
      '<label class="cv-field cv-check u3-snap"><span>Save the layer state with the view</span><input type="checkbox"></label>' +
      '<div class="u3-btns"></div></div></div>'));
    this.list = q(this.body, '.u3-list');
    this.name = q<HTMLInputElement>(this.body, '.u3-name');
    this.name.placeholder = t('View name');
    this.snap = q<HTMLInputElement>(this.body, '.u3-snap input');
    this.detail = q(this.body, '.u3-detail');
    const btns = q(this.body, '.u3-btns');
    const mk = (label: string, run: () => void): HTMLButtonElement => {
      const b = el<HTMLButtonElement>('<button class="cv-btn" type="button"></button>');
      setText(b, t(label));
      b.addEventListener('click', run);
      btns.appendChild(b);
      return b;
    };
    this.bRestore = mk('Set Current', () => void this.act({ action: 'restore', name: this.selected }, true));
    this.bSave = mk('Save Current View', () => void this.saveCurrent());
    this.bWindow = mk('Define Window', () => this.defineWindow());
    this.bDelete = mk('Delete', () => void this.act({ action: 'delete', name: this.selected }));
    this.button('Close', 'primary', () => this.close());
    this.name.addEventListener('input', () => this.gate());
    this.name.addEventListener('keydown', (e) => { if (e.key === 'Enter' && !this.bSave.disabled) { e.preventDefault(); void this.saveCurrent(); } });
    this.snap.addEventListener('change', () => void this.act({ action: 'settings', snapshot: this.snap.checked }));
    this.list.addEventListener('click', (e) => {
      const key = (e.target as HTMLElement).closest<HTMLElement>('[data-key]')?.dataset.key;
      if (key) { this.selected = key; this.paint(); }
    });
    this.list.addEventListener('dblclick', (e) => {
      const key = (e.target as HTMLElement).closest<HTMLElement>('[data-key]')?.dataset.key;
      if (key) void this.act({ action: 'restore', name: key }, true);
    });
    docStore.onChange(() => { if (this.isOpen && docStore.activeId !== this.openedFor) this.close(); });
  }

  async show(): Promise<void> {
    const id = docStore.activeId;
    if (!id) return;
    this.openedFor = id;
    await this.reload();
    this.open(this.name);
  }

  private async reload(): Promise<void> {
    const id = docStore.activeId;
    if (!id) return;
    try {
      const r = await cad.views(id);
      this.views = r.views;
      this.snapshot = r.snapshot;
      if (!this.views.some((v) => v.name === this.selected)) this.selected = this.views[0]?.name ?? '';
      this.paint();
    } catch (e) {
      toast(text(e), 'error');
    }
  }

  private async act(body: Record<string, unknown>, close = false): Promise<void> {
    const id = docStore.activeId;
    if (!id) return;
    try {
      const r = await cad.viewAction(id, body);
      this.views = r.views;
      this.snapshot = r.snapshot;
      this.paint();
      layoutState.schedule();
      void docStore.refresh();
      if (close) this.close();
    } catch (e) {
      toast(text(e), 'error');
    }
  }

  private async saveCurrent(): Promise<void> {
    const name = this.name.value.trim();
    if (!name) return;
    await this.act({ action: 'save', name });
    this.selected = name;
    this.name.value = '';
    this.paint();
  }

  private defineWindow(): void {
    this.close();
    void feed('-view', 'Window');
  }

  private gate(): void {
    setDisabled(this.bSave, !this.name.value.trim());
    setDisabled(this.bRestore, !this.selected);
    setDisabled(this.bDelete, !this.selected);
  }

  private paint(): void {
    patchList(this.list, this.views, {
      key: (v) => v.name,
      create: (v) => row(v.name),
      update: (n, v) => {
        const cells = n.querySelectorAll('span');
        setText(cells[1], v.name);
        setText(cells[2], v.layout ? v.layout : t('Model'));
        setClass(n, 'is-selected', v.name === this.selected);
        n.setAttribute('aria-selected', String(v.name === this.selected));
      },
    });
    const v = this.views.find((x) => x.name === this.selected);
    setText(this.detail, v ? `${v.name} · ${v.layout || t('Model')} · ${v.width.toFixed(2)} x ${v.height.toFixed(2)}${v.layerState ? ` · ${t('layer state saved')}` : ''}` : t('No named views.'));
    setChecked(this.snap, this.snapshot);
    this.gate();
  }
}

export class NamedViewports extends Dialog {
  private configs: string[] = [];
  private tiles: TileBox[] = [];
  private previews: Record<string, TileBox[]> = {};
  private selected = '';
  private readonly list: HTMLElement;
  private readonly preview: SVGSVGElement;
  private readonly label: HTMLElement;
  private readonly bRestore: HTMLButtonElement;
  private readonly bDelete: HTMLButtonElement;
  private openedFor = '';

  constructor() {
    super('Named Viewports', 520);
    this.scrim.classList.add('cv-scrim-through');
    this.body.appendChild(el(
      '<div class="u3-nv"><div class="u3-nv-label"></div><div class="u3-vm"><div class="cv-list u3-list" role="listbox"></div>' +
      '<svg class="u3-nv-prev" viewBox="0 0 180 120" preserveAspectRatio="none" aria-hidden="true"></svg></div></div>'));
    this.label = q(this.body, '.u3-nv-label');
    this.list = q(this.body, '.u3-list');
    this.preview = q<SVGSVGElement>(this.body, '.u3-nv-prev');
    this.bRestore = this.button('Restore', 'ghost', () => void this.restore());
    this.bDelete = this.button('Delete', 'ghost', () => void this.remove());
    this.button('Close', 'primary', () => this.close());
    this.list.addEventListener('click', (e) => {
      const key = (e.target as HTMLElement).closest<HTMLElement>('[data-key]')?.dataset.key;
      if (key) { this.selected = key; this.paint(); }
    });
    this.list.addEventListener('dblclick', () => void this.restore());
    docStore.onChange(() => { if (this.isOpen && docStore.activeId !== this.openedFor) this.close(); });
  }

  async show(): Promise<void> {
    const id = docStore.activeId;
    if (!id) return;
    this.openedFor = id;
    await this.reload();
    this.open();
  }

  private async reload(): Promise<void> {
    const id = docStore.activeId;
    if (!id) return;
    try {
      const r = await cad.vports(id);
      this.configs = r.configs;
      this.tiles = r.tiles;
      this.previews = r.previews ?? {};
      if (!this.configs.includes(this.selected)) this.selected = this.configs[0] ?? '';
      this.paint();
    } catch (e) {
      toast(text(e), 'error');
    }
  }

  private async restore(): Promise<void> {
    const id = docStore.activeId;
    if (!id || !this.selected) return;
    if (layoutState.inLayout) {
      this.close();
      void feed('mview', 'Restore', this.selected);
      return;
    }
    try {
      await cad.vportAction(id, { option: 'restore', name: this.selected });
      layoutState.schedule();
      this.close();
    } catch (e) {
      toast(text(e), 'error');
    }
  }

  private async remove(): Promise<void> {
    const id = docStore.activeId;
    if (!id || !this.selected) return;
    try {
      const r = await cad.vportAction(id, { option: 'delete', names: [this.selected] });
      this.configs = r.configs ?? this.configs.filter((c) => c !== this.selected);
      this.previews = r.previews ?? this.previews;
      this.selected = this.configs[0] ?? '';
      this.paint();
    } catch (e) {
      toast(text(e), 'error');
    }
  }

  private paint(): void {
    setText(this.label, layoutState.inLayout ? t('Saved configurations will be placed in the layout.') : `${t('Current name')}: *Active`);
    patchList(this.list, this.configs.map((c) => ({ name: c })), {
      key: (c) => c.name,
      create: (c) => row(c.name),
      update: (n, c) => {
        const cells = n.querySelectorAll('span');
        setText(cells[1], c.name);
        setClass(n, 'is-selected', c.name === this.selected);
      },
    });
    const shown = this.previews[this.selected] ?? this.tiles;
    const rects = this.preview.children;
    while (rects.length < shown.length) this.preview.appendChild(document.createElementNS('http://www.w3.org/2000/svg', 'rect'));
    while (rects.length > shown.length) this.preview.lastElementChild?.remove();
    shown.forEach((tile, i) => {
      const [x0, y0] = tile.lowerLeft, [x1, y1] = tile.upperRight;
      const r = rects[i] as SVGRectElement;
      const put = (k: string, v: string): void => { if (r.getAttribute(k) !== v) r.setAttribute(k, v); };
      put('x', (x0 * 180).toFixed(1));
      put('y', ((1 - y1) * 120).toFixed(1));
      put('width', ((x1 - x0) * 180).toFixed(1));
      put('height', ((y1 - y0) * 120).toFixed(1));
      put('class', tile.current ? 'is-cur' : '');
    });
    setDisabled(this.bRestore, !this.selected);
    setDisabled(this.bDelete, !this.selected);
  }
}
