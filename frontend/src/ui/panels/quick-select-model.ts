import { kindTitle } from './props-kinds';

export type Rec = Record<string, unknown>;
export type Scalar = string | number | boolean | null;
export type ChoiceSource = 'color' | 'layer' | 'linetype' | 'type' | null;

export interface QuickProp {
  id: string;
  label: string;
  choices: ChoiceSource;
  get(e: Rec): Scalar;
}

export type Operator = '=' | '<>' | '>' | '<' | '*';

const COLOR_NAMES = ['', 'Red', 'Yellow', 'Green', 'Cyan', 'Blue', 'Magenta', 'White'];
const DEG = 180 / Math.PI;

export function colorName(c: unknown): string {
  if (c === 256) return 'ByLayer';
  if (c === 0) return 'ByBlock';
  if (typeof c === 'number') return COLOR_NAMES[c] || String(c);
  return typeof c === 'string' ? c : '';
}

const pointAxis = (field: string, i: 0 | 1) => (e: Rec): Scalar => {
  const v = e[field];
  return Array.isArray(v) && typeof v[i] === 'number' ? v[i] : null;
};
const plain = (field: string) => (e: Rec): Scalar => {
  const v = e[field];
  return typeof v === 'number' || typeof v === 'string' || typeof v === 'boolean' ? v : null;
};
const degrees = (field: string) => (e: Rec): Scalar => {
  const v = e[field];
  return typeof v === 'number' ? Number((v * DEG).toFixed(9)) : null;
};
const make = (id: string, label: string, get: (e: Rec) => Scalar, choices: ChoiceSource = null): QuickProp => ({ id, label, get, choices });
const dist = (a: unknown, b: unknown): number | null => (Array.isArray(a) && Array.isArray(b) ? Math.hypot(Number(b[0]) - Number(a[0]), Number(b[1]) - Number(a[1])) : null);

export const COMMON: QuickProp[] = [
  make('color', 'Color', (e) => colorName(e.color), 'color'),
  make('layer', 'Layer', plain('layer'), 'layer'),
  make('linetype', 'Linetype', plain('linetype'), 'linetype'),
  make('ltscale', 'Linetype scale', plain('ltscale')),
  make('lineweight', 'Lineweight', (e) => (typeof e.lineweight === 'number' ? (e.lineweight === -1 ? 'ByLayer' : e.lineweight === -2 ? 'ByBlock' : e.lineweight === -3 ? 'Default' : e.lineweight / 100) : null)),
  make('thickness', 'Thickness', plain('thickness')),
  make('kind', 'Type', (e) => kindTitle(String(e.kind)), 'type'),
];

export const BY_KIND: Record<string, QuickProp[]> = {
  line: [
    make('start_x', 'Start X', pointAxis('start', 0)), make('start_y', 'Start Y', pointAxis('start', 1)),
    make('end_x', 'End X', pointAxis('end', 0)), make('end_y', 'End Y', pointAxis('end', 1)),
    make('length', 'Length', (e) => dist(e.start, e.end)),
    make('angle', 'Angle', (e) => {
      const s = e.start, t = e.end;
      if (!Array.isArray(s) || !Array.isArray(t)) return null;
      const a = Math.atan2(Number(t[1]) - Number(s[1]), Number(t[0]) - Number(s[0])) * DEG;
      return Number(((a + 360) % 360).toFixed(9));
    }),
  ],
  circle: [
    make('center_x', 'Center X', pointAxis('center', 0)), make('center_y', 'Center Y', pointAxis('center', 1)),
    make('radius', 'Radius', plain('radius')),
    make('diameter', 'Diameter', (e) => (typeof e.radius === 'number' ? e.radius * 2 : null)),
    make('circumference', 'Circumference', (e) => (typeof e.radius === 'number' ? 2 * Math.PI * e.radius : null)),
    make('area', 'Area', (e) => (typeof e.radius === 'number' ? Math.PI * e.radius * e.radius : null)),
  ],
  arc: [
    make('center_x', 'Center X', pointAxis('center', 0)), make('center_y', 'Center Y', pointAxis('center', 1)),
    make('radius', 'Radius', plain('radius')),
    make('start_angle', 'Start angle', degrees('start_angle')), make('end_angle', 'End angle', degrees('end_angle')),
  ],
  ellipse: [make('center_x', 'Center X', pointAxis('center', 0)), make('center_y', 'Center Y', pointAxis('center', 1)), make('ratio', 'Ratio', plain('ratio'))],
  lwpolyline: [make('closed', 'Closed', plain('closed')), make('const_width', 'Global width', plain('const_width')), make('elevation', 'Elevation', plain('elevation'))],
  text: [
    make('text', 'Contents', plain('text')), make('height', 'Height', plain('height')), make('rotation', 'Rotation', degrees('rotation')),
    make('width_factor', 'Width factor', plain('width_factor')), make('style', 'Style', plain('style')),
    make('position_x', 'Position X', pointAxis('position', 0)), make('position_y', 'Position Y', pointAxis('position', 1)),
  ],
  mtext: [
    make('contents', 'Contents', plain('contents')), make('height', 'Text height', plain('height')), make('width', 'Defined width', plain('width')),
    make('rotation', 'Rotation', degrees('rotation')), make('style', 'Style', plain('style')),
  ],
  insert: [make('block', 'Name', plain('block')), make('rotation', 'Rotation', degrees('rotation')), make('position_x', 'Position X', pointAxis('position', 0)), make('position_y', 'Position Y', pointAxis('position', 1))],
  hatch: [make('pattern', 'Pattern', plain('pattern')), make('pattern_scale', 'Scale', plain('pattern_scale')), make('pattern_angle', 'Angle', degrees('pattern_angle'))],
  dimension: [make('text_override', 'Text override', plain('text_override')), make('style', 'Dim style', plain('style'))],
  assoc_array: [make('shape', 'Shape', plain('shape')), make('columns', 'Columns', plain('columns')), make('rows', 'Rows', plain('rows')), make('levels', 'Levels', plain('levels')), make('items', 'Items', plain('items'))],
  point: [make('position_x', 'Position X', pointAxis('position', 0)), make('position_y', 'Position Y', pointAxis('position', 1))],
};

export function propsFor(kind: string | null): QuickProp[] {
  return kind && BY_KIND[kind] ? [...COMMON, ...BY_KIND[kind]] : COMMON;
}

const glob = (pattern: string): RegExp => new RegExp(`^${pattern.replace(/[.+^${}()|[\]\\]/g, '\\$&').replace(/\*/g, '.*').replace(/\?/g, '.')}$`, 'i');

export function matches(value: Scalar, op: Operator, typed: string): boolean {
  if (op === '*') return value !== null && glob(typed).test(String(value));
  if (value === null) return op === '<>';
  const n = Number(typed);
  if (typeof value === 'number' && typed.trim() !== '' && Number.isFinite(n)) {
    const same = Math.abs(value - n) <= 1e-9 * Math.max(1, Math.abs(n));
    return op === '=' ? same : op === '<>' ? !same : op === '>' ? value > n && !same : value < n && !same;
  }
  const a = String(value).toLowerCase(), b = typed.toLowerCase();
  return op === '=' ? a === b : op === '<>' ? a !== b : op === '>' ? a > b : a < b;
}
