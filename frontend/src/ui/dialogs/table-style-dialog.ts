import { aciField, checkField, numField, selectField, setOptions } from './fields';
import { StyleManager } from './style-manager';
import type { StyleRecord } from './style-manager';

const ALIGN: ReadonlyArray<readonly [string, string]> = [
  ['1', 'Top left'], ['2', 'Top center'], ['3', 'Top right'], ['4', 'Middle left'], ['5', 'Middle center'], ['6', 'Middle right'],
  ['7', 'Bottom left'], ['8', 'Bottom center'], ['9', 'Bottom right'],
];

export class TableStyleDialog extends StyleManager {
  private readonly cellPick = selectField('Cell style', [['Data', 'Data']]);
  private readonly cellText = selectField('Cell text style', [['Standard', 'Standard']]);
  private cellName = 'Data';

  constructor() {
    super({ title: 'Table Style', table: 'tablestyles', command: 'tablestyle', currentVar: 'CTABLESTYLE', width: 700 });
    const height = numField('Text height', { min: 0 });
    const margin = numField('Cell margin', { min: 0 });
    const title = checkField('Title row');
    const header = checkField('Header row');
    this.bind(height, 'text_height', (r) => Number(r.text_height ?? 0));
    this.bind(margin, 'margin', (r) => Number(r.margin ?? 0));
    this.bind(title, 'title_row', (r) => r.title_row !== false);
    this.bind(header, 'header_row', (r) => r.header_row !== false);
    const cell = (r: StyleRecord): StyleRecord => this.cellOf(r);
    const cHeight = numField('Cell text height', { min: 0 });
    const cColor = aciField('Cell text color');
    const cAlign = selectField('Alignment', ALIGN);
    const cMh = numField('Horizontal margin', { min: 0 });
    const cMv = numField('Vertical margin', { min: 0 });
    const cFormat = selectField('Data format', [['general', 'General'], ['decimal', 'Decimal'], ['percent', 'Percent'], ['text', 'Text']]);
    const cPrec = numField('Precision', { min: 0, max: 8, int: true });
    const cMerge = checkField('Merge across');
    this.bind(this.cellText, 'cell.text_style', (r) => String(cell(r).text_style ?? 'Standard'));
    this.bind(cHeight, 'cell.text_height', (r) => Number(cell(r).text_height ?? 0));
    this.bind(cColor, 'cell.text_color', (r) => Number(cell(r).text_color ?? 0));
    this.bind(cAlign, 'cell.alignment', (r) => String(cell(r).alignment ?? 4), (f) => Number(f.get()));
    this.bind(cMh, 'cell.margin_h', (r) => Number(cell(r).margin_h ?? 0));
    this.bind(cMv, 'cell.margin_v', (r) => Number(cell(r).margin_v ?? 0));
    this.bind(cFormat, 'cell.format', (r) => String(cell(r).format ?? 'general'));
    this.bind(cPrec, 'cell.precision', (r) => Number(cell(r).precision ?? 0));
    this.bind(cMerge, 'cell.merge_across', (r) => !!cell(r).merge_across);
    this.cellPick.change = () => { this.cellName = String(this.cellPick.get()); this.paint(); };
    for (const f of [height, margin, title, header, this.cellPick, this.cellText, cHeight, cColor, cAlign, cMh, cMv, cFormat, cPrec, cMerge]) this.props.appendChild(f.el);
  }

  private cellOf(rec: StyleRecord): StyleRecord {
    const list = (rec.cell_styles ?? []) as StyleRecord[];
    return list.find((c) => String(c.name) === this.cellName) ?? list.find((c) => String(c.name) === 'Data') ?? {};
  }

  protected afterFill(rec: StyleRecord): void {
    const list = (rec.cell_styles ?? []) as StyleRecord[];
    const names = list.map((c) => String(c.name));
    if (!names.includes(this.cellName)) this.cellName = 'Data';
    setOptions(this.cellPick, names.map((n) => [n, n] as const));
    this.cellPick.set(this.cellName);
    const styles = (this.tables?.textstyles ?? []).map((s) => String(s.name));
    setOptions(this.cellText, styles.map((n) => [n, n] as const));
    this.cellText.set(String(this.cellOf(rec).text_style ?? 'Standard'));
  }

  protected editArgs(_rec: StyleRecord, key: string, value: unknown): Record<string, unknown> {
    if (key.startsWith('cell.')) return { cell_style: { name: this.cellName, [key.slice(5)]: value } };
    return { [key]: value };
  }

  protected createArgs(base: StyleRecord | undefined, name: string): Record<string, unknown> {
    const out: Record<string, unknown> = { action: 'create', name, current: false };
    if (!base) return out;
    out.text_height = base.text_height;
    out.margin = base.margin;
    out.title_row = base.title_row;
    out.header_row = base.header_row;
    out.cell_styles = ((base.cell_styles ?? []) as StyleRecord[]).map((c) => {
      const copy: Record<string, unknown> = {};
      for (const k of ['name', 'text_style', 'text_height', 'text_color', 'fill', 'alignment', 'margin_h', 'margin_v', 'format', 'precision', 'merge_across']) copy[k] = c[k];
      return copy;
    });
    return out;
  }
}
