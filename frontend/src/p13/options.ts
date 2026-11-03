import { el, setText } from '../ui/dom';
import { t } from '../ui/i18n';
import { fieldForm, type FieldForm, type FieldSpec } from '../p12/fields';
import { fillSelect } from './kit';
import { optionSpecs } from './forms';
import type { Json, Rec } from './sim-store';

export interface OptionForm { el: HTMLElement; read(): Json; load(o: Json): void; refresh?(contacts: Rec[]): void }

const nz = (v: unknown): number | null => (typeof v === 'number' && Number.isFinite(v) ? v : null);
const obj = (v: unknown): Json => (v && typeof v === 'object' && !Array.isArray(v) ? v as Json : {});
const rd = (x: number): number => Number(x.toPrecision(10));
const scaled = (v: unknown, k: number): number | null => { const n = nz(v); return n === null ? null : rd(n * k); };
const unscaled = (v: unknown, k: number): number | null => { const n = nz(v); return n === null ? null : rd(n / k); };

function clean(o: unknown): unknown {
  if (Array.isArray(o)) return o;
  if (o && typeof o === 'object') {
    const out: Json = {};
    for (const [k, v] of Object.entries(o as Json)) {
      if (v === null || v === undefined || v === '' || (typeof v === 'number' && !Number.isFinite(v))) continue;
      const c = clean(v);
      if (c && typeof c === 'object' && !Array.isArray(c) && !Object.keys(c as Json).length) continue;
      out[k] = c;
    }
    return out;
  }
  return o;
}

const N = (name: string, label: string, unit?: string, extra: Partial<FieldSpec> = {}): FieldSpec => ({ name, type: 'number', label, unit: unit ?? null, nullable: true, ...extra });
const B = (name: string, label: string, def = false): FieldSpec => ({ name, type: 'bool', label, default: def });
const C = (name: string, label: string, choices: Array<[string, string]>, def?: string): FieldSpec => ({ name, type: 'choice', label, choices, default: def ?? choices[0][0] });
const note = (s: string): HTMLElement => { const p = el('<p class="u8-note sm-optnote"></p>'); setText(p, t(s)); return p; };
const group = (title: string): HTMLElement => { const h = el('<div class="cm-group"></div>'); setText(h, t(title)); return h; };

function frame(...parts: Array<HTMLElement | FieldForm>): HTMLElement {
  const root = el('<div class="sm-optform"></div>');
  for (const p of parts) root.appendChild(p instanceof HTMLElement ? p : p.el);
  return root;
}

const slotSpecs = (extra: FieldSpec[]): FieldSpec[] => [B('use', 'Use this entry'), ...extra];

const boxSpecs = (): FieldSpec[] => [N('x0', 'Corner x', 'mm', { default: 0 }), N('y0', 'Corner y', 'mm', { default: 0 }), N('z0', 'Corner z', 'mm', { default: 0 }), N('x1', 'Opposite x', 'mm', { default: 0 }), N('y1', 'Opposite y', 'mm', { default: 0 }), N('z1', 'Opposite z', 'mm', { default: 0 })];
const box = (v: Json): number[][] => [[Number(v.x0 ?? 0), Number(v.y0 ?? 0), Number(v.z0 ?? 0)], [Number(v.x1 ?? 0), Number(v.y1 ?? 0), Number(v.z1 ?? 0)]];
const boxForm = (b: unknown): Json => { const a = Array.isArray(b) ? b as number[][] : [[0, 0, 0], [0, 0, 0]]; return { x0: a[0]?.[0], y0: a[0]?.[1], z0: a[0]?.[2], x1: a[1]?.[0], y1: a[1]?.[1], z1: a[1]?.[2] }; };

function usable(f: FieldForm, extra: string[]): void {
  f.show(new Set(f.read().use === true ? ['use', ...extra] : ['use']));
}

function flowForm(): OptionForm {
  const vis = (): void => { f.show(new Set(['solver', 'density', 'viscosity', ...(f.read().solver === 'su2' ? ['iter'] : [])])); };
  const f = fieldForm([
    C('solver', 'Solver', [['own', 'Own Stokes solver'], ['su2', 'Optional CFD program']], 'own'),
    N('density', 'Fluid density', 'kg/m3', { min: 0 }),
    N('viscosity', 'Fluid viscosity', 'mPa s', { min: 0 }),
    N('iter', 'CFD program iterations', undefined, { min: 1 }),
  ], () => vis());
  return {
    el: frame(f, note('Creeping flow in a passage with flat inlet and outlet faces. No fluid table ships; enter the density and viscosity.')),
    read() { const v = f.read(); return clean({ solver: v.solver, fluid: { density: nz(v.density), viscosity: scaled(v.viscosity, 1e-3) }, su2_options: v.solver === 'su2' ? { ITER: nz(v.iter) } : {} }) as Json; },
    load(o) { const fl = obj(o.fluid); f.set({ solver: o.solver ?? 'own', density: fl.density ?? null, viscosity: unscaled(fl.viscosity, 1e-3), iter: obj(o.su2_options).ITER ?? null }); vis(); },
  };
}

const SRC_KEYS = ['name', 'x0', 'y0', 'z0', 'x1', 'y1', 'z1', 'power_w', 'k'];

function coolingForm(): OptionForm {
  const f = fieldForm([N('h', 'Film coefficient on exposed faces', 'W/m2K', { min: 0 }), N('t_amb', 'Ambient temperature', 'K', { default: 293.15, min: 0 })], () => undefined);
  const slots: FieldForm[] = [0, 1, 2].map((i) => fieldForm(slotSpecs([{ name: 'name', type: 'text', label: 'Name', default: `Part ${i + 1}` }, ...boxSpecs(), N('power_w', 'Heat output', 'W', { min: 0 }), N('k', 'Conductivity override', 'W/mK', { min: 0 })]), () => usable(slots[i], SRC_KEYS)));
  return {
    el: frame(f, group('Heat sources in boxes'), ...slots, note('A heat source is a box of the body that gives off the stated power.')),
    read() {
      const v = f.read();
      const sources = slots.map((s) => s.read()).filter((s) => s.use === true).map((s) => clean({ name: s.name, box: box(s), power_w: nz(s.power_w), k: nz(s.k) }));
      return clean({ h: nz(v.h), t_amb: nz(v.t_amb), sources: sources.length ? sources : undefined }) as Json;
    },
    load(o) {
      f.set({ h: o.h ?? null, t_amb: o.t_amb ?? 293.15 });
      const src = Array.isArray(o.sources) ? o.sources as Json[] : [];
      slots.forEach((s, i) => {
        const r = src[i];
        s.set(r ? { use: true, name: r.name ?? `Part ${i + 1}`, ...boxForm(r.box), power_w: r.power_w ?? null, k: r.k ?? null } : { use: false, name: `Part ${i + 1}`, ...boxForm(null), power_w: null, k: null });
        usable(s, SRC_KEYS);
      });
    },
  };
}

const PACK_KEYS = ['diffusivity', 't_melt', 't_mould', 't_freeze', 't_eject', 'thickness', 'gate_thickness'];

function fillOptionForm(): OptionForm {
  const polyVis = (): void => { poly.show(new Set(poly.read().model === 'power' ? ['model', 'k', 'n'] : ['model', 'eta'])); };
  const driveVis = (): void => { drive.show(new Set(['by', 'pressure_limit', drive.read().by === 'flow' ? 'flow' : 'fill_time'])); };
  const warpVis = (): void => { const v = warp.read(); warp.show(new Set(v.use === true ? ['use', 'by', ...(v.by === 'alpha' ? ['alpha', 'delta_t'] : ['delta_strain']), 'thickness', 'length'] : ['use'])); };
  const poly = fieldForm([C('model', 'Melt model', [['newtonian', 'Newtonian'], ['power', 'Power law']], 'newtonian'), N('eta', 'Viscosity', 'Pa s', { min: 0 }), N('k', 'Consistency', 'Pa s^n', { min: 0 }), N('n', 'Power law exponent', undefined, { min: 0.05, max: 1.5 })], () => polyVis());
  const drive = fieldForm([C('by', 'Drive the fill by', [['fill_time', 'Fill time'], ['flow', 'Flow rate']], 'fill_time'), N('fill_time', 'Fill time', 's', { min: 0 }), N('flow', 'Flow rate', 'cm3/s', { min: 0 }), N('pressure_limit', 'Pressure limit', 'MPa', { min: 0 })], () => driveVis());
  const pull = fieldForm([N('px', 'Mould opening direction x'), N('py', 'Mould opening direction y'), N('pz', 'Mould opening direction z')], () => undefined);
  const pack = fieldForm(slotSpecs([N('diffusivity', 'Thermal diffusivity', 'mm2/s', { min: 0 }), N('t_melt', 'Melt temperature', 'C'), N('t_mould', 'Mould temperature', 'C'), N('t_freeze', 'Freeze temperature', 'C'), N('t_eject', 'Ejection temperature', 'C'), N('thickness', 'Wall thickness', 'mm', { min: 0 }), N('gate_thickness', 'Gate thickness', 'mm', { min: 0 })]), () => usable(pack, PACK_KEYS));
  const warp = fieldForm(slotSpecs([C('by', 'Differential shrinkage given as', [['delta_strain', 'Strain difference'], ['alpha', 'Coefficient and temperature difference']], 'delta_strain'), N('delta_strain', 'Strain difference between faces'), N('alpha', 'Shrinkage coefficient', '1e-6/K'), N('delta_t', 'Mould half temperature difference', 'K'), N('thickness', 'Thickness', 'mm', { min: 0 }), N('length', 'Strip length', 'mm', { min: 0 })]), () => warpVis());
  return {
    el: frame(group('Melt'), poly, group('Filling'), drive, pull, group('Pack estimate'), pack, group('Warp estimate'), warp, note('Hele-Shaw estimate on a midplane of a thin walled part. Pressure and times are indicative.')),
    read() {
      const p = poly.read(), d = drive.read(), u = pull.read(), pk = pack.read(), w = warp.read();
      const pull3 = [nz(u.px), nz(u.py), nz(u.pz)];
      const o: Json = {
        polymer: p.model === 'power' ? { k: nz(p.k), n: nz(p.n) } : { eta: nz(p.eta) },
        fill_time: d.by === 'fill_time' ? nz(d.fill_time) : null,
        flow: d.by === 'flow' ? scaled(d.flow, 1e-6) : null,
        pressure_limit: scaled(d.pressure_limit, 1e6),
        pull: pull3.every((x) => x !== null) ? pull3 : null,
      };
      if (pk.use === true) o.pack = { diffusivity: scaled(pk.diffusivity, 1e-6), t_melt: nz(pk.t_melt), t_mould: nz(pk.t_mould), t_freeze: nz(pk.t_freeze), t_eject: nz(pk.t_eject), thickness: scaled(pk.thickness, 1e-3), gate_thickness: scaled(pk.gate_thickness, 1e-3) };
      if (w.use === true) o.warp = w.by === 'alpha' ? { alpha: scaled(w.alpha, 1e-6), delta_t: nz(w.delta_t), thickness: scaled(w.thickness, 1e-3), length: scaled(w.length, 1e-3) } : { delta_strain: nz(w.delta_strain), thickness: scaled(w.thickness, 1e-3), length: scaled(w.length, 1e-3) };
      return clean(o) as Json;
    },
    load(o) {
      const py = obj(o.polymer);
      poly.set({ model: py.k !== undefined || py.n !== undefined ? 'power' : 'newtonian', eta: py.eta ?? null, k: py.k ?? null, n: py.n ?? null });
      drive.set({ by: o.flow !== undefined && o.flow !== null ? 'flow' : 'fill_time', fill_time: o.fill_time ?? null, flow: unscaled(o.flow, 1e-6), pressure_limit: unscaled(o.pressure_limit, 1e6) });
      const pl = Array.isArray(o.pull) ? o.pull as number[] : [];
      pull.set({ px: pl[0] ?? null, py: pl[1] ?? null, pz: pl[2] ?? null });
      const pk = obj(o.pack), w = obj(o.warp);
      pack.set({ use: Object.keys(pk).length > 0, diffusivity: unscaled(pk.diffusivity, 1e-6), t_melt: pk.t_melt ?? null, t_mould: pk.t_mould ?? null, t_freeze: pk.t_freeze ?? null, t_eject: pk.t_eject ?? null, thickness: unscaled(pk.thickness, 1e-3), gate_thickness: unscaled(pk.gate_thickness, 1e-3) });
      warp.set({ use: Object.keys(w).length > 0, by: w.alpha !== undefined ? 'alpha' : 'delta_strain', delta_strain: w.delta_strain ?? null, alpha: unscaled(w.alpha, 1e-6), delta_t: w.delta_t ?? null, thickness: unscaled(w.thickness, 1e-3), length: unscaled(w.length, 1e-3) });
      polyVis(); driveVis(); usable(pack, PACK_KEYS); warpVis();
    },
  };
}

function fatigueForm(): OptionForm {
  const vis = (): void => { const ref = f.read().kind !== 'basquin'; f.show(new Set(['kind', ...(ref ? ['cycles', 'amplitude'] : ['C']), 'b', 'endurance', 'corr', 'history', 'stress_ratio', 'max_scale'])); };
  const f = fieldForm([
    C('kind', 'S-N curve given as', [['reference', 'One reference point and slope'], ['basquin', 'Basquin constants']], 'reference'),
    N('cycles', 'Reference cycles', undefined, { default: 1e6, min: 1 }),
    N('amplitude', 'Amplitude at the reference', 'MPa', { default: 250, min: 0 }),
    N('C', 'Basquin strength coefficient', 'MPa', { min: 0 }),
    N('b', 'Basquin exponent', undefined, { default: -0.09, max: 0 }),
    N('endurance', 'Endurance limit', 'MPa', { min: 0 }),
    C('corr', 'Mean stress correction', [['goodman', 'Goodman'], ['gerber', 'Gerber'], ['soderberg', 'Soderberg'], ['none', 'None']], 'goodman'),
    { name: 'history', type: 'text', label: 'Load history (multipliers at the turning points, separated by commas)' },
    N('stress_ratio', 'Stress ratio when there is no history', undefined, { default: 0, min: -1, max: 0.99 }),
    N('max_scale', 'Peak multiplier when there is no history', undefined, { default: 1, min: 0 }),
  ], () => vis());
  return {
    el: frame(f, note('No S-N data ships; enter your own. The reference load of the study has multiplier 1.')),
    read() {
      const v = f.read();
      const sn: Json = v.kind === 'basquin' ? { C: scaled(v.C, 1e6), b: nz(v.b) } : { reference: { cycles: nz(v.cycles), amplitude: scaled(v.amplitude, 1e6), b: nz(v.b) } };
      const hist = String(v.history ?? '').split(/[\s,;]+/).filter(Boolean).map(Number).filter(Number.isFinite);
      return clean({ sn: { ...sn, endurance_limit: scaled(v.endurance, 1e6) }, mean_stress_correction: v.corr, history: hist.length ? hist : undefined, stress_ratio: hist.length ? undefined : nz(v.stress_ratio), max_scale: hist.length ? undefined : nz(v.max_scale) }) as Json;
    },
    load(o) {
      const sn = obj(o.sn), ref = obj(sn.reference);
      f.set({
        kind: sn.C !== undefined ? 'basquin' : 'reference', cycles: ref.cycles ?? 1e6, amplitude: unscaled(ref.amplitude, 1e6) ?? 250, C: unscaled(sn.C, 1e6), b: ref.b ?? sn.b ?? -0.09, endurance: unscaled(sn.endurance_limit, 1e6),
        corr: o.mean_stress_correction ?? 'goodman', history: Array.isArray(o.history) ? (o.history as number[]).join(', ') : '', stress_ratio: o.stress_ratio ?? 0, max_scale: o.max_scale ?? 1,
      });
      vis();
    },
  };
}

const PLANE_KEYS = ['contact', 'px', 'py', 'pz', 'nx', 'ny', 'nz'];

function planeSlot(): { form: FieldForm; get(): Json | null; set(p: Json | null): void; contacts(c: Rec[]): void } {
  const form = fieldForm(slotSpecs([{ name: 'contact', type: 'choice', label: 'Contact record', choices: [['', '-']], default: '' }, N('px', 'Plane point x', 'mm', { default: 0 }), N('py', 'Plane point y', 'mm', { default: 0 }), N('pz', 'Plane point z', 'mm', { default: 0 }), N('nx', 'Plane normal x', undefined, { default: 0 }), N('ny', 'Plane normal y', undefined, { default: 0 }), N('nz', 'Plane normal z', undefined, { default: 1 })]), () => usable(form, PLANE_KEYS));
  let last = '';
  return {
    form,
    get() { const v = form.read(); if (v.use !== true || !v.contact) return null; return { contact: String(v.contact), point_mm: [Number(v.px ?? 0), Number(v.py ?? 0), Number(v.pz ?? 0)], normal: [Number(v.nx ?? 0), Number(v.ny ?? 0), Number(v.nz ?? 1)] }; },
    set(p) {
      const pt = Array.isArray(p?.point_mm) ? p?.point_mm as number[] : [0, 0, 0], nm = Array.isArray(p?.normal) ? p?.normal as number[] : [0, 0, 1];
      form.set({ use: !!p, contact: p?.contact ?? '', px: pt[0], py: pt[1], pz: pt[2], nx: nm[0], ny: nm[1], nz: nm[2] });
      usable(form, PLANE_KEYS);
    },
    contacts(c) {
      const sig = c.map((r) => r.id).join(',');
      if (sig === last) return;
      last = sig;
      const sel = form.rowOf('contact')?.querySelector('select');
      if (sel) { const cur = sel.value; fillSelect(sel, [['', '-'], ...c.map((r) => [r.id, String(r.label || r.name || r.id)] as [string, string])]); sel.value = cur; }
    },
  };
}

function genericForm(raw: unknown, extras: { vector?: boolean; planes?: boolean }): OptionForm {
  const f = fieldForm(optionSpecs(raw), () => undefined);
  const vec = fieldForm([N('vx', 'Initial velocity x', 'm/s', { default: 0 }), N('vy', 'Initial velocity y', 'm/s', { default: 0 }), N('vz', 'Initial velocity z', 'm/s', { default: 0 })], () => undefined);
  const plane = planeSlot();
  return {
    el: frame(f, ...(extras.vector ? [vec] : []), ...(extras.planes ? [group('Rigid plane for contact'), plane.form] : [])),
    read() {
      const o = f.read();
      if (extras.vector) { const v = vec.read(); const a = [nz(v.vx), nz(v.vy), nz(v.vz)]; if (a.some((x) => x)) o.velocity = a.map((x) => x ?? 0); }
      if (extras.planes) { const p = plane.get(); if (p) o.rigid_planes = [p]; }
      return clean(o) as Json;
    },
    load(o) {
      f.set(o);
      if (extras.vector) { const v = Array.isArray(o.velocity) ? o.velocity as number[] : [0, 0, 0]; vec.set({ vx: v[0], vy: v[1], vz: v[2] }); }
      if (extras.planes) plane.set(Array.isArray(o.rigid_planes) && o.rigid_planes.length ? o.rigid_planes[0] as Json : null);
    },
    refresh: extras.planes ? (c) => plane.contacts(c) : undefined,
  };
}

const REGION_KEYS = ['x0', 'y0', 'z0', 'x1', 'y1', 'z1'];

function regionSlot(label: string): { form: FieldForm; get(): Json | null; set(r: unknown): void } {
  const form = fieldForm(slotSpecs(boxSpecs().map((s, i) => ({ ...s, label: `${label} ${i < 3 ? 'minimum' : 'maximum'} ${'xyz'[i % 3]}` }))), () => usable(form, REGION_KEYS));
  return {
    form,
    get() {
      const v = form.read();
      if (v.use !== true) return null;
      const b = box(v);
      return { kind: 'box', min: [0, 1, 2].map((i) => Math.min(b[0][i], b[1][i])), max: [0, 1, 2].map((i) => Math.max(b[0][i], b[1][i])) };
    },
    set(r) {
      const o = Array.isArray(r) ? obj(r[0]) : {};
      const has = o.kind === 'box';
      form.set({ use: has, ...boxForm(has ? [o.min, o.max] : null) });
      usable(form, REGION_KEYS);
    },
  };
}

function topologyForm(): OptionForm {
  const f = fieldForm([
    N('reduction', 'Mass to remove', '%', { default: 50, min: 2, max: 95 }),
    N('stress_limit_mpa', 'Stress limit', 'MPa', { min: 0 }),
    N('safety_factor', 'Safety factor on yield', undefined, { default: 1.5, min: 1 }),
    { name: 'cells', type: 'int', label: 'Design cells', default: 3000, min: 100, nullable: true },
    N('cell_mm', 'Cell size (overrides the count)', 'mm', { min: 0 }),
    B('sx', 'Mirror in x'), B('sy', 'Mirror in y'), B('sz', 'Mirror in z'),
    C('extrusion', 'Keep the section constant along', [['', 'No axis'], ['x', 'x'], ['y', 'y'], ['z', 'z']], ''),
    N('penalty', 'Stiffness penalty', undefined, { default: 3, min: 1, max: 6 }),
    N('radius_cells', 'Filter radius', 'cells', { default: 1.5, min: 1, max: 8 }),
    { name: 'iterations', type: 'int', label: 'Iterations per pass', default: 100, min: 1, max: 1000, nullable: true },
    { name: 'max_outer', type: 'int', label: 'Passes with the stress check', default: 6, min: 1, max: 8, nullable: true },
    B('projection', 'Sharpen to solid and void', true), B('auto_preserve', 'Keep cells at loads and fixtures solid', true),
  ], () => undefined);
  const keep = regionSlot('Keep solid'), skip = regionSlot('Keep empty');
  return {
    el: frame(f, group('Regions'), keep.form, skip.form, note('The outcome is checked against the stress limit and re-solved when it is exceeded.')),
    read() {
      const v = f.read();
      const sym = ['x', 'y', 'z'].filter((a) => v[`s${a}`] === true);
      const p = keep.get(), s = skip.get();
      return clean({
        reduction: scaled(v.reduction, 0.01), stress_limit_mpa: nz(v.stress_limit_mpa), safety_factor: nz(v.safety_factor), cells: nz(v.cells), cell_mm: nz(v.cell_mm), symmetry: sym.length ? sym : undefined,
        extrusion: v.extrusion || undefined, penalty: nz(v.penalty), radius_cells: nz(v.radius_cells), iterations: nz(v.iterations), max_outer: nz(v.max_outer), projection: v.projection === true, auto_preserve: v.auto_preserve === true,
        preserve: p ? [p] : undefined, obstacles: s ? [s] : undefined,
      }) as Json;
    },
    load(o) {
      const sym = Array.isArray(o.symmetry) ? o.symmetry as string[] : [];
      f.set({ reduction: unscaled(o.reduction, 0.01) ?? 50, stress_limit_mpa: o.stress_limit_mpa ?? null, safety_factor: o.safety_factor ?? 1.5, cells: o.cells ?? 3000, cell_mm: o.cell_mm ?? null, sx: sym.includes('x'), sy: sym.includes('y'), sz: sym.includes('z'), extrusion: o.extrusion ?? '', penalty: o.penalty ?? 3, radius_cells: o.radius_cells ?? 1.5, iterations: o.iterations ?? 100, max_outer: o.max_outer ?? 6, projection: o.projection !== false, auto_preserve: o.auto_preserve !== false });
      keep.set(o.preserve);
      skip.set(o.obstacles);
    },
  };
}

const VAR_KEYS = ['param', 'min', 'max'];

function shapeForm(): OptionForm {
  const f = fieldForm([C('objective', 'Minimise', [['mass', 'Mass'], ['compliance', 'Compliance']], 'mass'), N('stress_limit_mpa', 'Stress limit', 'MPa', { min: 0 }), { name: 'cells', type: 'int', label: 'Analysis cells', default: 1500, min: 100, nullable: true }, { name: 'evaluations', type: 'int', label: 'Most candidates to try', default: 40, min: 4, nullable: true }], () => undefined);
  const slots: FieldForm[] = [0, 1, 2].map((i) => fieldForm(slotSpecs([{ name: 'param', type: 'text', label: 'Document parameter' }, N('min', 'Smallest value'), N('max', 'Largest value')]), () => usable(slots[i], VAR_KEYS)));
  return {
    el: frame(f, group('Parameters to vary'), ...slots),
    read() {
      const v = f.read();
      const vars = slots.map((s) => s.read()).filter((s) => s.use === true && s.param).map((s) => ({ param: String(s.param), min: nz(s.min), max: nz(s.max) }));
      return clean({ objective: v.objective, stress_limit_mpa: nz(v.stress_limit_mpa), cells: nz(v.cells), evaluations: nz(v.evaluations), variables: vars.length ? vars : undefined }) as Json;
    },
    load(o) {
      f.set({ objective: o.objective ?? 'mass', stress_limit_mpa: o.stress_limit_mpa ?? null, cells: o.cells ?? 1500, evaluations: o.evaluations ?? 40 });
      const vs = Array.isArray(o.variables) ? o.variables as Json[] : [];
      slots.forEach((s, i) => { const r = vs[i]; s.set({ use: !!r, param: r?.param ?? '', min: r?.min ?? null, max: r?.max ?? null }); usable(s, VAR_KEYS); });
    },
  };
}

export function optionForm(type: string, raw: unknown): OptionForm {
  switch (type) {
    case 'flow': return flowForm();
    case 'cooling': return coolingForm();
    case 'fill': return fillOptionForm();
    case 'fatigue': return fatigueForm();
    case 'topology': return topologyForm();
    case 'shape': return shapeForm();
    case 'nonlinear_static': case 'event_quasistatic': return genericForm(raw, { planes: true });
    case 'event_explicit': return genericForm(raw, { vector: true, planes: true });
    default: return genericForm(raw, {});
  }
}
