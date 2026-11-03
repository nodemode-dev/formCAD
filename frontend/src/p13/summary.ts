import { SI } from './kit';
import type { Json } from './sim-store';

export interface Curve { id: string; label: string; xLabel: string; yLabel: string; points: Array<[number, number]> }

const PRIORITY = [
  'pressure_drop', 'inlet_pressure', 'outlet_pressure', 'mean_speed', 'flow_rate', 'reynolds', 'hydraulic_diameter', 'length',
  'max_temperature_k', 'min_temperature_k', 'total_power_w', 'heat_input_w', 'convected_w', 'energy_balance_error_w', 'thermal_resistance_k_per_w',
  'fill_time_s', 'peak_pressure_pa', 'closing_pressure_pa', 'clamp_force_n', 'thickness_min_m', 'thickness_max_m',
  'max_displacement_m', 'max_von_mises_pa', 'max_plastic_strain', 'yielded_fraction', 'reached_load_factor', 'limit_load_factor', 'newton_iterations',
  'time_step_s', 'steps', 'peak_contact_force_n', 'contact_impulse_ns',
  'min_life_repeats', 'min_life_cycles', 'cycles_per_repeat',
  'target_reduction', 'reduction', 'met_target', 'met_stress', 'stress_limit_mpa', 'peak_stress_before_mpa', 'peak_stress_after_mpa', 'initial_mass_kg', 'final_mass_kg',
  'frequency_hz', 'load_factor', 'unknowns', 'seconds', 'solver', 'model',
];
const SKIP = new Set(['history', 'cycle_table', 'outer_attempts', 'sources', 'grid', 'size', 'counts', 'mesh', 'label', 'warnings', 'notes', 'last_filled_mm', 'stress_basis']);

const nice = (k: string): string => {
  const u = NAMED[k] ? undefined : SUFFIX.find(([s]) => k.endsWith(s));
  return (u ? k.slice(0, -u[0].length) : k).replace(/_/g, ' ');
};

const NAMED: Record<string, string> = { pressure_drop: 'Pa', inlet_pressure: 'Pa', outlet_pressure: 'Pa', mean_speed: 'm/s', flow_rate: 'm3/s', hydraulic_diameter: 'm', length: 'm', diameter: 'm', seconds: 's', delta_t: 'K', gate_freeze_time: 's', cooling_time: 's', deflection: 'm', radius: 'm', curvature: '1/m' };
const SUFFIX: Array<[string, string]> = [['_m_s', 'm/s'], ['_m3_s', 'm3/s'], ['_ns', 'N s'], ['_mpa', 'MPa'], ['_pa', 'Pa'], ['_hz', 'Hz'], ['_kg', 'kg'], ['_mm3', 'mm3'], ['_mm', 'mm'], ['_k', 'K'], ['_w', 'W'], ['_n', 'N'], ['_s', 's'], ['_m', 'm'], ['_j', 'J']];
const unitOf = (k: string): string => NAMED[k] ?? SUFFIX.find(([s]) => k.endsWith(s))?.[1] ?? '';

function scalar(v: unknown, key = ''): string | null {
  if (typeof v === 'number') return SI(v, unitOf(key));
  if (typeof v === 'boolean') return v ? 'yes' : 'no';
  if (typeof v === 'string') return v.length > 90 ? `${v.slice(0, 88)}..` : v;
  if (Array.isArray(v) && v.length <= 4 && v.every((x) => typeof x === 'number')) return (v as number[]).map((x) => SI(x, '')).join(' ');
  return null;
}

export function summaryLines(sm: Json, limit: number): string[] {
  const out: string[] = [];
  const seen = new Set<string>();
  const add = (k: string, v: unknown, pre = ''): void => {
    const s = scalar(v, k);
    if (s !== null) out.push(`${pre}${nice(k)}: ${s}`);
    else if (Array.isArray(v) && v.length && typeof v[0] === 'object' && !SKIP.has(k)) out.push(`${pre}${nice(k)}: ${v.length}`);
  };
  const warn = (k: string): void => { const v = sm[k]; if (Array.isArray(v)) for (const w of v) out.push(`${k === 'warnings' ? 'Warning' : 'Note'}: ${String(w)}`); };
  const label = typeof sm.label === 'string' ? sm.label : '';
  if (label) out.push(label);
  warn('warnings');
  for (const k of PRIORITY) { if (k in sm && !SKIP.has(k)) { seen.add(k); add(k, sm[k]); } }
  for (const k of ['reference', 'pack', 'warp']) {
    const o = sm[k];
    if (o && typeof o === 'object' && !Array.isArray(o)) for (const [kk, v] of Object.entries(o as Json)) if (kk !== 'notes') add(kk, v, `${k} `);
  }
  for (const [k, v] of Object.entries(sm)) { if (!seen.has(k) && !SKIP.has(k) && !['reference', 'pack', 'warp'].includes(k)) add(k, v); }
  const srcs = sm.sources;
  if (Array.isArray(srcs)) for (const s of srcs as Json[]) out.push(`${String(s.name ?? 'source')}: mean ${SI(Number(s.mean_temperature_k), 'K')}, max ${SI(Number(s.max_temperature_k), 'K')}`);
  warn('notes');
  return out.slice(0, limit);
}

const pairs = (rows: unknown, fx: (r: Json) => number, fy: (r: Json) => number): Array<[number, number]> => {
  if (!Array.isArray(rows)) return [];
  const out: Array<[number, number]> = [];
  for (const r of rows as Json[]) { const x = fx(r), y = fy(r); if (Number.isFinite(x) && Number.isFinite(y)) out.push([x, y]); }
  return out;
};

export function curvesOf(sm: Json, topoRows: unknown): Curve[] {
  const out: Curve[] = [];
  const hist = sm.history;
  if (Array.isArray(hist) && hist.length && typeof hist[0] === 'object') {
    out.push({ id: 'fill_pressure', label: 'Fill pressure over time', xLabel: 'time (s)', yLabel: 'pressure (Pa)', points: pairs(hist, (r) => Number(r.time), (r) => Number(r.pressure)) });
    out.push({ id: 'fill_fraction', label: 'Filled fraction over time', xLabel: 'time (s)', yLabel: 'fraction', points: pairs(hist, (r) => Number(r.time), (r) => Number(r.fraction)) });
  }
  const steps = sm.steps;
  if (Array.isArray(steps) && steps.length && typeof steps[0] === 'object') {
    out.push({ id: 'load_disp', label: 'Largest displacement per load factor', xLabel: 'load factor', yLabel: 'displacement (m)', points: pairs(steps, (r) => Number(r.load_factor), (r) => Number(r.umax_m)) });
    out.push({ id: 'load_react', label: 'Reaction per load factor', xLabel: 'load factor', yLabel: 'reaction (N)', points: pairs(steps, (r) => Number(r.load_factor), (r) => (Array.isArray(r.reaction_n) ? Math.hypot(...(r.reaction_n as number[])) : NaN)) });
  }
  const att = sm.outer_attempts;
  if (Array.isArray(att) && att.length) out.push({ id: 'pass_stress', label: 'Peak stress per pass', xLabel: 'pass', yLabel: 'stress (MPa)', points: pairs(att, (r) => Number(r.pass), (r) => Number(r.peak_stress_mpa)) });
  if (Array.isArray(topoRows) && topoRows.length) {
    out.push({ id: 'topo_compliance', label: 'Compliance per iteration', xLabel: 'iteration', yLabel: 'compliance', points: pairs(topoRows, (r) => Number((r as unknown as number[])[0]), (r) => Number((r as unknown as number[])[1])) });
    out.push({ id: 'topo_volume', label: 'Volume fraction per iteration', xLabel: 'iteration', yLabel: 'volume', points: pairs(topoRows, (r) => Number((r as unknown as number[])[0]), (r) => Number((r as unknown as number[])[2])) });
  }
  return out.filter((c) => c.points.length > 1);
}
