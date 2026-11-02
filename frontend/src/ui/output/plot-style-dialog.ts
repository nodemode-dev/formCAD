import { loadTables } from '../dialogs/engine';
import { Dialog, confirmAction, promptName } from '../dialogs';
import { docStore } from '../doc-store';
import { el, patchList, q, setChecked, setDisabled, setHidden, setText, setValue } from '../dom';
import { t } from '../i18n';
import { toast } from '../toast';
import { failure, out, type PlotStyle, type StyleTable, type StyleTableInfo } from './output-api';

const WEIGHTS = ['0', '0.09', '0.13', '0.18', '0.25', '0.3', '0.35', '0.5', '0.7', '1', '1.4', '2.11'];
const OBJECT = '';

const hex = (c: number[] | null): string => (c ? `#${c.map((v) => Math.max(0, Math.min(255, v)).toString(16).padStart(2, '0')).join('')}` : '#000000');
const rgb = (h: string): number[] => [1, 3, 5].map((i) => parseInt(h.slice(i, i + 2), 16));
const part = (row: HTMLElement, f: string): HTMLInputElement | HTMLSelectElement => q(row, `[data-f="${f}"]`);

export class PlotStyleDialog extends Dialog {
  private readonly pick: HTMLSelectElement;
  private readonly grid: HTMLElement;
  private readonly desc: HTMLElement;
  private readonly note: HTMLElement;
  private readonly err: HTMLElement;
  private readonly layoutLine: HTMLElement;
  private readonly layoutText: HTMLElement;
  private readonly use: HTMLButtonElement;
  private readonly show: HTMLInputElement;
  private readonly copyBtn: HTMLButtonElement;
  private readonly delBtn: HTMLButtonElement;
  private readonly addRow: HTMLElement;
  private readonly addName: HTMLInputElement;
  private readonly addBtn: HTMLButtonElement;
  private readonly empty: HTMLElement;
  private readonly head: HTMLElement;
  private tables: StyleTableInfo[] = [];
  private table: StyleTable | null = null;
  private linetypes: string[] = [];
  private layout = '';
  private layoutStyle = '';
  private doc = '';
  private busy = false;

  constructor() {
    super('Plot Style Manager', 860);
    this.scrim.classList.add('cv-scrim-through');
    this.body.appendChild(el(
      '<div class="op-ps-top"><label class="op-ps-pick"><span></span><select class="cv-input" aria-label="Plot style table"></select></label><div class="op-ps-btns"></div></div>'));
    this.body.appendChild(el('<div class="op-ps-layout" hidden><span class="op-ps-ltext"></span><button class="cv-btn" type="button"></button><label class="cv-check op-ps-show"><span></span><input type="checkbox"></label></div>'));
    this.body.appendChild(el('<p class="cv-note op-ps-desc"></p>'));
    this.body.appendChild(el('<p class="cv-note op-ps-built" hidden></p>'));
    this.body.appendChild(el(
      '<div class="op-grid" role="table"><div class="op-grid-head op-row" role="row"><span></span><span></span><span></span><span></span><span></span><span></span><span></span></div><div class="op-grid-body"></div></div>'));
    this.body.appendChild(el('<div class="op-ps-add" hidden><input class="cv-input" type="text" spellcheck="false" autocomplete="off"><button class="cv-btn" type="button"></button></div>'));
    this.body.appendChild(el('<p class="cv-list-empty op-ps-empty" hidden></p>'));
    this.body.appendChild(el('<p class="u2-message op-note" hidden></p>'));
    this.pick = q<HTMLSelectElement>(this.body, '.op-ps-pick select');
    setText(q(this.body, '.op-ps-pick span'), t('Plot style table'));
    const btns = q(this.body, '.op-ps-btns');
    const mk = (label: string, run: () => void): HTMLButtonElement => {
      const b = el<HTMLButtonElement>('<button class="cv-btn" type="button"></button>');
      setText(b, t(label));
      b.addEventListener('click', run);
      btns.appendChild(b);
      return b;
    };
    this.copyBtn = mk('Copy', () => void this.copy());
    mk('New CTB', () => void this.create('color'));
    mk('New STB', () => void this.create('named'));
    this.delBtn = mk('Delete', () => void this.remove());
    this.layoutLine = q(this.body, '.op-ps-layout');
    this.layoutText = q(this.body, '.op-ps-ltext');
    this.use = q<HTMLButtonElement>(this.layoutLine, 'button');
    setText(this.use, t('Use for this layout'));
    this.show = q<HTMLInputElement>(this.layoutLine, 'input');
    setText(q(this.layoutLine, '.op-ps-show span'), t('Display plot styles'));
    this.desc = q(this.body, '.op-ps-desc');
    this.note = q(this.body, '.op-ps-built');
    this.grid = q(this.body, '.op-grid-body');
    this.head = q(this.body, '.op-grid-head');
    const labels = ['Plot style', 'Color', 'Grayscale', 'Screening', 'Linetype', 'Lineweight', ''];
    Array.from(this.head.children).forEach((c, i) => setText(c, t(labels[i])));
    this.addRow = q(this.body, '.op-ps-add');
    this.addName = q<HTMLInputElement>(this.addRow, 'input');
    this.addName.placeholder = t('New style');
    this.addBtn = q<HTMLButtonElement>(this.addRow, 'button');
    setText(this.addBtn, t('Add'));
    this.empty = q(this.body, '.op-ps-empty');
    this.err = q(this.body, '.op-note');
    setText(this.empty, t('No plot style tables.'));
    this.pick.addEventListener('change', () => void this.load(this.pick.value));
    this.use.addEventListener('click', () => void this.useForLayout());
    this.show.addEventListener('change', () => void this.useForLayout(true));
    this.addBtn.addEventListener('click', () => void this.addStyle());
    this.addName.addEventListener('keydown', (e) => { if (e.key === 'Enter') { e.preventDefault(); void this.addStyle(); } });
    this.button('Close', 'primary', () => this.close());
    docStore.onChange(() => { if (this.isOpen && docStore.activeId !== this.doc) this.close(); });
  }

  async showFor(): Promise<void> {
    const id = docStore.activeId;
    if (!id) return;
    this.doc = id;
    this.say('');
    try {
      const [lays, tables] = await Promise.all([out.layouts(id), loadTables()]);
      this.linetypes = (tables?.linetypes ?? []).map((l) => l.name);
      this.layout = lays.current !== 'Model' ? lays.current : '';
      await this.refreshList();
      await this.refreshLayout();
      const keep = this.tables.find((x) => x.name === this.layoutStyle)?.name ?? this.tables[0]?.name ?? '';
      await this.load(keep);
    } catch (e) {
      this.say(failure(e));
    }
    this.open(this.pick);
  }

  private say(text: string): void {
    setText(this.err, text);
    setHidden(this.err, !text);
  }

  private async refreshList(): Promise<void> {
    this.tables = (await out.styles(this.doc)).tables;
    const want = this.tables.map((x) => x.name);
    const have = Array.from(this.pick.options).map((o) => o.value);
    if (want.length !== have.length || want.some((n, i) => n !== have[i])) {
      this.pick.replaceChildren(...want.map((n) => { const o = document.createElement('option'); o.value = n; o.textContent = n; return o; }));
    }
    setHidden(this.empty, want.length > 0);
  }

  private async refreshLayout(): Promise<void> {
    setHidden(this.layoutLine, !this.layout);
    if (!this.layout) return;
    const ps = await out.pageSetup(this.doc, this.layout);
    this.layoutStyle = ps.style_table;
    setText(this.layoutText, `${this.layout}: ${ps.style_table || t('None')}`);
    setChecked(this.show, ps.display_styles);
  }

  private async load(name: string): Promise<void> {
    if (!name) { this.table = null; this.paint(); return; }
    try {
      this.table = await out.style(this.doc, name);
      setValue(this.pick, name);
      this.say('');
      this.paint();
    } catch (e) {
      this.say(failure(e));
    }
  }

  private paint(): void {
    const tb = this.table;
    setText(this.desc, tb?.description ?? '');
    setHidden(this.note, !tb?.builtin);
    setText(this.note, tb?.builtin ? t('Editing keeps an edited copy in the drawing.') : '');
    setDisabled(this.copyBtn, !tb);
    setDisabled(this.delBtn, !tb?.stored);
    setHidden(this.addRow, tb?.kind !== 'named');
    patchList<PlotStyle>(this.grid, tb?.styles ?? [], {
      key: (s) => s.name,
      create: (s) => this.makeRow(s),
      update: (row, s) => this.fillRow(row, s),
    });
    for (const row of Array.from(this.grid.children) as HTMLElement[]) setHidden(part(row, 'rm') as unknown as HTMLElement, tb?.kind !== 'named' || row.dataset.key === 'Normal');
  }

  private makeRow(s: PlotStyle): HTMLElement {
    const row = el(
      '<div class="op-row" role="row"><span class="op-name"></span>' +
      '<span class="op-cell"><label class="op-obj"><input type="checkbox" data-f="obj"><span></span></label><input type="color" data-f="color" aria-label="Color"></span>' +
      '<span class="op-cell"><input type="checkbox" data-f="gray" aria-label="Grayscale"></span>' +
      '<span class="op-cell"><input class="cv-input" type="number" min="0" max="100" step="1" data-f="screen" aria-label="Screening"></span>' +
      '<span class="op-cell"><select class="cv-input" data-f="lt" aria-label="Linetype"></select></span>' +
      '<span class="op-cell"><select class="cv-input" data-f="lw" aria-label="Lineweight"></select></span>' +
      '<span class="op-cell"><button class="cv-btn" type="button" data-f="rm"></button></span></div>');
    setText(q(row, '.op-obj span'), t('Object'));
    setText(q(row, '[data-f="rm"]'), t('Remove'));
    const lw = part(row, 'lw') as HTMLSelectElement;
    lw.replaceChildren(...[[OBJECT, t('Use object lineweight')], ...WEIGHTS.map((w) => [w, `${w} mm`])].map(([v, x]) => { const o = document.createElement('option'); o.value = v; o.textContent = x; return o; }));
    const lt = part(row, 'lt') as HTMLSelectElement;
    const fillLt = (): void => {
      if (lt.options.length > 1) return;
      const keep = lt.value;
      lt.replaceChildren(...[[OBJECT, t('Use object linetype')], ...this.linetypes.map((n) => [n, n])].map(([v, x]) => { const o = document.createElement('option'); o.value = v; o.textContent = x; return o; }));
      lt.value = keep;
    };
    lt.addEventListener('pointerdown', fillLt);
    lt.addEventListener('focus', fillLt);
    const send = (fields: Record<string, unknown>): void => void this.edit(row.dataset.key ?? '', fields);
    const obj = part(row, 'obj') as HTMLInputElement;
    const color = part(row, 'color') as HTMLInputElement;
    obj.addEventListener('change', () => send({ color: obj.checked ? null : rgb(color.value) }));
    color.addEventListener('change', () => { obj.checked = false; send({ color: rgb(color.value) }); });
    part(row, 'gray').addEventListener('change', (e) => send({ grayscale: (e.target as HTMLInputElement).checked }));
    part(row, 'screen').addEventListener('change', (e) => send({ screening: Number((e.target as HTMLInputElement).value) }));
    lt.addEventListener('change', () => send({ linetype: lt.value === OBJECT ? null : lt.value }));
    lw.addEventListener('change', () => send({ lineweight: lw.value === OBJECT ? null : Number(lw.value) }));
    part(row, 'rm').addEventListener('click', () => void this.removeStyle(row.dataset.key ?? ''));
    row.dataset.key = s.name;
    this.fillRow(row, s);
    return row;
  }

  private fillRow(row: HTMLElement, s: PlotStyle): void {
    setText(q(row, '.op-name'), s.name);
    (q(row, '.op-name') as HTMLElement).title = s.description;
    const obj = part(row, 'obj') as HTMLInputElement;
    const color = part(row, 'color') as HTMLInputElement;
    setChecked(obj, s.color === null);
    setValue(color, hex(s.color));
    color.disabled = false;
    setChecked(part(row, 'gray') as HTMLInputElement, s.grayscale);
    setValue(part(row, 'screen'), String(s.screening));
    const lt = part(row, 'lt') as HTMLSelectElement;
    const want = s.linetype ?? OBJECT;
    if (!Array.from(lt.options).some((o) => o.value === want)) {
      const o = document.createElement('option');
      o.value = want;
      o.textContent = want || t('Use object linetype');
      lt.appendChild(o);
    }
    if (lt.value !== want && document.activeElement !== lt) lt.value = want;
    const lw = part(row, 'lw') as HTMLSelectElement;
    const wlw = s.lineweight === null ? OBJECT : String(Number(s.lineweight));
    if (!Array.from(lw.options).some((o) => o.value === wlw)) {
      const o = document.createElement('option');
      o.value = wlw;
      o.textContent = `${wlw} mm`;
      lw.appendChild(o);
    }
    if (lw.value !== wlw && document.activeElement !== lw) lw.value = wlw;
  }

  private async act<T>(action: string, args: Record<string, unknown>): Promise<T | null> {
    if (this.busy) return null;
    this.busy = true;
    try {
      const r = await out.styleAction<T>(this.doc, action, args);
      this.say('');
      return r;
    } catch (e) {
      this.say(failure(e));
      return null;
    } finally {
      this.busy = false;
    }
  }

  private async edit(style: string, fields: Record<string, unknown>): Promise<void> {
    if (!this.table) return;
    const r = await this.act<StyleTable>('setstyle', { table: this.table.name, style, fields });
    if (r) { this.table = r; await this.refreshList(); this.paint(); } else { await this.load(this.table.name); }
  }

  private async removeStyle(style: string): Promise<void> {
    if (!this.table) return;
    const r = await this.act<StyleTable>('removestyle', { table: this.table.name, style });
    if (r) { this.table = r; await this.refreshList(); this.paint(); }
  }

  private async addStyle(): Promise<void> {
    const name = this.addName.value.trim();
    if (!this.table || !name) return;
    const r = await this.act<StyleTable>('addstyle', { table: this.table.name, style: name });
    if (r) { this.table = r; this.addName.value = ''; await this.refreshList(); this.paint(); }
  }

  private async copy(): Promise<void> {
    if (!this.table) return;
    const r = await this.act<StyleTable>('copy', { name: this.table.name });
    if (r) { await this.refreshList(); await this.load(r.name); }
  }

  private async create(kind: 'color' | 'named'): Promise<void> {
    const name = await promptName(kind === 'color' ? 'New color-dependent table' : 'New named table', '', 'Create');
    if (!name) return;
    const r = await this.act<StyleTable>('create', { kind, name });
    if (r) { await this.refreshList(); await this.load(r.name); }
  }

  private async remove(): Promise<void> {
    if (!this.table?.stored) return;
    if (!(await confirmAction('Delete Plot Style Table', `${t('Delete')} ${this.table.name}?`, 'Delete', true))) return;
    const r = await this.act<{ deleted: string }>('delete', { name: this.table.name });
    if (r) { toast(`${t('Deleted')} ${r.deleted}.`); await this.refreshList(); await this.refreshLayout(); await this.load(this.tables[0]?.name ?? ''); }
  }

  private async useForLayout(displayOnly = false): Promise<void> {
    if (!this.layout) return;
    const name = displayOnly ? this.layoutStyle || 'None' : this.table?.name;
    if (!name) return;
    const r = await this.act('use', { layout: this.layout, name, display: this.show.checked });
    if (r) await this.refreshLayout();
  }
}
