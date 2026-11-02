import type { PropertyField } from '../../io/api';

export type Props = Record<string, PropertyField>;
export type RowType = 'number' | 'text' | 'choice' | 'bool' | 'read' | 'color' | 'lineweight';

export interface RowDef {
  id: string;
  label: string;
  type: RowType;
  show(p: Props): PropertyField | undefined;
  write?(value: unknown, p: Props): Record<string, unknown> | string | null;
}

export interface KindSpec {
  kind: string;
  title: string;
  rows: RowDef[];
}

export const NEED_ONE = 'Select one object, or objects that share this value, to edit it.';

const pt = (f?: PropertyField): [number, number] | null => (f && !f.varies && Array.isArray(f.value) && f.value.length >= 2 ? [Number(f.value[0]), Number(f.value[1])] : null);
const num = (f?: PropertyField): number | null => (f && !f.varies && typeof f.value === 'number' ? f.value : null);
const open = (f?: PropertyField): PropertyField | undefined => (f ? { ...f, readonly: false } : undefined);

function axis(id: string, label: string, field: string, i: 0 | 1): RowDef {
  return {
    id, label, type: 'number',
    show: (p) => {
      const f = p[field];
      if (!f) return undefined;
      return { value: Array.isArray(f.value) ? Number(f.value[i]) : null, varies: f.varies, type: 'number', readonly: f.readonly };
    },
    write: (v, p) => {
      const cur = pt(p[field]);
      if (!cur) return NEED_ONE;
      const next: [number, number] = [cur[0], cur[1]];
      next[i] = Number(v);
      return { [field]: next };
    },
  };
}

function plain(field: string, label: string, type: RowType = 'number', id: string = field): RowDef {
  return { id, label, type, show: (p) => p[field], write: (v) => ({ [field]: v }) };
}

function fixed(field: string, label: string, type: RowType = 'number', id: string = field): RowDef {
  return { id, label, type: type === 'number' ? 'read' : type, show: (p) => p[field] };
}

function between(id: string, label: string, a: string, b: string, i: 0 | 1): RowDef {
  return {
    id, label, type: 'read',
    show: (p) => {
      if (!p[a] || !p[b]) return undefined;
      const pa = pt(p[a]), pb = pt(p[b]);
      return { value: pa && pb ? pb[i] - pa[i] : null, varies: !(pa && pb), type: 'number', readonly: true };
    },
  };
}

const lineLength: RowDef = {
  id: 'length', label: 'Length', type: 'number',
  show: (p) => open(p.length),
  write: (v, p) => {
    const s = pt(p.start), e = pt(p.end), len = num(p.length);
    if (!s || !e || len === null) return NEED_ONE;
    const k = len > 0 ? Number(v) / len : 0;
    return { end: len > 0 ? [s[0] + (e[0] - s[0]) * k, s[1] + (e[1] - s[1]) * k] : [s[0] + Number(v), s[1]] };
  },
};

const lineAngle: RowDef = {
  id: 'angle', label: 'Angle', type: 'number',
  show: (p) => open(p.angle),
  write: (v, p) => {
    const s = pt(p.start), e = pt(p.end), len = num(p.length);
    if (!s || !e || len === null) return NEED_ONE;
    const a = (Number(v) * Math.PI) / 180;
    return { end: [s[0] + len * Math.cos(a), s[1] + len * Math.sin(a)] };
  },
};

const circleRows: RowDef[] = [
  axis('cx', 'Center X', 'center', 0),
  axis('cy', 'Center Y', 'center', 1),
  plain('radius', 'Radius'),
  plain('diameter', 'Diameter'),
  {
    id: 'circumference', label: 'Circumference', type: 'number',
    show: (p) => open(p.circumference),
    write: (v) => ({ radius: Number(v) / (2 * Math.PI) }),
  },
  {
    id: 'area', label: 'Area', type: 'number',
    show: (p) => open(p.area),
    write: (v) => (Number(v) > 0 ? { radius: Math.sqrt(Number(v) / Math.PI) } : 'The area must be greater than zero.'),
  },
];

const shapeOf = (shapes: string[], def: RowDef): RowDef => ({
  ...def,
  show: (p) => {
    const s = p.shape;
    if (s) {
      if (s.varies && shapes.length < 3) return undefined;
      if (!s.varies && !shapes.includes(String(s.value))) return undefined;
    }
    return def.show(p);
  },
});

const ALL3 = ['rect', 'polar', 'path'];

const arrayRows: RowDef[] = [
  fixed('shape', 'Type', 'text'),
  shapeOf(['rect'], plain('columns', 'Columns')),
  shapeOf(['polar', 'path'], plain('items', 'Items')),
  shapeOf(ALL3, plain('rows', 'Rows')),
  shapeOf(ALL3, plain('levels', 'Levels')),
  shapeOf(['rect'], plain('column_spacing', 'Column spacing')),
  shapeOf(ALL3, plain('row_spacing', 'Row spacing')),
  shapeOf(ALL3, plain('level_spacing', 'Level spacing')),
  shapeOf(ALL3, plain('row_elevation', 'Row elevation')),
  shapeOf(['rect'], plain('axis_angle', 'Axis angle')),
  shapeOf(['polar'], plain('fill_angle', 'Fill angle')),
  shapeOf(['polar'], plain('rotate_items', 'Rotate items', 'bool')),
  shapeOf(['path'], plain('align', 'Align items', 'bool')),
  fixed('item_count', 'Item count'),
];

export const KINDS: KindSpec[] = [
  {
    kind: 'line', title: 'Line',
    rows: [
      axis('sx', 'Start X', 'start', 0), axis('sy', 'Start Y', 'start', 1),
      axis('ex', 'End X', 'end', 0), axis('ey', 'End Y', 'end', 1),
      between('dx', 'Delta X', 'start', 'end', 0), between('dy', 'Delta Y', 'start', 'end', 1),
      lineLength, lineAngle,
    ],
  },
  { kind: 'circle', title: 'Circle', rows: circleRows },
  {
    kind: 'arc', title: 'Arc',
    rows: [axis('cx', 'Center X', 'center', 0), axis('cy', 'Center Y', 'center', 1), plain('radius', 'Radius'), plain('start_angle', 'Start angle'), plain('end_angle', 'End angle'), fixed('length', 'Length')],
  },
  { kind: 'ellipse', title: 'Ellipse', rows: [axis('cx', 'Center X', 'center', 0), axis('cy', 'Center Y', 'center', 1), plain('ratio', 'Ratio'), fixed('length', 'Length')] },
  {
    kind: 'lwpolyline', title: 'Polyline',
    rows: [
      plain('const_width', 'Global width'),
      fixed('length', 'Length'),
      { id: 'area', label: 'Area', type: 'read', show: (p) => (p.closed && p.closed.value === true && !p.closed.varies ? p.area : undefined) },
      plain('closed', 'Closed', 'bool'),
      plain('elevation', 'Elevation'),
      fixed('vertices', 'Vertices'),
    ],
  },
  { kind: 'polyline3d', title: '3D Polyline', rows: [plain('closed', 'Closed', 'bool'), fixed('vertices', 'Vertices'), fixed('length', 'Length')] },
  { kind: 'spline', title: 'Spline', rows: [fixed('degree', 'Degree'), plain('closed', 'Closed', 'bool'), fixed('length', 'Length')] },
  { kind: 'point', title: 'Point', rows: [axis('px', 'Position X', 'position', 0), axis('py', 'Position Y', 'position', 1)] },
  { kind: 'ray', title: 'Ray', rows: [axis('bx', 'Base X', 'base', 0), axis('by', 'Base Y', 'base', 1)] },
  { kind: 'xline', title: 'Construction Line', rows: [axis('bx', 'Base X', 'base', 0), axis('by', 'Base Y', 'base', 1)] },
  {
    kind: 'text', title: 'Text',
    rows: [plain('text', 'Contents', 'text'), plain('height', 'Height'), plain('rotation', 'Rotation'), plain('width_factor', 'Width factor'), plain('style', 'Style', 'choice'), plain('oblique', 'Oblique'), axis('px', 'Position X', 'position', 0), axis('py', 'Position Y', 'position', 1)],
  },
  {
    kind: 'mtext', title: 'Multiline Text',
    rows: [plain('text', 'Contents', 'text'), plain('height', 'Text height'), plain('width', 'Defined width'), plain('rotation', 'Rotation'), plain('style', 'Style', 'choice'), axis('px', 'Position X', 'position', 0), axis('py', 'Position Y', 'position', 1)],
  },
  {
    kind: 'attdef', title: 'Attribute Definition',
    rows: [plain('tag', 'Tag', 'text'), plain('prompt', 'Prompt', 'text'), plain('default', 'Default', 'text'), plain('height', 'Height'), plain('rotation', 'Rotation'), plain('style', 'Style', 'choice'), axis('px', 'Position X', 'position', 0), axis('py', 'Position Y', 'position', 1)],
  },
  {
    kind: 'insert', title: 'Block Reference',
    rows: [
      fixed('block', 'Name', 'text'),
      { ...axis('px', 'Position X', 'position', 0), write: undefined, show: (p) => { const f = p.position; return f ? { value: Array.isArray(f.value) ? Number(f.value[0]) : null, varies: f.varies, type: 'number', readonly: true } : undefined; } },
      { ...axis('py', 'Position Y', 'position', 1), write: undefined, show: (p) => { const f = p.position; return f ? { value: Array.isArray(f.value) ? Number(f.value[1]) : null, varies: f.varies, type: 'number', readonly: true } : undefined; } },
      plain('rotation', 'Rotation'), plain('scale_x', 'Scale X'), plain('scale_y', 'Scale Y'), plain('scale_z', 'Scale Z'),
    ],
  },
  { kind: 'hatch', title: 'Hatch', rows: [plain('pattern', 'Pattern', 'text'), plain('pattern_scale', 'Scale'), plain('pattern_angle', 'Angle'), plain('solid', 'Solid', 'bool'), fixed('associative', 'Associative', 'bool')] },
  { kind: 'solid', title: '2D Solid', rows: [] },
  {
    kind: 'dimension', title: 'Dimension',
    rows: [plain('text_override', 'Text override', 'text'), plain('style', 'Dim style', 'text'), plain('text_height', 'Text height'), plain('arrow_size', 'Arrow size'), plain('scale', 'Dim scale overall'), plain('precision', 'Precision'), fixed('measurement', 'Measurement')],
  },
  { kind: 'helix', title: 'Helix', rows: [axis('cx', 'Center X', 'center', 0), axis('cy', 'Center Y', 'center', 1), plain('turns', 'Turns'), plain('height', 'Height'), plain('base_radius', 'Base radius'), plain('top_radius', 'Top radius')] },
  { kind: 'mline', title: 'Multiline', rows: [plain('scale', 'Scale'), plain('justification', 'Justification'), plain('closed', 'Closed', 'bool')] },
  { kind: 'wipeout', title: 'Wipeout', rows: [] },
  { kind: 'assoc_array', title: 'Associative Array', rows: arrayRows },
  {
    kind: 'leader', title: 'Leader',
    rows: [plain('arrowhead', 'Arrowhead', 'bool'), plain('spline', 'Spline', 'bool'), plain('arrow_size', 'Arrow size'), fixed('style', 'Style'), fixed('vertices', 'Vertices'), fixed('length', 'Length')],
  },
  {
    kind: 'mleader', title: 'Multileader',
    rows: [plain('text', 'Contents', 'text'), fixed('content_type', 'Content'), fixed('leader_type', 'Leader type'), fixed('style', 'Style'), fixed('leader_lines', 'Leader lines'), plain('size_scale', 'Scale'), axis('px', 'Content X', 'content_pos', 0), axis('py', 'Content Y', 'content_pos', 1)],
  },
  {
    kind: 'table', title: 'Table',
    rows: [axis('px', 'Position X', 'position', 0), axis('py', 'Position Y', 'position', 1), plain('rotation', 'Rotation'), fixed('style', 'Style'), fixed('table_rows', 'Rows'), fixed('table_columns', 'Columns'), fixed('table_width', 'Width')],
  },
  { kind: 'region', title: 'Region', rows: [] },
  { kind: 'viewport', title: 'Viewport', rows: [] },
];

export const KIND_BY_NAME = new Map(KINDS.map((k) => [k.kind, k]));

export function kindTitle(kind: string): string {
  const known = KIND_BY_NAME.get(kind);
  if (known) return known.title;
  const words = kind.replace(/[_-]+/g, ' ').trim();
  return words ? words.charAt(0).toUpperCase() + words.slice(1) : 'Object';
}

export const GENERAL: RowDef[] = [
  { id: 'color', label: 'Color', type: 'color', show: (p) => p.color, write: (v) => ({ color: v }) },
  plain('layer', 'Layer', 'choice'),
  plain('linetype', 'Linetype', 'choice'),
  plain('ltscale', 'Linetype scale'),
  plain('lineweight', 'Lineweight', 'lineweight'),
  plain('transparency', 'Transparency', 'text'),
  plain('thickness', 'Thickness'),
];

export const QUICK_GENERAL = ['color', 'layer', 'linetype'];

export const QUICK: Record<string, string[]> = {
  line: ['length', 'angle'],
  circle: ['cx', 'cy', 'radius', 'diameter', 'area'],
  arc: ['radius', 'start_angle', 'end_angle'],
  lwpolyline: ['length', 'area', 'const_width'],
  text: ['text', 'height', 'rotation'],
  mtext: ['text', 'height'],
  insert: ['block', 'rotation', 'scale_x'],
  dimension: ['text_override'],
};

export const QUICK_READONLY = new Set(['circle:area']);
