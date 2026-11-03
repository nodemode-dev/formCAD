import { api } from '../io/api';
import { docStore } from '../ui/doc-store';
import type { DockPanel } from '../ui/dock';
import { el, patchList, q, setValue } from '../ui/dom';
import { icon } from '../ui/icons';
import { t } from '../ui/i18n';
import { toast } from '../ui/toast';
import { view3d } from '../view3d/mount';
import type { AnalysisColors, AnalysisState, Ramp } from './analysis-colors';
import { text } from './net';
import { button, buttons, checkCtl, fmt, numberCtl, readout, section, selectCtl } from './ui';

const MODES: ReadonlyArray<readonly [string, string]> = [
  ['zebra', 'Zebra stripes'], ['isophote', 'Isophote bands'], ['gaussian', 'Gaussian curvature'], ['mean', 'Mean curvature'], ['draft', 'Draft angle'], ['deviation', 'Surface deviation'],
];
const RAMP_OF: Record<string, string> = { zebra: 'zebra', isophote: 'zebra', gaussian: 'diverging', mean: 'diverging', draft: 'draft', deviation: 'deviation' };
const PULLS: ReadonlyArray<readonly [string, string]> = [['z', '+Z'], ['-z', '-Z'], ['x', '+X'], ['-x', '-X'], ['y', '+Y'], ['-y', '-Y']];

export function analysisPanel(colors: () => AnalysisColors | null): DockPanel {
  return {
    id: 'analysis3d',
    label: 'Surface Analysis',
    icon: 'csSeam',
    order: 42,
    build(body) {
      const mode = selectCtl('Analysis', MODES, () => sync());
      const only = checkCtl('Selected surfaces only', false);
      const dir = selectCtl('Stripe direction', [['vertical', 'Vertical'], ['horizontal', 'Horizontal']]);
      const band = numberCtl('Stripe width (deg)', 6);
      const pull = selectCtl('Pull direction', PULLS);
      const lower = numberCtl('Lower limit (deg)', -3);
      const upper = numberCtl('Upper limit (deg)', 3);
      const signed = checkCtl('Signed distance', false);
      const good = numberCtl('Good distance', 0);
      const bad = numberCtl('Bad distance', 0);
      const target = readout('Target surface');
      const useTarget = button('Use selection as target', () => { const b = view3d()?.vp?.sel.bodies[0]; if (b === undefined) { toast(t('Select the target surface first.'), 'info'); return; } targetHandle = b; sync(); });
      let targetHandle: number | null = null;
      const params = section('Settings');
      params.root.classList.add('u8-params');
      params.body.append(mode.el, only.el, dir.el, band.el, pull.el, lower.el, upper.el, signed.el, good.el, bad.el, target.el, useTarget);

      const rampSec = section('Colour ramp');
      const rampName = readout('Ramp');
      const stopsEl = el('<div class="u8-stops"></div>');
      const rmin = numberCtl('Lower limit', 0);
      const rmax = numberCtl('Upper limit', 0);
      const rcenter = numberCtl('Centre', 0);
      const rsym = checkCtl('Symmetric about the centre', false);
      let work: Ramp | null = null;
      const paintStops = (): void => {
        const stops = work?.stops ?? [];
        patchList(stopsEl, stops.map((s, i) => ({ s, i })), {
          key: (r) => `s${r.i}`,
          create: (r) => {
            const row = el('<div class="u8-stop"><input class="cv-input u8-num" type="text" inputmode="decimal" aria-label="Position"><input class="u8-color" type="color" aria-label="Colour"><button class="u8-x" type="button" aria-label="Remove stop">' + icon('close', 12) + '</button></div>');
            const pos = q<HTMLInputElement>(row, 'input.cv-input');
            const col = q<HTMLInputElement>(row, 'input.u8-color');
            pos.addEventListener('change', () => { const v = Number(pos.value.replace(',', '.')); if (work && Number.isFinite(v)) { work.stops[r.i][0] = Math.min(1, Math.max(0, v)); } });
            col.addEventListener('input', () => { if (work) work.stops[r.i][1] = col.value; });
            q(row, '.u8-x').addEventListener('click', () => { if (work && work.stops.length > 2) { work.stops.splice(r.i, 1); paintStops(); } });
            return row;
          },
          update: (node, r) => { setValue(q<HTMLInputElement>(node, 'input.cv-input'), String(r.s[0])); setValue(q<HTMLInputElement>(node, 'input.u8-color'), r.s[1]); },
        });
      };
      const loadRamp = (): void => {
        const st = state;
        const name = RAMP_OF[mode.get()];
        rampName.set(name);
        const r = st?.ramps[name];
        work = r ? JSON.parse(JSON.stringify(r)) as Ramp : null;
        if (!work) return;
        rmin.set(work.min); rmax.set(work.max); rcenter.set(work.center); rsym.set(work.symmetric);
        paintStops();
      };
      const addStop = button('Add stop', () => { if (!work) return; const s = work.stops; const last = s[s.length - 1]; s.push([Math.min(1, last[0]), last[1]]); paintStops(); });
      const rampOut = (): Ramp | null => {
        if (!work) return null;
        return { ...work, min: rmin.get(), max: rmax.get(), center: rcenter.get(), symmetric: rsym.get() };
      };
      rampSec.body.append(rampName.el, stopsEl, addStop, rmin.el, rmax.el, rcenter.el, rsym.el);

      const stats = section('Result');
      const rs = { surfaces: readout('Surfaces'), verts: readout('Vertices'), lo: readout('Lowest'), hi: readout('Highest'), mean: readout('Mean'), comb: readout('Curvature comb') };
      stats.body.append(rs.surfaces.el, rs.verts.el, rs.lo.el, rs.hi.el, rs.mean.el, rs.comb.el);
      const combScale = numberCtl('Comb height scale', 1);
      const combSec = section('Curvature comb');
      combSec.body.append(combScale.el);

      let state: AnalysisState | null = null;
      const sync = (): void => {
        const m = mode.get();
        const show = (c: HTMLElement, on: boolean): void => { if (c.hidden !== !on) c.hidden = !on; };
        show(dir.el, m === 'zebra'); show(band.el, m === 'zebra' || m === 'isophote');
        show(pull.el, m === 'draft'); show(lower.el, m === 'draft'); show(upper.el, m === 'draft');
        show(signed.el, m === 'deviation'); show(good.el, m === 'deviation'); show(bad.el, m === 'deviation'); show(target.el, m === 'deviation'); show(useTarget, m === 'deviation');
        target.set(targetHandle === null ? '-' : `#${targetHandle}`);
        loadRamp();
      };

      const handles = (): number[] => {
        if (!only.get()) return [];
        const vp = view3d()?.vp;
        return vp ? [...vp.sel.bodies, ...vp.sel.faces.map((f) => f.body)] : [];
      };
      const run = async (name: string, args: Record<string, unknown>): Promise<boolean> => {
        const id = docStore.activeId;
        if (!id) return false;
        try {
          await api.runCommand(id, name, args);
          return true;
        } catch (e) {
          toast(text(e), 'error');
          return false;
        }
      };
      const show = async (): Promise<void> => {
        const m = mode.get();
        const ramp = rampOut();
        const hs = handles();
        let ok = false;
        if (m === 'zebra' || m === 'isophote') ok = await run('zebra', { style: m, handles: hs, direction: dir.get(), band: band.get() ?? 6, ramp });
        else if (m === 'gaussian' || m === 'mean') ok = await run('curvatureanalysis', { measure: m, handles: hs, ramp });
        else if (m === 'draft') ok = await run('draftanalysis', { handles: hs, pull: pull.get(), lower: lower.get() ?? -3, upper: upper.get() ?? 3, ramp });
        else {
          if (targetHandle === null) { toast(t('Choose a target surface first.'), 'info'); return; }
          ok = await run('deviation', { source: hs, target: targetHandle, signed: signed.get(), good: good.get() || null, bad: bad.get() || null, ramp });
        }
        if (ok) await view3d()?.with3d(() => undefined);
        if (ok) await colors()?.refresh();
      };
      const off = async (): Promise<void> => { if (await run('analysisoff', {})) await colors()?.refresh(); };
      const saveRamp = async (): Promise<void> => {
        const r = rampOut();
        if (!r) return;
        if (await run('analysisramp', { name: RAMP_OF[mode.get()], ramp: r })) { toast(t('Ramp stored in the document.'), 'info'); await colors()?.refresh(); }
      };
      const resetRamp = async (): Promise<void> => {
        if (await run('analysisramp', { name: RAMP_OF[mode.get()], reset: true })) await colors()?.refresh();
      };
      const comb = async (): Promise<void> => {
        const vp = view3d()?.vp;
        const hs = vp ? vp.sel.edges.map((e) => e.body) : [];
        const edges = vp ? vp.sel.edges.map((e) => ({ body: e.body, edge: e.edge })) : [];
        const curves = (await selectedCurves());
        if (!curves.length && !edges.length) { toast(t('Select curves or edges first.'), 'info'); return; }
        void hs;
        if (await run('curvaturecomb', { handles: curves, edges, scale: combScale.get() ?? 1 })) { await view3d()?.with3d(() => undefined); await colors()?.refresh(); }
      };
      async function selectedCurves(): Promise<number[]> {
        const id = docStore.activeId;
        if (!id) return [];
        try { return (await api.getSelection(id)).handles.map(Number); } catch { return []; }
      }
      const actions = buttons(button('Show analysis', () => void show(), 'primary'), button('Analysis off', () => void off()));
      const rampActions = buttons(button('Save ramp', () => void saveRamp()), button('Restore default', () => void resetRamp()));
      const combActions = buttons(button('Comb on selection', () => void comb()));
      combSec.body.append(combActions);
      rampSec.body.append(rampActions);
      body.classList.add('u8-panel');
      body.append(params.root, actions, rampSec.root, stats.root, combSec.root);

      const paint = (): void => {
        const c = colors();
        const m = c?.meta;
        rs.surfaces.set(m ? String(m.bodies.length) : '-');
        const st = m?.stats ?? {};
        rs.verts.set(m ? String(st.count ?? '-') : '-');
        rs.lo.set(m ? fmt(st.min as number | null) : '-');
        rs.hi.set(m ? fmt(st.max as number | null) : '-');
        rs.mean.set(m ? fmt(st.mean as number | null) : '-');
        const ci = c?.combInfo;
        rs.comb.set(ci ? `${ci.teeth} ${t('teeth')} · ${t('max')} ${fmt(ci.max)} · ${ci.inflections} ${t('inflections')}` : '-');
      };
      const bind = (): void => {
        const c = colors();
        if (!c) { window.setTimeout(bind, 400); return; }
        c.onChange = paint;
        void c.refresh().then((st) => { state = st; loadRamp(); paint(); });
      };
      document.addEventListener('formcad:view3d-created', () => window.setTimeout(bind, 50));
      docStore.onChange(() => { const c = colors(); if (c) void c.refresh().then((st) => { state = st; loadRamp(); paint(); }); });
      sync();
      bind();
      return { show: () => { void colors()?.refresh().then((st) => { state = st; loadRamp(); paint(); }); } };
    },
  };
}
