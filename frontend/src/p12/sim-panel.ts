import type { DockPanel } from '../ui/dock';
import { el, patchList, q, setClass, setHidden, setText } from '../ui/dom';
import { t } from '../ui/i18n';
import { toast } from '../ui/toast';
import { docStore } from '../ui/doc-store';
import { button, buttons, checkCtl } from '../u8/ui';
import { view3d } from '../view3d/mount';
import { cam, frac, labelOf } from './cam-store';
import { fieldForm } from './fields';
import { b64f32, b64u8, docCam, fillSelect, fixed, guard, progressBar, reportBox, req, secs, section, text, type Json } from './kit';
import type { SimLayer } from './sim-layer';

export const simView: { layer: SimLayer | null } = { layer: null };

interface Collision { op: string; move: number; kind: string; at: number[]; abc?: number[] | null; distance_mm?: number }
interface SimResult {
  mode: 'dexel' | 'voxel'; stock_volume_mm3?: number; removed_mm3?: number; final_volume_mm3?: number; min_distance_mm?: number | null;
  gouge?: { cells: number; max_depth_mm: number; area_mm2: number; first?: number[][] };
  collisions?: Collision[]; closest?: { holder_mm?: number; tool_mm?: number }; time_s?: number; time_simple_s?: number;
  per_op?: Array<{ op: string; removed_mm3: number; time_s: number; min_distance_mm?: number }>; grid?: { nx: number; ny: number; cell: number; origin: number[] }; snapshots?: number; warnings?: string[];
}
interface Snap { nx?: number; ny?: number; cell?: number; origin?: number[]; top?: string; bottom?: string; gouge?: string; mode?: string; points?: string; count?: number }
interface Pose { tip: number[]; axis: number[]; profile: number[][]; holder: number[][]; abc: number[] | null; move: number }

const KIND_TEXT: Record<string, string> = { holder_stock: 'Holder hits stock', holder_fixture: 'Holder hits fixture', shank_stock: 'Shank hits stock', travel: 'Out of travel', rapid_in_stock: 'Rapid in stock', flute_length: 'Past the flute length' };

export const simState: { job: string; result: SimResult | null; frame: number; frames: number; playing: boolean; setup: string } = { job: '', result: null, frame: 0, frames: 0, playing: false, setup: '' };

export function simPanel(): DockPanel {
  return {
    id: 'camsim', label: 'Simulation', icon: 'cam', order: 42,
    build(body) {
      body.classList.add('u8-panel', 'xw-panel');
      const note = el('<p class="u8-note"></p>');
      setText(note, t('Open a part or assembly and make toolpaths to simulate them.'));
      const live = el('<div class="u8-live cm-live"></div>');
      body.append(note, live);
      const paintShell = (): void => { const on = !!docStore.current(); setHidden(note, on); setHidden(live, !on); };

      const sRun = section('Simulation');
      const setupRow = el('<label class="cv-field"><span></span><select class="cv-input"></select></label>');
      setText(q(setupRow, 'span'), t('Setup'));
      const setupSel = q<HTMLSelectElement>(setupRow, 'select');
      setupSel.addEventListener('change', () => { cam.select(setupSel.value, ''); });
      const machineRow = el('<label class="cv-field"><span></span><select class="cv-input"></select></label>');
      setText(q(machineRow, 'span'), t('Machine model'));
      const machineSel = q<HTMLSelectElement>(machineRow, 'select');
      const opts = fieldForm([
        { name: 'cell', type: 'number', label: 'Grid cell (0 is automatic)', unit: 'mm', min: 0, max: 50 },
        { name: 'tolerance', type: 'number', label: 'Tolerance', unit: 'mm', min: 0.0001, max: 5 },
        { name: 'gouge_tolerance', type: 'number', label: 'Gouge tolerance', unit: 'mm', min: 0, max: 5 },
        { name: 'snapshots', type: 'int', label: 'Snapshots', min: 2, max: 200 },
      ], () => undefined);
      opts.set({ cell: 0, tolerance: 0.01, gouge_tolerance: 0.01, snapshots: 40 });
      const bar = progressBar();
      const report = reportBox(7);
      sRun.body.append(setupRow, machineRow, opts.el, buttons(button('Run simulation', () => { void run(); }, 'primary')), bar.el, report.el);

      const sIssues = section('Collisions and gouges');
      const issues = el('<div class="u8-list cm-list" role="listbox" aria-label="Collisions"></div>');
      const issuesEmpty = el('<p class="u8-note cm-empty"></p>');
      setText(issuesEmpty, t('Nothing to show until a simulation has run.'));
      sIssues.body.append(issues, issuesEmpty);

      const sPlay = section('Player');
      const slider = el<HTMLInputElement>('<input class="cm-slider" type="range" min="0" max="1" value="0" aria-label="Simulation position">');
      const out = el('<output class="cm-out"></output>');
      setText(out, '0 / 0');
      const row = el('<div class="cm-sliderrow"><span class="cm-sl-label"></span></div>');
      setText(q(row, '.cm-sl-label'), t('Step'));
      row.append(slider, out);
      const playBtn = button('Play', () => toggle());
      const showStock = checkCtl('Show the stock', true, () => { simView.layer?.setShown(showStock.get()); });
      const hideModel = checkCtl('Hide the model', false, () => { view3d()?.vp?.setBodiesHidden(hideModel.get()); });
      sPlay.body.append(row, buttons(button('Start', () => { void go(0); }), button('Back', () => { void go(simState.frame - 1); }), playBtn, button('Next', () => { void go(simState.frame + 1); }), button('End', () => { void go(simState.frames); })), showStock.el, hideModel.el);

      live.append(sRun.root, sIssues.root, sPlay.root);

      const snaps = new Map<number, Snap>();
      const poses = new Map<number, Pose>();
      let timer = 0;
      let seq = 0;

      const jobBase = (): string => docCam(`/simulate/${encodeURIComponent(simState.job)}`);

      async function run(): Promise<void> {
        const s = cam.setup();
        if (!s) { toast(t('Add a setup and make toolpaths first.'), 'info'); return; }
        stop();
        snaps.clear(); poses.clear();
        const o = opts.read();
        const body: Json = { setup: s.id, ops: [], cell: o.cell ?? 0, tolerance: o.tolerance ?? 0.01, gouge_tolerance: o.gouge_tolerance ?? 0.01, snapshots: o.snapshots ?? 40 };
        if (machineSel.value && s.machine === 'mill5') body.machine = machineSel.value;
        const first = await guard(() => req<Json>('POST', docCam('/simulate'), body));
        if (!first) return;
        simState.job = String(first.job ?? '');
        simState.setup = s.id;
        bar.onCancel(() => { void req('POST', `${jobBase()}/cancel`).catch(() => undefined); });
        bar.set(0, `${t('Simulating')} · 0 %`, true);
        let res: Json | null = null;
        for (let i = 0; i < 12000; i++) {
          res = await req<Json>('GET', jobBase()).catch(() => null);
          if (!res) break;
          const f = frac(res.progress as number);
          bar.set(f, `${String(res.phase ?? t('Simulating'))} · ${Math.round(f * 100)} %`, true);
          if (!['running', 'queued'].includes(String(res.state))) break;
          await new Promise((r) => setTimeout(r, 250));
        }
        bar.set(1, '', false);
        if (!res) { toast(t('The simulation answer was lost.'), 'error'); return; }
        if (res.state !== 'done') { report.set([`${t('Simulation')} ${String(res.state)}`, String(res.error ?? res.message ?? '')], res.state === 'failed'); return; }
        const r = res.result as SimResult;
        simState.result = r;
        simState.frames = Number(r.snapshots ?? 0);
        slider.max = String(Math.max(1, simState.frames));
        paintReport(r);
        paintIssues(r);
        await go(0);
      }

      function paintReport(r: SimResult): void {
        const g = r.gouge;
        const c = r.collisions ?? [];
        report.set([
          `${t('Removed')} ${fixed(r.removed_mm3, 5)} mm3 ${t('of')} ${fixed(r.stock_volume_mm3, 5)} mm3`,
          `${t('Closest to the model')} ${fixed(r.min_distance_mm, 4)} mm`,
          g ? `${t('Gouges')}: ${g.cells} ${t('cells')}, ${t('deepest')} ${fixed(g.max_depth_mm, 3)} mm, ${fixed(g.area_mm2, 4)} mm2` : `${t('Gouges')}: -`,
          `${t('Collisions')}: ${c.length}`,
          r.closest ? `${t('Holder clearance')} ${fixed(r.closest.holder_mm, 3)} mm, ${t('tool')} ${fixed(r.closest.tool_mm, 3)} mm` : '',
          `${t('Machining time')} ${secs(r.time_s)}`,
          ...(r.warnings ?? []).slice(0, 1),
        ].slice(0, 7), (g?.cells ?? 0) > 0 || c.length > 0);
      }

      function paintIssues(r: SimResult | null): void {
        const rows: Array<{ key: string; label: string; sub: string; at: number[]; abc?: number[] | null }> = [];
        const g = r?.gouge;
        if (g && g.cells > 0) (g.first ?? []).slice(0, 20).forEach((p, i) => rows.push({ key: `g${i}`, label: t('Gouge'), sub: `${fixed(p[0], 3)} ${fixed(p[1], 3)} ${fixed(p[2], 3)}`, at: p }));
        (r?.collisions ?? []).slice(0, 60).forEach((c, i) => rows.push({ key: `c${i}`, label: t(KIND_TEXT[c.kind] ?? c.kind), sub: `${c.op} · ${t('move')} ${c.move}`, at: c.at, abc: c.abc }));
        setHidden(issuesEmpty, rows.length > 0 || !!r);
        if (r && !rows.length) setText(issuesEmpty, t('No gouges and no collisions.'));
        setHidden(issuesEmpty, rows.length > 0);
        patchList(issues, rows, {
          key: (x) => x.key,
          create: (x) => {
            const rr = el('<div class="u8-row cm-row-i" role="option"><span class="u8-row-sub"></span><span class="u8-row-name"></span></div>');
            rr.addEventListener('click', () => { simView.layer?.poseTool(x.at, null); });
            return rr;
          },
          update: (rr, x) => { setText(q(rr, '.u8-row-sub'), x.key.startsWith('g') ? 'G' : 'C'); setText(q(rr, '.u8-row-name'), `${x.label} · ${x.sub}`); },
        });
      }

      async function snap(n: number): Promise<Snap | null> {
        const have = snaps.get(n);
        if (have) return have;
        const s = await req<Snap>('GET', `${jobBase()}/snapshot/${n}`).catch(() => null);
        if (s) snaps.set(n, s);
        return s;
      }

      async function pose(n: number): Promise<Pose | null> {
        const have = poses.get(n);
        if (have) return have;
        const p = await req<Pose>('GET', `${jobBase()}/tool/${n}`).catch(() => null);
        if (p) poses.set(n, p);
        return p;
      }

      async function go(n: number): Promise<void> {
        const layer = simView.layer;
        if (!layer || !simState.job) return;
        const k = Math.max(0, Math.min(simState.frames, n));
        const my = ++seq;
        const [s, p] = await Promise.all([snap(k), pose(k)]);
        if (my !== seq || !s) return;
        const s0 = k === 0 ? s : snaps.get(0) ?? s;
        const wcs = cam.wcsOf(simState.setup);
        if (s.mode === 'voxel' || s.points) {
          layer.showVoxels(b64f32(s.points ?? ''), wcs);
        } else if (s.nx && s.ny && s.cell && s.origin) {
          const top = b64f32(s.top ?? '');
          const g = { nx: s.nx, ny: s.ny, cell: s.cell, origin: s.origin };
          if (!layer.ready || layer.info?.nx !== g.nx || layer.info?.ny !== g.ny) {
            const t0 = b64f32(s0.top ?? s.top ?? '');
            const b0 = b64f32(s0.bottom ?? '');
            let hi = -Infinity, lo = Infinity;
            for (const v of t0) if (Number.isFinite(v)) { hi = Math.max(hi, v); lo = Math.min(lo, v); }
            for (const v of b0) if (Number.isFinite(v)) lo = Math.min(lo, v);
            for (const v of top) if (Number.isFinite(v)) lo = Math.min(lo, v);
            layer.build(g, wcs, [Number.isFinite(lo) ? lo : 0, Number.isFinite(hi) ? hi : 1]);
          }
          const mask = s.gouge ? b64u8(s.gouge) : null;
          layer.show(top, mask && mask.length ? mask : null);
        }
        if (p) {
          if (k === 0 || !layer.hasTool) layer.setTool(p.profile, p.holder);
          layer.poseTool(p.tip, p.axis);
        }
        simState.frame = k;
        slider.value = String(k);
        setText(out, `${k} / ${simState.frames}`);
      }

      function stop(): void { if (timer) { clearInterval(timer); timer = 0; } simState.playing = false; setText(playBtn, t('Play')); }

      function toggle(): void {
        if (timer) { stop(); return; }
        if (!simState.job) return;
        simState.playing = true;
        setText(playBtn, t('Pause'));
        if (simState.frame >= simState.frames) void go(0);
        timer = window.setInterval(() => {
          if (simState.frame >= simState.frames) { stop(); return; }
          void go(simState.frame + 1);
        }, 160);
      }

      slider.addEventListener('input', () => { stop(); void go(Number(slider.value)); });

      const paint = (): void => {
        paintShell();
        fillSelect(setupSel, cam.setups.map((s) => [s.id, labelOf(s)] as [string, string]));
        if (cam.setupId && setupSel.value !== cam.setupId && document.activeElement !== setupSel) setupSel.value = cam.setupId;
        fillSelect(machineSel, cam.machines.map((m) => [m.id, m.name] as [string, string]));
        const five = cam.setup()?.machine === 'mill5';
        setClass(machineRow, 'is-off', !five);
      };
      cam.onChange(paint);
      docStore.onChange(() => { paintShell(); if (!docStore.current()) { stop(); simView.layer?.reset(); simState.job = ''; simState.result = null; paintIssues(null); } });
      paintShell();
      paint();
      paintIssues(null);
      void text;
    },
  };
}
