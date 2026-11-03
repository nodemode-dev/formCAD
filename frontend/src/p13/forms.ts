import { el, q, setText } from '../ui/dom';
import { t } from '../ui/i18n';
import { button } from '../u8/ui';
import { fieldForm, type FieldForm, type FieldSpec } from '../p12/fields';
import type { Json, Rec } from './sim-store';

export const LOAD_TYPES: Array<[string, string]> = [
  ['force', 'Force'], ['pressure', 'Pressure'], ['traction', 'Traction'], ['gravity', 'Gravity'], ['heat_flux', 'Heat flux'],
  ['convection', 'Convection'], ['heat_load', 'Heat load'], ['temperature_field', 'Temperature field'], ['reference_load', 'Reference load for buckling'],
  ['flow_inlet', 'Flow inlet'], ['flow_outlet', 'Flow outlet'], ['injection_gate', 'Injection gate'],
];
export const FIXTURE_TYPES: Array<[string, string]> = [['fixed', 'Fixed'], ['roller', 'Roller'], ['symmetry', 'Symmetry'], ['displacement', 'Prescribed displacement'], ['temperature', 'Temperature']];
export const CONTACT_TYPES: Array<[string, string]> = [['bonded', 'Bonded'], ['frictionless', 'Frictionless'], ['frictional', 'Frictional']];

const dir = (): FieldSpec[] => [
  { name: 'dx', type: 'number', label: 'Direction x', default: 0 },
  { name: 'dy', type: 'number', label: 'Direction y', default: 0 },
  { name: 'dz', type: 'number', label: 'Direction z', default: -1 },
];
const axis = [['x', 'x'], ['y', 'y'], ['z', 'z']];

export const LOAD_SPECS: Record<string, FieldSpec[]> = {
  force: [{ name: 'value', type: 'number', label: 'Total force', unit: 'N', default: 100, nullable: false }, ...dir()],
  pressure: [{ name: 'value', type: 'number', label: 'Pressure', unit: 'MPa', default: 1 }],
  traction: [{ name: 'tx', type: 'number', label: 'Traction x', unit: 'MPa', default: 0 }, { name: 'ty', type: 'number', label: 'Traction y', unit: 'MPa', default: 0 }, { name: 'tz', type: 'number', label: 'Traction z', unit: 'MPa', default: 0 }],
  gravity: [{ name: 'value', type: 'number', label: 'Acceleration', unit: 'm/s2', default: 9.81 }, ...dir()],
  heat_flux: [{ name: 'value', type: 'number', label: 'Heat flux', unit: 'W/m2', default: 1000 }],
  convection: [{ name: 'h', type: 'number', label: 'Film coefficient', unit: 'W/m2K', default: 10, min: 0 }, { name: 't_inf', type: 'number', label: 'Ambient temperature', unit: 'K', default: 293.15, min: 0 }],
  heat_load: [{ name: 'value', type: 'number', label: 'Heat in the body', unit: 'W', default: 10 }],
  temperature_field: [{ name: 'value', type: 'number', label: 'Uniform temperature', unit: 'K', default: 343.15, min: 0 }],
  reference_load: [{ name: 'value', type: 'number', label: 'Reference force', unit: 'N', default: 1 }, ...dir()],
  flow_inlet: [
    { name: 'by', type: 'choice', label: 'Give the inlet as', choices: [['speed', 'Mean speed'], ['flow', 'Volume flow']], default: 'speed' },
    { name: 'speed', type: 'number', label: 'Mean speed', unit: 'm/s', default: 0.05, min: 0 },
    { name: 'flow_lpm', type: 'number', label: 'Volume flow', unit: 'L/min', default: 1, min: 0 },
  ],
  flow_outlet: [{ name: 'value', type: 'number', label: 'Outlet pressure', unit: 'Pa', default: 0 }],
  injection_gate: [],
};

export const FIXTURE_SPECS: Record<string, FieldSpec[]> = {
  fixed: [],
  roller: [{ name: 'free_x', type: 'bool', label: 'Free in x', default: false }, { name: 'free_y', type: 'bool', label: 'Free in y', default: true }, { name: 'free_z', type: 'bool', label: 'Free in z', default: false }],
  symmetry: [{ name: 'axis', type: 'choice', label: 'Mirror axis', choices: axis, default: 'x' }],
  displacement: [
    { name: 'ux', type: 'number', label: 'Move x (empty is free)', unit: 'mm', nullable: true },
    { name: 'uy', type: 'number', label: 'Move y (empty is free)', unit: 'mm', nullable: true },
    { name: 'uz', type: 'number', label: 'Move z (empty is free)', unit: 'mm', nullable: true },
  ],
  temperature: [{ name: 'value', type: 'number', label: 'Temperature', unit: 'K', default: 293.15, min: 0 }],
};

export const CONTACT_SPECS: FieldSpec[] = [
  { name: 'friction', type: 'number', label: 'Friction coefficient', default: 0.2, min: 0, max: 2 },
];

export const CONTROL_SPECS: FieldSpec[] = [
  { name: 'maxh_mm', type: 'number', label: 'Element size on these faces', unit: 'mm', default: 2, min: 0.001 },
];

export const MATERIAL_SPECS: FieldSpec[] = [
  { name: 'name', type: 'text', label: 'Name' },
  { name: 'rho', type: 'number', label: 'Density', unit: 'kg/m3', min: 0, nullable: true },
  { name: 'E', type: 'number', label: 'Young modulus', unit: 'GPa', min: 0, nullable: true },
  { name: 'nu', type: 'number', label: 'Poisson ratio', min: 0, max: 0.5, nullable: true },
  { name: 'sigma_y', type: 'number', label: 'Yield strength', unit: 'MPa', min: 0, nullable: true },
  { name: 'sigma_u', type: 'number', label: 'Ultimate strength', unit: 'MPa', min: 0, nullable: true },
  { name: 'k', type: 'number', label: 'Conductivity', unit: 'W/mK', min: 0, nullable: true },
  { name: 'alpha', type: 'number', label: 'Expansion', unit: '1e-6/K', nullable: true },
  { name: 'cp', type: 'number', label: 'Specific heat', unit: 'J/kgK', min: 0, nullable: true },
];

const MAT_SCALE: Record<string, number> = { E: 1e9, sigma_y: 1e6, sigma_u: 1e6, alpha: 1e-6 };
const nz = (v: unknown): number | null => (typeof v === 'number' && Number.isFinite(v) ? v : null);
const rd = (x: number): number => Number(x.toPrecision(10));

export function materialToForm(r: Rec): Json {
  const o: Json = { name: r.name ?? '' };
  for (const k of ['rho', 'nu', 'k', 'cp']) o[k] = nz(r[k]);
  for (const [k, s] of Object.entries(MAT_SCALE)) { const v = nz(r[k]); o[k] = v === null ? null : rd(v / s); }
  return o;
}

export function materialFromForm(v: Json): Json {
  const o: Json = { name: String(v.name ?? '') };
  for (const k of ['rho', 'nu', 'k', 'cp']) o[k] = nz(v[k]);
  for (const [k, s] of Object.entries(MAT_SCALE)) { const x = nz(v[k]); o[k] = x === null ? null : rd(x * s); }
  return o;
}

export function loadToForm(r: Rec): Json {
  const type = String(r.type ?? 'force');
  const d = Array.isArray(r.direction) ? r.direction as number[] : [0, 0, -1];
  const o: Json = { dx: d[0] ?? 0, dy: d[1] ?? 0, dz: d[2] ?? 0 };
  if (type === 'pressure') o.value = nz(r.value) === null ? null : rd((r.value as number) / 1e6);
  else if (type === 'traction') { const v = Array.isArray(r.vector) ? r.vector as number[] : [0, 0, 0]; o.tx = rd((v[0] ?? 0) / 1e6); o.ty = rd((v[1] ?? 0) / 1e6); o.tz = rd((v[2] ?? 0) / 1e6); }
  else if (type === 'convection') { o.h = r.h ?? null; o.t_inf = r.t_inf ?? null; }
  else if (type === 'flow_inlet') { o.by = nz(r.flow) !== null ? 'flow' : 'speed'; o.speed = nz(r.speed) ?? 0.05; o.flow_lpm = nz(r.flow) === null ? 1 : rd((r.flow as number) * 6e4); }
  else if (type === 'injection_gate') o.value = null;
  else o.value = r.value ?? null;
  return o;
}

export function loadFromForm(type: string, v: Json): Json {
  const out: Json = { type };
  const d = [Number(v.dx ?? 0), Number(v.dy ?? 0), Number(v.dz ?? 0)];
  if (type === 'pressure') out.value = rd(Number(v.value ?? 0) * 1e6);
  else if (type === 'traction') out.vector = [Number(v.tx ?? 0) * 1e6, Number(v.ty ?? 0) * 1e6, Number(v.tz ?? 0) * 1e6];
  else if (type === 'convection') { out.h = v.h; out.t_inf = v.t_inf; }
  else if (type === 'flow_inlet') { const byFlow = v.by === 'flow'; out.speed = byFlow ? null : v.speed; out.flow = byFlow ? rd(Number(v.flow_lpm ?? 0) / 6e4) : null; }
  else if (type === 'injection_gate') return out;
  else out.value = v.value;
  if (['force', 'gravity', 'reference_load'].includes(type)) out.direction = d;
  return out;
}

export function fixtureToForm(r: Rec): Json {
  const type = String(r.type ?? 'fixed');
  if (type === 'roller') { const a = Array.isArray(r.axes) ? r.axes as number[] : [1]; return { free_x: a.includes(0), free_y: a.includes(1), free_z: a.includes(2) }; }
  if (type === 'symmetry') return { axis: ['x', 'y', 'z'][Number(r.axis ?? 0)] ?? 'x' };
  if (type === 'displacement') {
    const comps = Array.isArray(r.components) ? r.components as number[] : [1, 1, 1];
    const val = Array.isArray(r.value) ? r.value as number[] : [];
    const at = (i: number): number | null => (comps[i] && nz(val[i]) !== null ? rd((val[i]) * 1e3) : null);
    return { ux: at(0), uy: at(1), uz: at(2) };
  }
  if (type === 'temperature') return { value: r.value ?? null };
  return {};
}

export function fixtureFromForm(type: string, v: Json): Json {
  const out: Json = { type };
  if (type === 'roller') out.axes = [v.free_x ? 0 : -1, v.free_y ? 1 : -1, v.free_z ? 2 : -1].filter((i) => i >= 0);
  else if (type === 'symmetry') out.axis = Math.max(0, ['x', 'y', 'z'].indexOf(String(v.axis)));
  else if (type === 'displacement') {
    const raw = [v.ux, v.uy, v.uz].map(nz);
    out.components = raw.map((x) => (x === null ? 0 : 1));
    out.value = raw.map((x) => (x === null ? 0 : x / 1e3));
  } else if (type === 'temperature') out.value = v.value;
  return out;
}

export interface SelectorEditor { el: HTMLElement; get(): Json | null; set(sel: unknown): void; onChange(fn: () => void): void; summary(): string }

const KINDS: Array<[string, string]> = [['faces', 'Picked faces'], ['all', 'All faces'], ['plane', 'On a plane'], ['box', 'Inside a box'], ['point', 'Nearest to a point']];

export function selectorEditor(label: string, picked: () => number[]): SelectorEditor {
  const root = el('<div class="sm-sel"><label class="cv-field"><span></span><select class="cv-input"></select></label></div>');
  setText(q(root, 'span'), t(label));
  const sel = q<HTMLSelectElement>(root, 'select');
  for (const [v, l] of KINDS) { const o = document.createElement('option'); o.value = v; o.textContent = t(l); sel.appendChild(o); }
  const faces = fieldForm([{ name: 'faces', type: 'text', label: 'Face numbers' }], () => fire());
  const plane = fieldForm([{ name: 'axis', type: 'choice', label: 'Plane normal', choices: axis, default: 'x' }, { name: 'value', type: 'number', label: 'Position', unit: 'mm', default: 0 }, { name: 'tol', type: 'number', label: 'Tolerance', unit: 'mm', default: 0.01, min: 0 }], () => fire());
  const box = fieldForm(['x0', 'y0', 'z0', 'x1', 'y1', 'z1'].map((n) => ({ name: n, type: 'number', label: `Corner ${n}`, unit: 'mm', default: 0 })), () => fire());
  const point = fieldForm([{ name: 'px', type: 'number', label: 'x', unit: 'mm', default: 0 }, { name: 'py', type: 'number', label: 'y', unit: 'mm', default: 0 }, { name: 'pz', type: 'number', label: 'z', unit: 'mm', default: 0 }], () => fire());
  const from = button('Use the picked faces', () => { faces.set({ faces: picked().join(', ') }); fire(); });
  const parts: Record<string, HTMLElement[]> = { faces: [faces.el, from], plane: [plane.el], box: [box.el], point: [point.el], all: [] };
  const holder = el('<div class="sm-sel-body"></div>');
  const all = [faces.el, from, plane.el, box.el, point.el];
  holder.append(...all);
  root.appendChild(holder);
  let cb = (): void => undefined;
  function show(): void { const on = new Set(parts[sel.value] ?? []); for (const n of all) n.hidden = !on.has(n); }
  function fire(): void { cb(); }
  sel.addEventListener('change', () => { show(); fire(); });
  show();
  const num = (f: FieldForm, n: string): number => Number(f.read()[n] ?? 0);
  return {
    el: root,
    onChange(fn) { cb = fn; },
    get() {
      switch (sel.value) {
        case 'all': return { all: true };
        case 'plane': return { plane: { axis: String(plane.read().axis ?? 'x'), value: num(plane, 'value'), tol: num(plane, 'tol') || 0.01 } };
        case 'box': return { box: [[num(box, 'x0'), num(box, 'y0'), num(box, 'z0')], [num(box, 'x1'), num(box, 'y1'), num(box, 'z1')]], tol: 0.01 };
        case 'point': return { point: [num(point, 'px'), num(point, 'py'), num(point, 'pz')] };
        default: {
          const list = String(faces.read().faces ?? '').split(/[\s,]+/).filter(Boolean).map(Number).filter((n) => Number.isInteger(n) && n >= 0);
          return list.length ? { faces: list } : null;
        }
      }
    },
    set(s) {
      const o = (s && typeof s === 'object' ? s : {}) as Json;
      if (Array.isArray(o.faces)) { sel.value = 'faces'; faces.set({ faces: (o.faces as number[]).join(', ') }); }
      else if (o.all) sel.value = 'all';
      else if (o.plane && typeof o.plane === 'object') { sel.value = 'plane'; plane.set(o.plane as Json); }
      else if (Array.isArray(o.box)) { sel.value = 'box'; const b = o.box as number[][]; box.set({ x0: b[0][0], y0: b[0][1], z0: b[0][2], x1: b[1][0], y1: b[1][1], z1: b[1][2] }); }
      else if (Array.isArray(o.point)) { sel.value = 'point'; const p = o.point as number[]; point.set({ px: p[0], py: p[1], pz: p[2] }); }
      else { sel.value = 'faces'; faces.set({ faces: '' }); }
      show();
    },
    summary() { const g = this.get(); return g ? (g.faces ? `${(g.faces as number[]).length} faces` : g.all ? 'all faces' : g.plane ? 'plane' : g.box ? 'box' : 'point') : 'nothing picked'; },
  };
}

const TYPE_MAP: Record<string, string> = { float: 'number', double: 'number', number: 'number', integer: 'int', int: 'int', boolean: 'bool', bool: 'bool', enum: 'choice', choice: 'choice', string: 'text', text: 'text' };

export function optionSpecs(raw: unknown): FieldSpec[] {
  const out: FieldSpec[] = [];
  const add = (name: string, o: unknown): void => {
    const d = (o && typeof o === 'object' && !Array.isArray(o) ? o : { default: o }) as Json;
    const def = d.default;
    if (typeof d.type === 'string' && ['list', 'object', 'vector'].includes(d.type)) return;
    const declared = typeof d.type === 'string' ? TYPE_MAP[d.type] : undefined;
    const whole = typeof def === 'number' && Number.isInteger(def) && (d.min === undefined || Number.isInteger(d.min));
    const type = d.choices ? 'choice' : declared ?? (typeof def === 'boolean' ? 'bool' : whole ? 'int' : typeof def === 'number' ? 'number' : 'text');
    if (def !== null && typeof def === 'object') return;
    out.push({ name, type, label: typeof d.label === 'string' ? d.label : undefined, unit: typeof d.unit === 'string' ? d.unit : null, min: typeof d.min === 'number' ? d.min : null, max: typeof d.max === 'number' ? d.max : null, choices: d.choices, default: def, nullable: true });
  };
  if (Array.isArray(raw)) for (const r of raw) { const o = r as Json; if (o && typeof o.name === 'string') add(o.name, o); }
  else if (raw && typeof raw === 'object') for (const [k, v] of Object.entries(raw as Json)) add(k, v);
  return out;
}
