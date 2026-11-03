import { el, q, setClass, setHidden } from '../ui/dom';
import { t } from '../ui/i18n';
import type { ParamSchema } from './api';

export interface FieldView {
  row: HTMLElement;
  name: string;
  set(v: unknown): void;
  get(): unknown;
  show(on: boolean): void;
  bad(): boolean;
}

export const pretty = (s: string): string => {
  const w = s.replace(/_/g, ' ');
  return w.charAt(0).toUpperCase() + w.slice(1);
};

const CHOICE_WORDS: Record<string, string> = {
  kfactor: 'K-factor',
  allowance: 'Bend allowance',
  deduction: 'Bend deduction',
  table: 'Bend table',
  clamp_warn: 'Hold the nearest value and warn',
  backup_k: 'Use the backup K-factor',
  rect: 'Rectangular',
  material_inside: 'Material inside the outline',
  material_outside: 'Material outside the outline',
  bend_outside: 'Bend outside the outline',
  tangent: 'Tangent to the bend',
  centered: 'Centred on the edge',
  offsets: 'Offsets from the ends',
  full: 'Whole edge',
  rule: 'From the sheet metal rule',
  on: 'Relieve',
  off: 'Do not relieve',
  closed: 'Closed',
  open: 'Open',
  teardrop: 'Teardrop',
  rolled: 'Rolled',
};

const numeric = (s: string): number | null => {
  if (!s.trim()) return null;
  const n = Number(s);
  return Number.isFinite(n) ? n : null;
};

function shell(label: string, kind: string): { row: HTMLElement; lab: HTMLElement } {
  const row = el<HTMLElement>(`<label class="pp-row pp-${kind}"><span class="pp-lab"></span></label>`);
  const lab = q(row, '.pp-lab');
  lab.textContent = t(label);
  return { row, lab };
}

function expression(p: ParamSchema, change: () => void, integer: boolean): FieldView {
  const { row } = shell(p.label || p.name, p.kind);
  const input = el<HTMLInputElement>('<input class="cv-input pp-in" type="text" inputmode="decimal" spellcheck="false" autocomplete="off">');
  row.appendChild(input);
  if (p.kind === 'angle') row.appendChild(el('<span class="pp-unit">deg</span>'));
  input.addEventListener('input', change);
  input.addEventListener('keydown', (e) => { if (e.key === 'Enter') change(); });
  return {
    row,
    name: p.name,
    set: (v) => { input.value = v === null || v === undefined ? '' : String(v); },
    get: () => {
      const n = numeric(input.value);
      if (n !== null) return integer ? Math.round(n) : n;
      const s = input.value.trim();
      return s ? s : null;
    },
    show: (on) => setHidden(row, !on),
    bad: () => false,
  };
}

function check(p: ParamSchema, change: () => void): FieldView {
  const row = el<HTMLElement>('<label class="pp-row pp-check"><input type="checkbox"><span class="pp-lab"></span></label>');
  const box = q<HTMLInputElement>(row, 'input');
  q(row, '.pp-lab').textContent = t(p.label || p.name);
  box.addEventListener('change', change);
  return { row, name: p.name, set: (v) => { box.checked = !!v; }, get: () => box.checked, show: (on) => setHidden(row, !on), bad: () => false };
}

function choice(p: ParamSchema, change: () => void): FieldView {
  const { row } = shell(p.label || p.name, 'enum');
  const sel = el<HTMLSelectElement>('<select class="cv-input pp-in"></select>');
  const optional = p.default === null || p.default === undefined;
  if (optional) {
    const o = document.createElement('option');
    o.value = '';
    o.textContent = t('From the sheet metal rule');
    sel.appendChild(o);
  }
  for (const c of p.choices ?? []) {
    const o = document.createElement('option');
    o.value = String(c);
    o.textContent = t(CHOICE_WORDS[String(c)] ?? pretty(String(c)));
    sel.appendChild(o);
  }
  row.appendChild(sel);
  sel.addEventListener('change', change);
  return {
    row,
    name: p.name,
    set: (v) => { sel.value = v === null || v === undefined ? (optional ? '' : String(p.default ?? p.choices?.[0] ?? '')) : String(v); },
    get: () => (optional && sel.value === '' ? null : sel.value),
    show: (on) => setHidden(row, !on),
    bad: () => false,
  };
}

function text(p: ParamSchema, change: () => void): FieldView {
  const { row } = shell(p.label || p.name, 'text');
  const input = el<HTMLInputElement>('<input class="cv-input pp-in" type="text" spellcheck="false" autocomplete="off">');
  row.appendChild(input);
  input.addEventListener('input', change);
  return { row, name: p.name, set: (v) => { input.value = v === null || v === undefined ? '' : String(v); }, get: () => input.value, show: (on) => setHidden(row, !on), bad: () => false };
}

function vector(p: ParamSchema, change: () => void): FieldView {
  const { row } = shell(p.label || p.name, 'vector');
  const box = el<HTMLElement>('<span class="pp-vec"><input class="cv-input" type="text" inputmode="decimal" aria-label="X"><input class="cv-input" type="text" inputmode="decimal" aria-label="Y"><input class="cv-input" type="text" inputmode="decimal" aria-label="Z"></span>');
  row.appendChild(box);
  const ins = Array.from(box.querySelectorAll('input'));
  for (const i of ins) i.addEventListener('input', change);
  return {
    row,
    name: p.name,
    set: (v) => { ins.forEach((i, k) => { i.value = Array.isArray(v) && v[k] !== undefined && v[k] !== null ? String(v[k]) : ''; }); },
    get: () => {
      const vals = ins.map((i) => numeric(i.value));
      return vals.every((x) => x === null) ? null : vals.map((x) => x ?? 0);
    },
    show: (on) => setHidden(row, !on),
    bad: () => false,
  };
}

function structure(p: ParamSchema, change: () => void): FieldView {
  const { row } = shell(p.label || p.name, 'json');
  const area = el<HTMLTextAreaElement>('<textarea class="cv-input pp-area" rows="3" spellcheck="false"></textarea>');
  row.appendChild(area);
  let invalid = false;
  const parse = (): unknown => {
    const s = area.value.trim();
    invalid = false;
    if (!s) return null;
    try { return JSON.parse(s); } catch { invalid = true; return null; }
  };
  area.addEventListener('input', () => { parse(); setClass(area, 'is-bad', invalid); change(); });
  return {
    row,
    name: p.name,
    set: (v) => { area.value = v === null || v === undefined ? '' : JSON.stringify(v); invalid = false; setClass(area, 'is-bad', false); },
    get: () => parse(),
    show: (on) => setHidden(row, !on),
    bad: () => { parse(); return invalid; },
  };
}

export function makeField(p: ParamSchema, change: () => void): FieldView {
  switch (p.kind) {
    case 'length':
    case 'angle': return expression(p, change, false);
    case 'int': return expression(p, change, true);
    case 'bool': return check(p, change);
    case 'enum': return choice(p, change);
    case 'vector': return vector(p, change);
    case 'json': return structure(p, change);
    default: return text(p, change);
  }
}

const SHEET_TYPES = new Set(['base_flange', 'convert_sheet', 'edge_flange', 'miter_flange', 'hem', 'jog', 'sketched_bend', 'bend_relief']);

function sheetShown(type: string, name: string, g: (k: string) => unknown): boolean {
  const method = g('bend_method');
  const rootType = type === 'base_flange' || type === 'convert_sheet';
  if (name === 'k_factor') return method === 'kfactor' || (!rootType && !method);
  if (name === 'ba') return method === 'allowance';
  if (name === 'bd') return method === 'deduction';
  if (name === 'table_id') return method === 'table' || (!rootType && !!g('table_id'));
  if (name === 'table_out_of_range' || name === 'backup_k') return method === 'table';
  if (name === 'width') return g('width_mode') !== 'full';
  if (name === 'offset1' || name === 'offset2') return g('width_mode') === 'offsets';
  if (name === 'gap' && type === 'hem') return g('hem') === 'open';
  if (type === 'hem' && (name === 'angle' || name === 'hem_radius')) return g('hem') === 'teardrop' || g('hem') === 'rolled';
  if (name === 'relief_type') return rootType ? true : g('relief_mode') !== 'off';
  if (name === 'relief_width_ratio' || name === 'relief_extra') return g('relief_type') !== 'none' && (rootType || g('relief_mode') !== 'off');
  if (name === 'relief_remnant' || name === 'min_gap' || name === 'auto_relief') return rootType;
  return true;
}

export function showWhen(type: string, name: string, v: Record<string, unknown>): boolean {
  const g = (k: string): unknown => v[k];
  const sweepOrExtrude = type === 'extrude' || type === 'extrude_cut';
  if (sweepOrExtrude) {
    if (name === 'depth1') return g('end1') === 'blind' || g('end1') === 'mid';
    if (name === 'end2') return !!g('two');
    if (name === 'depth2') return !!g('two') && g('end2') === 'blind';
    if (name === 'draft_out') return Number(g('draft') ?? 0) !== 0;
    if (name === 'thin_mode' || name === 'thin1' || name === 'thin_flip') return !!g('thin');
    if (name === 'thin2') return !!g('thin') && g('thin_mode') === 'two';
  }
  if (type === 'revolve' || type === 'revolve_cut') {
    if (name === 'angle2') return !g('mid');
    if (name === 'thin_mode' || name === 'thin1' || name === 'thin_flip') return !!g('thin');
    if (name === 'thin2') return !!g('thin') && g('thin_mode') === 'two';
  }
  if (type === 'pattern') {
    if (name === 'directions') return g('pattern') === 'linear';
    if (name === 'axis' || name === 'angle' || name === 'step') return g('pattern') === 'circular';
  }
  if (type === 'sweep' || type === 'sweep_cut') {
    if (name === 'binormal') return g('mode') === 'binormal';
  }
  if (type === 'loft' || type === 'loft_cut') {
    if (name === 'start_magnitude') return g('start_kind') !== 'none';
    if (name === 'start_dir') return g('start_kind') === 'direction';
    if (name === 'end_magnitude') return g('end_kind') !== 'none';
    if (name === 'end_dir') return g('end_kind') === 'direction';
  }
  if (type === 'rib' && name === 'draft_out') return Number(g('draft') ?? 0) !== 0;
  if (SHEET_TYPES.has(type)) return sheetShown(type, name, g);
  if (type === 'hole') {
    const k = g('kind');
    if (name === 'depth') return g('end') === 'blind';
    if (name === 'diameter') return k !== 'tapped';
    if (name === 'fit') return k !== 'tapped';
    if (name === 'cbore_diameter' || name === 'cbore_depth') return k === 'counterbore';
    if (name === 'csk_diameter' || name === 'csk_angle') return k === 'countersink';
    if (name === 'tap_drill' || name === 'thread_nominal' || name === 'thread_pitch' || name === 'thread_depth' || name === 'cosmetic') return k === 'tapped';
    if (name === 'standard') return false;
  }
  return true;
}

export function slotShown(type: string, slot: string, v: Record<string, unknown>): boolean {
  if ((type === 'extrude' || type === 'extrude_cut') && slot === 'face1') return v.end1 === 'face';
  if ((type === 'sweep' || type === 'sweep_cut') && slot === 'guide') return true;
  return true;
}
