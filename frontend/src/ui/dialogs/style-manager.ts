import { Dialog } from '../dialogs';
import { docStore } from '../doc-store';
import { el, patchList, q, setClass, setDisabled, setHidden, setText } from '../dom';
import { t } from '../i18n';
import { exec, loadTables } from './engine';
import type { StyleTables } from './engine';
import type { Field } from './fields';

export type StyleRecord = Record<string, unknown>;

export interface StyleSpec {
  title: string;
  table: 'textstyles' | 'tablestyles' | 'mleaderstyles';
  command: string;
  currentVar: string;
  width: number;
}

interface Binding {
  field: Field;
  key: string;
  read: (rec: StyleRecord) => string | number | boolean;
  write: (f: Field) => unknown;
}

export abstract class StyleManager extends Dialog {
  protected records: StyleRecord[] = [];
  protected selected = '';
  protected current = '';
  protected tables: StyleTables | null = null;
  protected readonly props: HTMLElement;
  private readonly head: HTMLElement;
  private readonly propsHead: HTMLElement;
  private readonly list: HTMLElement;
  private readonly nameBox: HTMLInputElement;
  private readonly setCurrent: HTMLButtonElement;
  private readonly addBtn: HTMLButtonElement;
  private readonly renameBtn: HTMLButtonElement;
  private readonly delBtn: HTMLButtonElement;
  private readonly note: HTMLElement;
  private readonly bindings: Binding[] = [];
  private openedFor = '';
  private busy = false;

  protected constructor(protected readonly spec: StyleSpec) {
    super(spec.title, spec.width);
    this.scrim.classList.add('cv-scrim-through');
    this.body.appendChild(el(
      '<div class="u2-sm">' +
      '<div class="u2-sm-left"><div class="u2-sm-cur"></div><div class="cv-list u2-sm-list" role="listbox"></div>' +
      '<div class="u2-sm-new"><input class="cv-input" type="text" spellcheck="false" autocomplete="off"></div>' +
      '<div class="u2-sm-btns"></div></div>' +
      '<div class="u2-sm-right"><div class="u2-sm-ph"></div><div class="u2-sm-props"></div></div>' +
      '</div>'));
    this.body.appendChild(el('<p class="cv-note u2-sm-note" hidden></p>'));
    this.head = q(this.body, '.u2-sm-cur');
    this.list = q(this.body, '.u2-sm-list');
    this.nameBox = q<HTMLInputElement>(this.body, '.u2-sm-new input');
    this.nameBox.placeholder = t('New style name');
    this.propsHead = q(this.body, '.u2-sm-ph');
    this.props = q(this.body, '.u2-sm-props');
    this.note = q(this.body, '.u2-sm-note');
    const btns = q(this.body, '.u2-sm-btns');
    const mk = (label: string, run: () => void): HTMLButtonElement => {
      const b = el<HTMLButtonElement>('<button class="cv-btn" type="button"></button>');
      setText(b, t(label));
      b.addEventListener('click', run);
      btns.appendChild(b);
      return b;
    };
    this.setCurrent = mk('Set Current', () => void this.act('current', {}));
    this.addBtn = mk('New', () => void this.create());
    this.renameBtn = mk('Rename', () => void this.rename());
    this.delBtn = mk('Delete', () => void this.act('delete', {}));
    this.nameBox.addEventListener('input', () => this.gate());
    this.nameBox.addEventListener('keydown', (e) => { if (e.key === 'Enter' && !this.addBtn.disabled) { e.preventDefault(); void this.create(); } });
    this.button('Close', 'primary', () => this.close());
    docStore.onChange(() => { if (this.isOpen && docStore.activeId !== this.openedFor) this.close(); });
  }

  protected bind(field: Field, key: string, read: (rec: StyleRecord) => string | number | boolean, write: (f: Field) => unknown = (f) => f.get()): Field {
    this.bindings.push({ field, key, read, write });
    field.change = () => void this.edit(key, write(field));
    return field;
  }

  protected abstract afterFill(rec: StyleRecord): void;
  protected abstract createArgs(base: StyleRecord | undefined, name: string): Record<string, unknown>;

  protected currentRecord(): StyleRecord | undefined {
    return this.records.find((r) => String(r.name) === this.selected);
  }

  async show(): Promise<void> {
    if (!docStore.activeId) return;
    this.openedFor = docStore.activeId;
    await this.reload(true);
    this.open(this.nameBox);
  }

  protected async reload(pickCurrent = false): Promise<void> {
    const tables = await loadTables();
    if (!tables) return;
    this.tables = tables;
    this.records = tables[this.spec.table] as StyleRecord[];
    this.current = String(tables.header[this.spec.currentVar] ?? 'Standard');
    if (pickCurrent || !this.records.some((r) => String(r.name) === this.selected)) this.selected = this.records.some((r) => String(r.name) === this.current) ? this.current : String(this.records[0]?.name ?? '');
    this.paint();
  }

  protected paint(): void {
    setText(this.head, `${t('Current style')}: ${this.current}`);
    const update = (node: HTMLElement, r: StyleRecord): void => {
      const name = String(r.name);
      const names = node.querySelectorAll('span');
      setText(names[1], name);
      setText(names[2], name === this.current ? t('current') : '');
      setClass(node, 'is-selected', name === this.selected);
      setClass(node, 'is-current', name === this.current);
      node.setAttribute('aria-selected', String(name === this.selected));
    };
    patchList(this.list, this.records, {
      key: (r) => String(r.name),
      create: (r) => {
        const row = el<HTMLButtonElement>('<button class="cv-list-row u2-sm-row" type="button" role="option"><span></span><span class="cv-list-name"></span><span class="cv-list-meta"></span></button>');
        const name = String(r.name);
        row.addEventListener('click', () => { this.selected = name; this.paint(); });
        update(row, r);
        return row;
      },
      update,
    });
    const rec = this.currentRecord();
    setText(this.propsHead, rec ? `${t('Properties of')} ${this.selected}` : '');
    if (rec) {
      for (const b of this.bindings) b.field.set(b.read(rec));
      this.afterFill(rec);
    }
    this.gate();
  }

  private gate(): void {
    const typed = this.nameBox.value.trim();
    const dup = this.records.some((r) => String(r.name).toLowerCase() === typed.toLowerCase());
    const standard = this.selected.toLowerCase() === 'standard';
    setDisabled(this.setCurrent, !this.selected || this.selected === this.current);
    setDisabled(this.addBtn, !typed || dup);
    setDisabled(this.renameBtn, !typed || dup || !this.selected || standard);
    setDisabled(this.delBtn, !this.selected || standard || this.selected === this.current);
  }

  protected tell(text: string): void {
    setText(this.note, text);
    setHidden(this.note, !text);
  }

  private async act(action: string, extra: Record<string, unknown>): Promise<boolean> {
    if (this.busy || !this.selected) return false;
    this.busy = true;
    try {
      const out = this.spec.command === 'style' ? await this.textAct(action, extra) : await exec(this.spec.command, { action, name: this.selected, ...extra });
      if (!out) return false;
      this.tell('');
      await this.reload();
      return true;
    } finally {
      this.busy = false;
    }
  }

  private textAct(action: string, extra: Record<string, unknown>): ReturnType<typeof exec> {
    if (action === 'current') return exec('style.current', { name: this.selected });
    if (action === 'delete') return exec('style.delete', { name: this.selected });
    if (action === 'rename') return exec('style.rename', { name: this.selected, new_name: extra.to });
    return exec('style', { name: this.selected, ...extra });
  }

  private async edit(key: string, value: unknown): Promise<void> {
    const rec = this.currentRecord();
    if (!rec) return;
    await this.act('modify', this.editArgs(rec, key, value));
  }

  protected editArgs(_rec: StyleRecord, key: string, value: unknown): Record<string, unknown> {
    return { [key]: value };
  }

  private async create(): Promise<void> {
    const name = this.nameBox.value.trim();
    if (!name || this.busy) return;
    this.busy = true;
    try {
      const out = await exec(this.spec.command === 'style' ? 'style' : this.spec.command, this.createArgs(this.currentRecord(), name));
      if (!out) return;
      this.nameBox.value = '';
      this.selected = name;
      await this.reload();
    } finally {
      this.busy = false;
    }
  }

  private async rename(): Promise<void> {
    const to = this.nameBox.value.trim();
    if (!to) return;
    const was = this.selected;
    if (await this.act('rename', { to })) {
      this.nameBox.value = '';
      this.selected = to;
      if (was === this.current) this.current = to;
      await this.reload();
    }
  }
}
