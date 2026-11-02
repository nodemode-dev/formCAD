import { api } from '../../io/api';
import { auto, type AliasList, type AliasRow } from '../../io/api-auto';
import { Dialog } from '../dialogs';
import { el, patchList, q, setClass, setDisabled, setHidden, setText, setValue } from '../dom';
import { pickPath, type FileKind } from '../file-dialogs';
import { t } from '../i18n';
import { toast } from '../toast';

const ALIAS_FILE: FileKind = { name: 'Command alias file', extensions: ['fcalias', 'pgp'] };
const SUGGEST_SLOTS = 8;

interface Row { alias: string; command: string; note: string; builtin: boolean }

export class AliasEditor extends Dialog {
  private base: AliasRow[] = [];
  private user = new Map<string, string>();
  private saved = '';
  private file = '';
  private limit = 2000;
  private length = 32;
  private sel = '';
  private filter = '';
  private known = new Set<string>();
  private editing: string | null = null;
  private timer = 0;
  private readonly head: HTMLElement;
  private readonly list: HTMLElement;
  private readonly search: HTMLInputElement;
  private readonly bAdd: HTMLButtonElement;
  private readonly bEdit: HTMLButtonElement;
  private readonly bRemove: HTMLButtonElement;
  private readonly form: HTMLElement;
  private readonly fAlias: HTMLInputElement;
  private readonly fCommand: HTMLInputElement;
  private readonly fMsg: HTMLElement;
  private readonly sugs: HTMLButtonElement[] = [];
  private readonly ok: HTMLButtonElement;
  private readonly apply: HTMLButtonElement;
  private readonly msg: HTMLElement;

  constructor() {
    super('Command Aliases', 560);
    this.scrim.classList.add('cv-scrim-through');
    this.body.appendChild(el(
      '<div class="ae"><div class="ae-top"><span class="ae-file"></span><span class="ae-tools"><button class="cv-btn ae-load" type="button">Load File...</button><button class="cv-btn ae-save" type="button">Save File...</button></span></div>' +
      '<input class="cv-input ae-filter" type="search" spellcheck="false" autocomplete="off" aria-label="Filter">' +
      '<div class="ae-table" role="table"><div class="ae-head" role="row"><span>Alias</span><span>Command</span><span></span></div><div class="ae-scroll" role="rowgroup"></div></div>' +
      '<div class="ae-btns"><button class="cv-btn ae-add" type="button">Add...</button><button class="cv-btn ae-edit" type="button">Edit...</button><button class="cv-btn ae-rm" type="button">Remove</button></div>' +
      '<div class="ae-form"><div class="ae-fields"><label class="cv-field"><span>Alias</span><input class="cv-input ae-fa" type="text" spellcheck="false" autocomplete="off"></label>' +
      '<label class="cv-field"><span>Command</span><input class="cv-input ae-fc" type="text" spellcheck="false" autocomplete="off"></label></div>' +
      '<div class="ae-sugs"></div><p class="ae-fmsg" role="alert"></p><div class="ae-fbtns"><button class="cv-btn cv-btn-primary ae-fsave" type="button">Save alias</button><button class="cv-btn ae-fdisc" type="button">Discard</button></div></div>' +
      '<p class="ae-msg" role="status"></p></div>'));
    this.head = q(this.body, '.ae-head');
    this.list = q(this.body, '.ae-scroll');
    this.search = q<HTMLInputElement>(this.body, '.ae-filter');
    this.bAdd = q<HTMLButtonElement>(this.body, '.ae-add');
    this.bEdit = q<HTMLButtonElement>(this.body, '.ae-edit');
    this.bRemove = q<HTMLButtonElement>(this.body, '.ae-rm');
    this.form = q(this.body, '.ae-form');
    this.fAlias = q<HTMLInputElement>(this.body, '.ae-fa');
    this.fCommand = q<HTMLInputElement>(this.body, '.ae-fc');
    this.fMsg = q(this.body, '.ae-fmsg');
    this.msg = q(this.body, '.ae-msg');
    const sugBox = q(this.body, '.ae-sugs');
    for (let i = 0; i < SUGGEST_SLOTS; i++) {
      const b = el<HTMLButtonElement>('<button class="cv-btn ae-sug" type="button" hidden></button>');
      b.addEventListener('click', () => { this.fCommand.value = (b.textContent ?? '').toLowerCase(); this.suggest(); });
      this.sugs.push(b);
      sugBox.appendChild(b);
    }
    this.words();
    this.ok = this.button('OK', 'primary', () => { void this.commit(true); });
    this.button('Cancel', 'ghost', () => this.close());
    this.apply = this.button('Apply', 'ghost', () => { void this.commit(false); });
    this.search.addEventListener('input', () => { this.filter = this.search.value.trim().toLowerCase(); this.paint(); });
    this.bAdd.addEventListener('click', () => this.openForm(null));
    this.bEdit.addEventListener('click', () => { if (this.sel) this.openForm(this.sel); });
    this.bRemove.addEventListener('click', () => this.remove());
    q(this.body, '.ae-fsave').addEventListener('click', () => this.saveRow());
    q(this.body, '.ae-fdisc').addEventListener('click', () => this.closeForm());
    this.fCommand.addEventListener('input', () => this.later());
    for (const f of [this.fAlias, this.fCommand]) f.addEventListener('keydown', (e) => { if (e.key === 'Enter') { e.preventDefault(); this.saveRow(); } });
    q(this.body, '.ae-load').addEventListener('click', () => { void this.loadFile(); });
    q(this.body, '.ae-save').addEventListener('click', () => { void this.saveFile(); });
  }

  private words(): void {
    this.search.placeholder = t('Filter by alias or command');
    const w = this.head.querySelectorAll('span');
    setText(w[0], t('Alias'));
    setText(w[1], t('Command'));
    for (const [sel, text] of [['.ae-load', 'Load File...'], ['.ae-save', 'Save File...'], ['.ae-add', 'Add...'], ['.ae-edit', 'Edit...'], ['.ae-rm', 'Remove'], ['.ae-fsave', 'Save alias'], ['.ae-fdisc', 'Discard']] as const) setText(q(this.body, sel), t(text));
    for (const [sel, text] of [['.ae-fa', 'Alias'], ['.ae-fc', 'Command']] as const) setText(q(this.body, sel).previousElementSibling, t(text));
  }

  async showFor(): Promise<void> {
    await this.pull();
    this.closeForm();
    if (!this.isOpen) this.open(this.search);
  }

  private async pull(): Promise<void> {
    try {
      if (this.known.size === 0) {
        const { commands } = await api.commands();
        this.known = new Set(commands.flatMap((c) => [c.name.toLowerCase(), ...c.aliases.map((a) => a.toLowerCase())]));
      }
      const l: AliasList = await auto.aliases();
      this.base = l.builtin;
      this.user = new Map(l.user.map((r) => [r.alias.toLowerCase(), r.command]));
      this.saved = this.snapshot();
      this.file = l.file;
      this.limit = l.limit;
      this.length = l.aliasLength;
    } catch (e) {
      this.say(e instanceof Error ? e.message : t('The engine did not answer'), true);
    }
    this.sel = '';
    this.paint();
  }

  private snapshot(): string {
    return JSON.stringify([...this.user.entries()].sort());
  }

  private rows(): Row[] {
    const out: Row[] = [];
    const shadow = new Set(this.base.map((b) => b.alias.toLowerCase()));
    for (const [alias, command] of [...this.user.entries()].sort()) out.push({ alias, command, note: shadow.has(alias) ? t('overrides built-in') : '', builtin: false });
    for (const b of this.base) if (!this.user.has(b.alias.toLowerCase())) out.push({ alias: b.alias, command: b.command, note: t('built-in'), builtin: true });
    return out;
  }

  private say(text: string, bad = false): void {
    setText(this.msg, text);
    setClass(this.msg, 'is-bad', bad);
  }

  private paint(): void {
    setText(q(this.body, '.ae-file'), this.file ? `${t('Alias file')}: ${this.file.split(/[\\/]/).pop()}` : t("No alias file loaded. REINIT replaces these aliases with a file's."));
    const rows = this.rows();
    patchList(this.list, rows, {
      key: (r) => r.alias.toLowerCase(),
      create: (r) => {
        const n = el<HTMLElement>('<div class="ae-row" role="row"><span class="ae-a"></span><span class="ae-c"></span><span class="ae-n"></span></div>');
        n.addEventListener('click', () => { this.sel = n.dataset.key ?? ''; this.syncSel(); });
        n.addEventListener('dblclick', () => { this.sel = n.dataset.key ?? ''; this.syncSel(); this.openForm(this.sel); });
        this.fill(n, r);
        return n;
      },
      update: (n, r) => this.fill(n, r),
    });
    const shown = new Set(rows.filter((r) => !this.filter || r.alias.toLowerCase().includes(this.filter) || r.command.toLowerCase().includes(this.filter)).map((r) => r.alias.toLowerCase()));
    for (const n of Array.from(this.list.children) as HTMLElement[]) setHidden(n, !shown.has(n.dataset.key ?? ''));
    this.syncSel();
    this.gate();
  }

  private fill(n: HTMLElement, r: Row): void {
    setText(q(n, '.ae-a'), r.alias);
    setText(q(n, '.ae-c'), r.command);
    setText(q(n, '.ae-n'), r.note);
    setClass(n, 'is-builtin', r.builtin);
  }

  private syncSel(): void {
    for (const n of Array.from(this.list.children) as HTMLElement[]) setClass(n, 'is-sel', n.dataset.key === this.sel);
    setDisabled(this.bEdit, !this.sel);
    setDisabled(this.bRemove, !this.sel || !this.user.has(this.sel));
  }

  private gate(): void {
    const dirty = this.snapshot() !== this.saved;
    setDisabled(this.apply, !dirty);
  }

  private openForm(alias: string | null): void {
    this.editing = alias;
    const row = alias ? this.rows().find((r) => r.alias.toLowerCase() === alias) : undefined;
    setValue(this.fAlias, row?.alias ?? '');
    setValue(this.fCommand, row?.command ?? '');
    this.fAlias.readOnly = !!alias;
    setText(this.fMsg, '');
    setClass(this.form, 'is-open', true);
    this.suggest();
    (alias ? this.fCommand : this.fAlias).focus();
  }

  private closeForm(): void {
    this.editing = null;
    setClass(this.form, 'is-open', false);
    for (const b of this.sugs) setHidden(b, true);
    setText(this.fMsg, '');
  }

  private later(): void {
    window.clearTimeout(this.timer);
    this.timer = window.setTimeout(() => this.suggest(), 120);
  }

  private suggest(): void {
    const text = this.fCommand.value.trim().toLowerCase();
    if (!text || this.known.has(text)) { for (const b of this.sugs) setHidden(b, true); return; }
    auto.suggest(text).then((r) => {
      this.sugs.forEach((b, i) => {
        const w = r.items[i];
        setHidden(b, !w);
        if (w) setText(b, w);
      });
    }).catch(() => { for (const b of this.sugs) setHidden(b, true); });
  }

  private saveRow(): void {
    const alias = this.fAlias.value.trim();
    const command = this.fCommand.value.trim();
    const key = alias.toLowerCase();
    let bad = '';
    if (!alias) bad = t('Type an alias name.');
    else if (!command) bad = t('Choose the command the alias starts.');
    else if (alias.length > this.length) bad = `${t('An alias can be at most')} ${this.length} ${t('characters.')}`;
    else if (!this.user.has(key) && this.user.size >= this.limit) bad = `${t('More than')} ${this.limit} ${t('aliases.')}`;
    if (bad) { setText(this.fMsg, bad); return; }
    this.user.set(key, command);
    this.sel = key;
    this.closeForm();
    this.paint();
  }

  private remove(): void {
    if (!this.sel || !this.user.has(this.sel)) return;
    this.user.delete(this.sel);
    this.sel = '';
    this.paint();
  }

  private async commit(close: boolean): Promise<void> {
    try {
      if (this.snapshot() !== this.saved) await auto.replaceAliases(Object.fromEntries(this.user));
      await this.pull();
      this.say(t('Aliases applied.'), false);
      if (close) this.close();
    } catch (e) {
      this.say(e instanceof Error ? e.message : t('The engine did not answer'), true);
    }
  }

  private async loadFile(): Promise<void> {
    const p = await pickPath('open', 'Load Alias File', '', [ALIAS_FILE], 'Load');
    if (!p) return;
    try {
      const r = await auto.loadAliases(p);
      toast(r.message);
      await this.pull();
      this.say(r.warnings.length ? `${r.warnings.length} ${t('warnings')}: ${r.warnings[0]}` : r.message, r.warnings.length > 0);
    } catch (e) {
      this.say(e instanceof Error ? e.message : t('The engine did not answer'), true);
    }
  }

  private async saveFile(): Promise<void> {
    const p = await pickPath('save', 'Save Alias File', this.file || 'aliases.fcalias', [ALIAS_FILE], 'Save');
    if (!p) return;
    try {
      if (this.snapshot() !== this.saved) await auto.replaceAliases(Object.fromEntries(this.user));
      const r = await auto.saveAliases(p);
      await this.pull();
      this.say(`${t('Saved')} ${r.path}`, false);
    } catch (e) {
      this.say(e instanceof Error ? e.message : t('The engine did not answer'), true);
    }
  }
}
