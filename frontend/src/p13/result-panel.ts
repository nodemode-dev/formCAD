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
import { fillSelect, reportBox, section, SI } from './kit';
import { rampCss } from './result-layer';
import { sim, type DisplayPayload, type Json, type Probe, type ResultField } from './sim-store';

const RAMPS: Array<[string, string]> = [['sequential', 'Sequential'], ['diverging', 'Diverging'], ['deviation', 'Green to red'], ['wall', 'Red to blue']];
const FIELD_LABEL: Record<string, string> = { disp: 'Displacement', disp_mag: 'Displacement size', vm: 'Von Mises stress', s1: 'Maximum principal stress', reaction: 'Reaction force', mode_shape: 'Mode shape', temperature: 'Temperature', flux_mag: 'Heat flux size', frequency: 'Frequency', load_factor: 'Load factor' };

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
      const summary = reportBox(10);
      sSum.body.append(summary.el);

      const sRep = section('Report');
      const repMsg = reportBox(2);
      sRep.body.append(buttons(button('Report as HTML...', () => { void report('html'); }), button('Report as PDF...', () => { void report('pdf'); })), repMsg.el);

      live.append(sPlot.root, sSec.root, sProbe.root, sSum.root, sRep.root);

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
          const rows = fields.map((f) => [f.name, fieldLabel(f)] as [string, string]);
          fillSelect(fieldSel.input as HTMLSelectElement, rows);
          const sm = (r.summary ?? {}) as Json;
          const flat: Array<[string, string]> = [];
          const walk = (o: unknown, pre: string): void => {
            if (typeof o === 'number') flat.push([pre, SI(o, '')]);
            else if (typeof o === 'string') flat.push([pre, o]);
            else if (Array.isArray(o)) flat.push([pre, o.map((x) => (typeof x === 'number' ? SI(x, '') : String(x))).join(' ')]);
            else if (o && typeof o === 'object') for (const [k, v] of Object.entries(o as Json)) walk(v, pre ? `${pre} ${k}` : k);
          };
          walk(sm, '');
          const lines = flat.slice(0, 10).map(([k, v]) => `${k.replace(/_/g, ' ')}: ${v}`);
          summary.set(lines);
          const mf = fields.find((f) => (f.modes ?? 0) > 0);
          const first = fields.find((f) => f.name === 'vm') ?? fields.find((f) => f.name === 'temperature') ?? fields.find((f) => f.name === 'disp_mag') ?? fields[0];
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
