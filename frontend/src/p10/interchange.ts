import { ApiError, call } from '../io/api';
import { Dialog } from '../ui/dialogs';
import { docStore } from '../ui/doc-store';
import { el, patchList, q, setChecked, setHidden, setText, store, stored } from '../ui/dom';
import { t } from '../ui/i18n';
import { trackWork } from '../ui/output/job-feed';
import { toast } from '../ui/toast';
import { view3d } from '../view3d/mount';
import { fixed, num, type Json } from './kit';

const enc = encodeURIComponent;
const tail = (p: string): string => p.split(/[\\/]/).pop() ?? p;
const extOf = (p: string): string => /\.([A-Za-z0-9]+)$/.exec(p.trim())?.[1].toLowerCase() ?? '';

export const STEP_EXT = ['step', 'stp'];
export const IGES_EXT = ['iges', 'igs'];
const UNITLESS = ['stl', 'obj', 'ply'];
export const IMPORT_EXT = [...STEP_EXT, ...IGES_EXT, '3mf', 'glb', 'gltf', ...UNITLESS];
const MESH_WRITE = ['3mf', 'glb', 'gltf', 'ply'];
export const EXPORT_EXT = [...STEP_EXT, ...IGES_EXT, ...MESH_WRITE];

export interface Inspect {
  kind: string; ext: string; bytes: number; schema: string; unit: string; unit_mm: number; document_unit: string;
  mismatch: boolean; warnings: string[]; units_known: boolean;
  suggestion?: { diagonal_raw?: number; diagonal_mm_in_document_unit?: number; suggested_unit?: string };
}

export interface PmiReport { written?: number; dropped?: number; read?: number; not_recovered?: number; detail?: string[] }
export interface InterchangeNotes {
  notes?: string[]; warnings?: string[]; counts?: Record<string, number>; pmi?: PmiReport; schema?: string; unit?: string;
}

interface ImportOptions { unit_choice: 'convert' | 'keep'; unit?: string; pmi: boolean; assembly: boolean; scale_check: boolean }
interface ExportOptions { schema?: string; unit?: string; pmi?: boolean; bodies?: number[] | null; binary?: boolean; linear?: number; angular?: number }

const UNITS: ReadonlyArray<readonly [string, string]> = [['mm', 'Millimetres'], ['cm', 'Centimetres'], ['m', 'Metres'], ['inch', 'Inches'], ['foot', 'Feet'], ['micron', 'Microns']];
const SCHEMAS: ReadonlyArray<readonly [string, string]> = [['ap214', 'AP214 (automotive, default)'], ['ap203', 'AP203 (configuration controlled design)'], ['ap242', 'AP242 (DIS schema, carries model based notes)']];

function select(options: ReadonlyArray<readonly [string, string]>, label: string): HTMLSelectElement {
  const s = el<HTMLSelectElement>('<select class="cv-input"></select>');
  s.setAttribute('aria-label', label);
  for (const [v, text] of options) { const o = document.createElement('option'); o.value = v; o.textContent = t(text); s.appendChild(o); }
  return s;
}

function check(label: string): { row: HTMLElement; box: HTMLInputElement } {
  const row = el('<label class="cv-field cv-check"><span></span><input type="checkbox"></label>');
  setText(q(row, 'span'), t(label));
  return { row, box: q<HTMLInputElement>(row, 'input') };
}

function numberInput(label: string, value: string): { row: HTMLElement; input: HTMLInputElement } {
  const row = el('<label class="cv-field"><span></span><input class="cv-input xw-num" type="text" inputmode="decimal" spellcheck="false" autocomplete="off"></label>');
  setText(q(row, 'span'), t(label));
  const input = q<HTMLInputElement>(row, 'input');
  input.value = value;
  input.addEventListener('keydown', (e) => { e.stopPropagation(); if (e.key === 'Enter') { e.preventDefault(); input.blur(); } });
  return { row, input };
}

function readoutRow(label: string): { row: HTMLElement; set(v: string): void } {
  const row = el('<div class="cv-field xw-read"><span></span><output></output></div>');
  setText(q(row, 'span'), t(label));
  const out = q(row, 'output');
  return { row, set(v) { setText(out, v); if (out.title !== v) out.title = v; } };
}

const NOTE_ROWS = 4;

function noteBlock(): { el: HTMLElement; set(lines: string[]): void } {
  const root = el('<div class="xw-notes is-scroll" role="status"></div>');
  const rows: HTMLElement[] = [];
  for (let i = 0; i < NOTE_ROWS; i++) { const r = el('<p class="cv-note xw-notep"></p>'); root.appendChild(r); rows.push(r); }
  return { el: root, set(lines) { rows.forEach((r, i) => setText(r, lines[i] ?? '')); } };
}

class ImportDialog extends Dialog {
  private readonly file = readoutRow('File');
  private readonly kind = readoutRow('Format');
  private readonly fileUnit = readoutRow('Unit in the file');
  private readonly docUnit = readoutRow('Document unit');
  private readonly choice = select([['convert', 'Convert to the document unit'], ['keep', 'Keep the numbers as they are']], 'When the units differ');
  private readonly choiceRow: HTMLElement;
  private readonly unit = select(UNITS, 'Unit of the numbers in the file');
  private readonly unitRow: HTMLElement;
  private readonly pmi = check('Read model based notes (PMI)');
  private readonly assembly = check('Keep the assembly structure');
  private readonly scale = check('Check the size of the result');
  private readonly notes = noteBlock();
  private readonly go: HTMLButtonElement;
  private resolve: ((v: ImportOptions | null) => void) | null = null;
  private info: Inspect | null = null;

  constructor() {
    super('Import 3D File', 480);
    this.body.append(this.file.row, this.kind.row, this.fileUnit.row, this.docUnit.row);
    this.choiceRow = el('<label class="cv-field"><span></span></label>');
    setText(q(this.choiceRow, 'span'), t('When the units differ'));
    this.choiceRow.appendChild(this.choice);
    this.unitRow = el('<label class="cv-field"><span></span></label>');
    setText(q(this.unitRow, 'span'), t('Unit of the numbers'));
    this.unitRow.appendChild(this.unit);
    this.body.append(this.choiceRow, this.unitRow, this.pmi.row, this.assembly.row, this.scale.row, this.notes.el);
    this.button('Cancel', 'ghost', () => this.finish(null));
    this.go = this.button('Import', 'primary', () => this.finish(this.collect()));
    this.onClose = () => this.finish(null);
  }

  private collect(): ImportOptions {
    const i = this.info;
    const o: ImportOptions = { unit_choice: this.choice.value === 'keep' ? 'keep' : 'convert', pmi: this.pmi.box.checked, assembly: this.assembly.box.checked, scale_check: this.scale.box.checked };
    if (i && !i.units_known) {
      o.unit = this.unit.value;
      store(this.key(), this.unit.value);
    }
    return o;
  }

  private key(): string { return `formCAD.import.unit.${docStore.current()?.name ?? ''}`; }

  private finish(v: ImportOptions | null): void {
    const r = this.resolve;
    this.resolve = null;
    if (this.isOpen) this.close();
    r?.(v);
  }

  ask(path: string, info: Inspect): Promise<ImportOptions | null> {
    this.info = info;
    const ext = extOf(path);
    const model = STEP_EXT.includes(ext) || IGES_EXT.includes(ext);
    this.file.set(tail(path));
    this.kind.set(`${info.kind || ext.toUpperCase()}${info.schema ? ` · ${info.schema}` : ''}`);
    this.fileUnit.set(info.units_known ? `${info.unit}${info.unit_mm ? ` (${fixed(info.unit_mm, 4)} mm)` : ''}` : t('Not stated by the file'));
    this.docUnit.set(info.document_unit);
    setHidden(this.choiceRow, !(info.units_known && info.mismatch));
    setHidden(this.unitRow, info.units_known);
    if (!info.units_known) {
      const mine = stored(this.key());
      const pick = UNITS.some(([v]) => v === mine) ? mine : UNITS.some(([v]) => v === info.document_unit) ? info.document_unit : 'mm';
      if (pick) this.unit.value = pick;
    }
    this.choice.value = 'convert';
    setHidden(this.pmi.row, !STEP_EXT.includes(ext));
    setHidden(this.assembly.row, !model);
    setChecked(this.pmi.box, true);
    setChecked(this.assembly.box, true);
    setChecked(this.scale.box, true);
    const lines = info.units_known ? [...info.warnings] : info.warnings.filter((w) => !/carries no unit/i.test(w));
    const hint = info.suggestion?.suggested_unit;
    if (!info.units_known && hint) lines.unshift(`${t('The size looks wrong in the document unit; the numbers may be in')} ${hint}.`);
    if (!info.units_known) lines.unshift(t('This format carries no unit. Choose the unit of its numbers; nothing is rescaled without your choice.'));
    else if (info.mismatch) lines.push(t('Convert scales the numbers; Keep leaves them unchanged.'));
    this.notes.set(lines);
    this.open(this.go);
    return new Promise((r) => { this.resolve = r; });
  }
}

class ExportDialog extends Dialog {
  private readonly file = readoutRow('File');
  private readonly schema = select(SCHEMAS, 'STEP schema');
  private readonly schemaRow: HTMLElement;
  private readonly unit = select([['mm', 'Millimetres'], ['inch', 'Inches'], ['m', 'Metres']], 'Unit written to the file');
  private readonly unitRow: HTMLElement;
  private readonly pmi = check('Write model based notes (PMI)');
  private readonly selected = check('Selected solids only');
  private readonly binary = check('Binary file');
  private readonly linear = numberInput('Chord deviation (mm)', '0.01');
  private readonly angular = numberInput('Angle deviation (rad)', '0.1');
  private readonly notes = noteBlock();
  private readonly go: HTMLButtonElement;
  private resolve: ((v: ExportOptions | null) => void) | null = null;
  private ext = '';

  constructor() {
    super('Export 3D File', 480);
    this.schemaRow = el('<label class="cv-field"><span></span></label>');
    setText(q(this.schemaRow, 'span'), t('STEP schema'));
    this.schemaRow.appendChild(this.schema);
    this.unitRow = el('<label class="cv-field"><span></span></label>');
    setText(q(this.unitRow, 'span'), t('Unit in the file'));
    this.unitRow.appendChild(this.unit);
    this.body.append(this.file.row, this.schemaRow, this.unitRow, this.pmi.row, this.selected.row, this.binary.row, this.linear.row, this.angular.row, this.notes.el);
    this.schema.addEventListener('change', () => { if (this.schema.value === 'ap242') setChecked(this.pmi.box, true); this.paint(); });
    this.button('Cancel', 'ghost', () => this.finish(null));
    this.go = this.button('Export', 'primary', () => this.finish(this.collect()));
    this.onClose = () => this.finish(null);
  }

  private paint(): void {
    const ext = this.ext;
    const step = STEP_EXT.includes(ext);
    const ap242 = this.schema.value === 'ap242';
    this.pmi.box.disabled = !(step && ap242);
    if (step && !ap242) setChecked(this.pmi.box, false);
    const lines: string[] = [];
    if (step) lines.push(ap242 ? t('AP242 (DIS schema, OCCT 8.0.1) carries dimensions, tolerances and datums. What it cannot write is listed afterwards.') : t('Model based notes need the AP242 schema; they are left out of this file.'));
    if (ext === 'glb' || ext === 'gltf') lines.push(t('glTF is always in metres: the numbers are scaled from the document unit.'));
    if (ext === '3mf') lines.push(t('3MF stores triangles with a unit and colours. Curved faces are tessellated.'));
    if (ext === 'ply') lines.push(t('PLY has no unit field; the unit is written as a comment.'));
    this.notes.set(lines);
  }

  private collect(): ExportOptions {
    const ext = this.ext;
    const o: ExportOptions = {};
    if (STEP_EXT.includes(ext)) { o.schema = this.schema.value; o.pmi = this.pmi.box.checked && !this.pmi.box.disabled; o.unit = this.unit.value; }
    if (IGES_EXT.includes(ext)) o.unit = this.unit.value;
    if (ext === '3mf' || ext === 'ply') o.unit = this.unit.value;
    if (ext === 'ply') o.binary = this.binary.box.checked;
    if (MESH_WRITE.includes(ext)) {
      o.linear = Math.min(5, Math.max(0.0005, Number(this.linear.input.value.replace(',', '.')) || 0.01));
      o.angular = Math.min(1, Math.max(0.01, Number(this.angular.input.value.replace(',', '.')) || 0.1));
    }
    const vp = view3d()?.vp;
    o.bodies = this.selected.box.checked && vp && vp.sel.bodies.length ? [...vp.sel.bodies] : null;
    return o;
  }

  private finish(v: ExportOptions | null): void {
    const r = this.resolve;
    this.resolve = null;
    if (this.isOpen) this.close();
    r?.(v);
  }

  ask(path: string, docUnit: string): Promise<ExportOptions | null> {
    this.ext = extOf(path);
    const ext = this.ext;
    this.file.set(tail(path));
    setHidden(this.schemaRow, !STEP_EXT.includes(ext));
    setHidden(this.unitRow, ext === 'glb' || ext === 'gltf');
    setHidden(this.pmi.row, !STEP_EXT.includes(ext));
    setHidden(this.binary.row, ext !== 'ply');
    setHidden(this.linear.row, !MESH_WRITE.includes(ext));
    setHidden(this.angular.row, !MESH_WRITE.includes(ext));
    this.unit.value = ['mm', 'inch', 'm'].includes(docUnit) ? docUnit : 'mm';
    this.schema.value = 'ap214';
    setChecked(this.binary.box, true);
    setChecked(this.selected.box, false);
    const vp = view3d()?.vp;
    this.selected.box.disabled = !(vp && vp.sel.bodies.length);
    this.paint();
    this.open(this.go);
    return new Promise((r) => { this.resolve = r; });
  }
}

class ReportDialog extends Dialog {
  private readonly list = el('<div class="xw-rep is-scroll" role="log"></div>');
  private readonly head = el('<p class="cv-note xw-rep-head"></p>');

  constructor() {
    super('Interchange Report', 520);
    this.body.append(this.head, this.list);
    this.button('Close', 'primary', () => this.close());
  }

  show(title: string, n: InterchangeNotes | null | undefined): void {
    const rows: Array<{ key: string; text: string; tone: string }> = [];
    const add = (tone: string, text: string): void => { rows.push({ key: `r${rows.length}`, text, tone }); };
    for (const w of n?.warnings ?? []) add('warn', w);
    for (const w of n?.notes ?? []) add('note', w);
    const c = n?.counts ?? {};
    for (const [k, v] of Object.entries(c)) add('note', `${k.replace(/_/g, ' ')}: ${v}`);
    const p = n?.pmi;
    if (p) {
      if (p.written !== undefined) add('note', `${t('PMI written')}: ${num(p.written)}`);
      if (p.dropped) add('warn', `${t('PMI dropped')}: ${num(p.dropped)}`);
      if (p.read !== undefined) add('note', `${t('PMI read back')}: ${num(p.read)}`);
      if (p.not_recovered) add('warn', `${t('PMI not recovered')}: ${num(p.not_recovered)}`);
      for (const d of p.detail ?? []) add('warn', d);
    }
    if (!rows.length) add('note', t('Nothing to report.'));
    setText(this.head, `${title}${n?.schema ? ` · ${n.schema}` : ''}${n?.unit ? ` · ${n.unit}` : ''}`);
    patchList(this.list, rows, {
      key: (r) => r.key,
      create: () => el('<div class="xw-rep-row"></div>'),
      update: (node, r) => { setText(node, r.text); node.dataset.tone = r.tone; },
    });
    this.open();
  }
}

let importDlg: ImportDialog | null = null;
let exportDlg: ExportDialog | null = null;
let reportDlg: ReportDialog | null = null;

export const report = (title: string, n: InterchangeNotes | null | undefined): void => { (reportDlg ??= new ReportDialog()).show(title, n); };

const hasProblems = (n?: InterchangeNotes | null): boolean => !!n && ((n.warnings?.length ?? 0) > 0 || !!n.pmi?.dropped || !!n.pmi?.not_recovered);

export async function importWithOptions(path: string): Promise<boolean> {
  const ext = extOf(path);
  const id = docStore.activeId;
  if (!id || !IMPORT_EXT.includes(ext)) return false;
  let info: Inspect;
  try {
    info = await call<Inspect>('POST', '/api/interchange/inspect', { path, document: id });
  } catch (e) {
    if (e instanceof ApiError && (e.status === 404 || e.status === 405)) return false;
    toast(e instanceof Error ? e.message : t('The file could not be read.'), 'error');
    return true;
  }
  const options = await (importDlg ??= new ImportDialog()).ask(path, info);
  if (!options) return true;
  try {
    const r = await trackWork(`${t('Import')} ${tail(path)}`, () => call<Json & { notes?: InterchangeNotes; report?: InterchangeNotes; summary?: string }>('POST', `/api/docs/${enc(id)}/interchange/import`, { path, options }));
    const n = r.notes ?? r.report ?? null;
    void docStore.refresh();
    await view3d()?.with3d(() => undefined);
    if (hasProblems(n)) report(`${t('Imported')} ${tail(path)}`, n);
    else toast(`${t('Imported')} ${tail(path)}.${n?.notes?.length ? ` ${n.notes[0]}` : ''}`, 'info');
  } catch (e) {
    toast(e instanceof Error ? e.message : t('The import failed.'), 'error');
  }
  return true;
}

export async function openOptions(path: string): Promise<ImportOptions | null | false> {
  if (!IMPORT_EXT.includes(extOf(path))) return false;
  let info: Inspect;
  try {
    info = await call<Inspect>('POST', '/api/interchange/inspect', { path });
  } catch (e) {
    if (e instanceof ApiError && (e.status === 404 || e.status === 405)) return false;
    toast(e instanceof Error ? e.message : t('The file could not be read.'), 'error');
    return null;
  }
  return (importDlg ??= new ImportDialog()).ask(path, { ...info, mismatch: false, document_unit: info.unit || t('New document') });
}

export async function exportWithOptions(path: string): Promise<boolean> {
  const ext = extOf(path);
  const id = docStore.activeId;
  if (!id || !EXPORT_EXT.includes(ext)) return false;
  const options = await (exportDlg ??= new ExportDialog()).ask(path, 'mm');
  if (!options) return true;
  try {
    const r = await trackWork(`${t('Export')} ${tail(path)}`, () => call<{ path: string; notes?: InterchangeNotes }>('POST', `/api/docs/${enc(id)}/interchange/export`, { path, options }));
    if (options.pmi || hasProblems(r.notes)) report(`${t('Exported')} ${tail(path)}`, r.notes);
    else toast(`${t('Exported')} ${tail(path)}.${r.notes?.notes?.length ? ` ${r.notes.notes[0]}` : ''}`, 'info');
  } catch (e) {
    toast(e instanceof Error ? e.message : t('The export failed.'), 'error');
  }
  return true;
}
