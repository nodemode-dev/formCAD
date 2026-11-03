import { docStore } from '../ui/doc-store';
import type { DockPanel } from '../ui/dock';
import { el, patchList, q, setClass, setHidden, setText } from '../ui/dom';
import { t } from '../ui/i18n';
import { toast } from '../ui/toast';
import { button, buttons, selectCtl } from '../u8/ui';
import { view3d } from '../view3d/mount';
import { runCmd } from '../p10/kit';
import { fixtureFromForm, loadFromForm } from '../p13/forms';
import { sim } from '../p13/sim-store';
import { gen, type Outcome } from './gen-store';
import { asArr, entityList, fillSelect, formGrid, mm, progressBar, reportBox, section, sig, type Json, type RowItem } from './kit';

const DIRS: Array<[string, string]> = [['+x', '+x'], ['-x', '-x'], ['+y', '+y'], ['-y', '-y'], ['+z', '+z'], ['-z', '-z']];
const AXES: Array<[string, string]> = [['x', 'x'], ['y', 'y'], ['z', 'z']];
const METHOD_LABEL: Record<string, string> = { additive: 'Additive', milling3: '3-axis milling', cutting: '2-axis cutting', casting: 'Casting', free: 'Unconstrained' };

const pickedFaces = (body?: number): number[] => {
  const s = view3d()?.vp?.sel;
  if (!s) return [];
  return s.faces.filter((f) => body === undefined || f.body === body).map((f) => f.face);
};
const regionText = (r: Json): string => {
  const k = String(r.kind ?? (r.body !== undefined ? 'body' : 'box'));
  const v = (a: unknown): string => (Array.isArray(a) ? a.map((n) => mm(n, 1)).join(' ') : '');
  if (k === 'box') return `box ${v(r.min)} to ${v(r.max)}`;
  if (k === 'cylinder') return `cylinder ${String(r.axis ?? 'z')} at ${v(r.centre)} r ${mm(r.radius, 1)}`;
  if (k === 'sphere') return `sphere at ${v(r.centre)} r ${mm(r.radius, 1)}`;
  return `body ${String(r.body ?? '')}`;
};

export function genPanel(): DockPanel {
  return {
    id: 'gen', label: 'Generative design', icon: 'generative', order: 47,
    build(body) {
      body.classList.add('u8-panel', 'xw-panel', 'p14-panel');
      const note = el('<p class="u8-note"></p>');
      setText(note, t('Open a part to set up a generative study.'));
      const live = el('<div class="u8-live cm-live"></div>');
      body.append(note, live);
      const paintShell = (): void => { const on = !!docStore.current(); setHidden(note, on); setHidden(live, !on); };

      const sList = section('Studies');
      const list = el('<div class="u8-list p14-list" role="listbox" aria-label="Generative studies"></div>');
      const empty = el('<p class="u8-note p14-empty"></p>');
      sList.body.append(list, empty, buttons(button('New study from the selected body', () => { void newStudy(); }, 'primary'), button('Delete', () => { void removeStudy(); })));
      const paintList = entityList(list, (k) => gen.select(k), (k) => { void removeStudy(k); });

      const sSet = section('Study setup');
      const matSel = selectCtl('Material', [], () => { const s = gen.study(); if (s) void sim.update(s.id, { material: matSel.get() || null }); });
      const libSel = selectCtl('Library material', []);
      const loadForm = formGrid([{ key: 'value', label: 'Force (N)', value: 1000 }, { key: 'dx', label: 'Direction x', value: 0 }, { key: 'dy', label: 'Direction y', value: 0 }, { key: 'dz', label: 'Direction z', value: -1 }]);
      const attachList = el('<div class="u8-list p14-list p14-list-s" role="listbox" aria-label="Loads and fixtures"></div>');
      const paintAttach = entityList(attachList, (k) => sim.select(gen.studyId, k), (k) => { void removeAttach(k); });
      const grid = formGrid([{ key: 'cells', label: 'Grid cells', value: 1500 }], () => queueSave());
      const regionList = el('<div class="u8-list p14-list p14-list-s" role="listbox" aria-label="Regions"></div>');
      const paintRegions = entityList(regionList, () => undefined, (k) => { void removeRegion(k); });
      const rg = formGrid([
        { key: 'role', label: 'Role', kind: 'select', options: [['preserve', 'Preserve'], ['obstacles', 'Obstacle']] },
        { key: 'kind', label: 'Shape', kind: 'select', options: [['box', 'Box'], ['cylinder', 'Cylinder'], ['sphere', 'Sphere']] },
        { key: 'x0', label: 'x min or centre', value: 0 }, { key: 'y0', label: 'y min or centre', value: 0 }, { key: 'z0', label: 'z min or centre', value: 0 },
        { key: 'x1', label: 'x max', value: 10 }, { key: 'y1', label: 'y max', value: 10 }, { key: 'z1', label: 'z max', value: 10 },
        { key: 'radius', label: 'Radius', value: 5 }, { key: 'axis', label: 'Axis', kind: 'select', options: AXES, value: 'z' },
      ], () => paintRegionForm());
      const paintRegionForm = (): void => {
        const k = String(rg.ctl.kind.get());
        for (const key of ['x1', 'y1', 'z1']) rg.show(key, k === 'box');
        rg.show('radius', k !== 'box');
        rg.show('axis', k === 'cylinder');
      };
      sSet.body.append(
        matSel.el, libSel.el, buttons(button('Add library material', () => { void addLibrary(); })),
        loadForm.el, buttons(button('Add load on the picked faces', () => { void addLoad(); }), button('Add fixture on the picked faces', () => { void addFixture(); })), attachList,
        grid.el, regionList, rg.el, buttons(button('Add region', () => { void addRegion(); }), button('Use the selected body as region', () => { void addBodyRegion(); })),
      );

      const sObj = section('Objective and methods');
      const obj = formGrid([
        { key: 'objective', label: 'Objective', kind: 'select', options: [['min_mass', 'Lightest at a safety factor'], ['min_compliance', 'Stiffest at a mass']] },
        { key: 'safety_factor', label: 'Safety factor', value: 2 },
        { key: 'volume_fractions', label: 'Volume fractions', kind: 'text', value: '0.3, 0.45' },
        { key: 'min_member_cells', label: 'Smallest member (cells)', value: 2.5 },
        { key: 'passes', label: 'Passes per method', value: 4 },
        { key: 'iterations', label: 'Iterations per pass', value: 60 },
      ], () => queueSave());
      const mAdd = formGrid([{ key: 'on', label: 'Additive', kind: 'check', value: true }, { key: 'dir', label: 'Build direction', kind: 'select', options: DIRS, value: '+z' }], () => queueSave());
      const mMill = formGrid([{ key: 'on', label: '3-axis milling', kind: 'check', value: true }, { key: 'dirs', label: 'Tool directions', kind: 'text', value: '+y,-y' }], () => queueSave());
      const mCut = formGrid([{ key: 'on', label: '2-axis cutting', kind: 'check', value: true }, { key: 'axis', label: 'Cut axis', kind: 'select', options: AXES, value: 'y' }], () => queueSave());
      const mCast = formGrid([{ key: 'on', label: 'Casting', kind: 'check', value: true }, { key: 'dir', label: 'Draw direction', kind: 'select', options: DIRS, value: '+z' }], () => queueSave());
      const mFree = formGrid([{ key: 'on', label: 'Unconstrained reference', kind: 'check', value: false }], () => queueSave());
      sObj.body.append(obj.el, mAdd.el, mMill.el, mCut.el, mCast.el, mFree.el);

      const sRun = section('Run');
      const prevBox = reportBox(4);
      const bar = progressBar();
      const runBox = reportBox(3);
      sRun.body.append(prevBox.el, buttons(button('Check the study', () => { void gen.loadPreview(); }), button('Run', () => { void doRun(); }, 'primary')), bar.el, runBox.el);
      bar.onCancel(() => { void gen.cancel(); });

      const sOut = section('Outcomes');
      const baseBox = reportBox(2);
      const sortSel = selectCtl('Sort by', [['mass', 'Mass'], ['sf', 'Safety factor'], ['method', 'Method']], () => paintOutcomes());
      const cards = el('<div class="p14-cards" role="listbox" aria-label="Outcomes"></div>');
      const detail = reportBox(5);
      const applyForm = formGrid([{ key: 'name', label: 'Body name', kind: 'text', value: '' }, { key: 'unite', label: 'Unite with the preserve bodies', kind: 'check', value: false }]);
      const applyBtns = buttons(button('Show in the view', () => { if (gen.outcomeId) void gen.show(gen.outcomeId); }), button('Add mesh body', () => { void apply(false); }), button('Add solid body', () => { void apply(true); }, 'primary'));
      sOut.body.append(baseBox.el, sortSel.el, cards, detail.el, applyForm.el, applyBtns);

      body.addEventListener('click', (e) => {
        const card = (e.target as HTMLElement).closest<HTMLElement>('.p14-card');
        if (card?.dataset.oid) { gen.outcomeId = card.dataset.oid; gen.emit(); void gen.show(card.dataset.oid); }
      });
      live.append(sList.root, sSet.root, sObj.root, sRun.root, sOut.root);

      let saveTimer = 0;
      let formSig = '';
      const options = (): Json => {
        const o = obj.get();
        const methods: Json[] = [];
        if (mAdd.ctl.on.get()) methods.push({ method: 'additive', direction: mAdd.ctl.dir.get() });
        if (mMill.ctl.on.get()) methods.push({ method: 'milling3', directions: String(mMill.ctl.dirs.get() || '+y').split(/[,\s]+/).filter(Boolean) });
        if (mCut.ctl.on.get()) methods.push({ method: 'cutting', axis: mCut.ctl.axis.get() });
        if (mCast.ctl.on.get()) methods.push({ method: 'casting', direction: mCast.ctl.dir.get() });
        if (mFree.ctl.on.get()) methods.push({ method: 'free' });
        const fr = String(obj.ctl.volume_fractions.get()).split(/[,\s]+/).map(Number).filter((n) => Number.isFinite(n) && n > 0 && n < 1);
        return { ...o, volume_fractions: fr.length ? fr : [0.3, 0.45], methods };
      };
      const queueSave = (): void => {
        window.clearTimeout(saveTimer);
        saveTimer = window.setTimeout(() => { void saveOptions(); }, 450);
      };
      async function saveOptions(patch: Json = {}): Promise<void> {
        const s = gen.study();
        if (!s) return;
        const cur = (s.options ?? {}) as Json;
        const g = options();
        const cells = Number(grid.ctl.cells.get());
        await sim.update(s.id, { options: { ...cur, ...(Number.isFinite(cells) && cells > 0 ? { cells } : {}), generative: g, ...patch } });
      }

      const readForm = (): void => {
        const s = gen.study();
        const o = ((s?.options ?? {}) as Json);
        const g = ((o.generative ?? {}) as Json);
        const key = JSON.stringify([s?.id, o]);
        if (key === formSig) return;
        formSig = key;
        if (typeof o.cells === 'number') grid.set('cells', o.cells);
        obj.set('objective', g.objective ?? 'min_mass');
        obj.set('safety_factor', typeof g.safety_factor === 'number' ? g.safety_factor : 2);
        obj.set('volume_fractions', Array.isArray(g.volume_fractions) ? (g.volume_fractions as number[]).join(', ') : '0.3, 0.45');
        obj.set('min_member_cells', typeof g.min_member_cells === 'number' ? g.min_member_cells : 2.5);
        obj.set('passes', typeof g.passes === 'number' ? g.passes : 4);
        obj.set('iterations', typeof g.iterations === 'number' ? g.iterations : 60);
        const ms = asArr<Json>(g.methods);
        const by = (m: string): Json | undefined => ms.find((x) => x.method === m);
        mAdd.set('on', !!by('additive')); mAdd.set('dir', by('additive')?.direction ?? '+z');
        mMill.set('on', !!by('milling3')); mMill.set('dirs', asArr<string>(by('milling3')?.directions).join(',') || '+y,-y');
        mCut.set('on', !!by('cutting')); mCut.set('axis', by('cutting')?.axis ?? 'y');
        mCast.set('on', !!by('casting')); mCast.set('dir', by('casting')?.direction ?? '+z');
        mFree.set('on', !!by('free'));
      };

      const regionsOf = (): Array<{ role: 'preserve' | 'obstacles'; idx: number; r: Json }> => {
        const o = ((gen.study()?.options ?? {}) as Json);
        const out: Array<{ role: 'preserve' | 'obstacles'; idx: number; r: Json }> = [];
        for (const role of ['preserve', 'obstacles'] as const) asArr<Json>(o[role]).forEach((r, idx) => out.push({ role, idx, r }));
        return out;
      };

      async function addRegion(): Promise<void> {
        const s = gen.study();
        if (!s) { toast(t('Make a study first.'), 'error'); return; }
        const v = rg.get();
        const n = (k: string): number => Number(v[k] ?? 0);
        const kind = String(v.kind ?? 'box');
        const spec: Json = kind === 'box'
          ? { kind, min: [Math.min(n('x0'), n('x1')), Math.min(n('y0'), n('y1')), Math.min(n('z0'), n('z1'))], max: [Math.max(n('x0'), n('x1')), Math.max(n('y0'), n('y1')), Math.max(n('z0'), n('z1'))] }
          : kind === 'cylinder' ? { kind, axis: v.axis ?? 'z', centre: [n('x0'), n('y0'), n('z0')], radius: n('radius') } : { kind, centre: [n('x0'), n('y0'), n('z0')], radius: n('radius') };
        const role = String(v.role ?? 'preserve');
        const o = (s.options ?? {}) as Json;
        await saveOptions({ [role]: [...asArr<Json>(o[role]), spec] });
      }
      async function addBodyRegion(): Promise<void> {
        const s = gen.study();
        const sel = view3d()?.vp?.sel;
        const b = sel?.bodies[0];
        if (!s || b === undefined) { toast(t('Select a body in the view first.'), 'error'); return; }
        const role = String(rg.ctl.role.get());
        const o = (s.options ?? {}) as Json;
        await saveOptions({ [role]: [...asArr<Json>(o[role]), { body: b }] });
      }
      async function removeRegion(k: string): Promise<void> {
        const s = gen.study();
        const hit = regionsOf().find((r) => `${r.role}:${r.idx}` === k);
        if (!s || !hit) return;
        const o = (s.options ?? {}) as Json;
        await saveOptions({ [hit.role]: asArr<Json>(o[hit.role]).filter((_, i) => i !== hit.idx) });
      }

      const bodyOfStudy = (): number | undefined => { const g = gen.study()?.geometry as Json | undefined; return g && typeof g.body === 'number' ? g.body : undefined; };
      async function attach(kind: 'load' | 'fixture', fields: Json): Promise<void> {
        const s = gen.study();
        if (!s) { toast(t('Make a study first.'), 'error'); return; }
        const rec = await sim.create(kind, fields);
        if (!rec) return;
        const key = kind === 'load' ? 'loads' : 'fixtures';
        await sim.update(s.id, { [key]: [...sim.ids(sim.study(s.id) ?? s, key), rec.id] });
      }
      async function addLoad(): Promise<void> {
        const faces = pickedFaces(bodyOfStudy());
        if (!faces.length) { toast(t('Pick faces of the study body in the view first.'), 'error'); return; }
        const v = loadForm.get();
        await attach('load', { name: `Force ${sim.of('load').length + 1}`, ...loadFromForm('force', { value: v.value ?? 0, dx: v.dx ?? 0, dy: v.dy ?? 0, dz: v.dz ?? -1 }), select: { faces } });
      }
      async function addFixture(): Promise<void> {
        const faces = pickedFaces(bodyOfStudy());
        if (!faces.length) { toast(t('Pick faces of the study body in the view first.'), 'error'); return; }
        await attach('fixture', { name: `Fixed ${sim.of('fixture').length + 1}`, ...fixtureFromForm('fixed', {}), select: { faces } });
      }
      async function removeAttach(k: string): Promise<void> {
        const s = gen.study();
        const rec = sim.get(k);
        if (!s || !rec) return;
        const key = rec.kind === 'load' ? 'loads' : 'fixtures';
        await sim.update(s.id, { [key]: sim.ids(s, key).filter((i) => i !== k) });
        await sim.remove(k);
      }
      async function addLibrary(): Promise<void> {
        const s = gen.study();
        const id = libSel.get();
        const m = sim.library.find((x) => String(x.id ?? x.name) === id);
        if (!s || !m) { toast(t('Choose a library material first.'), 'error'); return; }
        const rec = await sim.create('material', { name: m.name ?? id, library: m.id ?? id });
        if (rec) await sim.update(s.id, { material: rec.id });
      }

      async function newStudy(): Promise<void> {
        const vp = view3d()?.vp;
        const bodyId = vp?.sel.bodies[0] ?? vp?.sel.faces[0]?.body ?? [...(vp?.bodyViews.keys() ?? [])][0];
        if (bodyId === undefined) { toast(t('Add a body first, then make a study.'), 'error'); return; }
        const n = gen.studies().length + 1;
        const defaults = ((gen.limits?.defaults ?? {}) as Json);
        const rec = await sim.create('study', { name: `Generative ${n}`, type: 'generative', geometry: { body: bodyId }, loads: [], fixtures: [], contacts: [], mesh: { maxh_mm: null, order: 2, controls: [] }, options: { cells: 1500, generative: { ...defaults, iterations: 40 } } });
        if (rec) gen.select(rec.id);
      }
      async function removeStudy(id = gen.studyId): Promise<void> {
        if (!id) return;
        await sim.remove(id);
      }

      async function doRun(): Promise<void> {
        const s = gen.study();
        if (!s) { toast(t('Make a study first.'), 'error'); return; }
        window.clearTimeout(saveTimer);
        await saveOptions();
        await gen.run();
      }

      async function apply(solid: boolean): Promise<void> {
        const o = gen.outcome();
        if (!o || !gen.studyId) { toast(t('Select an outcome first.'), 'error'); return; }
        const v = applyForm.get();
        const r = await runCmd('genapply', { study: gen.studyId, outcome: o.id, name: String(v.name || `${o.id} ${METHOD_LABEL[o.method] ?? o.method}`), ...(solid ? { to_solid: true } : {}), ...(v.unite === true ? { unite_preserve: true } : {}) });
        if (r) { toast(solid ? t('Solid body added.') : t('Mesh body added.'), 'info'); gen.hide(); }
      }

      const metaLine = (o: Outcome): string => `${sig(o.mass_kg, 4)} kg  SF ${sig(o.safety_factor, 3)}`;
      const sorted = (): Outcome[] => {
        const list = [...(gen.data?.outcomes ?? [])];
        const by = sortSel.get();
        list.sort((a, b) => by === 'sf' ? b.safety_factor - a.safety_factor : by === 'method' ? a.method.localeCompare(b.method) : a.mass_kg - b.mass_kg);
        return list;
      };
      function paintOutcomes(): void {
        const key = gen.data?.result ?? '';
        patchList(cards, sorted(), {
          key: (o) => `${key}:${o.id}`,
          create: () => el('<div class="p14-card" role="option"><img class="p14-thumb" width="144" height="108" alt=""><div class="p14-card-body"><div class="p14-card-t"></div><div class="p14-card-m"></div><div class="p14-card-s"></div><div class="p14-card-b"></div></div></div>'),
          update: (n, o) => {
            n.dataset.oid = o.id;
            const img = q<HTMLImageElement>(n, 'img');
            const src = o.thumbnail_png_base64 ? `data:image/png;base64,${o.thumbnail_png_base64}` : '';
            if (src && img.getAttribute('src') !== src) img.src = src;
            setText(q(n, '.p14-card-t'), `${o.id}  ${METHOD_LABEL[o.method] ?? o.label}`);
            setText(q(n, '.p14-card-m'), metaLine(o));
            setText(q(n, '.p14-card-s'), `peak ${sig(o.peak_stress_mpa, 3)} MPa  ${sig(o.volume_fraction * 100, 3)} % volume`);
            setText(q(n, '.p14-card-b'), `${o.meets_safety_factor ? t('Meets the safety factor') : t('Below the safety factor')}  ${o.manufacturable ? t('Manufacturable') : t('Check the process')}`);
            setClass(n, 'is-selected', o.id === gen.outcomeId);
            setClass(n, 'is-bad', !o.meets_safety_factor || !o.manufacturable);
          },
        });
      }

      const paint = (): void => {
        paintShell();
        const studies = gen.studies();
        const items: RowItem[] = studies.map((s) => ({ key: s.id, badge: 'GD', name: String(s.name ?? s.id), sub: String(s.status ?? ''), selected: s.id === gen.studyId }));
        paintList(items);
        setText(empty, studies.length ? '' : t('No generative study yet.'));
        const s = gen.study();
        readForm();
        const mats = sim.of('material').map((m) => [m.id, String(m.name ?? m.id)] as [string, string]);
        fillSelect(matSel.input as HTMLSelectElement, [['', t('None')], ...mats]);
        matSel.set(String(s?.material ?? ''));
        const lib = sim.library.map((m) => [String(m.id ?? m.name), String(m.name ?? m.id)] as [string, string]);
        fillSelect(libSel.input as HTMLSelectElement, lib.length ? lib : [['', t('The library is empty')]]);
        const at: RowItem[] = s ? [...sim.ids(s, 'loads').map((i) => ({ key: i, badge: 'LD', name: String(sim.get(i)?.name ?? i), sub: `${sig(sim.get(i)?.value, 4)} N` })), ...sim.ids(s, 'fixtures').map((i) => ({ key: i, badge: 'FX', name: String(sim.get(i)?.name ?? i), sub: String(sim.get(i)?.type ?? '') }))] : [];
        paintAttach(at);
        paintRegions(regionsOf().map((r) => ({ key: `${r.role}:${r.idx}`, badge: r.role === 'preserve' ? 'PR' : 'OB', name: regionText(r.r), sub: '' })));
        paintRegionForm();

        const p = gen.preview;
        const pi = ((p?.info ?? {}) as Json);
        const pg = ((pi.grid ?? {}) as Json);
        if (p?.error) prevBox.set([String(p.error)], true);
        else if (p) prevBox.set([`${t('Grid')} ${pg.nx} x ${pg.ny} x ${pg.nz}, ${mm(pg.h, 2)} mm`, `${pi.cells_design} ${t('design cells')}, ${pi.cells_preserved} ${t('preserved')}`, `${p.runs} ${t('runs')}`, ...asArr<string>(pi.notes).slice(0, 1)]);
        else prevBox.set([t('Check the study to see the grid and the number of runs.')]);

        const j = gen.job;
        const on = gen.running;
        bar.set(j?.progress ?? 0, j ? `${j.phase || j.state} - ${Math.round((j.progress ?? 0) * 100)} %` : '', on);
        runBox.set(j ? [`${t('State')}: ${j.state}`, j.message || ''] : [t('Not run yet.')], j?.state === 'error' || j?.state === 'failed');

        const d = gen.data;
        const b = (d?.baseline ?? {}) as Json;
        baseBox.set(d ? [`${t('Full body')}: ${sig(b.mass_kg, 4)} kg, SF ${sig(b.safety_factor, 3)}`, `${t('Required safety factor')} ${sig(d.required_safety_factor, 3)}, ${t('limit')} ${sig(d.stress_limit_mpa, 4)} MPa`] : [t('No outcomes yet.')]);
        paintOutcomes();
        const o = gen.outcome();
        const man = (o?.manufacturing?.violations ?? {}) as Record<string, number>;
        detail.set(o ? [`${o.id} ${METHOD_LABEL[o.method] ?? o.label}: ${sig(o.mass_kg, 4)} kg`, `${t('Peak')} ${sig(o.peak_stress_mpa, 4)} MPa, ${t('p99')} ${sig(o.p99_stress_mpa, 4)} MPa, ${t('displacement')} ${sig(o.max_displacement_mm, 3)} mm`, `${t('Process violations')}: ${Object.entries(man).map(([k, v]) => `${k} ${v}`).join(', ') || t('none')}`, ...(o.notes ?? []).slice(0, 2)] : [t('Select an outcome to see its details.')]);
      };
      gen.onChange(paint);
      sim.onChange(paint);
      docStore.onChange(paint);
      paint();
      return { show: () => { void sim.loadLibrary(); void gen.loadLimits(); void sim.refresh(); } };
    },
  };
}
