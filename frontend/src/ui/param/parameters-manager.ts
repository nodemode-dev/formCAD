import { events } from '../../io/events';
import { param, Refusal, type ParamRow } from '../../io/api-param';
import { Dialog } from '../dialogs';
import { docStore } from '../doc-store';
import { el, patchList, q, setClass, setDisabled, setHidden, setText, setTitle, setValue } from '../dom';
import { icon } from '../icons';
import { t } from '../i18n';

type Explain = (e: Refusal) => void;

const GROUPS: Array<{ id: 'dimensional' | 'user'; label: string }> = [
  { id: 'dimensional', label: 'Dimensional Constraint Parameters' },
  { id: 'user', label: 'User Parameters' },
];

const rowKey = (r: ParamRow): string => `${r.group}:${r.name.toLowerCase()}`;

export class ParametersManager extends Dialog {
  private rows: ParamRow[] = [];
  private filter = '';
  private seq = 0;
  private timer = 0;
  private readonly head: HTMLElement;
  private readonly lists = new Map<string, HTMLElement>();
  private readonly titles = new Map<string, HTMLElement>();
  private readonly search: HTMLInputElement;
  private readonly add: HTMLButtonElement;
  private readonly msg: HTMLElement;
  private readonly empty: HTMLElement;
  private doc = '';

  constructor(private readonly explain: Explain) {
    super('Parameters Manager', 720);
    this.scrim.classList.add('cv-scrim-through');
    this.body.appendChild(el(
      '<div class="pm"><div class="pm-bar"><button class="cv-btn pm-add" type="button"><span class="pm-fx">fx</span><span class="pm-add-t"></span></button>' +
      '<input class="cv-input pm-search" type="search" spellcheck="false" autocomplete="off"></div>' +
      '<div class="pm-table" role="table"><div class="pm-head" role="row"><span>Name</span><span>Expression</span><span>Unit</span><span>Value</span><span>Type</span><span></span></div>' +
      '<div class="pm-scroll"></div></div><p class="pm-msg" role="status"></p></div>'));
    this.head = q(this.body, '.pm-head');
    this.add = q<HTMLButtonElement>(this.body, '.pm-add');
    this.search = q<HTMLInputElement>(this.body, '.pm-search');
    this.msg = q(this.body, '.pm-msg');
    const scroll = q(this.body, '.pm-scroll');
    for (const g of GROUPS) {
      const title = el<HTMLElement>('<div class="pm-group" role="row"></div>');
      const list = el<HTMLElement>('<div class="pm-rows" role="rowgroup"></div>');
      const sec = el<HTMLElement>('<div class="pm-sec"></div>');
      sec.append(title, list);
      scroll.appendChild(sec);
      this.titles.set(g.id, title);
      this.lists.set(g.id, list);
    }
    this.empty = el('<p class="pm-empty"></p>');
    scroll.appendChild(this.empty);
    setText(q(this.add, '.pm-add-t'), t('New User Parameter'));
    this.search.placeholder = t('Search for parameter');
    this.search.setAttribute('aria-label', t('Search for parameter'));
    this.button('Done', 'primary', () => this.close());
    this.add.addEventListener('click', () => { void this.create(); });
    this.search.addEventListener('input', () => { this.filter = this.search.value.trim().toLowerCase(); this.paint(); });
    this.words();
    events.on('doc', (e) => {
      if (this.isOpen && e.id === docStore.activeId) this.later();
    });
    docStore.onChange(() => {
      if (this.isOpen && docStore.activeId !== this.doc) void this.load();
    });
    this.onClose = () => { window.clearTimeout(this.timer); };
  }

  private words(): void {
    const names = this.head.querySelectorAll('span');
    ['Name', 'Expression', 'Unit', 'Value', 'Type', ''].forEach((w, i) => setText(names[i], w ? t(w) : ''));
    for (const g of GROUPS) setText(this.titles.get(g.id) ?? null, t(g.label));
  }

  async showFor(): Promise<void> {
    if (!docStore.activeId) return;
    await this.load();
    if (!this.isOpen) this.open(this.search);
  }

  private later(): void {
    window.clearTimeout(this.timer);
    this.timer = window.setTimeout(() => { void this.load(); }, 120);
  }

  private async load(): Promise<void> {
    const id = docStore.activeId;
    if (!id) return;
    const mine = ++this.seq;
    try {
      const list = await param.list(id);
      if (mine !== this.seq) return;
      this.doc = id;
      this.rows = list.parameters;
      this.paint();
    } catch (e) {
      this.say(e);
    }
  }

  private say(e: unknown): void {
    if (e instanceof Refusal) { this.explain(e); setText(this.msg, e.message); setClass(this.msg, 'is-bad', true); return; }
    setText(this.msg, e instanceof Error ? e.message : t('The engine did not answer'));
    setClass(this.msg, 'is-bad', true);
  }

  private ok(text: string): void {
    setText(this.msg, text);
    setClass(this.msg, 'is-bad', false);
  }

  private shows(r: ParamRow): boolean {
    return !this.filter || r.name.toLowerCase().includes(this.filter) || r.expr.toLowerCase().includes(this.filter);
  }

  private paint(): void {
    this.words();
    let visible = 0;
    for (const g of GROUPS) {
      const rows = this.rows.filter((r) => r.group === g.id);
      const list = this.lists.get(g.id) as HTMLElement;
      patchList(list, rows, {
        key: rowKey,
        create: (r) => this.make(r),
        update: (n, r) => this.fill(n, r),
      });
      const shown = rows.filter((r) => this.shows(r));
      visible += shown.length;
      for (const n of Array.from(list.children) as HTMLElement[]) setHidden(n, !shown.some((r) => rowKey(r) === n.dataset.key));
      const title = this.titles.get(g.id) as HTMLElement;
      setHidden(title, shown.length === 0);
    }
    setHidden(this.empty, visible > 0);
    setText(this.empty, this.rows.length === 0 ? t('No parameters yet. Add a dimensional constraint or a user parameter.') : t('No parameter matches.'));
    if (!this.msg.classList.contains('is-bad')) setText(this.msg, `${this.rows.length} ${t('parameters')}`);
  }

  private make(r: ParamRow): HTMLElement {
    const n = el<HTMLElement>(
      '<div class="pm-row" role="row"><input class="pm-name" type="text" readonly spellcheck="false" autocomplete="off" aria-label="Name">' +
      '<input class="pm-expr" type="text" spellcheck="false" autocomplete="off" aria-label="Expression">' +
      '<input class="pm-unit" type="text" spellcheck="false" autocomplete="off" aria-label="Unit">' +
      '<span class="pm-val"></span><span class="pm-type"></span>' +
      `<span class="pm-act"><button class="cv-icon-btn pm-drive" type="button">${icon('lock', 14)}</button><button class="cv-icon-btn pm-del" type="button">${icon('delete', 14)}</button></span></div>`);
    const name = q<HTMLInputElement>(n, '.pm-name');
    const expr = q<HTMLInputElement>(n, '.pm-expr');
    const unit = q<HTMLInputElement>(n, '.pm-unit');
    const cur = (): ParamRow | undefined => this.rows.find((x) => rowKey(x) === n.dataset.key);
    name.addEventListener('dblclick', () => { if (!name.readOnly) return; name.readOnly = false; name.select(); });
    const leave = (keep: boolean): void => {
      if (name.readOnly) return;
      const row = cur();
      name.readOnly = true;
      if (!row) return;
      if (keep && name.value.trim() && name.value.trim() !== row.name) void this.rename(row.name, name.value.trim());
      else name.value = row.name;
    };
    name.addEventListener('keydown', (e) => {
      if (e.key === 'Enter') { e.preventDefault(); leave(true); name.blur(); }
      else if (e.key === 'Escape') { e.preventDefault(); e.stopPropagation(); leave(false); name.blur(); }
    });
    name.addEventListener('blur', () => leave(true));
    expr.addEventListener('keydown', (e) => {
      if (e.key === 'Enter') { e.preventDefault(); expr.blur(); }
      else if (e.key === 'Escape') { e.preventDefault(); e.stopPropagation(); const row = cur(); if (row) expr.value = row.expr; expr.blur(); }
    });
    expr.addEventListener('change', () => { const row = cur(); if (row) void this.edit(row, { expr: expr.value.trim() || '0' }); });
    unit.addEventListener('keydown', (e) => { if (e.key === 'Enter') { e.preventDefault(); unit.blur(); } });
    unit.addEventListener('change', () => { const row = cur(); if (row && row.group === 'user') void this.edit(row, { expr: row.expr, unit: unit.value.trim() }); });
    q(n, '.pm-del').addEventListener('click', () => { const row = cur(); if (row) void this.remove(row); });
    q(n, '.pm-drive').addEventListener('click', () => { const row = cur(); if (row) void this.edit(row, { driving: !row.driving }); });
    this.fill(n, r);
    return n;
  }

  private fill(n: HTMLElement, r: ParamRow): void {
    const user = r.group === 'user';
    setValue(q<HTMLInputElement>(n, '.pm-name'), r.name);
    setValue(q<HTMLInputElement>(n, '.pm-expr'), r.expr);
    const unit = q<HTMLInputElement>(n, '.pm-unit');
    setValue(unit, r.unit);
    unit.readOnly = !user;
    const val = q(n, '.pm-val');
    setText(val, r.error ? t('error') : r.shown);
    setTitle(val, r.error);
    setClass(val, 'is-bad', !!r.error);
    setClass(q(n, '.pm-expr'), 'is-bad', !!r.error);
    setTitle(q(n, '.pm-expr'), r.error);
    setText(q(n, '.pm-type'), r.type);
    const del = q<HTMLButtonElement>(n, '.pm-del');
    const drive = q<HTMLButtonElement>(n, '.pm-drive');
    setHidden(del, !user);
    setHidden(drive, user);
    const label = r.driving ? t('Driving: click to make it a reference only') : t('Reference only: click to make it driving');
    setTitle(drive, label);
    drive.setAttribute('aria-label', label);
    setClass(drive, 'is-on', r.driving);
    setTitle(del, t('Delete parameter'));
    del.setAttribute('aria-label', t('Delete parameter'));
    setDisabled(del, false);
    n.dataset.group = r.group;
  }

  private async run(job: () => Promise<unknown>, done: string): Promise<boolean> {
    try {
      await job();
      this.ok(done);
      await this.load();
      return true;
    } catch (e) {
      this.say(e);
      await this.load();
      return false;
    }
  }

  private async create(): Promise<void> {
    const id = docStore.activeId;
    if (!id) return;
    const taken = new Set(this.rows.map((r) => r.name.toLowerCase()));
    let i = 1;
    while (taken.has(`user${i}`)) i++;
    const name = `user${i}`;
    if (await this.run(() => param.add(id, name, '1'), t('Parameter added.'))) {
      const n = this.lists.get('user')?.querySelector<HTMLElement>(`[data-key="user:${name}"]`);
      const box = n?.querySelector<HTMLInputElement>('.pm-name');
      if (box) { box.readOnly = false; box.focus(); box.select(); }
    }
  }

  private async rename(from: string, to: string): Promise<void> {
    const id = docStore.activeId;
    if (id) await this.run(() => param.edit(id, from, { new_name: to }), t('Renamed.'));
  }

  private async edit(r: ParamRow, body: { expr?: string; unit?: string; driving?: boolean }): Promise<void> {
    const id = docStore.activeId;
    if (id) await this.run(() => param.edit(id, r.name, body), t('Updated.'));
  }

  private async remove(r: ParamRow): Promise<void> {
    const id = docStore.activeId;
    if (id) await this.run(() => param.remove(id, r.name), t('Parameter deleted.'));
  }
}
