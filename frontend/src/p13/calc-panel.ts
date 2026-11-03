import { docStore } from '../ui/doc-store';
import type { DockPanel } from '../ui/dock';
import { el } from '../ui/dom';
import { t } from '../ui/i18n';
import { toast } from '../ui/toast';
import { req, text } from '../u8/net';
import { button, buttons } from '../u8/ui';
import { fieldForm, type FieldForm, type FieldSpec } from '../p12/fields';
import { reportBox, section, SI } from './kit';
import { summaryLines } from './summary';
import type { Json } from './sim-store';

const nz = (v: unknown): number | null => (typeof v === 'number' && Number.isFinite(v) ? v : null);
const k = (v: unknown, f: number): number | null => { const n = nz(v); return n === null ? null : Number((n * f).toPrecision(12)); };
const N = (name: string, label: string, unit?: string, extra: Partial<FieldSpec> = {}): FieldSpec => ({ name, type: 'number', label, unit: unit ?? null, nullable: true, ...extra });
const C = (name: string, label: string, choices: Array<[string, string]>, def?: string): FieldSpec => ({ name, type: 'choice', label, choices, default: def ?? choices[0][0] });
const B = (name: string, label: string, def = false): FieldSpec => ({ name, type: 'bool', label, default: def });
const T = (name: string, label: string, def = ''): FieldSpec => ({ name, type: 'text', label, default: def });

const strip = (o: Json): Json => { const out: Json = {}; for (const [key, v] of Object.entries(o)) if (v !== null && v !== undefined && v !== '') out[key] = v; return out; };
const list = (s: unknown): number[] => String(s ?? '').split(/[\s,;]+/).filter(Boolean).map(Number).filter(Number.isFinite);

type Action = [string, (v: Json) => Promise<string[]>, boolean?];

function card(title: string, rows: number, forms: FieldForm[], actions: Action[], extra: HTMLElement[] = []): HTMLElement {
  const s = section(title);
  const out = reportBox(rows);
  const bar = actions.map(([label, fn, primary]) => button(label, () => {
    const v: Json = {};
    for (const f of forms) Object.assign(v, f.read());
    out.set([t('Working...')]);
    void fn(v).then((lines) => out.set(lines), (e) => out.set([text(e)], true));
  }, primary ? 'primary' : 'ghost'));
  s.body.append(...forms.map((f) => f.el), ...extra, buttons(...bar), out.el);
  return s.root;
}

const post = (path: string, spec: Json): Promise<Json> => req<Json>('POST', `/api/flow/${path}`, { spec });
const lines = (r: Json, n: number): string[] => summaryLines(r, n);

function ductCard(): HTMLElement {
  const base = fieldForm([N('density', 'Fluid density', 'kg/m3', { min: 0 }), N('viscosity', 'Fluid viscosity', 'mPa s', { min: 0 }), N('flow', 'Volume flow', 'L/s', { min: 0 }), C('method', 'Friction factor', [['swamee_jain', 'Swamee-Jain'], ['colebrook', 'Colebrook']])], () => undefined);
  const vis = (f: FieldForm): void => {
    const ty = f.read().type;
    f.show(new Set(['type', ...(ty === 'round' ? ['diameter', 'length', 'roughness'] : ty === 'rect' ? ['width', 'height', 'length', 'roughness'] : ty === 'fitting' ? ['k', 'name'] : ty === 'equivalent' ? ['length'] : [])]));
  };
  const segs: FieldForm[] = [0, 1, 2, 3].map((i) => {
    const f: FieldForm = fieldForm([C('type', `Segment ${i + 1}`, [['', 'Not used'], ['round', 'Round straight run'], ['rect', 'Rectangular straight run'], ['fitting', 'Fitting with a loss coefficient'], ['equivalent', 'Equivalent length']], i === 0 ? 'round' : ''), N('diameter', 'Diameter', 'mm', { min: 0 }), N('width', 'Width', 'mm', { min: 0 }), N('height', 'Height', 'mm', { min: 0 }), N('length', 'Length', 'm', { min: 0 }), N('roughness', 'Roughness', 'mm', { min: 0 }), N('k', 'Loss coefficient', undefined, { min: 0 }), T('name', 'Name')], () => vis(f));
    vis(f);
    return f;
  });
  return card('Duct loss', 8, [base, ...segs], [['Calculate', async (v) => {
    const rows: Json[] = [];
    for (const f of segs) {
      const s = f.read();
      if (s.type === 'round') rows.push(strip({ kind: 'straight', shape: 'round', diameter: k(s.diameter, 1e-3), length: nz(s.length), roughness: k(s.roughness, 1e-3) }));
      else if (s.type === 'rect') rows.push(strip({ kind: 'straight', shape: 'rect', width: k(s.width, 1e-3), height: k(s.height, 1e-3), length: nz(s.length), roughness: k(s.roughness, 1e-3) }));
      else if (s.type === 'fitting') rows.push(strip({ kind: 'fitting', k: nz(s.k), name: s.name }));
      else if (s.type === 'equivalent') rows.push(strip({ kind: 'equivalent_length', length: nz(s.length) }));
    }
    const r = await post('duct', strip({ density: nz(v.density), viscosity: k(v.viscosity, 1e-3), flow: k(v.flow, 1e-3), method: v.method, segments: rows }));
    const out = [`${t('Pressure drop')}: ${SI(Number(r.pressure_drop), 'Pa')}`];
    const per = Array.isArray(r.segments) ? r.segments as Json[] : [];
    per.slice(0, 4).forEach((s, i) => out.push(`${i + 1}: ${SI(Number(s.pressure_drop), 'Pa')} · ${t('speed')} ${SI(Number(s.velocity), 'm/s')} · Re ${SI(Number(s.reynolds), '')}`));
    return [...out, ...lines({ label: r.label, notes: r.notes }, 3)];
  }, true]]);
}

function finCard(): HTMLElement {
  const f: FieldForm = fieldForm([
    N('h', 'Film coefficient', 'W/m2K', { min: 0 }), N('k', 'Conductivity', 'W/mK', { min: 0 }), N('length', 'Fin length', 'mm', { min: 0 }), N('theta', 'Root temperature above ambient', 'K'),
    C('shape', 'Section', [['plate', 'Plate'], ['pin', 'Round pin']]), N('width', 'Width', 'mm', { min: 0 }), N('thickness', 'Thickness', 'mm', { min: 0 }), N('diameter', 'Diameter', 'mm', { min: 0 }),
    C('tip', 'Tip', [['adiabatic', 'Insulated'], ['convective', 'Convecting']]), N('count', 'Fins on the sink', undefined, { min: 1 }), N('base', 'Exposed base area', 'mm2', { min: 0 }),
  ], () => vis());
  const vis = (): void => { f.show(new Set(['h', 'k', 'length', 'theta', 'shape', ...(f.read().shape === 'pin' ? ['diameter'] : ['width', 'thickness']), 'tip', 'count', 'base'])); };
  vis();
  const spec = (v: Json): Json => strip({ h: nz(v.h), k: nz(v.k), length: k(v.length, 1e-3), theta_root: nz(v.theta), width: v.shape === 'pin' ? null : k(v.width, 1e-3), thickness: v.shape === 'pin' ? null : k(v.thickness, 1e-3), diameter: v.shape === 'pin' ? k(v.diameter, 1e-3) : null, tip: v.tip });
  return card('Fin and heat sink', 8, [f], [
    ['Fin', async (v) => lines(await post('fin', spec(v)), 8), true],
    ['Heat sink', async (v) => lines(await post('sink', { ...spec(v), count: nz(v.count), base_area: k(v.base, 1e-6) }), 8)],
  ]);
}

function plateCard(): HTMLElement {
  const f: FieldForm = fieldForm([N('length', 'Flow length', 'mm', { min: 0 }), N('width', 'Width', 'mm', { min: 0 }), N('gap', 'Gap', 'mm', { min: 0 }), N('flow', 'Flow rate', 'cm3/s', { min: 0 }), C('model', 'Melt model', [['newtonian', 'Newtonian'], ['power', 'Power law']]), N('eta', 'Viscosity', 'Pa s', { min: 0 }), N('kk', 'Consistency', 'Pa s^n', { min: 0 }), N('n', 'Exponent', undefined, { min: 0.05, max: 1.5 })], () => vis());
  const vis = (): void => { f.show(new Set(['length', 'width', 'gap', 'flow', 'model', ...(f.read().model === 'power' ? ['kk', 'n'] : ['eta'])])); };
  vis();
  return card('Plate fill', 6, [f], [['Calculate', async (v) => {
    const m = v.model === 'power' ? { k: nz(v.kk), n: nz(v.n) } : { eta: nz(v.eta) };
    const r = await post('plate-fill', strip({ length: k(v.length, 1e-3), width: k(v.width, 1e-3), gap: k(v.gap, 1e-3), flow: k(v.flow, 1e-6), ...m }));
    return lines(r, 6);
  }, true]]);
}

function packWarpCard(): HTMLElement {
  const f = fieldForm([N('diffusivity', 'Thermal diffusivity', 'mm2/s', { min: 0 }), N('t_melt', 'Melt temperature', 'C'), N('t_mould', 'Mould temperature', 'C'), N('t_freeze', 'Freeze temperature', 'C'), N('thickness', 'Wall thickness', 'mm', { min: 0 }), N('gate_thickness', 'Gate thickness', 'mm', { min: 0 })], () => undefined);
  const w: FieldForm = fieldForm([C('by', 'Differential shrinkage given as', [['strain', 'Strain difference'], ['alpha', 'Coefficient and temperature difference']]), N('strain', 'Strain difference'), N('alpha', 'Coefficient', '1e-6/K'), N('dt', 'Mould half temperature difference', 'K'), N('wl', 'Strip length', 'mm', { min: 0 })], () => vis());
  const vis = (): void => { w.show(new Set(['by', ...(w.read().by === 'alpha' ? ['alpha', 'dt'] : ['strain']), 'wl'])); };
  vis();
  return card('Pack and warp', 8, [f, w], [
    ['Pack', async (v) => lines(await post('pack', strip({ thickness: k(v.thickness, 1e-3), gate_thickness: k(v.gate_thickness, 1e-3), diffusivity: k(v.diffusivity, 1e-6), t_melt: nz(v.t_melt), t_mould: nz(v.t_mould), t_freeze: nz(v.t_freeze) })), 8), true],
    ['Warp', async (v) => lines(await post('warp', strip({ length: k(v.wl, 1e-3), thickness: k(v.thickness, 1e-3), ...(v.by === 'alpha' ? { alpha: k(v.alpha, 1e-6), delta_t: nz(v.dt) } : { delta_strain: nz(v.strain) }) })), 8)],
  ]);
}

function laminateCard(docId: () => string | null): HTMLElement {
  const f = fieldForm([
    N('E1', 'Ply modulus along the fibre', 'GPa', { min: 0 }), N('E2', 'Ply modulus across the fibre', 'GPa', { min: 0 }), N('G12', 'Ply shear modulus', 'GPa', { min: 0 }), N('nu12', 'Ply Poisson ratio', undefined, { min: 0, max: 1 }),
    N('Xt', 'Strength along, tension', 'MPa', { min: 0 }), N('Xc', 'Strength along, compression', 'MPa', { min: 0 }), N('Yt', 'Strength across, tension', 'MPa', { min: 0 }), N('Yc', 'Strength across, compression', 'MPa', { min: 0 }), N('S', 'Shear strength', 'MPa', { min: 0 }),
    T('layup', 'Ply angles in degrees, separated by commas', '0, 90, 90, 0'), N('thickness', 'Ply thickness', 'mm', { min: 0 }), B('symmetric', 'Mirror the stack about the middle'),
    N('nx', 'Force per width Nx', 'N/m'), N('ny', 'Force per width Ny', 'N/m'), N('nxy', 'Force per width Nxy', 'N/m'),
  ], () => undefined);
  return card('Laminate', 8, [f], [['Calculate', async (v) => {
    const ply = strip({ E1: k(v.E1, 1e9), E2: k(v.E2, 1e9), G12: k(v.G12, 1e9), nu12: nz(v.nu12), Xt: k(v.Xt, 1e6), Xc: k(v.Xc, 1e6), Yt: k(v.Yt, 1e6), Yc: k(v.Yc, 1e6), S: k(v.S, 1e6) });
    const loads = [v.nx, v.ny, v.nxy].some((x) => nz(x)) ? { N: [nz(v.nx) ?? 0, nz(v.ny) ?? 0, nz(v.nxy) ?? 0], M: [0, 0, 0] } : undefined;
    const id = docId();
    if (!id) throw new Error(t('Open a part first.'));
    const r = await req<Json>('POST', `/api/docs/${encodeURIComponent(id)}/sim/laminate`, strip({ ply, layup: list(v.layup), thickness: k(v.thickness, 1e-3), symmetric: v.symmetric === true, loads }));
    const c = (r.constants ?? {}) as Json, A = (r.A ?? []) as number[][], D = (r.D ?? []) as number[][], B = (r.B ?? []) as number[][];
    const out = [
      `Ex ${SI(Number(c.Ex) / 1e9, 'GPa')} · Ey ${SI(Number(c.Ey) / 1e9, 'GPa')} · Gxy ${SI(Number(c.Gxy) / 1e9, 'GPa')}`,
      `${t('Poisson')} nu_xy ${SI(Number(c.nu_xy), '')} · ${t('thickness')} ${SI(Number(r.thickness_m) * 1e3, 'mm')}`,
      `A11 ${SI(A[0]?.[0] ?? 0, 'N/m')} · A12 ${SI(A[0]?.[1] ?? 0, 'N/m')} · A66 ${SI(A[2]?.[2] ?? 0, 'N/m')}`,
      `D11 ${SI(D[0]?.[0] ?? 0, 'N m')} · D22 ${SI(D[1]?.[1] ?? 0, 'N m')}`,
      `${t('Largest coupling B')} ${SI(Math.max(...B.flat().map(Math.abs), 0), 'N')}`,
    ];
    const an = (r.analysis ?? null) as Json | null;
    const w = an ? an.first_ply_failure as Json | null : null;
    if (an) out.push(w ? `${t('First ply failure')}: ${t('ply')} ${Number(w.ply) + 1} ${String(w.at)} · ${t('strength ratio')} ${SI(Number(w.strength_ratio), '')}` : t('Give all five strengths for the failure check.'));
    return out;
  }, true]]);
}

function fatigueCard(docId: () => string | null): HTMLElement {
  const f = fieldForm([
    T('points', 'Load history turning points, separated by commas', '-2, 1, -3, 5, -1, 3, -4, 4, -2'), B('repeating', 'The history repeats'),
    N('cycles', 'S-N reference cycles', undefined, { default: 1e6, min: 1 }), N('amp', 'S-N amplitude at the reference', 'MPa', { default: 250, min: 0 }), N('b', 'S-N exponent', undefined, { default: -0.09, max: 0 }),
    C('corr', 'Mean stress correction', [['goodman', 'Goodman'], ['gerber', 'Gerber'], ['soderberg', 'Soderberg'], ['none', 'None']]), N('su', 'Ultimate strength', 'MPa', { min: 0 }), N('sy', 'Yield strength', 'MPa', { min: 0 }),
    T('blocks', 'Spectrum blocks as amplitude, mean, cycles; separated by semicolons', '100, 0, 100000; 150, 20, 20000'),
  ], () => undefined);
  const need = (): string => { const id = docId(); if (!id) throw new Error(t('Open a part first.')); return encodeURIComponent(id); };
  return card('Rainflow and fatigue life', 8, [f], [
    ['Count cycles', async (v) => {
      const r = await req<Json>('POST', `/api/docs/${need()}/sim/fatigue/rainflow`, { points: list(v.points), repeating: v.repeating === true });
      const rows = Array.isArray(r.cycles) ? r.cycles as Json[] : [];
      return [`${t('Total cycles')}: ${SI(Number(r.total_cycles), '')}`, ...rows.slice(0, 6).map((c) => `${t('range')} ${SI(Number(c.range), '')} · ${t('mean')} ${SI(Number(c.mean), '')} · ${t('count')} ${SI(Number(c.count), '')}`)];
    }, true],
    ['Life from spectrum', async (v) => {
      const spectrum = String(v.blocks ?? '').split(';').map((s) => list(s)).filter((a) => a.length >= 3).map((a) => ({ amplitude: a[0] * 1e6, mean: a[1] * 1e6, cycles: a[2] }));
      const body = strip({ sn: { reference: { cycles: nz(v.cycles), amplitude: k(v.amp, 1e6), b: nz(v.b) } }, spectrum, correction: v.corr, sigma_u: k(v.su, 1e6), sigma_y: k(v.sy, 1e6) });
      const r = await req<Json>('POST', `/api/docs/${need()}/sim/fatigue/life`, body);
      return [`${t('Damage per block')}: ${SI(Number(r.damage_per_block), '')}`, `${t('Repeats to failure')}: ${SI(Number(r.repeats_to_failure), '')}`];
    }],
  ]);
}

function su2Card(): HTMLElement {
  const f = fieldForm([B('enabled', 'Use the optional CFD program'), T('path', 'Path to the program (named SU2_CFD)'), T('mpi', 'Path to mpirun (optional)'), { name: 'ranks', type: 'int', label: 'Processes', default: 1, min: 1, max: 256, nullable: true }], () => undefined);
  const status = reportBox(3);
  const body = (): Json => { const v = f.read(); return { enabled: v.enabled === true, path: String(v.path ?? ''), mpi_path: String(v.mpi ?? ''), ranks: nz(v.ranks) ?? 1 }; };
  const show = (r: Json): void => { status.set([String(r.message ?? ''), `${t('Present')}: ${r.present ? t('yes') : t('no')} · ${t('Usable')}: ${r.usable ? t('yes') : t('no')}`, String(r.label ?? '')]); };
  const load = (): void => { void req<Json>('GET', '/api/flow/su2').then((r) => { f.set({ enabled: r.enabled, path: r.path, mpi: r.mpiPath, ranks: r.ranks }); show(r); }, (e) => status.set([text(e)], true)); };
  const s = section('Optional CFD program');
  s.body.append(f.el, buttons(button('Save the settings', () => { void req<Json>('PUT', '/api/flow/su2', body()).then(show, (e) => { status.set([text(e)], true); toast(text(e), 'error'); }); }, 'primary'), button('Check again', load)), status.el);
  load();
  return s.root;
}

export function calcPanel(): DockPanel {
  return {
    id: 'simcalc', label: 'Flow and design calculators', icon: 'simulate', order: 46,
    build(body) {
      body.classList.add('u8-panel', 'xw-panel');
      const live = el('<div class="u8-live cm-live"></div>');
      body.append(live);
      const id = (): string | null => docStore.activeId;
      live.append(ductCard(), finCard(), plateCard(), packWarpCard(), laminateCard(id), fatigueCard(id), su2Card());
    },
  };
}
