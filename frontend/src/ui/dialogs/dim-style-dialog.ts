import { api } from '../../io/api';
import { Dialog, confirmAction } from '../dialogs';
import { docStore } from '../doc-store';
import { el, patchList, q, setClass, setDisabled, setHidden, setText } from '../dom';
import { t } from '../i18n';
import { ARROW_NAMES, blockOf, nameOfBlock } from './arrows';
import { exec, loadTables } from './engine';
import type { StyleTables } from './engine';
import { aciField, checkField, comboField, group, numField, selectField, setOptions, textField } from './fields';
import type { Field } from './fields';
import { ItemSvg } from './item-svg';

type Vars = Record<string, unknown>;
type Opt = ReadonlyArray<readonly [string, string]>;

const LUNIT: Opt = [['1', 'Scientific'], ['2', 'Decimal'], ['3', 'Engineering'], ['4', 'Architectural'], ['5', 'Fractional'], ['6', 'Windows desktop']];
const AUNIT: Opt = [['0', 'Decimal degrees'], ['1', 'Degrees minutes seconds'], ['2', 'Gradians'], ['3', 'Radians']];
const FRAC: Opt = [['0', 'Horizontal'], ['1', 'Diagonal'], ['2', 'Not stacked']];
const FEET: Opt = [['0', 'Suppress zero feet and inches'], ['1', 'Show zero feet and inches'], ['2', 'Show zero feet only'], ['3', 'Show zero inches only']];
const LW: Opt = [['-2', 'ByBlock'], ['-1', 'ByLayer'], ['-3', 'Default'], ['0', '0.00 mm'], ['5', '0.05 mm'], ['9', '0.09 mm'], ['13', '0.13 mm'], ['15', '0.15 mm'], ['18', '0.18 mm'],
  ['20', '0.20 mm'], ['25', '0.25 mm'], ['30', '0.30 mm'], ['35', '0.35 mm'], ['40', '0.40 mm'], ['50', '0.50 mm'], ['53', '0.53 mm'], ['60', '0.60 mm'], ['70', '0.70 mm'],
  ['80', '0.80 mm'], ['90', '0.90 mm'], ['100', '1.00 mm'], ['106', '1.06 mm'], ['120', '1.20 mm'], ['140', '1.40 mm'], ['158', '1.58 mm'], ['200', '2.00 mm'], ['211', '2.11 mm']];

interface Row { field: Field; key: string; enabled?: (v: Vars) => boolean; read?: (v: Vars) => string | number | boolean; write?: (f: Field, v: Vars) => Vars }

const str = (v: unknown): string => (v === undefined || v === null ? '' : String(v));
const num = (v: unknown): number => (typeof v === 'number' ? v : Number(v) || 0);

export class DimStyleDialog extends Dialog {
  private readonly rows: Row[] = [];
  private readonly list: HTMLElement;
  private readonly head: HTMLElement;
  private readonly nameBox: HTMLInputElement;
  private readonly btnCur: HTMLButtonElement;
  private readonly btnNew: HTMLButtonElement;
  private readonly btnRen: HTMLButtonElement;
  private readonly btnDel: HTMLButtonElement;
  private readonly btnApply: HTMLButtonElement;
  private readonly annotative = checkField('Annotative');
  private readonly description = textField('Description');
  private readonly overall = numField('Overall scale', { min: 0 });
  private readonly textStyle = selectField('Text style', [['Standard', 'Standard']]);
  private readonly ltypes: Field[] = [];
  private readonly compareSel = selectField('Compare with', [['Standard', 'Standard']]);
  private readonly compareOut = el<HTMLElement>('<pre class="u2-compare" hidden></pre>');
  private readonly tabs: HTMLElement[] = [];
  private readonly tabBtns: HTMLButtonElement[] = [];
  private readonly kindBtns: HTMLButtonElement[] = [];
  private readonly svg = new ItemSvg();
  private readonly previewNote: HTMLElement;
  private tables: StyleTables | null = null;
  private work: Vars = {};
  private base: Vars = {};
  private selected = '';
  private current = '';
  private dirty = false;
  private kind = 'linear';
  private frame = 0;
  private serial = 0;
  private openedFor = '';
  private method = 'none';

  constructor() {
    super('Dimension Style Manager', 980);
    this.scrim.classList.add('cv-scrim-through');
    this.body.appendChild(el(
      '<div class="u2-dim">' +
      '<div class="u2-dim-left"><div class="u2-sm-cur"></div><div class="cv-list u2-sm-list" role="listbox"></div>' +
      '<div class="u2-sm-new"><input class="cv-input" type="text" spellcheck="false" autocomplete="off"></div>' +
      '<div class="u2-sm-btns"></div><div class="u2-dim-meta"></div></div>' +
      '<div class="u2-dim-mid"><div class="u2-tabbar" role="tablist"></div><div class="u2-tabs"></div></div>' +
      '<div class="u2-dim-right"><div class="u2-kinds"></div><div class="u2-preview"></div><p class="cv-note u2-preview-note"></p></div>' +
      '</div>'));
    this.head = q(this.body, '.u2-sm-cur');
    this.list = q(this.body, '.u2-sm-list');
    this.nameBox = q<HTMLInputElement>(this.body, '.u2-sm-new input');
    this.nameBox.placeholder = t('New style name');
    const btns = q(this.body, '.u2-sm-btns');
    const mk = (label: string, run: () => void): HTMLButtonElement => {
      const b = el<HTMLButtonElement>('<button class="cv-btn" type="button"></button>');
      setText(b, t(label));
      b.addEventListener('click', run);
      btns.appendChild(b);
      return b;
    };
    this.btnCur = mk('Set Current', () => void this.setCurrent());
    this.btnNew = mk('New', () => void this.create());
    this.btnRen = mk('Rename', () => void this.rename());
    this.btnDel = mk('Delete', () => void this.remove());
    const meta = q(this.body, '.u2-dim-meta');
    meta.append(this.annotative.el, this.description.el, this.compareSel.el, this.compareOut);
    this.annotative.change = () => this.touch();
    this.description.change = () => this.touch();
    this.compareSel.change = () => void this.compare();
    this.nameBox.addEventListener('input', () => this.gate());
    this.nameBox.addEventListener('keydown', (e) => { if (e.key === 'Enter' && !this.btnNew.disabled) { e.preventDefault(); void this.create(); } });
    q(this.body, '.u2-preview').appendChild(this.svg.svg);
    this.previewNote = q(this.body, '.u2-preview-note');
    this.buildKinds();
    this.buildTabs();
    this.button('Close', 'ghost', () => this.close());
    this.btnApply = this.button('Apply', 'ghost', () => void this.apply());
    this.button('OK', 'primary', () => { void this.apply().then((ok) => { if (ok) this.close(); }); });
    docStore.onChange(() => { if (this.isOpen && docStore.activeId !== this.openedFor) this.close(); });
  }

  private buildKinds(): void {
    const host = q(this.body, '.u2-kinds');
    for (const [k, label] of [['linear', 'Linear'], ['radius', 'Radius'], ['diameter', 'Diameter'], ['angular', 'Angular']] as const) {
      const b = el<HTMLButtonElement>('<button class="cv-btn u2-kind" type="button"></button>');
      setText(b, t(label));
      b.dataset.kind = k;
      b.addEventListener('click', () => { this.kind = k; this.syncKinds(); this.schedule(); });
      host.appendChild(b);
      this.kindBtns.push(b);
    }
    this.syncKinds();
  }

  private syncKinds(): void {
    for (const b of this.kindBtns) setClass(b, 'is-on', b.dataset.kind === this.kind);
  }

  private add(host: HTMLElement, key: string, field: Field, extra: Partial<Row> = {}): Field {
    const row: Row = { field, key, ...extra };
    this.rows.push(row);
    field.live = true;
    field.change = () => {
      const patch = row.write ? row.write(field, this.work) : { [key]: field.get() };
      Object.assign(this.work, patch);
      this.touch();
      this.sync();
    };
    host.appendChild(field.el);
    return field;
  }

  private custom(host: HTMLElement, field: Field, key: string, read: (v: Vars) => string | number | boolean, write: (f: Field, v: Vars) => Vars, enabled?: (v: Vars) => boolean): Field {
    return this.add(host, key, field, { read, write, enabled });
  }

  private pane(name: string): HTMLElement {
    const idx = this.tabs.length;
    const btn = el<HTMLButtonElement>('<button class="u2-tab" type="button" role="tab"></button>');
    setText(btn, t(name));
    btn.addEventListener('click', () => this.showTab(idx));
    q(this.body, '.u2-tabbar').appendChild(btn);
    this.tabBtns.push(btn);
    const pane = el('<div class="u2-pane" role="tabpanel" hidden></div>');
    q(this.body, '.u2-tabs').appendChild(pane);
    this.tabs.push(pane);
    return pane;
  }

  private showTab(i: number): void {
    this.tabs.forEach((p, n) => { setHidden(p, n !== i); setClass(this.tabBtns[n], 'is-on', n === i); this.tabBtns[n].setAttribute('aria-selected', String(n === i)); });
  }

  private zero(host: HTMLElement, key: string, _label: string, feet: boolean, enabled?: (v: Vars) => boolean): void {
    const lead = checkField('Leading');
    const trail = checkField('Trailing');
    const bit = (f: Field, mask: number) => (v: Vars): Vars => ({ [key]: (num(v[key]) & ~mask) | (f.get() ? mask : 0) });
    const lm = feet ? 4 : 1, tm = feet ? 8 : 2;
    this.custom(host, lead, key, (v) => (num(v[key]) & lm) !== 0, (f, v) => bit(f, lm)(v), enabled);
    this.custom(host, trail, key, (v) => (num(v[key]) & tm) !== 0, (f, v) => bit(f, tm)(v), enabled);
    if (feet) {
      const ft = selectField('Feet and inches', FEET);
      this.custom(host, ft, key, (v) => String(num(v[key]) & 3), (f, v) => ({ [key]: (num(v[key]) & ~3) | Number(f.get()) }), enabled);
    }
  }

  private buildTabs(): void {
    const lines = this.pane('Lines');
    const dl = el('<div class="u2-cols"></div>');
    const ex = el('<div class="u2-cols"></div>');
    const dim = (host: HTMLElement, key: string, f: Field, extra: Partial<Row> = {}): Field => this.add(host, key, f, extra);
    const lt = (label: string): Field => { const f = selectField(label, [['', 'ByBlock'], ['ByLayer', 'ByLayer'], ['Continuous', 'Continuous']]); this.ltypes.push(f); return f; };
    dim(dl, 'DIMCLRD', aciField('Color'));
    dim(dl, 'DIMLWD', selectField('Lineweight', LW), { read: (v) => String(num(v.DIMLWD)), write: (f) => ({ DIMLWD: Number(f.get()) }) });
    dim(dl, 'DIMLTYPE', lt('Linetype'));
    dim(dl, 'DIMDLE', numField('Extend beyond ticks'));
    dim(dl, 'DIMDLI', numField('Baseline spacing', { min: 0 }));
    dim(dl, 'DIMSD1', checkField('Suppress dimension line 1'), { read: (v) => !!num(v.DIMSD1), write: (f) => ({ DIMSD1: f.get() ? 1 : 0 }) });
    dim(dl, 'DIMSD2', checkField('Suppress dimension line 2'), { read: (v) => !!num(v.DIMSD2), write: (f) => ({ DIMSD2: f.get() ? 1 : 0 }) });
    dim(ex, 'DIMCLRE', aciField('Color'));
    dim(ex, 'DIMLWE', selectField('Lineweight', LW), { read: (v) => String(num(v.DIMLWE)), write: (f) => ({ DIMLWE: Number(f.get()) }) });
    dim(ex, 'DIMLTEX1', lt('Linetype ext 1'));
    dim(ex, 'DIMLTEX2', lt('Linetype ext 2'));
    dim(ex, 'DIMEXE', numField('Extend beyond dimension line', { min: 0 }));
    dim(ex, 'DIMEXO', numField('Offset from origin', { min: 0 }));
    dim(ex, 'DIMSE1', checkField('Suppress extension line 1'), { read: (v) => !!num(v.DIMSE1), write: (f) => ({ DIMSE1: f.get() ? 1 : 0 }) });
    dim(ex, 'DIMSE2', checkField('Suppress extension line 2'), { read: (v) => !!num(v.DIMSE2), write: (f) => ({ DIMSE2: f.get() ? 1 : 0 }) });
    dim(ex, 'DIMFXLON', checkField('Fixed length extension lines'), { read: (v) => !!num(v.DIMFXLON), write: (f) => ({ DIMFXLON: f.get() ? 1 : 0 }) });
    dim(ex, 'DIMFXL', numField('Length', { min: 0 }), { enabled: (v) => !!num(v.DIMFXLON) });
    lines.append(group('Dimension lines', dl), group('Extension lines', ex));

    const sym = this.pane('Symbols and Arrows');
    const ar = el('<div class="u2-cols"></div>');
    const first = selectField('First arrowhead', ARROW_NAMES);
    const second = selectField('Second arrowhead', ARROW_NAMES);
    const leader = selectField('Leader arrowhead', ARROW_NAMES);
    this.custom(ar, first, 'DIMBLK1', (v) => nameOfBlock(str(v.DIMBLK1) || str(v.DIMBLK)), (f, v) => ({ DIMBLK1: blockOf(str(f.get())), DIMBLK: blockOf(str(f.get())), DIMBLK2: str(v.DIMBLK2) || str(v.DIMBLK) || blockOf('closed filled') }));
    this.custom(ar, second, 'DIMBLK2', (v) => nameOfBlock(str(v.DIMBLK2) || str(v.DIMBLK)), (f, v) => ({ DIMBLK2: blockOf(str(f.get())), DIMBLK1: str(v.DIMBLK1) || str(v.DIMBLK) || blockOf('closed filled') }));
    this.custom(ar, leader, 'DIMLDRBLK', (v) => nameOfBlock(str(v.DIMLDRBLK)), (f) => ({ DIMLDRBLK: blockOf(str(f.get())) }));
    dim(ar, 'DIMASZ', numField('Arrow size', { min: 0 }));
    dim(ar, 'DIMTSZ', numField('Tick size', { min: 0 }));
    const ce = el('<div class="u2-cols"></div>');
    dim(ce, 'DIMCEN', numField('Center mark size'));
    ce.appendChild(el('<p class="cv-note">A negative size draws center lines.</p>'));
    const arc = el('<div class="u2-cols"></div>');
    dim(arc, 'DIMARCSYM', selectField('Arc length symbol', [['0', 'Before dimension text'], ['1', 'Above dimension text'], ['2', 'None']]), { read: (v) => String(num(v.DIMARCSYM)), write: (f) => ({ DIMARCSYM: Number(f.get()) }) });
    dim(arc, 'DIMJOGANG', numField('Radius jog angle', { min: 5, max: 90 }));
    sym.append(group('Arrowheads', ar), group('Center marks', ce), group('Arc length and radius jog', arc));

    const text = this.pane('Text');
    const tx = el('<div class="u2-cols"></div>');
    this.add(tx, 'DIMTXSTY', this.textStyle);
    dim(tx, 'DIMCLRT', aciField('Text color'));
    dim(tx, 'DIMTFILL', selectField('Fill', [['0', 'None'], ['1', 'Background'], ['2', 'Color']]), { read: (v) => String(num(v.DIMTFILL)), write: (f) => ({ DIMTFILL: Number(f.get()) }) });
    dim(tx, 'DIMTFILLCLR', aciField('Fill color'), { enabled: (v) => num(v.DIMTFILL) === 2 });
    dim(tx, 'DIMTXT', numField('Text height', { min: 0 }));
    dim(tx, 'DIMTFAC', numField('Fraction height scale', { min: 0 }));
    const frame = checkField('Draw frame around text');
    this.custom(tx, frame, 'DIMGAP', (v) => num(v.DIMGAP) < 0, (f, v) => ({ DIMGAP: (f.get() ? -1 : 1) * Math.abs(num(v.DIMGAP)) }));
    const pl = el('<div class="u2-cols"></div>');
    dim(pl, 'DIMTAD', selectField('Vertical', [['0', 'Centered'], ['1', 'Above'], ['2', 'Outside'], ['3', 'JIS'], ['4', 'Below']]), { read: (v) => String(num(v.DIMTAD)), write: (f) => ({ DIMTAD: Number(f.get()) }) });
    dim(pl, 'DIMJUST', selectField('Horizontal', [['0', 'Centered'], ['1', 'At ext line 1'], ['2', 'At ext line 2'], ['3', 'Over ext line 1'], ['4', 'Over ext line 2']]), { read: (v) => String(num(v.DIMJUST)), write: (f) => ({ DIMJUST: Number(f.get()) }) });
    dim(pl, 'DIMTVP', numField('Vertical position offset'));
    this.custom(pl, numField('Offset from dimension line'), 'DIMGAP', (v) => Math.abs(num(v.DIMGAP)), (f, v) => ({ DIMGAP: (num(v.DIMGAP) < 0 ? -1 : 1) * Math.abs(Number(f.get())) }));
    const al = el('<div class="u2-cols"></div>');
    const dir = selectField('Text alignment', [['h', 'Horizontal'], ['a', 'Aligned with dimension line'], ['i', 'ISO standard']]);
    this.custom(al, dir, 'DIMTIH', (v) => (num(v.DIMTIH) && num(v.DIMTOH) ? 'h' : !num(v.DIMTIH) && !num(v.DIMTOH) ? 'a' : 'i'), (f) => {
      const k = String(f.get());
      return { DIMTIH: k === 'h' ? 1 : 0, DIMTOH: k === 'a' ? 0 : k === 'h' ? 1 : 1 };
    });
    text.append(group('Text appearance', tx), group('Text placement', pl), group('Text alignment', al));

    const fit = this.pane('Fit');
    const fo = el('<div class="u2-cols"></div>');
    dim(fo, 'DIMATFIT', selectField('Fit options', [['3', 'Either text or arrows (best fit)'], ['1', 'Move arrows first'], ['2', 'Move text first'], ['0', 'Move both text and arrows']]), { read: (v) => String(num(v.DIMATFIT)), write: (f) => ({ DIMATFIT: Number(f.get()) }) });
    dim(fo, 'DIMTIX', checkField('Always keep text between extension lines'), { read: (v) => !!num(v.DIMTIX), write: (f) => ({ DIMTIX: f.get() ? 1 : 0 }) });
    dim(fo, 'DIMSOXD', checkField('Suppress arrows if they do not fit'), { read: (v) => !!num(v.DIMSOXD), write: (f) => ({ DIMSOXD: f.get() ? 1 : 0 }) });
    dim(fo, 'DIMTOFL', checkField('Draw dimension line between extension lines'), { read: (v) => !!num(v.DIMTOFL), write: (f) => ({ DIMTOFL: f.get() ? 1 : 0 }) });
    const tp = el('<div class="u2-cols"></div>');
    dim(tp, 'DIMTMOVE', selectField('Text placement', [['0', 'Beside the dimension line'], ['1', 'Over the dimension line, with leader'], ['2', 'Over the dimension line, no leader']]), { read: (v) => String(num(v.DIMTMOVE)), write: (f) => ({ DIMTMOVE: Number(f.get()) }) });
    const sc = el('<div class="u2-cols"></div>');
    this.add(sc, 'DIMSCALE', this.overall);
    sc.appendChild(el('<p class="cv-note">A scale of 0 follows the annotation scale of the drawing.</p>'));
    fit.append(group('Fit options', fo), group('Text placement', tp), group('Scale for dimension features', sc));

    const prim = this.pane('Primary Units');
    const pu = el('<div class="u2-cols"></div>');
    dim(pu, 'DIMLUNIT', selectField('Unit format', LUNIT), { read: (v) => String(num(v.DIMLUNIT)), write: (f) => ({ DIMLUNIT: Number(f.get()) }) });
    dim(pu, 'DIMDEC', numField('Precision', { min: 0, max: 8, int: true }));
    dim(pu, 'DIMFRAC', selectField('Fraction format', FRAC), { read: (v) => String(num(v.DIMFRAC)), write: (f) => ({ DIMFRAC: Number(f.get()) }), enabled: (v) => num(v.DIMLUNIT) >= 4 && num(v.DIMLUNIT) <= 5 });
    dim(pu, 'DIMDSEP', textField('Decimal separator'), { read: (v) => str(v.DIMDSEP), write: (f) => ({ DIMDSEP: str(f.get()).slice(0, 1) || '.' }) });
    dim(pu, 'DIMRND', numField('Round off', { min: 0 }));
    dim(pu, 'DIMPOST', textField('Prefix and suffix', 'Use <> for the value'));
    dim(pu, 'DIMLFAC', numField('Measurement scale factor'));
    const pz = el('<div class="u2-cols"></div>');
    this.zero(pz, 'DIMZIN', 'Zero suppression', true);
    const au = el('<div class="u2-cols"></div>');
    dim(au, 'DIMAUNIT', selectField('Units format', AUNIT), { read: (v) => String(num(v.DIMAUNIT)), write: (f) => ({ DIMAUNIT: Number(f.get()) }) });
    dim(au, 'DIMADEC', numField('Precision', { min: 0, max: 8, int: true }));
    this.zero(au, 'DIMAZIN', 'Zero suppression', false);
    prim.append(group('Linear dimensions', pu), group('Zero suppression', pz), group('Angular dimensions', au));

    const alt = this.pane('Alternate Units');
    const on = (v: Vars): boolean => !!num(v.DIMALT);
    const ac = el('<div class="u2-cols"></div>');
    dim(ac, 'DIMALT', checkField('Display alternate units'), { read: (v) => !!num(v.DIMALT), write: (f) => ({ DIMALT: f.get() ? 1 : 0 }) });
    dim(ac, 'DIMALTU', selectField('Unit format', LUNIT), { read: (v) => String(num(v.DIMALTU)), write: (f) => ({ DIMALTU: Number(f.get()) }), enabled: on });
    dim(ac, 'DIMALTD', numField('Precision', { min: 0, max: 8, int: true }), { enabled: on });
    dim(ac, 'DIMALTF', numField('Multiplier for alternate units', { min: 0 }), { enabled: on });
    dim(ac, 'DIMALTRND', numField('Round distances to', { min: 0 }), { enabled: on });
    dim(ac, 'DIMAPOST', textField('Prefix and suffix'), { enabled: on });
    const az = el('<div class="u2-cols"></div>');
    this.zero(az, 'DIMALTZ', 'Zero suppression', true, on);
    alt.append(group('Alternate units', ac), group('Zero suppression', az));

    const tol = this.pane('Tolerances');
    const tm = el('<div class="u2-cols"></div>');
    const method = selectField('Method', [['none', 'None'], ['sym', 'Symmetrical'], ['dev', 'Deviation'], ['lim', 'Limits']]);
    this.custom(tm, method, 'DIMTOL', () => this.method, (f, v) => {
      const m = String(f.get());
      this.method = m;
      const out: Vars = { DIMTOL: m === 'sym' || m === 'dev' ? 1 : 0, DIMLIM: m === 'lim' ? 1 : 0 };
      if (m === 'sym') out.DIMTM = num(v.DIMTP);
      return out;
    });
    const on2 = (): boolean => this.method !== 'none';
    const tv = (key: string, f: Field, extra: Partial<Row> = {}): Field => this.add(tm, key, f, { enabled: () => on2(), ...extra });
    tv('DIMTP', numField('Upper value'), { write: (f) => ({ DIMTP: Number(f.get()), ...(this.method === 'sym' ? { DIMTM: Number(f.get()) } : {}) }) });
    tv('DIMTM', numField('Lower value'), { enabled: () => this.method === 'dev' || this.method === 'lim' });
    tv('DIMTDEC', numField('Precision', { min: 0, max: 8, int: true }));
    tv('DIMTFAC', numField('Scaling for height', { min: 0 }));
    tv('DIMTOLJ', selectField('Vertical position', [['0', 'Bottom'], ['1', 'Middle'], ['2', 'Top']]), { read: (v) => String(num(v.DIMTOLJ)), write: (f) => ({ DIMTOLJ: Number(f.get()) }) });
    const tzh = el('<div class="u2-cols"></div>');
    this.zero(tzh, 'DIMTZIN', 'Zero suppression', true, () => on2());
    tol.append(group('Tolerance format', tm), group('Zero suppression', tzh));
    this.showTab(0);
  }

  private touch(): void {
    this.dirty = true;
    setDisabled(this.btnApply, false);
    this.schedule();
  }

  private sync(): void {
    for (const r of this.rows) {
      const v = r.read ? r.read(this.work) : (this.work[r.key] as string | number | boolean);
      r.field.set(v ?? '');
      if (r.enabled) r.field.enable(r.enabled(this.work));
    }
  }

  private methodOf(v: Vars): string {
    if (num(v.DIMLIM)) return 'lim';
    if (num(v.DIMTOL)) return num(v.DIMTP) === num(v.DIMTM) ? 'sym' : 'dev';
    return 'none';
  }

  private records(): Array<{ name: string; vars: Vars; annotative?: boolean; description?: string }> {
    return this.tables?.dimstyles ?? [];
  }

  private select(name: string): void {
    const rec = this.records().find((r) => r.name === name);
    if (!rec) return;
    this.selected = name;
    this.base = { ...rec.vars };
    this.work = { ...rec.vars };
    this.dirty = false;
    this.method = this.methodOf(this.work);
    this.annotative.set(!!rec.annotative);
    this.description.set(String(rec.description ?? ''));
    this.compareOut.hidden = true;
    setDisabled(this.btnApply, true);
    this.paintList();
    this.sync();
    this.schedule();
  }

  private paintList(): void {
    setText(this.head, `${t('Current style')}: ${this.current}`);
    const update = (node: HTMLElement, r: { name: string }): void => {
      const spans = node.querySelectorAll('span');
      setText(spans[1], r.name);
      setText(spans[2], r.name === this.current ? t('current') : '');
      setClass(node, 'is-selected', r.name === this.selected);
      setClass(node, 'is-current', r.name === this.current);
    };
    patchList(this.list, this.records(), {
      key: (r) => r.name,
      create: (r) => {
        const row = el<HTMLButtonElement>('<button class="cv-list-row u2-sm-row" type="button" role="option"><span></span><span class="cv-list-name"></span><span class="cv-list-meta"></span></button>');
        row.addEventListener('click', () => void this.choose(r.name));
        update(row, r);
        return row;
      },
      update,
    });
    setOptions(this.compareSel, this.records().map((r) => [r.name, r.name] as const));
    const names = (this.tables?.textstyles ?? []).map((s) => String(s.name));
    setOptions(this.textStyle, names.map((n) => [n, n] as const));
    const lts = ['', 'ByLayer', 'Continuous', ...(this.tables?.linetypes ?? []).map((l) => l.name).filter((n) => !['ByBlock', 'ByLayer', 'Continuous'].includes(n))];
    for (const f of this.ltypes) setOptions(f, lts.map((n) => [n, n === '' ? 'ByBlock' : n] as const));
    this.gate();
  }

  private gate(): void {
    const typed = this.nameBox.value.trim();
    const dup = this.records().some((r) => r.name.toLowerCase() === typed.toLowerCase());
    setDisabled(this.btnCur, !this.selected || this.selected === this.current);
    setDisabled(this.btnNew, !typed || dup);
    setDisabled(this.btnRen, !typed || dup || !this.selected || this.selected.toLowerCase() === 'standard');
    setDisabled(this.btnDel, !this.selected || this.selected.toLowerCase() === 'standard' || this.selected === this.current);
  }

  private async choose(name: string): Promise<void> {
    if (name === this.selected) return;
    if (this.dirty && !(await confirmAction('Dimension Style Manager', 'Discard the changes made to this style?', 'Discard', true))) return;
    this.select(name);
  }

  private async load(pick?: string): Promise<void> {
    const tables = await loadTables();
    if (!tables) return;
    this.tables = tables;
    this.current = String(tables.header.DIMSTYLE ?? 'Standard');
    const want = pick ?? (this.records().some((r) => r.name === this.selected) ? this.selected : this.current);
    this.selected = '';
    this.select(this.records().some((r) => r.name === want) ? want : this.records()[0]?.name ?? '');
  }

  async show(): Promise<void> {
    if (!docStore.activeId) return;
    this.openedFor = docStore.activeId;
    await this.load();
    this.open(this.nameBox);
  }

  private changed(): Vars {
    const out: Vars = {};
    for (const [k, v] of Object.entries(this.work)) if (JSON.stringify(v) !== JSON.stringify(this.base[k])) out[k] = v;
    return out;
  }

  private async apply(): Promise<boolean> {
    if (!this.selected) return true;
    const rec = this.records().find((r) => r.name === this.selected);
    const vars = this.changed();
    const meta = !!rec && (!!rec.annotative !== !!this.annotative.get() || str(rec.description) !== str(this.description.get()));
    if (!Object.keys(vars).length && !meta) return true;
    const out = await exec('dimstyle', { action: 'modify', name: this.selected, vars, annotative: !!this.annotative.get(), description: str(this.description.get()) });
    if (!out) return false;
    await this.load(this.selected);
    return true;
  }

  private async setCurrent(): Promise<void> {
    if (await this.apply() && await exec('dimstyle', { action: 'restore', name: this.selected })) await this.load(this.selected);
  }

  private async create(): Promise<void> {
    const name = this.nameBox.value.trim();
    if (!name) return;
    const out = await exec('dimstyle', { action: 'create', name, from: this.selected || undefined, vars: this.changed(), annotative: !!this.annotative.get(), description: str(this.description.get()) });
    if (!out) return;
    this.nameBox.value = '';
    this.dirty = false;
    await this.load(name);
  }

  private async rename(): Promise<void> {
    const to = this.nameBox.value.trim();
    if (!to || !this.selected) return;
    if (!(await exec('dimstyle', { action: 'rename', name: this.selected, new: to }))) return;
    this.nameBox.value = '';
    await this.load(to);
  }

  private async remove(): Promise<void> {
    if (!this.selected || !(await confirmAction('Delete Dimension Style', `Delete the style ${this.selected}?`, 'Delete', true))) return;
    if (!(await exec('dimstyle', { action: 'delete', name: this.selected }))) return;
    this.dirty = false;
    await this.load(this.current);
  }

  private async compare(): Promise<void> {
    const other = String(this.compareSel.get());
    if (!other || other === this.selected) { this.compareOut.hidden = true; return; }
    const out = await exec('dimstyle', { action: 'compare', a: this.selected, b: other }, true);
    const diff = (out?.result?.differences ?? {}) as Record<string, unknown[]>;
    const lines = Object.entries(diff).map(([k, v]) => `${k}: ${str(v[0])} | ${str(v[1])}`);
    setText(this.compareOut, lines.length ? lines.join('\n') : t('No differences.'));
    this.compareOut.hidden = false;
  }

  private schedule(): void {
    if (this.frame) return;
    this.frame = requestAnimationFrame(() => { this.frame = 0; void this.preview(); });
  }

  private async preview(): Promise<void> {
    const id = docStore.activeId;
    if (!id || !this.isOpen || !this.selected) return;
    const mine = ++this.serial;
    try {
      const res = await api.dimPreview(id, this.work, this.kind, this.selected);
      if (mine !== this.serial) return;
      this.svg.paint(res.items);
      setText(this.previewNote, '');
    } catch (e) {
      if (mine === this.serial) setText(this.previewNote, e instanceof Error ? e.message : '');
    }
  }
}
