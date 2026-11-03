import * as THREE from 'three';
import { docStore } from '../ui/doc-store';
import type { DockPanel } from '../ui/dock';
import { pickPath } from '../ui/file-dialogs';
import { el, patchList, q, setClass, setHidden, setText } from '../ui/dom';
import { t } from '../ui/i18n';
import { toast } from '../ui/toast';
import { button, buttons, checkCtl, selectCtl } from '../u8/ui';
import { view3d } from '../view3d/mount';
import { fieldForm } from '../p12/fields';
import { lastCmdError, runCmd } from '../p10/kit';
import { chart } from './chart';
import { fillSelect, reportBox, section, SI } from './kit';
import { curvesOf, summaryLines, type Curve } from './summary';
import { rampCss } from './result-layer';
import { sim, type DisplayPayload, type Json, type Probe, type ResultField } from './sim-store';

const RAMPS: Array<[string, string]> = [['sequential', 'Sequential'], ['diverging', 'Diverging'], ['deviation', 'Green to red'], ['wall', 'Red to blue']];
const FIELD_LABEL: Record<string, string> = { disp: 'Displacement', disp_mag: 'Displacement size', vm: 'Von Mises stress', s1: 'Maximum principal stress', reaction: 'Reaction force', mode_shape: 'Mode shape', temperature: 'Temperature', flux_mag: 'Heat flux size', frequency: 'Frequency', load_factor: 'Load factor', pressure: 'Pressure', speed: 'Speed', velocity: 'Velocity', arrival_time: 'Fill arrival time', fill_pressure: 'Fill pressure at 98 percent', thickness: 'Wall thickness', plastic_strain: 'Equivalent plastic strain', contact_force: 'Contact force', life_repeats: 'Life in repeats', damage: 'Damage per repeat', log10_life_cycles: 'Log10 of life in cycles', stress: 'Von Mises stress of the outcome' };

export const resultState: { data: DisplayPayload | null; probes: Probe[]; study: string; field: string; mode: number } = { data: null, probes: [], study: '', field: '', mode: 0 };

const fieldLabel = (f: ResultField): string => `${FIELD_LABEL[f.name] ?? f.name.replace(/_/g, ' ')}${f.unit ? ` (${f.unit})` : ''}`;

export function resultPanel(): DockPanel {
  return {
    id: 'simresult', label: 'Simulation results', icon: 'simulate', order: 45,
    build(body) {
      body.classList.add('u8-panel', 'xw-panel');
      const note = el('<p class="u8-note"></p>');
      setText(note, t('Solve a study to see results.'));
      const live = el('<div class="u8-live cm-live"></div>');
      body.append(note, live);

      const sPlot = section('Plot');
      const head = el('<p class="u8-note sm-head"></p>');
      const fieldSel = selectCtl('Result', []);
      const modeSel = selectCtl('Mode', []);
      const rampSel = selectCtl('Colours', RAMPS);
      const legend = el('<div class="sm-legend"><div class="sm-legend-bar"></div><div class="sm-legend-ends"><span class="sm-lo"></span><span class="sm-mid"></span><span class="sm-hi"></span></div></div>');
      const range = fieldForm([
        { name: 'lo', type: 'number', label: 'Lower limit', nullable: true },
        { name: 'hi', type: 'number', label: 'Upper limit', nullable: true },
      ], () => applyRange());
      const deformed = checkCtl('Show the deformed shape', true, () => paintAmp());
      const scale = fieldForm([{ name: 'scale', type: 'number', label: 'Deformation scale', default: 1, min: 0 }], () => paintAmp());
      const animate = checkCtl('Animate', false, () => toggleAnim());
      const speed = el<HTMLInputElement>('<input class="cm-slider" type="range" min="1" max="40" value="10" aria-label="Animation speed">');
      const speedRow = el('<div class="cm-sliderrow"><span class="cm-sl-label"></span></div>');
      setText(q(speedRow, '.cm-sl-label'), t('Speed'));
      speedRow.append(speed);
      const showBody = checkCtl('Show the original body', false, () => { view3d()?.vp?.setBodiesHidden(!showBody.get()); });
      const showWire = checkCtl('Show mesh lines on the result', false, () => { sim.layer?.setWire(showWire.get()); });
      sPlot.body.append(head, fieldSel.el, modeSel.el, rampSel.el, legend, range.el, deformed.el, scale.el, animate.el, speedRow, showBody.el, showWire.el);

      const sSec = section('Section');
      const secOn = checkCtl('Cut the result with the section plane', false, () => applySection());
      const secFlip = checkCtl('Flip the side', false, () => applySection());
      const secOff = el<HTMLInputElement>('<input class="cm-slider" type="range" min="0" max="1000" value="500" aria-label="Section position">');
      secOff.addEventListener('input', () => applySection());
      const secRow = el('<div class="cm-sliderrow"><span class="cm-sl-label"></span></div>');
      setText(q(secRow, '.cm-sl-label'), t('Position'));
      secRow.append(secOff);
      sSec.body.append(secOn.el, secFlip.el, secRow);

      const sProbe = section('Probes');
      const probeOn = checkCtl('Click the result to probe it', false, () => armProbe());
      const probeList = el('<div class="u8-list sm-probes" role="listbox" aria-label="Probes"></div>');
      const probeEmpty = el('<p class="u8-note cm-empty"></p>');
      setText(probeEmpty, t('No probes yet.'));
      sProbe.body.append(probeOn.el, probeList, probeEmpty, buttons(button('Clear probes', () => { resultState.probes = []; paintProbes(); })));

      const sSum = section('Summary');
      const summary = reportBox(16);
      sSum.body.append(summary.el);

      const sHist = section('Study history');
      const curveSel = selectCtl('Curve', [['', '-']]);
      const plot = chart();
      sHist.body.append(curveSel.el, plot.el);

      const sApply = section('Apply to the document');
      const applyForm = fieldForm([
        { name: 'name', type: 'text', label: 'Body name', default: 'Optimised shape' },
        { name: 'smooth', type: 'int', label: 'Smoothing passes', default: 8, min: 0, max: 50 },
        { name: 'sigma', type: 'number', label: 'Smoothing strength', default: 0.6, min: 0, max: 5 },
        { name: 'max_triangles', type: 'int', label: 'Most triangles', default: 20000, min: 100 },
        { name: 'to_solid', type: 'bool', label: 'Also make a solid body', default: false },
      ], () => undefined);
      applyForm.set({});
      const applyNote = el('<p class="u8-note sm-apply-note"></p>');
      const applyBtn = button('Apply the outcome', () => { void applyOutcome(); }, 'primary');
      (applyBtn as HTMLButtonElement).disabled = true;
      const applyMsg = reportBox(2);
      sApply.body.append(applyNote, applyForm.el, buttons(applyBtn), applyMsg.el);

      const sRep = section('Report');
      const repMsg = reportBox(2);
      sRep.body.append(buttons(button('Report as HTML...', () => { void report('html'); }), button('Report as PDF...', () => { void report('pdf'); })), repMsg.el);

      live.append(sPlot.root, sSec.root, sProbe.root, sSum.root, sHist.root, sRep.root, sApply.root);

      let curves: Curve[] = [];
      let topo = false;
      let fields: ResultField[] = [];
      let modes: Array<{ index: number; frequency_hz?: number; load_factor?: number }> = [];
      let loadedFor = '';
      let ticket = 0;
      let raf = 0;
      let t0 = 0;
      let armed = false;

      const fetchPlot = async (): Promise<void> => {
        const s = sim.study();
        const layer = sim.layer;
        if (!s || !layer || !fieldSel.get()) return;
        const my = ++ticket;
        const d = await sim.display(s.id, { field: fieldSel.get(), mode: Number(modeSel.get() || 0), ramp: rampSel.get(), scale: 'auto' });
        if (!d || my !== ticket) return;
        if (d.unit === 'Pa' && Math.max(Math.abs(d.min), Math.abs(d.max)) < 1e4) { d.display_unit = 'Pa'; d.display_factor = 1; }
        resultState.data = d;
        resultState.study = s.id;
        resultState.field = fieldSel.get();
        resultState.mode = Number(modeSel.get() || 0);
        layer.setData(d);
        layer.setBodyShown(true);
        scale.set({ scale: Number((d.scale ?? 1).toPrecision(4)) });
        range.set({ lo: null, hi: null });
        paintAmp();
        paintLegend(d);
        if (!showBody.get()) view3d()?.vp?.setBodiesHidden(true);
        const vp = view3d()?.vp;
        if (vp && !modes.length) vp.invalidate();
      };

      function paintLegend(d: DisplayPayload): void {
        const bar = q(legend, '.sm-legend-bar');
        const css = rampCss(d.ramp);
        if (bar.style.getPropertyValue('--sm-ramp') !== css) bar.style.setProperty('--sm-ramp', css);
        const f = d.display_factor ?? 1, u = d.display_unit ?? d.unit;
        const lo = (sim.layer?.lower ?? d.min) * f, hi = (sim.layer?.upper ?? d.max) * f;
        setText(q(legend, '.sm-lo'), SI(lo, u));
        setText(q(legend, '.sm-mid'), d.mean !== undefined ? `${t('mean')} ${SI(d.mean * f, u)}` : '');
        setText(q(legend, '.sm-hi'), SI(hi, u));
        setText(head, `${d.label || d.field}${u ? ` (${u})` : ''}`);
      }

      function applyRange(): void {
        const d = resultState.data;
        if (!d || !sim.layer) return;
        const v = range.read();
        const f = d.display_factor || 1;
        sim.layer.setRange(typeof v.lo === 'number' ? v.lo / f : null, typeof v.hi === 'number' ? v.hi / f : null, d.ramp.min ?? d.min, d.ramp.max ?? d.max);
        paintLegend(d);
      }

      function scaleNow(): number { const v = scale.read().scale; return typeof v === 'number' && v >= 0 ? v : 1; }

      function paintAmp(): void {
        if (raf) return;
        sim.layer?.setDeformation(deformed.get(), scaleNow());
      }

      function toggleAnim(): void {
        if (!animate.get()) { cancelAnimationFrame(raf); raf = 0; paintAmp(); return; }
        t0 = performance.now();
        const tick = (now: number): void => {
          const hz = Number(speed.value) / 10;
          const phase = Math.sin(((now - t0) / 1000) * hz * Math.PI * 2);
          sim.layer?.setPhase(phase, true, scaleNow());
          raf = requestAnimationFrame(tick);
        };
        raf = requestAnimationFrame(tick);
      }

      function applySection(): void {
        const vp = view3d()?.vp;
        const layer = sim.layer;
        if (!vp || !layer) return;
        const b = layer.bounds();
        const span = b ? Math.max(b.max[0] - b.min[0], b.max[1] - b.min[1], b.max[2] - b.min[2]) : 100;
        const off = (Number(secOff.value) / 1000 - 0.5) * span;
        vp.setSection(secOn.get(), secFlip.get(), off);
        layer.setClip(secOn.get() ? vp.kit.clip : []);
      }

      const ray = new THREE.Raycaster();
      const onDown = (e: PointerEvent): void => {
        const vp = view3d()?.vp;
        const layer = sim.layer;
        if (!armed || !vp || !layer || e.button !== 0 || !layer.shown) return;
        const r = vp.canvas.getBoundingClientRect();
        const ndc = new THREE.Vector2(((e.clientX - r.left) / r.width) * 2 - 1, -(((e.clientY - r.top) / r.height) * 2 - 1));
        ray.setFromCamera(ndc, vp.camera);
        const hit = ray.intersectObject(layer.pickTarget, false)[0];
        if (!hit) return;
        e.stopPropagation();
        void addProbe([hit.point.x, hit.point.y, hit.point.z]);
      };

      function armProbe(): void {
        const vp = view3d()?.vp;
        armed = probeOn.get();
        if (!vp) return;
        vp.canvas.removeEventListener('pointerdown', onDown, true);
        if (armed) vp.canvas.addEventListener('pointerdown', onDown, true);
      }

      async function addProbe(at: number[]): Promise<void> {
        const s = sim.study();
        if (!s) return;
        const r = await sim.probe(s.id, at, Number(modeSel.get() || 0));
        if (!r) return;
        if (r.inside === false) { toast(t('That point is outside the meshed body.'), 'error'); return; }
        const values: Array<[string, string]> = [];
        const walk = (o: unknown, pre: string): void => {
          if (typeof o === 'number') values.push([pre, SI(o, '')]);
          else if (Array.isArray(o) && o.every((x) => typeof x === 'number')) values.push([pre, (o as number[]).map((x) => SI(x, '')).join(' ')]);
          else if (o && typeof o === 'object') for (const [k, v] of Object.entries(o as Json)) if (k !== 'point' && k !== 'inside') walk(v, pre ? `${pre}.${k}` : k);
        };
        walk(r, '');
        if (!values.length) values.push([t('values'), t('not given for this study type')]);
        resultState.probes = [...resultState.probes, { point: at, values }].slice(-16);
        paintProbes();
      }

      function paintProbes(): void {
        patchList(probeList, resultState.probes.map((p, i) => ({ p, i })), {
          key: (r) => String(r.i),
          create: () => el('<div class="u8-row sm-probe"><span class="u8-row-sub"></span><span class="u8-row-name"></span></div>'),
          update: (n, r) => {
            setText(q(n, '.u8-row-sub'), `P${r.i + 1}`);
            const txt = `${r.p.point.map((x) => x.toFixed(2)).join(', ')} mm · ${r.p.values.map((v) => `${v[0]} ${v[1]}`).join(' · ')}`;
            setText(q(n, '.u8-row-name'), txt);
            if (n.title !== txt) n.title = txt;
          },
        });
        setHidden(probeEmpty, resultState.probes.length > 0);
        sim.layer?.setPins(resultState.probes.map((p) => p.point));
      }

      async function report(format: string): Promise<void> {
        const s = sim.study();
        if (!s) return;
        const path = await pickPath('save', t('Save the simulation report'), `${s.name || 'study'}.${format}`, [{ name: format === 'pdf' ? 'PDF document' : 'HTML page', extensions: [format] }], t('Save'));
        if (!path) return;
        const r = await sim.report(s.id, path, format);
        if (r) { repMsg.set([`${t('Report written')}: ${String(r.path ?? path)}`]); toast(t('Report written'), 'info'); } else repMsg.set([t('The report could not be written.')], true);
      }

      function plotCurve(): void { plot.set(curves.find((c) => c.id === curveSel.get()) ?? curves[0] ?? null); }
      curveSel.input.addEventListener('change', plotCurve);

      async function applyOutcome(): Promise<void> {
        const s = sim.study();
        if (!s || !topo) return;
        const v = applyForm.read();
        const args: Json = { study: s.id, name: String(v.name || 'Optimised shape'), smooth: v.smooth ?? 8, sigma: v.sigma ?? 0.6, max_triangles: v.max_triangles ?? 20000, to_solid: v.to_solid === true };
        applyMsg.set([t('Applying...')]);
        const r = await runCmd('TOPOAPPLY', args);
        if (r) { applyMsg.set([`${t('Applied')}: ${String(args.name)}`, ...summaryLines(r as Json, 1)]); toast(t('The optimised shape was added to the document.'), 'info'); } else applyMsg.set([lastCmdError() || t('The outcome could not be applied.')], true);
      }

      function paintFields(): void {
        const s = sim.study();
        const have = !!s && !!s.result;
        setHidden(note, have);
        setHidden(live, !have);
        if (!s || !s.result) { loadedFor = ''; sim.layer?.clear(); return; }
        const key = `${s.id}:${String(s.result)}:${String(s.status)}`;
        if (loadedFor === key) return;
        loadedFor = key;
        void sim.result(s.id, true).then(async (whole) => {
          const r = (whole?.result ?? null) as Json | null;
          if (!r || loadedFor !== key) return;
          fields = (Array.isArray(r.fields) ? r.fields : []) as ResultField[];
          const drawn = fields.filter((f) => !f.location || f.location === 'node');
          const rows = drawn.map((f) => [f.name, fieldLabel(f)] as [string, string]);
          fillSelect(fieldSel.input as HTMLSelectElement, rows);
          const sm = (r.summary ?? {}) as Json;
          summary.set(summaryLines(sm, 16));
          curves = curvesOf(sm, whole?.history);
          fillSelect(curveSel.input as HTMLSelectElement, curves.length ? curves.map((c) => [c.id, t(c.label)] as [string, string]) : [['', '-']]);
          plotCurve();
          topo = sim.topo(s.id);
          (applyBtn as HTMLButtonElement).disabled = !topo;
          setText(applyNote, topo ? t('Adds the optimised shape to the document as a mesh body, or as a solid when you ask for one.') : t('Only topology studies can be applied to the document.'));
          const mf = drawn.find((f) => (f.modes ?? 0) > 0);
          const first = ['vm', 'temperature', 'pressure', 'arrival_time', 'log10_life_cycles', 'disp_mag'].map((n) => drawn.find((f) => f.name === n)).find((f) => !!f) ?? drawn[0];
          if (first && !fieldSel.get()) fieldSel.set(first.name);
          if (first) fieldSel.set(first.name);
          const n = mf?.modes ?? 0;
          fillSelect(modeSel.input as HTMLSelectElement, n ? Array.from({ length: n }, (_, i) => [String(i), `${t('Mode')} ${i + 1}`] as [string, string]) : [['0', '-']]);
          await fetchPlot();
          fillModes();
        });
      }

      function fillModes(): void {
        modes = resultState.data?.modes ?? [];
        if (!modes.length) return;
        fillSelect(modeSel.input as HTMLSelectElement, modes.map((m) => [String(m.index), `${t('Mode')} ${m.index + 1} · ${m.frequency_hz !== undefined ? `${SI(m.frequency_hz, 'Hz')}` : m.load_factor !== undefined ? `${t('factor')} ${SI(m.load_factor, '')}` : ''}`] as [string, string]));
      }

      fieldSel.input.addEventListener('change', () => { void fetchPlot(); });
      modeSel.input.addEventListener('change', () => { void fetchPlot(); });
      rampSel.input.addEventListener('change', () => { void fetchPlot(); });

      sim.onChange(() => { setClass(live, 'is-busy', sim.running); paintFields(); void docStore.current(); });
      paintFields();
    },
  };
}
