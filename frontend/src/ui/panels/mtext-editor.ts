import { api, ApiError } from '../../io/api';
import type { MTextProps } from '../../io/api';
import { drawingCanvas } from '../../canvas/mount';
import { docStore } from '../doc-store';
import { el, q, setClass, setHidden, setStyleVar, setText, setValue } from '../dom';
import { t } from '../i18n';
import { toast } from '../toast';
import { loadTables } from '../dialogs/engine';
import { copyPara, DEFAULT_FMT, DEFAULT_PARA, fmtKey, parseContents, plainOf, serializeContents } from './mtext-codes';
import type { MFmt, MNode, MPara, MParagraph } from './mtext-codes';

const FONTS = ['Arial', 'Times New Roman', 'Courier New', 'Verdana', 'Georgia', 'Calibri'];
const ATTACH = ['Top left', 'Top center', 'Top right', 'Middle left', 'Middle center', 'Middle right', 'Bottom left', 'Bottom center', 'Bottom right'];
const ACI_CSS: Record<number, string> = { 1: '#ff3b30', 2: '#ffd60a', 3: '#30d158', 4: '#64d2ff', 5: '#0a84ff', 6: '#bf5af2', 7: '#f2f2f2' };
const SYMBOLS: ReadonlyArray<readonly [string, string, string]> = [['°', 'Degree', 'deg'], ['±', 'Plus/minus', '+/-'], ['⌀', 'Diameter', 'dia']];
const COLORS: ReadonlyArray<readonly [string, string]> = [['', 'ByLayer'], ['i:1', 'Red'], ['i:2', 'Yellow'], ['i:3', 'Green'], ['i:4', 'Cyan'], ['i:5', 'Blue'], ['i:6', 'Magenta'], ['i:7', 'White'], ['r', 'True color...']];

interface Pos { p: number; o: number }
interface Sel { a: Pos; b: Pos }

const SIZE_MIN = 13;
const SIZE_MAX = 36;

const cssColor = (c: string): string => {
  if (c.startsWith('i:')) return ACI_CSS[Number(c.slice(2))] ?? '#a0a0a0';
  if (c.startsWith('r:')) return `#${(Number(c.slice(2)) & 0xffffff).toString(16).padStart(6, '0')}`;
  return '';
};

const leafLen = (n: MNode): number => (n.t === 'text' ? n.s.length : 1);
const paraLen = (p: MParagraph): number => p.nodes.reduce((s, n) => s + leafLen(n), 0);
const cmpPos = (a: Pos, b: Pos): number => (a.p - b.p) || (a.o - b.o);

function merge(nodes: MNode[]): MNode[] {
  const out: MNode[] = [];
  for (const n of nodes) {
    const last = out[out.length - 1];
    if (n.t === 'text' && n.s === '') continue;
    if (last && last.t === 'text' && n.t === 'text' && fmtKey(last.f) === fmtKey(n.f)) last.s += n.s;
    else out.push(n.t === 'text' ? { ...n } : n);
  }
  return out;
}

function splitNodes(nodes: MNode[], offset: number): { left: MNode[]; right: MNode[] } {
  const left: MNode[] = [], right: MNode[] = [];
  let at = 0;
  for (const n of nodes) {
    const len = leafLen(n);
    if (at + len <= offset) left.push(n);
    else if (at >= offset) right.push(n);
    else if (n.t === 'text') {
      left.push({ t: 'text', s: n.s.slice(0, offset - at), f: { ...n.f } });
      right.push({ t: 'text', s: n.s.slice(offset - at), f: { ...n.f } });
    } else right.push(n);
    at += len;
  }
  return { left, right };
}

export class MTextEditor {
  private readonly root: HTMLElement;
  private readonly edit: HTMLElement;
  private readonly bar: HTMLElement;
  private readonly ruler: HTMLElement;
  private readonly findBox: HTMLElement;
  private readonly hint: HTMLElement;
  private readonly okBtn: HTMLButtonElement;
  private readonly buttons = new Map<string, HTMLButtonElement>();
  private readonly styleSel: HTMLSelectElement;
  private readonly fontSel: HTMLSelectElement;
  private readonly heightBox: HTMLInputElement;
  private readonly colorSel: HTMLSelectElement;
  private readonly colorPick: HTMLInputElement;
  private readonly justSel: HTMLSelectElement;
  private readonly colSel: HTMLSelectElement;
  private readonly colCount: HTMLInputElement;
  private readonly colGutter: HTMLInputElement;
  private readonly findIn: HTMLInputElement;
  private readonly replIn: HTMLInputElement;
  private readonly caseBox: HTMLInputElement;
  private readonly markFirst: HTMLElement;
  private readonly markLeft: HTMLElement;
  private readonly tabMarks: HTMLElement[] = [];
  private docId = '';
  private handle: number | null = null;
  private props: MTextProps = {};
  private startProps: MTextProps = {};
  private baseH = 2.5;
  private face = 'txt';
  private pending: Partial<MFmt> | null = null;
  private pendingAt: Pos | null = null;
  private busy = false;
  private frame = 0;
  private lastFind: Pos | null = null;
  private lastSel: Sel | null = null;
  private shieldOff: (() => void) | null = null;
  private viewOff: (() => void) | null = null;

  constructor(private readonly host: HTMLElement) {
    this.root = el(
      '<div class="u2-mt" hidden>' +
      '<div class="u2-mt-bar"></div>' +
      '<div class="u2-mt-ruler"><div class="u2-mt-ticks"></div><span class="u2-mt-first" title="First line indent"></span><span class="u2-mt-left" title="Left indent"></span></div>' +
      '<div class="u2-mt-edit" contenteditable="true" spellcheck="false" role="textbox" aria-multiline="true"></div>' +
      '<div class="u2-mt-find" hidden></div>' +
      '<div class="u2-mt-foot"><span class="u2-mt-hint"></span><button class="cv-btn" type="button" data-cancel></button><button class="cv-btn cv-btn-primary" type="button" data-ok></button></div>' +
      '</div>');
    this.bar = q(this.root, '.u2-mt-bar');
    this.ruler = q(this.root, '.u2-mt-ruler');
    this.edit = q(this.root, '.u2-mt-edit');
    this.findBox = q(this.root, '.u2-mt-find');
    this.hint = q(this.root, '.u2-mt-hint');
    this.markFirst = q(this.root, '.u2-mt-first');
    this.markLeft = q(this.root, '.u2-mt-left');
    this.okBtn = q(this.root, '[data-ok]');
    setText(this.okBtn, t('OK'));
    setText(q(this.root, '[data-cancel]'), t('Cancel'));
    setText(this.hint, `${t('Ctrl+Enter to finish')}`);
    this.styleSel = this.select('Style', [['Standard', 'Standard']], 'u2-mt-wide');
    this.fontSel = this.select('Font', [['', 'Style font'], ...FONTS.map((f) => [f, f] as const)], 'u2-mt-wide');
    this.heightBox = this.number('Text height', 'u2-mt-num');
    for (const [id, label, title] of [['b', 'B', 'Bold'], ['i', 'I', 'Italic'], ['u', 'U', 'Underline'], ['o', 'O', 'Overline'], ['k', 'S', 'Strikethrough']] as const) this.toggle(id, label, title);
    this.colorSel = this.select('Text color', COLORS, 'u2-mt-wide');
    this.colorPick = el<HTMLInputElement>('<input type="color" class="u2-mt-color" hidden tabindex="-1">');
    this.bar.appendChild(this.colorPick);
    this.action('stack', 'a/b', 'Stack');
    this.justSel = this.select('Justification', ATTACH.map((a, i) => [String(i + 1), a] as const), 'u2-mt-wide');
    for (const [id, label, title] of [['al', 'L', 'Align left'], ['ac', 'C', 'Align center'], ['ar', 'R', 'Align right'], ['aj', 'J', 'Justify'], ['bullet', '•', 'Bulleted list'], ['number', '1.', 'Numbered list'], ['tab', 'Tab', 'Insert tab']] as const) this.action(id, label, title);
    this.colSel = this.select('Columns', [['none', 'No columns'], ['dynamic', 'Dynamic columns'], ['static', 'Static columns']], 'u2-mt-wide');
    this.colCount = this.number('Column count', 'u2-mt-num');
    this.colGutter = this.number('Gutter', 'u2-mt-num');
    for (const [ch, title, label] of SYMBOLS) this.action(`sym:${ch}`, label, title);
    this.action('find', 'Find', 'Find and Replace');
    this.findIn = el<HTMLInputElement>('<input class="cv-input" type="text" spellcheck="false">');
    this.replIn = el<HTMLInputElement>('<input class="cv-input" type="text" spellcheck="false">');
    this.caseBox = el<HTMLInputElement>('<input type="checkbox">');
    this.buildFind();
    host.appendChild(this.root);
    this.wire();
  }

  get isOpen(): boolean { return !this.root.hidden; }
  get target(): number | null { return this.handle; }

  private select(label: string, options: ReadonlyArray<readonly [string, string]>, cls: string): HTMLSelectElement {
    const s = el<HTMLSelectElement>(`<select class="cv-input ${cls}" data-native></select>`);
    s.title = t(label);
    s.setAttribute('aria-label', label);
    for (const [v, text] of options) {
      const o = document.createElement('option');
      o.value = v;
      o.textContent = t(text);
      s.appendChild(o);
    }
    this.bar.appendChild(s);
    return s;
  }

  private number(label: string, cls: string): HTMLInputElement {
    const n = el<HTMLInputElement>(`<input class="cv-input ${cls}" type="text" inputmode="decimal" autocomplete="off">`);
    n.title = t(label);
    n.setAttribute('aria-label', label);
    n.placeholder = label.split(' ').pop() ?? '';
    this.bar.appendChild(n);
    return n;
  }

  private toggle(id: string, label: string, title: string): void {
    const b = el<HTMLButtonElement>(`<button class="u2-mt-btn u2-mt-${id}" type="button" data-fmt="${id}"></button>`);
    setText(b, label);
    b.title = t(title);
    b.setAttribute('aria-pressed', 'false');
    this.bar.appendChild(b);
    this.buttons.set(id, b);
  }

  private action(id: string, label: string, title: string): void {
    const b = el<HTMLButtonElement>(`<button class="u2-mt-btn" type="button" data-act="${id}"></button>`);
    setText(b, label);
    b.title = t(title);
    this.bar.appendChild(b);
    this.buttons.set(id, b);
  }

  private buildFind(): void {
    const mk = (label: string, run: () => void): HTMLButtonElement => {
      const b = el<HTMLButtonElement>('<button class="cv-btn" type="button"></button>');
      setText(b, t(label));
      b.addEventListener('click', run);
      return b;
    };
    const caseLabel = el('<label class="u2-mt-case"><span></span></label>');
    setText(q(caseLabel, 'span'), t('Match case'));
    caseLabel.prepend(this.caseBox);
    this.findIn.placeholder = t('Find');
    this.replIn.placeholder = t('Replace with');
    this.findBox.append(this.findIn, this.replIn, caseLabel, mk('Find Next', () => this.findNext()), mk('Replace', () => this.replaceOne()), mk('Replace All', () => this.replaceAll()));
    this.findIn.addEventListener('keydown', (e) => { if (e.key === 'Enter') { e.preventDefault(); this.findNext(); } });
  }

  private wire(): void {
    this.root.addEventListener('keydown', (e) => this.onKey(e));
    this.root.addEventListener('pointerdown', (e) => e.stopPropagation());
    this.root.addEventListener('wheel', (e) => e.stopPropagation(), { passive: true });
    this.bar.addEventListener('mousedown', (e) => { if ((e.target as HTMLElement).closest('button')) e.preventDefault(); });
    this.bar.addEventListener('click', (e) => {
      const b = (e.target as HTMLElement).closest<HTMLButtonElement>('button');
      if (!b) return;
      if (b.dataset.fmt) this.toggleFmt(b.dataset.fmt as 'b' | 'i' | 'u' | 'o' | 'k');
      else if (b.dataset.act) this.act(b.dataset.act);
    });
    this.styleSel.addEventListener('change', () => { this.props.style = this.styleSel.value; this.edit.focus(); });
    this.fontSel.addEventListener('change', () => { this.patchFmt({ f: this.fontSel.value }); this.edit.focus(); });
    this.heightBox.addEventListener('change', () => {
      const v = Number(this.heightBox.value);
      this.patchFmt({ h: Number.isFinite(v) && v > 0 && Math.abs(v - this.baseH) > 1e-9 ? String(Number(v.toFixed(6))) : '' });
      this.edit.focus();
    });
    this.colorSel.addEventListener('change', () => {
      if (this.colorSel.value === 'r') { this.colorPick.click(); return; }
      this.patchFmt({ c: this.colorSel.value });
      this.edit.focus();
    });
    this.colorPick.addEventListener('input', () => {
      const n = parseInt(this.colorPick.value.slice(1), 16);
      this.patchFmt({ c: `r:${n}` });
    });
    this.justSel.addEventListener('change', () => { this.props.attachment = Number(this.justSel.value); this.layout(); this.edit.focus(); });
    const cols = (): void => { this.props.columns = this.columnsValue(); this.syncColumns(); this.edit.focus(); };
    this.colSel.addEventListener('change', cols);
    this.colCount.addEventListener('change', cols);
    this.colGutter.addEventListener('change', cols);
    q(this.root, '[data-ok]').addEventListener('click', () => void this.commit());
    q(this.root, '[data-cancel]').addEventListener('click', () => void this.cancel());
    this.edit.addEventListener('beforeinput', (e) => this.beforeInput(e as InputEvent));
    this.edit.addEventListener('input', () => this.schedule());
    this.edit.addEventListener('paste', (e) => {
      e.preventDefault();
      const text = e.clipboardData?.getData('text/plain') ?? '';
      if (text) this.insertText(text);
    });
    this.edit.addEventListener('keyup', () => this.schedule());
    this.edit.addEventListener('pointerup', () => this.schedule());
    document.addEventListener('selectionchange', () => { if (this.isOpen && document.activeElement === this.edit) this.schedule(); });
    this.wireRuler();
  }

  private onKey(e: KeyboardEvent): void {
    e.stopPropagation();
    if (e.key === 'Escape') { e.preventDefault(); void this.cancel(); return; }
    if (e.key === 'Enter' && (e.ctrlKey || e.metaKey)) { e.preventDefault(); void this.commit(); return; }
    const mod = e.ctrlKey || e.metaKey;
    if (mod && !e.shiftKey && !e.altKey) {
      const k = e.key.toLowerCase();
      if (k === 'b' || k === 'i' || k === 'u') { e.preventDefault(); this.toggleFmt(k); return; }
      if (k === 'f' || k === 'h') { e.preventDefault(); this.act('find'); return; }
    }
    if (e.target === this.edit && e.key === 'Enter' && !mod) { e.preventDefault(); this.insertText('\n'); return; }
    if (e.target === this.edit && e.key === 'Tab' && !mod) { e.preventDefault(); this.insertText('\t'); }
  }

  private beforeInput(e: InputEvent): void {
    if (e.inputType === 'insertText' && this.pending && e.data) {
      e.preventDefault();
      this.insertText(e.data);
    }
  }

  private schedule(): void {
    if (this.frame) return;
    this.frame = requestAnimationFrame(() => { this.frame = 0; this.syncBar(); });
  }

  async openPending(docId: string, props: MTextProps): Promise<void> {
    if (this.isOpen) return;
    await this.begin(docId, null, props, '');
  }

  async openExisting(docId: string, handle: number): Promise<void> {
    if (this.isOpen) return;
    try {
      const rec = await api.mtextRead(docId, handle);
      await this.begin(docId, handle, rec.props, rec.contents);
    } catch (e) {
      toast(e instanceof ApiError || e instanceof Error ? e.message : 'The text could not be read', 'error');
    }
  }

  private async begin(docId: string, handle: number | null, props: MTextProps, contents: string): Promise<void> {
    this.docId = docId;
    this.handle = handle;
    this.props = JSON.parse(JSON.stringify(props)) as MTextProps;
    this.startProps = JSON.parse(JSON.stringify(props)) as MTextProps;
    this.baseH = Number(props.height) > 0 ? Number(props.height) : 2.5;
    this.pending = null;
    this.lastFind = null;
    const tables = await loadTables();
    const styles = (tables?.textstyles ?? []).map((s) => String(s.name));
    this.fillSelect(this.styleSel, styles.length ? styles : ['Standard']);
    const rec = (tables?.textstyles ?? []).find((s) => String(s.name).toLowerCase() === String(props.style ?? 'Standard').toLowerCase());
    this.face = String(rec?.font ?? 'txt');
    this.styleSel.value = String(rec?.name ?? props.style ?? 'Standard');
    this.props.style = this.styleSel.value;
    const faces = [...FONTS];
    if (this.face && !faces.includes(this.face)) faces.splice(0, 0, this.face);
    this.fillSelect(this.fontSel, ['', ...faces], (v) => (v === '' ? t('Style font') : v));
    const att = Math.min(9, Math.max(1, Number(props.attachment) || 1));
    this.justSel.value = String(att);
    this.props.attachment = att;
    const c = (props.columns ?? {}) as { type?: string; count?: number; gutter?: number };
    this.colSel.value = c.type === 'static' || c.type === 'dynamic' ? c.type : 'none';
    setValue(this.colCount, String(c.count ?? 2));
    setValue(this.colGutter, String(c.gutter ?? 0));
    this.syncColumns();
    this.render(parseContents(contents));
    setHidden(this.findBox, true);
    setHidden(this.root, false);
    setText(this.hint, `${t('Ctrl+Enter to finish')}`);
    this.attachWorld();
    this.layout();
    this.edit.focus();
    this.selectEnd();
    this.syncBar();
  }

  private fillSelect(sel: HTMLSelectElement, values: string[], label: (v: string) => string = (v) => v): void {
    const same = sel.options.length === values.length && Array.from(sel.options).every((o, i) => o.value === values[i]);
    if (same) return;
    sel.replaceChildren(...values.map((v) => { const o = document.createElement('option'); o.value = v; o.textContent = label(v); return o; }));
  }

  private attachWorld(): void {
    const c = drawingCanvas();
    if (!c) return;
    this.viewOff?.();
    this.viewOff = c.on('view', () => this.layout());
    const shield = (e: PointerEvent): void => {
      if (!this.root.contains(e.target as Node)) { e.stopPropagation(); e.preventDefault(); }
    };
    this.host.addEventListener('pointerdown', shield, true);
    this.shieldOff = () => this.host.removeEventListener('pointerdown', shield, true);
  }

  private layout(): void {
    if (!this.isOpen) return;
    const c = drawingCanvas();
    const pos = (this.props.position ?? [0, 0]) as number[];
    const att = Math.min(9, Math.max(1, Number(this.props.attachment) || 1));
    const box = this.host.getBoundingClientRect();
    const scale = c ? c.view.scale : 1;
    const size = Math.min(SIZE_MAX, Math.max(SIZE_MIN, this.baseH * scale));
    const wWorld = Number(this.props.width) || 0;
    const width = Math.min(box.width * 0.9, Math.max(280, wWorld > 0 ? wWorld * scale : 380));
    const s = c ? c.screenFromWorld(pos[0], pos[1]) : [box.width / 2, box.height / 2];
    const col = (att - 1) % 3;
    const row = Math.floor((att - 1) / 3);
    let left = s[0] - (col === 0 ? 0 : col === 1 ? width / 2 : width);
    const textH = 120;
    let top = s[1] - 70 - (row === 0 ? 0 : row === 1 ? textH / 2 : textH);
    left = Math.min(Math.max(4, left), Math.max(4, box.width - width - 4));
    top = Math.min(Math.max(4, top), Math.max(4, box.height - 250));
    setStyleVar(this.root, '--u2-mt-x', `${Math.round(left)}px`);
    setStyleVar(this.root, '--u2-mt-y', `${Math.round(top)}px`);
    setStyleVar(this.root, '--u2-mt-w', `${Math.round(width)}px`);
    setStyleVar(this.root, '--u2-mt-em', `${Math.round(size)}px`);
    this.syncRuler();
  }

  private close(): void {
    setHidden(this.root, true);
    this.viewOff?.();
    this.viewOff = null;
    this.shieldOff?.();
    this.shieldOff = null;
  }

  private async cancel(): Promise<void> {
    if (!this.isOpen) return;
    const wasNew = this.handle === null;
    this.close();
    if (wasNew && this.docId) {
      try {
        const s = await api.cancelCommand(this.docId);
        document.dispatchEvent(new CustomEvent('formcad:command-state', { detail: { doc: this.docId, state: s } }));
      } catch { return; }
    }
  }

  private async commit(): Promise<void> {
    if (this.busy || !this.isOpen) return;
    const contents = serializeContents(this.read(), this.face);
    if (!plainOf(this.read()).trim()) {
      toast('Text is empty', 'error');
      return;
    }
    this.busy = true;
    try {
      const changed = this.changedProps();
      if (this.handle === null) {
        const out = await api.mtextWrite(this.docId, { contents });
        if (out.state) document.dispatchEvent(new CustomEvent('formcad:command-state', { detail: { doc: this.docId, state: out.state } }));
        if (out.handle && Object.keys(changed).length) await api.mtextWrite(this.docId, { handle: out.handle, contents, props: changed });
      } else {
        await api.mtextWrite(this.docId, { handle: this.handle, contents, props: changed });
      }
      this.close();
    } catch (e) {
      toast(e instanceof ApiError || e instanceof Error ? e.message : 'The text could not be saved', 'error');
    } finally {
      this.busy = false;
    }
  }

  private changedProps(): Record<string, unknown> {
    const out: Record<string, unknown> = {};
    if (String(this.props.style) !== String(this.startProps.style)) out.style = this.props.style;
    if (Number(this.props.attachment) !== Number(this.startProps.attachment)) out.attachment = this.props.attachment;
    if (JSON.stringify(this.props.columns ?? {}) !== JSON.stringify(this.startProps.columns ?? {})) out.columns = this.props.columns ?? {};
    if (Number(this.props.height) !== Number(this.startProps.height)) out.height = this.props.height;
    return out;
  }

  private columnsValue(): Record<string, unknown> {
    const kind = this.colSel.value;
    if (kind === 'none') return {};
    const prev = (this.startProps.columns ?? {}) as Record<string, unknown>;
    return { ...(prev.type === kind ? prev : {}), type: kind, count: Math.max(1, Math.round(Number(this.colCount.value) || 2)), gutter: Math.max(0, Number(this.colGutter.value) || 0) };
  }

  private syncColumns(): void {
    const on = this.colSel.value !== 'none';
    setHidden(this.colCount, !(this.colSel.value === 'static'));
    setHidden(this.colGutter, !on);
  }

  private render(paras: MParagraph[]): void {
    const kids = Array.from(this.edit.children) as HTMLElement[];
    paras.forEach((para, i) => {
      let node = kids[i];
      if (!node) { node = document.createElement('p'); this.edit.appendChild(node); }
      this.paint(node, para);
    });
    for (let i = kids.length - 1; i >= paras.length; i--) kids[i].remove();
  }

  private paint(node: HTMLElement, para: MParagraph): void {
    const sig = `${JSON.stringify(para.p)}#${para.nodes.map((n) => n.t === 'text' ? `t${fmtKey(n.f)}:${n.s}` : n.t === 'stack' ? `s${fmtKey(n.f)}:${n.top}${n.sep}${n.bot}` : `b${fmtKey(n.f)}`).join('\u0001')}`;
    if (node.dataset.sig === sig && node.tagName === 'P') return;
    node.dataset.sig = sig;
    node.dataset.pp = JSON.stringify(para.p);
    const h = this.baseH;
    node.style.paddingLeft = `${para.p.l / h}em`;
    node.style.paddingRight = `${para.p.r / h}em`;
    node.style.textIndent = `${para.p.i / h}em`;
    node.style.marginTop = `${para.p.b / h}em`;
    node.style.marginBottom = `${para.p.a / h}em`;
    node.style.textAlign = para.p.q === 'c' ? 'center' : para.p.q === 'r' ? 'right' : para.p.q === 'j' || para.p.q === 'd' ? 'justify' : '';
    const parts: Node[] = [];
    for (const n of para.nodes) parts.push(this.build(n));
    if (!parts.length) {
      const br = document.createElement('br');
      br.dataset.ph = '1';
      parts.push(br);
    }
    node.replaceChildren(...parts);
  }

  private style(span: HTMLElement, f: MFmt): void {
    for (const k of ['b', 'i', 'u', 'o', 'k'] as const) if (f[k]) span.dataset[k] = '1';
    for (const k of ['c', 'f', 'h', 'w', 'q', 't', 'a'] as const) if (f[k]) span.dataset[k] = f[k];
    if (f.b) span.style.fontWeight = '700';
    if (f.i) span.style.fontStyle = 'italic';
    const deco = [f.u ? 'underline' : '', f.o ? 'overline' : '', f.k ? 'line-through' : ''].filter(Boolean).join(' ');
    if (deco) span.style.textDecorationLine = deco;
    const col = cssColor(f.c);
    if (col) span.style.color = col;
    if (f.f) span.style.fontFamily = `"${f.f}", sans-serif`;
    if (f.h) {
      const raw = f.h.trim();
      const mult = raw.toLowerCase().endsWith('x');
      const v = Number(mult ? raw.slice(0, -1) : raw);
      if (Number.isFinite(v) && v > 0) span.style.fontSize = `${mult ? v : v / this.baseH}em`;
    }
  }

  private build(n: MNode): Node {
    if (n.t === 'br') {
      const br = document.createElement('br');
      br.dataset.nl = '1';
      return br;
    }
    const span = document.createElement('span');
    this.style(span, n.f);
    if (n.t === 'text') {
      span.textContent = n.s;
      if (!Object.keys(span.dataset).length) { return document.createTextNode(n.s); }
      return span;
    }
    span.className = 'u2-mt-stack';
    span.contentEditable = 'false';
    span.dataset.top = n.top;
    span.dataset.sep = n.sep;
    span.dataset.bot = n.bot;
    const top = document.createElement('span');
    const bot = document.createElement('span');
    top.textContent = n.top;
    bot.textContent = n.bot;
    if (n.sep === '#') span.classList.add('is-diag');
    if (n.sep === '^') span.classList.add('is-tol');
    span.append(top, bot);
    return span;
  }

  private fmtOf(node: Node, root: HTMLElement, self = false): MFmt {
    const chain: HTMLElement[] = [];
    for (let cur: Node | null = self ? node : node.parentNode; cur && cur !== root; cur = cur.parentNode) if (cur instanceof HTMLElement && cur.tagName !== 'P' && cur.tagName !== 'DIV') chain.unshift(cur);
    const f: MFmt = { ...DEFAULT_FMT };
    for (const s of chain) {
      for (const k of ['b', 'i', 'u', 'o', 'k'] as const) if (s.dataset[k] !== undefined) f[k] = s.dataset[k] === '1';
      for (const k of ['c', 'f', 'h', 'w', 'q', 't', 'a'] as const) if (s.dataset[k] !== undefined) f[k] = s.dataset[k] ?? '';
    }
    return f;
  }

  read(): MParagraph[] {
    const out: MParagraph[] = [];
    const blocks = Array.from(this.edit.childNodes);
    let loose: MParagraph | null = null;
    for (const b of blocks) {
      if (b instanceof HTMLElement && (b.tagName === 'P' || b.tagName === 'DIV')) {
        loose = null;
        let pp: MPara = copyPara(DEFAULT_PARA);
        try { if (b.dataset.pp) pp = { ...pp, ...(JSON.parse(b.dataset.pp) as MPara) }; } catch { pp = copyPara(DEFAULT_PARA); }
        const para: MParagraph = { p: pp, nodes: [] };
        const walker = document.createTreeWalker(b, NodeFilter.SHOW_ELEMENT | NodeFilter.SHOW_TEXT, {
          acceptNode: (n) => (n instanceof HTMLElement && n.parentElement?.closest('.u2-mt-stack') ? NodeFilter.FILTER_REJECT : NodeFilter.FILTER_ACCEPT),
        });
        for (let n = walker.nextNode(); n; n = walker.nextNode()) {
          if (n instanceof Text) {
            if (n.data) para.nodes.push({ t: 'text', s: n.data.replace(/\n/g, ''), f: this.fmtOf(n, b) });
          } else if (n instanceof HTMLElement) {
            if (n.classList.contains('u2-mt-stack')) para.nodes.push({ t: 'stack', top: n.dataset.top ?? '', sep: n.dataset.sep ?? '/', bot: n.dataset.bot ?? '', f: this.fmtOf(n, b, true) });
            else if (n.tagName === 'BR' && n.dataset.nl) para.nodes.push({ t: 'br', f: this.fmtOf(n, b) });
          }
        }
        para.nodes = merge(para.nodes);
        out.push(para);
      } else if (b instanceof Text && b.data) {
        if (!loose) { loose = { p: copyPara(DEFAULT_PARA), nodes: [] }; out.push(loose); }
        loose.nodes.push({ t: 'text', s: b.data, f: { ...DEFAULT_FMT } });
      }
    }
    return out.length ? out : [{ p: copyPara(DEFAULT_PARA), nodes: [] }];
  }

  private posOf(node: Node, offset: number): Pos | null {
    let block: Node | null = node;
    while (block && block.parentNode !== this.edit) block = block.parentNode;
    if (!block || !(block instanceof HTMLElement)) return null;
    const p = Array.from(this.edit.children).indexOf(block);
    if (p < 0) return null;
    let o = 0;
    const walker = document.createTreeWalker(block, NodeFilter.SHOW_ELEMENT | NodeFilter.SHOW_TEXT, {
      acceptNode: (n) => (n instanceof HTMLElement && n.parentElement?.closest('.u2-mt-stack') ? NodeFilter.FILTER_REJECT : NodeFilter.FILTER_ACCEPT),
    });
    const countTo = (target: Node, off: number): number | null => {
      let total = 0;
      for (let n = walker.nextNode(); n; n = walker.nextNode()) {
        if (n === target) return total + (n instanceof Text ? off : off > 0 ? 1 : 0);
        if (n instanceof Text) total += n.data.length;
        else if (n instanceof HTMLElement && (n.classList.contains('u2-mt-stack') || (n.tagName === 'BR' && n.dataset.nl))) {
          if (n.contains(target)) return total + (off > 0 ? 1 : 0);
          total += 1;
        }
      }
      return null;
    };
    if (node === block) {
      let total = 0;
      const kids = Array.from(block.childNodes).slice(0, offset);
      for (const k of kids) total += this.lengthOf(k);
      return { p, o: total };
    }
    const r = countTo(node, offset);
    o = r ?? 0;
    return { p, o };
  }

  private lengthOf(n: Node): number {
    if (n instanceof Text) return n.data.length;
    if (n instanceof HTMLElement) {
      if (n.classList.contains('u2-mt-stack') || (n.tagName === 'BR' && n.dataset.nl)) return 1;
      if (n.tagName === 'BR') return 0;
      return Array.from(n.childNodes).reduce((s, c) => s + this.lengthOf(c), 0);
    }
    return 0;
  }

  private selection(): Sel | null {
    const s = document.getSelection();
    if (!s || !s.rangeCount || !this.edit.contains(s.anchorNode)) return this.root.contains(document.activeElement) ? this.lastSel : null;
    const a = this.posOf(s.anchorNode as Node, s.anchorOffset);
    const b = this.posOf(s.focusNode as Node, s.focusOffset);
    if (!a || !b) return null;
    this.lastSel = cmpPos(a, b) <= 0 ? { a, b } : { a: b, b: a };
    return this.lastSel;
  }

  private domPoint(pos: Pos): { node: Node; offset: number } {
    const block = this.edit.children[Math.min(pos.p, this.edit.children.length - 1)] as HTMLElement;
    let left = pos.o;
    const walker = document.createTreeWalker(block, NodeFilter.SHOW_ELEMENT | NodeFilter.SHOW_TEXT, {
      acceptNode: (n) => (n instanceof HTMLElement && n.parentElement?.closest('.u2-mt-stack') ? NodeFilter.FILTER_REJECT : NodeFilter.FILTER_ACCEPT),
    });
    let lastText: Text | null = null;
    for (let n = walker.nextNode(); n; n = walker.nextNode()) {
      if (n instanceof Text) {
        if (left <= n.data.length) return { node: n, offset: left };
        left -= n.data.length;
        lastText = n;
      } else if (n instanceof HTMLElement && (n.classList.contains('u2-mt-stack') || (n.tagName === 'BR' && n.dataset.nl))) {
        if (left === 0) return { node: block, offset: Array.from(block.childNodes).indexOf(n) };
        left -= 1;
      }
    }
    if (lastText) return { node: lastText, offset: lastText.data.length };
    return { node: block, offset: block.childNodes.length };
  }

  private setSelection(sel: Sel): void {
    const s = document.getSelection();
    if (!s) return;
    const a = this.domPoint(sel.a), b = this.domPoint(sel.b);
    const range = document.createRange();
    range.setStart(a.node, a.offset);
    range.setEnd(b.node, b.offset);
    s.removeAllRanges();
    s.addRange(range);
  }

  private selectEnd(): void {
    const paras = this.read();
    const last = paras.length - 1;
    const pos = { p: last, o: paraLen(paras[last]) };
    this.setSelection({ a: pos, b: pos });
  }

  private fmtBefore(paras: MParagraph[], pos: Pos): MFmt {
    const para = paras[pos.p];
    let at = 0;
    let last: MFmt | null = null;
    for (const n of para.nodes) {
      const len = leafLen(n);
      if (pos.o > at) last = n.f;
      if (pos.o <= at + len) break;
      at += len;
    }
    if (!last && para.nodes[0]) last = para.nodes[0].f;
    return { ...(last ?? DEFAULT_FMT) };
  }

  private deleteRange(paras: MParagraph[], sel: Sel): Pos {
    const { a, b } = sel;
    if (a.p === b.p) {
      const para = paras[a.p];
      const { left } = splitNodes(para.nodes, a.o);
      const { right } = splitNodes(para.nodes, b.o);
      para.nodes = merge([...left, ...right]);
    } else {
      const first = paras[a.p];
      const last = paras[b.p];
      const { left } = splitNodes(first.nodes, a.o);
      const { right } = splitNodes(last.nodes, b.o);
      first.nodes = merge([...left, ...right]);
      paras.splice(a.p + 1, b.p - a.p);
    }
    return { p: a.p, o: a.o };
  }

  private modify(fn: (paras: MParagraph[], sel: Sel) => Sel | void): void {
    const sel = this.selection();
    if (!sel) return;
    const paras = this.read();
    const out = fn(paras, sel) ?? sel;
    this.render(paras);
    this.edit.focus();
    this.setSelection(out);
    this.syncBar();
  }

  private insertText(text: string): void {
    this.modify((paras, sel) => {
      let pos = sel.a;
      const collapsed = cmpPos(sel.a, sel.b) === 0;
      const base = this.fmtBefore(paras, collapsed ? pos : { p: sel.a.p, o: sel.a.o + 1 });
      if (!collapsed) pos = this.deleteRange(paras, sel);
      const f: MFmt = { ...base, ...(this.pending ?? {}) };
      this.pending = null;
      const chunks = text.replace(/\r\n?/g, '\n').split('\n');
      chunks.forEach((chunk, idx) => {
        if (idx > 0) {
          const para = paras[pos.p];
          const { left, right } = splitNodes(para.nodes, pos.o);
          para.nodes = merge(left);
          paras.splice(pos.p + 1, 0, { p: copyPara(para.p), nodes: merge(right) });
          pos = { p: pos.p + 1, o: 0 };
        }
        if (chunk) {
          const para = paras[pos.p];
          const { left, right } = splitNodes(para.nodes, pos.o);
          para.nodes = merge([...left, { t: 'text', s: chunk, f: { ...f } }, ...right]);
          pos = { p: pos.p, o: pos.o + chunk.length };
        }
      });
      return { a: pos, b: pos };
    });
  }

  private rangeEach(paras: MParagraph[], sel: Sel, fn: (n: MNode) => void): void {
    for (let p = sel.a.p; p <= sel.b.p; p++) {
      const para = paras[p];
      const from = p === sel.a.p ? sel.a.o : 0;
      const to = p === sel.b.p ? sel.b.o : paraLen(para);
      const { left, right: rest } = splitNodes(para.nodes, from);
      const { left: mid, right } = splitNodes(rest, to - from);
      for (const n of mid) fn(n);
      para.nodes = merge([...left, ...mid, ...right]);
    }
  }

  private toggleFmt(k: 'b' | 'i' | 'u' | 'o' | 'k'): void {
    const sel = this.selection();
    if (!sel) return;
    if (cmpPos(sel.a, sel.b) === 0) {
      const paras = this.read();
      const cur = { ...this.fmtBefore(paras, sel.a), ...(this.pending ?? {}) };
      this.pending = { ...(this.pending ?? {}), [k]: !cur[k] };
      this.pendingAt = sel.a;
      this.syncBar();
      return;
    }
    const probe = this.read();
    let all = true;
    this.rangeEach(probe, sel, (n) => { if (!n.f[k]) all = false; });
    this.modify((paras, s) => { this.rangeEach(paras, s, (n) => { n.f[k] = !all; }); });
  }

  private patchFmt(patch: Partial<MFmt>): void {
    const sel = this.selection();
    if (!sel) return;
    if (cmpPos(sel.a, sel.b) === 0) {
      this.pending = { ...(this.pending ?? {}), ...patch };
      this.pendingAt = sel.a;
      this.syncBar();
      return;
    }
    this.modify((paras, s) => { this.rangeEach(paras, s, (n) => { Object.assign(n.f, patch); }); });
  }

  private paraEach(sel: Sel, paras: MParagraph[], fn: (p: MParagraph, i: number) => void): void {
    for (let i = sel.a.p; i <= sel.b.p; i++) fn(paras[i], i);
  }

  private act(id: string): void {
    if (id === 'find') { setHidden(this.findBox, !this.findBox.hidden); if (!this.findBox.hidden) this.findIn.focus(); return; }
    if (id.startsWith('sym:')) { this.insertText(id.slice(4)); return; }
    if (id === 'tab') { this.insertText('\t'); return; }
    if (id === 'stack') { this.stack(); return; }
    if (id === 'al' || id === 'ac' || id === 'ar' || id === 'aj') {
      const code = { al: 'l', ac: 'c', ar: 'r', aj: 'j' }[id];
      this.modify((paras, sel) => {
        const same = paras.slice(sel.a.p, sel.b.p + 1).every((p) => p.p.q === code);
        this.paraEach(sel, paras, (p) => { p.p.q = same ? '' : code; });
      });
      return;
    }
    if (id === 'bullet' || id === 'number') { this.list(id); }
  }

  private list(kind: 'bullet' | 'number'): void {
    const h = this.baseH;
    this.modify((paras, sel) => {
      const rows = paras.slice(sel.a.p, sel.b.p + 1);
      const isList = rows.every((p) => p.p.l === 3 * h && p.p.i === -3 * h);
      let n = 0;
      this.paraEach(sel, paras, (p) => {
        const first = p.nodes[0];
        const label = first && first.t === 'text' ? /^(•|\d+\.)\t/.exec(first.s) : null;
        if (label && first && first.t === 'text') first.s = first.s.slice(label[0].length);
        if (isList) {
          p.p = { ...p.p, l: 0, i: 0, t: [] };
        } else {
          n += 1;
          p.p = { ...p.p, l: 3 * h, i: -3 * h, t: [{ p: 3 * h, k: 'l' }] };
          p.nodes = merge([{ t: 'text', s: `${kind === 'bullet' ? '•' : `${n}.`}\t`, f: { ...DEFAULT_FMT } }, ...p.nodes]);
        }
      });
      return { a: { p: sel.a.p, o: 0 }, b: { p: sel.a.p, o: 0 } };
    });
  }

  private stack(): void {
    this.modify((paras, sel) => {
      if (cmpPos(sel.a, sel.b) === 0) {
        const para = paras[sel.a.p];
        const { left, right } = splitNodes(para.nodes, sel.a.o);
        const f = { ...this.fmtBefore(paras, sel.a), ...(this.pending ?? {}) };
        this.pending = null;
        para.nodes = merge([...left, { t: 'stack', top: '1', sep: '/', bot: '2', f }, ...right]);
        return { a: { p: sel.a.p, o: sel.a.o + 1 }, b: { p: sel.a.p, o: sel.a.o + 1 } };
      }
      if (sel.a.p === sel.b.p) {
        const para = paras[sel.a.p];
        const { left, right: rest } = splitNodes(para.nodes, sel.a.o);
        const { left: mid, right } = splitNodes(rest, sel.b.o - sel.a.o);
        if (mid.length === 1 && mid[0].t === 'stack') {
          const s = mid[0];
          para.nodes = merge([...left, { t: 'text', s: `${s.top}${s.sep}${s.bot}`, f: { ...s.f } }, ...right]);
          return { a: sel.a, b: { p: sel.a.p, o: sel.a.o + s.top.length + s.sep.length + s.bot.length } };
        }
        const plain = mid.map((n) => (n.t === 'text' ? n.s : '')).join('');
        const m = /^(.*?)([/#^])(.*)$/.exec(plain);
        const f = { ...(mid[0]?.f ?? DEFAULT_FMT) };
        const node: MNode = m ? { t: 'stack', top: m[1], sep: m[2], bot: m[3], f } : { t: 'stack', top: plain, sep: '^', bot: '', f };
        para.nodes = merge([...left, node, ...right]);
        return { a: { p: sel.a.p, o: sel.a.o + 1 }, b: { p: sel.a.p, o: sel.a.o + 1 } };
      }
      return sel;
    });
  }

  private textOf(p: MParagraph): string {
    return p.nodes.map((n) => (n.t === 'text' ? n.s : '\u0000')).join('');
  }

  private findNext(): void {
    const needle = this.findIn.value;
    if (!needle) return;
    const paras = this.read();
    const fold = (s: string): string => (this.caseBox.checked ? s : s.toLowerCase());
    const from = this.lastFind ?? this.selection()?.b ?? { p: 0, o: 0 };
    const hay = paras.map((p) => fold(this.textOf(p)));
    const n = fold(needle);
    for (let k = 0; k <= paras.length; k++) {
      const p = (from.p + k) % paras.length;
      const start = k === 0 ? from.o : 0;
      const idx = hay[p].indexOf(n, start);
      if (idx >= 0) {
        this.lastFind = { p, o: idx + n.length };
        this.edit.focus();
        this.setSelection({ a: { p, o: idx }, b: { p, o: idx + n.length } });
        return;
      }
    }
    this.lastFind = null;
    setText(this.hint, t('No match'));
  }

  private replaceOne(): void {
    const sel = this.selection();
    const needle = this.findIn.value;
    if (!sel || !needle || cmpPos(sel.a, sel.b) === 0 || sel.a.p !== sel.b.p) { this.findNext(); return; }
    const paras = this.read();
    const cur = this.textOf(paras[sel.a.p]).slice(sel.a.o, sel.b.o);
    const same = this.caseBox.checked ? cur === needle : cur.toLowerCase() === needle.toLowerCase();
    if (!same) { this.findNext(); return; }
    this.insertText(this.replIn.value);
    this.lastFind = null;
    this.findNext();
  }

  private replaceAll(): void {
    const needle = this.findIn.value;
    if (!needle) return;
    const repl = this.replIn.value;
    const paras = this.read();
    let count = 0;
    for (const para of paras) {
      para.nodes = merge(para.nodes.map((n) => {
        if (n.t !== 'text') return n;
        const re = new RegExp(needle.replace(/[.*+?^${}()|[\]\\]/g, '\\$&'), this.caseBox.checked ? 'g' : 'gi');
        return { ...n, s: n.s.replace(re, () => { count++; return repl; }) };
      }));
    }
    this.render(paras);
    setText(this.hint, `${count} ${t('replaced')}`);
  }

  private paraAtCaret(): MPara {
    const sel = this.selection();
    return sel ? this.read()[sel.a.p]?.p ?? DEFAULT_PARA : DEFAULT_PARA;
  }

  private syncBar(): void {
    const sel = this.selection();
    if (!sel) return;
    if (this.pending && this.pendingAt && cmpPos(this.pendingAt, sel.a) !== 0) this.pending = null;
    const paras = this.read();
    const collapsed = cmpPos(sel.a, sel.b) === 0;
    const probe: MFmt = { ...this.fmtBefore(paras, collapsed ? sel.a : { p: sel.a.p, o: sel.a.o + 1 }), ...(this.pending ?? {}) };
    for (const k of ['b', 'i', 'u', 'o', 'k'] as const) {
      const btn = this.buttons.get(k);
      if (!btn) continue;
      setClass(btn, 'is-on', probe[k]);
      if (btn.getAttribute('aria-pressed') !== String(probe[k])) btn.setAttribute('aria-pressed', String(probe[k]));
    }
    const para = paras[sel.a.p]?.p ?? DEFAULT_PARA;
    for (const [id, code] of [['al', 'l'], ['ac', 'c'], ['ar', 'r'], ['aj', 'j']] as const) {
      const b = this.buttons.get(id);
      if (b) setClass(b, 'is-on', para.q === code);
    }
    const colorKey = COLORS.some(([v]) => v === probe.c) ? probe.c : probe.c ? 'r' : '';
    if (this.colorSel.value !== colorKey) this.colorSel.value = colorKey;
    if (this.fontSel.value !== probe.f && Array.from(this.fontSel.options).some((o) => o.value === probe.f)) this.fontSel.value = probe.f;
    else if (!probe.f && this.fontSel.value !== '') this.fontSel.value = '';
    if (document.activeElement !== this.heightBox) setValue(this.heightBox, probe.h && !probe.h.endsWith('x') ? probe.h : String(this.baseH));
    this.syncRuler();
  }

  private unit(): number {
    return Number.parseFloat(getComputedStyle(this.edit).fontSize) || 16;
  }

  private syncRuler(): void {
    if (!this.isOpen) return;
    const p = this.paraAtCaret();
    const px = (v: number): number => (v / this.baseH) * this.unit();
    setStyleVar(this.markLeft, '--x', `${Math.round(px(p.l))}px`);
    setStyleVar(this.markFirst, '--x', `${Math.round(px(p.l + p.i))}px`);
    setStyleVar(this.ruler, '--u2-unit', `${Math.round(this.unit())}px`);
    while (this.tabMarks.length < p.t.length) {
      const m = el('<span class="u2-mt-tab" title="Tab stop"></span>');
      this.ruler.appendChild(m);
      this.tabMarks.push(m);
    }
    this.tabMarks.forEach((m, i) => {
      const tab = p.t[i];
      setHidden(m, !tab);
      if (tab) {
        setStyleVar(m, '--x', `${Math.round(px(tab.p))}px`);
        m.dataset.i = String(i);
        m.dataset.k = tab.k;
      }
    });
  }

  private wireRuler(): void {
    const snap = (px: number): number => {
      const step = this.unit() / 4;
      return Math.round(px / step) * (this.baseH / 4);
    };
    const apply = (fn: (p: MPara, v: number) => void, px: number): void => {
      const v = snap(px);
      this.modify((paras, sel) => { this.paraEach(sel, paras, (p) => fn(p.p, v)); });
    };
    const drag = (marker: HTMLElement, fn: (p: MPara, v: number) => void): void => {
      marker.addEventListener('pointerdown', (e) => {
        e.preventDefault();
        marker.setPointerCapture(e.pointerId);
        const rect = this.ruler.getBoundingClientRect();
        const move = (ev: PointerEvent): void => apply(fn, Math.max(0, ev.clientX - rect.left));
        const up = (): void => { marker.removeEventListener('pointermove', move); marker.removeEventListener('pointerup', up); };
        marker.addEventListener('pointermove', move);
        marker.addEventListener('pointerup', up);
      });
    };
    drag(this.markLeft, (p, v) => { const first = p.l + p.i; p.l = v; p.i = first - v; });
    drag(this.markFirst, (p, v) => { p.i = v - p.l; });
    this.ruler.addEventListener('pointerdown', (e) => {
      if ((e.target as HTMLElement).closest('.u2-mt-first, .u2-mt-left, .u2-mt-tab')) return;
      const rect = this.ruler.getBoundingClientRect();
      const v = snap(e.clientX - rect.left);
      this.modify((paras, sel) => { this.paraEach(sel, paras, (p) => { if (!p.p.t.some((x) => Math.abs(x.p - v) < 1e-9)) p.p.t = [...p.p.t, { p: v, k: 'l' }].sort((a, b) => a.p - b.p); }); });
    });
    this.ruler.addEventListener('contextmenu', (e) => {
      const m = (e.target as HTMLElement).closest<HTMLElement>('.u2-mt-tab');
      if (!m) return;
      e.preventDefault();
      const i = Number(m.dataset.i);
      this.modify((paras, sel) => { this.paraEach(sel, paras, (p) => { p.p.t = p.p.t.filter((_x, n) => n !== i); }); });
    });
  }
}
