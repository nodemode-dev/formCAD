import { part } from '../part/api';
import { messageOf, partStore } from '../part/store';
import { Dialog } from '../ui/dialogs';
import { docStore } from '../ui/doc-store';
import { el, patchList, q, setClass, setDisabled, setText } from '../ui/dom';
import { t } from '../ui/i18n';
import { toast } from '../ui/toast';
import { view3d } from '../view3d/mount';
import { sheet, type BendRecord, type TableRow } from './api';
import { sheetStore } from './store';
import { checkRow, choiceRow, fmt, heading, readoutRow, valueRow } from './ui';

const METHODS: Array<[string, string]> = [['kfactor', 'K-factor'], ['allowance', 'Bend allowance'], ['deduction', 'Bend deduction'], ['table', 'Bend table']];
const RELIEFS: Array<[string, string]> = [['rect', 'Rectangular'], ['obround', 'Obround'], ['tear', 'Tear'], ['none', 'None']];
const OUTSIDE: Array<[string, string]> = [['clamp_warn', 'Hold the nearest value and warn'], ['backup_k', 'Use the backup K-factor']];

interface Numbers { rn: number; ba: number; bd: number; ossb: number; issb: number; k: number }

export function bendNumbers(method: string, r: number, thick: number, k: number, ba90: number, bd90: number): Numbers | null {
  if (!(thick > 0) || !(r > 0)) return null;
  const theta = Math.PI / 2;
  const ossb = Math.tan(theta / 2) * (r + thick);
  const issb = Math.tan(theta / 2) * r;
  let kk = k;
  if (method === 'allowance') kk = (ba90 / theta - r) / thick;
  else if (method === 'deduction') kk = ((2 * ossb - bd90) / theta - r) / thick;
  else if (method !== 'kfactor') return null;
  const ba = theta * (r + kk * thick);
  return { rn: r + kk * thick, ba, bd: 2 * ossb - ba, ossb, issb, k: kk };
}

export class RuleDialog extends Dialog {
  private readonly thickness = valueRow('Thickness', 'mm', () => this.recalc());
  private readonly radius = valueRow('Inside radius', 'mm', () => this.recalc());
  private readonly method = choiceRow('Bend method', METHODS, () => this.recalc());
  private readonly k = valueRow('K-factor', '', () => this.recalc());
  private readonly ba = valueRow('Allowance at 90 degrees', 'mm', () => this.recalc());
  private readonly bd = valueRow('Deduction at 90 degrees', 'mm', () => this.recalc());
  private readonly table = choiceRow('Bend table', [['', 'None']], () => this.recalc());
  private readonly outside = choiceRow('Outside the table', OUTSIDE, () => this.recalc());
  private readonly backup = valueRow('Backup K-factor', '', () => this.recalc());
  private readonly relief = choiceRow('Relief type', RELIEFS, () => this.recalc());
  private readonly ratio = valueRow('Relief width', 'x thickness', () => this.recalc());
  private readonly extra = valueRow('Relief depth past bend', 'mm', () => this.recalc());
  private readonly auto = checkRow('Relieve automatically', () => this.recalc());
  private readonly rn = readoutRow('Neutral radius', 'mm');
  private readonly kOut = readoutRow('K-factor in use', '');
  private readonly baOut = readoutRow('Bend allowance, 90 degrees', 'mm');
  private readonly bdOut = readoutRow('Bend deduction, 90 degrees', 'mm');
  private readonly setback = readoutRow('Outside setback, 90 degrees', 'mm');
  private readonly list: HTMLElement;
  private readonly msg: HTMLElement;
  private readonly apply: HTMLButtonElement;
  private root: string | null = null;
  private tableIds: TableRow[] = [];
  private off: (() => void) | null = null;

  constructor() {
    super('Sheet Metal Rule', 900);
    const form = el('<div class="sm-cols"></div>');
    const left = el('<div class="sm-form"></div>');
    const right = el('<div class="sm-form"></div>');
    left.append(
      heading('Sheet'), this.thickness.root, this.radius.root,
      heading('Bend allowance'), this.method.root, this.k.root, this.ba.root, this.bd.root, this.table.root, this.outside.root, this.backup.root,
      heading('Relief'), this.relief.root, this.ratio.root, this.extra.root, this.auto.root,
    );
    right.append(heading('Computed'), this.rn.root, this.kOut.root, this.baOut.root, this.bdOut.root, this.setback.root, heading('Bends of this part'));
    this.list = el('<div class="sm-list" role="list"></div>');
    this.msg = el('<p class="sm-msg" role="alert"></p>');
    right.append(this.list, this.msg);
    form.append(left, right);
    this.body.appendChild(form);
    this.button('Close', 'ghost', () => this.close());
    this.apply = this.button('Apply', 'primary', () => { void this.save(); });
  }

  async showFor(): Promise<void> {
    const id = docStore.activeId;
    const root = sheetStore.rootFeature();
    if (!id || !root) { toast(t('Add a base flange or convert a solid to sheet metal first.'), 'error'); return; }
    this.root = root.id;
    try {
      const raw = await sheet.tables(id);
      this.tableIds = Array.isArray(raw) ? raw : raw.tables;
    } catch {
      this.tableIds = [];
    }
    this.fillTables();
    const p = root.params;
    this.thickness.set(p.thickness as number | string | null);
    this.radius.set(p.radius as number | string | null);
    this.method.set(String(p.bend_method ?? 'kfactor'));
    this.k.set((p.k_factor as number | null) ?? 0.44);
    this.ba.set((p.ba as number | null) ?? 0);
    this.bd.set((p.bd as number | null) ?? 0);
    this.table.set(String(p.table_id ?? ''));
    this.outside.set(String(p.table_out_of_range ?? 'clamp_warn'));
    this.backup.set((p.backup_k as number | null) ?? 0.44);
    this.relief.set(String(p.relief_type ?? 'rect'));
    this.ratio.set((p.relief_width_ratio as number | null) ?? 0.5);
    this.extra.set((p.relief_extra as number | null) ?? 0.5);
    this.auto.set(p.auto_relief !== false);
    setText(this.msg, '');
    this.recalc();
    this.paintBends();
    this.off?.();
    this.off = sheetStore.onChange(() => this.paintBends());
    this.onClose = () => { this.off?.(); this.off = null; };
    this.open();
  }

  private fillTables(): void {
    const sel = this.table.input as HTMLSelectElement;
    patchList<TableRow | { id: string }>(sel, [{ id: '' }, ...this.tableIds], {
      key: (r) => r.id,
      create: (r) => { const o = document.createElement('option'); o.value = r.id; return o; },
      update: (n, r) => setText(n, r.id === '' ? t('None') : `${(r as TableRow).name || r.id} (${(r as TableRow).mode.toUpperCase()})`),
    });
  }

  private num(row: { get(): number | string | null }): number {
    const v = row.get();
    return typeof v === 'number' ? v : Number.NaN;
  }

  private recalc(): void {
    const m = this.method.get();
    this.k.use(m === 'kfactor');
    this.ba.use(m === 'allowance');
    this.bd.use(m === 'deduction');
    this.table.use(m === 'table');
    this.outside.use(m === 'table');
    this.backup.use(m === 'table');
    const r = bendNumbers(m, this.num(this.radius), this.num(this.thickness), this.num(this.k), this.num(this.ba), this.num(this.bd));
    if (r) {
      this.rn.set(fmt(r.rn));
      this.kOut.set(fmt(r.k, 5));
      this.baOut.set(fmt(r.ba));
      this.bdOut.set(fmt(r.bd));
      this.setback.set(fmt(r.ossb));
    } else {
      const note = m === 'table' ? t('From the table, per bend') : '-';
      for (const o of [this.rn, this.kOut, this.baOut, this.bdOut, this.setback]) o.set(note);
    }
    const bad = m !== 'table' && !r;
    setDisabled(this.apply, bad);
  }

  private paintBends(): void {
    patchList<BendRecord>(this.list, sheetStore.bends, {
      key: (b) => b.id,
      create: () => el('<div class="sm-brow" role="listitem"><span class="sm-bid"></span><span class="sm-bdir"></span><span class="sm-bnum"></span></div>'),
      update: (n, b) => {
        setText(q(n, '.sm-bid'), b.id);
        setText(q(n, '.sm-bdir'), `${t(b.direction === 'up' ? 'Up' : 'Down')} ${fmt((b.angle * 180) / Math.PI, 2)}`);
        setText(q(n, '.sm-bnum'), `R ${fmt(b.radius, 4)}  K ${fmt(b.k, 4)}  BA ${fmt(b.ba, 4)}  BD ${fmt(b.bd, 4)}`);
        setClass(n, 'is-warn', (b.warnings ?? []).length > 0);
      },
    });
  }

  private async save(): Promise<void> {
    const id = docStore.activeId;
    if (!id || !this.root) return;
    const params: Record<string, unknown> = {
      thickness: this.thickness.get(),
      radius: this.radius.get(),
      bend_method: this.method.get(),
      k_factor: this.k.get(),
      ba: this.ba.get(),
      bd: this.bd.get(),
      table_id: this.table.get(),
      table_out_of_range: this.outside.get(),
      backup_k: this.backup.get(),
      relief_type: this.relief.get(),
      relief_width_ratio: this.ratio.get(),
      relief_extra: this.extra.get(),
      auto_relief: this.auto.get(),
    };
    setDisabled(this.apply, true);
    setText(this.msg, '');
    try {
      const done = await part.edit(id, this.root, { params });
      partStore.refresh(0);
      await view3d()?.refresh();
      sheetStore.refresh(0);
      if (done.state.status === 'error') setText(this.msg, done.state.message);
      else this.close();
    } catch (e) {
      setText(this.msg, messageOf(e));
    } finally {
      this.recalc();
    }
  }
}
