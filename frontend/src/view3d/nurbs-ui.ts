import { api, call } from '../io/api';
import type { CommandLineState } from '../io/api';
import { commands } from '../ui/commands';
import { docStore } from '../ui/doc-store';
import { registerDockPanel } from '../ui/dock';
import { boolDiagPanel } from '../ui/panels/bool-diag-panel';
import { selection } from '../ui/panels/selection-bus';
import { toast } from '../ui/toast';
import { AnalysisLayer } from './analysis-layer';
import { CurveLayer, type PointMode } from './curve-layer';
import { diag, type DiagState } from './diag-store';
import { onView3d, view3d } from './mount';
import { fetchLast, polylinesOf, countOf, type SeamReport } from './nurbs-api';
import { SurfaceLayer } from './surface-layer';
import type { Vec3 } from './types';
import type { Viewport3D } from './viewport';
import { analysis as stripes } from '../u8/register';

const ui = (action: string): void => { document.dispatchEvent(new CustomEvent('formcad:ui', { detail: { action } })); };

let curves: CurveLayer | null = null;
let surfaces: SurfaceLayer | null = null;
let analysis: AnalysisLayer | null = null;
let mmPerUnit = 1;
const seen = new Map<string, number>();

registerDockPanel(boolDiagPanel(() => ui('panel:reveal:bool-diag')));

function attach(vp: Viewport3D): void {
  if (curves) return;
  surfaces = new SurfaceLayer(vp, () => stripes);
  curves = new CurveLayer(vp);
  analysis = new AnalysisLayer(vp.host, () => vp.invalidate());
  vp.addLayer(curves);
  vp.addLayer(surfaces);
  vp.addLayer(analysis);
  paintNaked(diag.state);
}

document.addEventListener('formcad:view3d-created', (e) => { attach((e as CustomEvent<{ vp: Viewport3D }>).detail.vp); });
onView3d((c) => { if (c.vp) attach(c.vp); });

function nakedOf(s: DiagState): { lines: Vec3[][]; count: number } {
  if (s.source === 'naked' && s.naked) return { lines: polylinesOf(s.naked.naked_edges), count: countOf(s.naked.naked_edges) };
  const r = s.report;
  if (!r) return { lines: [], count: 0 };
  const lines: Vec3[][] = [];
  let count = 0;
  for (const a of r.arguments ?? []) { lines.push(...polylinesOf(a.naked_edges as never)); count += countOf(a.naked_edges as never); }
  lines.push(...polylinesOf(r.result?.naked_edges as never));
  count += countOf(r.result?.naked_edges as never);
  return { lines, count };
}

function paintNaked(s: DiagState): void {
  if (!analysis) return;
  if (!s.highlight || s.source === 'none') { if (analysis.nakedEdgeCount) analysis.clearNaked(); return; }
  const n = nakedOf(s);
  analysis.setNaked(n.lines, mmPerUnit, n.count);
}

diag.onChange(paintNaked);

function showSeam(r: SeamReport, owners: number[] = []): void {
  analysis?.setSeam(r, mmPerUnit, [...owners, ...(r.bodies ?? [])]);
}

async function absorb(doc: string, output: string[]): Promise<void> {
  let last;
  try {
    last = await fetchLast(doc);
  } catch {
    return;
  }
  if (doc !== docStore.activeId) return;
  const before = seen.get(doc) ?? 0;
  if (last.seq <= before) return;
  seen.set(doc, last.seq);
  mmPerUnit = last.mm_per_unit || 1;
  const text = output.join('\n');
  if (/NAKEDEDGES/.test(text) && last.naked) {
    diag.setNaked(last.naked);
    void view3d()?.with3d(() => undefined);
    return;
  }
  const r = last.report;
  if (!r) return;
  if ('arguments' in r && r.arguments) {
    const checkOnly = /check: /i.test(text);
    if (!r.ok || checkOnly) {
      diag.setBoolean(r, checkOnly);
      void view3d()?.with3d(() => undefined);
    }
    return;
  }
  if ('g0' in r && 'max_gap' in r) {
    showSeam(r);
    void view3d()?.with3d(() => undefined);
  }
}

for (const name of ['formcad:command-state', 'formcad:cmdline-applied']) {
  document.addEventListener(name, (e) => {
    const d = (e as CustomEvent<{ doc: string; state: CommandLineState & { output?: string[] } }>).detail;
    if (d.doc !== docStore.activeId || d.state.active) return;
    const out = d.state.output ?? [];
    if (!out.length) return;
    void absorb(d.doc, out);
  });
}

document.addEventListener('formcad:scene-touched', (e) => {
  const d = (e as CustomEvent<{ doc: string; ids?: number[] }>).detail;
  if (d.doc === docStore.activeId && analysis && analysis.seamCount > 0) analysis.clearSeamsOf(d.ids ?? []);
});

let lastDoc: string | null = null;
docStore.onChange(() => {
  const id = docStore.activeId;
  if (id === lastDoc) return;
  lastDoc = id;
  analysis?.clear();
  curves?.reset();
  surfaces?.reset();
  diag.clear();
  if (!id) return;
  void fetchLast(id).then((l) => { seen.set(id, l.seq); mmPerUnit = l.mm_per_unit || 1; }).catch(() => undefined);
});

async function seamsOfSelection(): Promise<void> {
  const id = docStore.activeId;
  if (!id) return;
  const handles = new Set<number>([...selection.handles, ...(view3d()?.vp?.sel.bodies ?? [])]);
  if (!handles.size) { toast('Select a blend or match surface first.', 'info'); return; }
  try {
    const res = await call<{ mm_per_unit: number; bodies: Array<{ handle: number; name: string; source: { seams?: number[]; report?: { seams?: Record<string, SeamReport>; seam?: SeamReport } } | null }> }>('GET', `/api/docs/${encodeURIComponent(id)}/solids`);
    mmPerUnit = res.mm_per_unit || 1;
    let n = 0;
    for (const b of res.bodies) {
      if (!handles.has(b.handle)) continue;
      const rep = b.source?.report;
      const owners = [b.handle, ...(Array.isArray(b.source?.seams) ? b.source.seams : [])];
      for (const s of Object.values(rep?.seams ?? {})) { if (s && s.hair) { showSeam(s, owners); n++; } }
      if (rep?.seam?.hair) { showSeam(rep.seam, owners); n++; }
    }
    if (!n) toast('The selected surfaces carry no stored seam report. Run SEAMCHECK on two edges.', 'info');
    else void view3d()?.with3d(() => undefined);
  } catch (e) {
    toast(e instanceof Error ? e.message : 'The seams could not be read', 'error');
  }
}

const has = (): boolean => !!docStore.current();

const setPoints = (mode: PointMode): void => {
  curves?.setMode(mode);
  surfaces?.setOn(mode === 'cv');
};

async function toggleZebra(): Promise<void> {
  const id = docStore.activeId;
  if (!id) return;
  const on = stripes?.meta?.mode === 'zebra';
  try {
    const state = await api.runCommand(id, on ? 'analysisoff' : 'zebra', on ? {} : { style: 'zebra', handles: [], direction: 'vertical', band: 6 });
    if (state.error) { toast(state.error, 'error'); return; }
    await view3d()?.with3d(() => undefined);
    await stripes?.refresh();
  } catch (e) {
    toast(e instanceof Error ? e.message : 'The stripes could not be changed', 'error');
  }
}

commands.add({ id: 'u7-points-cv', label: 'Show Control Points', group: 'View', run: () => { void view3d()?.with3d(() => setPoints(curves?.mode === 'cv' ? 'off' : 'cv')); }, checked: () => curves?.mode === 'cv', enabled: has });
commands.add({ id: 'u7-points-ep', label: 'Show Edit Points', group: 'View', run: () => { void view3d()?.with3d(() => setPoints(curves?.mode === 'ep' ? 'off' : 'ep')); }, checked: () => curves?.mode === 'ep', enabled: has });
commands.add({ id: 'u7-points-off', label: 'Hide Curve Points', group: 'View', run: () => setPoints('off'), enabled: has });
commands.add({ id: 'u9-zebra', label: 'Show Zebra Stripes', group: 'View', run: () => { void toggleZebra(); }, checked: () => stripes?.meta?.mode === 'zebra', enabled: has });
commands.add({ id: 'u7-seams-sel', label: 'Show Seams of Selected Surface', group: 'View', run: () => { void seamsOfSelection(); }, enabled: has });
commands.add({ id: 'u7-clear-analysis', label: 'Clear Analysis Display', group: 'View', run: () => { analysis?.clear(); diag.clear(); }, enabled: has });
commands.add({ id: 'u7-diag-open', label: 'Boolean Diagnostics Panel', group: 'Window', run: () => ui('panel:reveal:bool-diag'), enabled: has });
commands.add({ id: 'u7-tol-open', label: 'Model Tolerance Settings', group: 'Window', run: () => ui('panel:reveal:doc-info'), enabled: has });
