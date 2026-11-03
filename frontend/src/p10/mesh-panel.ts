import { events } from '../io/events';
import { docStore } from '../ui/doc-store';
import type { DockPanel } from '../ui/dock';
import { el, patchList, q, setChecked, setDisabled, setText } from '../ui/dom';
import { t } from '../ui/i18n';
import { toast } from '../ui/toast';
import { analysis } from '../u8/register';
import { button, buttons, checkCtl, numberCtl, selectCtl } from '../u8/ui';
import { view3d } from '../view3d/mount';
import { docUrl, fixed, jobBar, lastCmdError, num, reportBox, req, runCmd, section, text, type Json } from './kit';

interface MeshRow { handle: number; name: string; points_only: boolean; summary?: Json }
interface Limits { interactive: Record<string, number>; restricted: Record<string, number>; brep_interactive?: number }

const MODES: ReadonlyArray<readonly [string, string]> = [['tolerance', 'Tolerance'], ['proportion', 'Proportion'], ['count', 'Face count']];
const PLANES: ReadonlyArray<readonly [string, string]> = [['xy', 'XY'], ['yz', 'YZ'], ['zx', 'ZX']];
const OPS: ReadonlyArray<readonly [string, string]> = [['union', 'Union'], ['difference', 'Difference'], ['intersection', 'Intersection']];

const triangles = (m: MeshRow): number => num((m.summary as Json | undefined)?.triangles ?? (m.summary as Json | undefined)?.faces, 0);

export function stepLines(result: Json): string[] {
  const out: string[] = [];
  const rows = Array.isArray(result.results) ? (result.results as Json[]) : [];
  for (const r of rows) {
    const head = `#${String(r.handle ?? '')}`;
    const before = r.before as Json | undefined;
    const after = r.after as Json | undefined;
    if (typeof r.before === 'number' && typeof r.after === 'number') out.push(`${head} ${t('triangles')} ${r.before} > ${r.after}`);
    else if (before && after) {
      const keys = ['triangles', 'vertices', 'naked_edges', 'non_manifold_edges', 'components'].filter((k) => k in before || k in after);
      out.push(`${head} ${keys.map((k) => `${k.replace(/_/g, ' ')} ${String(before[k] ?? '-')} > ${String(after[k] ?? '-')}`).join(' · ')}`);
    }
    for (const s of Array.isArray(r.steps) ? (r.steps as Json[]) : []) {
      const bits = Object.entries(s).filter(([k, v]) => k !== 'step' && typeof v === 'number').map(([k, v]) => `${k.replace(/_/g, ' ')} ${String(v)}`);
      out.push(`  ${String(s.step)}${bits.length ? `: ${bits.join(', ')}` : ''}`);
    }
    if (typeof r.deviation_max === 'number') out.push(`  ${t('deviation')} ${t('max')} ${fixed(r.deviation_max, 4)}${typeof r.deviation_rms === 'number' ? ` · rms ${fixed(r.deviation_rms, 4)}` : ''}`);
    if (typeof r.edge_mean === 'number') out.push(`  ${t('edge length')} ${fixed(num(r.edge_min), 3)} / ${fixed(r.edge_mean, 3)} / ${fixed(num(r.edge_max), 3)}`);
    const si = r.self_intersections as Json | undefined;
    if (si) out.push(`  ${t('self intersections')} ${String(si.pairs ?? 0)} ${t('pairs')}`);
  }
  return out;
}

export function meshPanel(): DockPanel {
  return {
    id: 'meshws',
    label: 'Mesh Tools',
    icon: 'meshTools',
    order: 44,
    build(body) {
      body.classList.add('u8-panel', 'xw-panel');
      let meshes: MeshRow[] = [];
      let limits: Limits | null = null;
      const checked = new Set<number>();
      const list = el('<div class="u8-list xw-meshes is-scroll" role="group" aria-label="Mesh objects"></div>');
      const empty = el('<p class="u8-note xw-empty"></p>');
      const pick = section('Mesh objects');
      pick.body.append(list, empty);

      const targets = (): number[] => meshes.filter((m) => checked.has(m.handle) && !m.points_only).map((m) => m.handle);
      const paintList = (): void => {
        patchList(list, meshes, {
          key: (m) => String(m.handle),
          create: (m) => {
            const row = el('<label class="u8-row xw-row"><input type="checkbox"><span class="u8-row-name"></span><span class="u8-row-sub"></span></label>');
            q<HTMLInputElement>(row, 'input').addEventListener('change', (ev) => {
              const on = (ev.target as HTMLInputElement).checked;
              if (on) checked.add(m.handle); else checked.delete(m.handle);
              state();
            });
            return row;
          },
          update: (node, m) => {
            setChecked(q<HTMLInputElement>(node, 'input'), checked.has(m.handle));
            setText(q(node, '.u8-row-name'), m.name || `#${m.handle}`);
            setText(q(node, '.u8-row-sub'), m.points_only ? t('points') : `${triangles(m)} ${t('tri')}`);
          },
        });
        setText(empty, meshes.length ? '' : t('No mesh objects in this document. Import an STL, OBJ or PLY file, or convert a solid to a mesh.'));
        empty.hidden = meshes.length > 0;
      };

      const jobs = jobBar(['meshrepair', 'meshselfx', 'meshreduce', 'meshremesh', 'meshboolean', 'meshtobrep', 'meshsection'], (id) => docUrl(id, 'meshes/cancel'));

      const out = reportBox(8);
      let busy = false;
      const go = async (label: string, cmd: string, args: Json, after?: (r: Json) => string[]): Promise<void> => {
        if (busy) return;
        const handles = targets();
        busy = true;
        state();
        out.set([`${label}...`]);
        try {
          const r = await runCmd<Json>(cmd, { handles, ...args });
          if (!r) { out.set([lastCmdError() || t('The operation did not complete.')], true); return; }
          out.set(after ? after(r) : stepLines(r));
          await refresh();
          await view3d()?.with3d(() => undefined);
        } finally { busy = false; state(); }
      };

      const sRep = section('Repair');
      const weld = numberCtl('Weld distance', 0.0001);
      const fill = numberCtl('Fill holes up to (edges)', 32);
      const degenerate = checkCtl('Remove degenerate triangles', true);
      const dupes = checkCtl('Remove duplicate triangles', true);
      const unify = checkCtl('Unify orientation', true);
      const self = checkCtl('Check self intersections', true);
      const bRepair = button('Repair', () => void go(t('Repairing'), 'meshrepair', { weld: weld.get() ?? 0, degenerate: degenerate.get(), duplicates: dupes.get(), unify: unify.get(), fill_edges: Math.max(0, Math.round(fill.get() ?? 0)), self_check: self.get() }), 'primary');
      const bSelfx = button('Check intersections', () => void checkSelfx());
      const bClearMark = button('Clear marks', () => { analysis?.clearNaked(); });
      sRep.body.append(weld.el, fill.el, degenerate.el, dupes.el, unify.el, self.el, buttons(bRepair, bSelfx, bClearMark));

      const sRed = section('Reduce');
      const mode = selectCtl('Reduce by', MODES, () => modeSync());
      const value = numberCtl('Value', 0.01);
      const lockB = checkCtl('Keep open boundaries', true);
      const modeNote = el('<p class="u8-note xw-mode"></p>');
      const bReduce = button('Reduce', () => void go(t('Reducing'), 'meshreduce', { mode: mode.get(), value: value.get() ?? 0, lock_boundary: lockB.get() }), 'primary');
      sRed.body.append(mode.el, value.el, modeNote, lockB.el, buttons(bReduce));
      const modeSync = (): void => {
        const m = mode.get();
        setText(modeNote, m === 'tolerance' ? t('Largest allowed deviation, in document units.') : m === 'proportion' ? t('Share of triangles kept, between 0 and 1.') : t('Target triangle count.'));
        if (m === 'proportion' && (value.get() ?? 0) > 1) value.set(0.5);
        if (m === 'count' && (value.get() ?? 0) <= 1) value.set(5000);
        if (m === 'tolerance' && (value.get() ?? 0) >= 1 && Number.isInteger(value.get())) value.set(0.01);
      };

      const sRem = section('Remesh');
      const edge = numberCtl('Target edge length', 1);
      const iters = numberCtl('Iterations', 5);
      const feat = numberCtl('Feature angle (deg)', 30);
      const lockR = checkCtl('Keep open boundaries', true);
      const bRemesh = button('Remesh', () => void go(t('Remeshing'), 'meshremesh', { edge_length: edge.get() ?? 1, iterations: Math.max(1, Math.round(iters.get() ?? 5)), feature_angle: feat.get() ?? 30, lock_boundary: lockR.get() }), 'primary');
      sRem.body.append(edge.el, iters.el, feat.el, lockR.el, buttons(bRemesh));

      const sSec = section('Section');
      const plane = selectCtl('Plane', PLANES);
      const offset = numberCtl('Offset', 0);
      const closedOnly = checkCtl('Closed loops only', false);
      const bSection = button('Cut section', () => void go(t('Cutting'), 'meshsection', { plane: plane.get(), offset: offset.get() ?? 0, closed_only: closedOnly.get() }, (r) => [`${num(r.loops)} ${t('closed loops')}, ${num(r.chains)} ${t('open chains')}`, `${Array.isArray(r.curves) ? r.curves.length : 0} ${t('curves added')}`]), 'primary');
      sSec.body.append(plane.el, offset.el, closedOnly.el, buttons(bSection));

      const sBool = section('Boolean');
      const op = selectCtl('Operation', OPS);
      const keep = checkCtl('Keep the inputs', false);
      const boolNote = el('<p class="u8-note xw-mode"></p>');
      setText(boolNote, t('The first ticked mesh is the base; the other ticked meshes are the tools.'));
      const bBool = button('Combine', () => {
        const hs = targets();
        if (hs.length < 2) { toast(t('Tick at least two meshes: the base and one tool.'), 'info'); return; }
        void (async () => {
          if (busy) return;
          busy = true; state();
          out.set([`${t('Combining')}...`]);
          const r = await runCmd<Json>('meshboolean', { op: op.get(), base: hs[0], tools: hs.slice(1), keep_inputs: keep.get() });
          out.set(r ? [`${String(r.op ?? op.get())}: ${num(r.triangles)} ${t('triangles')}`, `${t('volume')} ${fixed(num(r.volume), 4)}`] : [lastCmdError() || t('The operation did not complete.')], !r);
          busy = false; state();
          await refresh();
          await view3d()?.with3d(() => undefined);
        })();
      }, 'primary');
      sBool.body.append(op.el, keep.el, boolNote, buttons(bBool));

      const sBrep = section('Mesh to solid');
      const mergeP = checkCtl('Merge flat faces', true);
      const mergeC = checkCtl('Merge round faces into cylinders', false);
      const tol = numberCtl('Tolerance', 0.001);
      const nameCtl = el('<label class="cv-field"><span></span><input class="cv-input" type="text" spellcheck="false" autocomplete="off"></label>');
      setText(q(nameCtl, 'span'), t('Name'));
      const nameIn = q<HTMLInputElement>(nameCtl, 'input');
      const keepMesh = checkCtl('Keep the mesh', true);
      const capNote = el('<p class="u8-note xw-mode"></p>');
      const bBrep = button('Convert to solid', () => {
        const hs = targets();
        if (hs.length !== 1) { toast(t('Tick exactly one mesh to convert.'), 'info'); return; }
        const m = meshes.find((x) => x.handle === hs[0]);
        const n = m ? triangles(m) : 0;
        const soft = limits?.brep_interactive ?? 5000;
        const hard = limits?.interactive.tobrep ?? 50000;
        if (n > hard) { toast(`${t('This mesh has')} ${n} ${t('triangles. Reduce it below')} ${hard} ${t('first.')}`, 'error'); return; }
        void go(t('Converting'), 'meshtobrep', { handle: hs[0], merge_planar: mergeP.get(), merge_cylinders: mergeC.get(), tolerance: tol.get() ?? 0.001, name: nameIn.value.trim(), keep_mesh: keepMesh.get(), confirm_large: n > soft }, (r) => [
          `${r.valid ? t('Valid solid') : t('Not a valid solid')} · ${num(r.faces)} ${t('faces')} (${num(r.planar_merged)} ${t('flat merged')}, ${num(r.cylinders)} ${t('cylinders')})`,
          `${t('free edges')} ${num(r.free_edges)}`,
          `${t('volume')} ${fixed(num(r.volume), 5)} · ${t('mesh volume')} ${fixed(num(r.mesh_volume), 5)}`,
          `${t('relative volume error')} ${fixed(num(r.relative_volume_error), 3)}`,
          `${fixed(num(r.seconds), 3)} s`,
        ]);
      }, 'primary');
      sBrep.body.append(mergeP.el, mergeC.el, tol.el, nameCtl, keepMesh.el, capNote, buttons(bBrep));

      const results = section('Result');
      results.body.append(out.el, jobs.el);

      const actions = [bRepair, bSelfx, bReduce, bRemesh, bSection, bBool, bBrep];
      const state = (): void => {
        const n = targets().length;
        const on = !busy && n > 0;
        for (const b of actions) setDisabled(b, !on);
        setDisabled(bBool, !(on && n >= 2));
        setDisabled(bBrep, !(on && n === 1));
        setText(capNote, t('Interactive up to about 5,000 triangles; reduce larger meshes first. Above 50,000 is refused.'));
      };

      async function checkSelfx(): Promise<void> {
        const id = docStore.activeId;
        const hs = targets();
        if (!id || !hs.length || busy) return;
        busy = true; state();
        out.set([`${t('Checking')}...`]);
        try {
          const lines: string[] = [];
          const marks: number[][][] = [];
          for (const h of hs) {
            const r = await req<Json>('POST', docUrl(id, `meshes/${h}/selfintersections`), {});
            lines.push(`#${h}: ${num(r.pairs)} ${t('intersecting pairs')}, ${num(r.triangles_involved)} ${t('triangles involved')}${r.capped ? ` (${t('capped')})` : ''}`);
            for (const p of (Array.isArray(r.points) ? r.points : []) as number[][]) {
              const d = 0.5;
              marks.push([[p[0] - d, p[1], p[2]], [p[0] + d, p[1], p[2]]], [[p[0], p[1] - d, p[2]], [p[0], p[1] + d, p[2]]], [[p[0], p[1], p[2] - d], [p[0], p[1], p[2] + d]]);
            }
          }
          analysis?.setNaked(marks);
          out.set(lines);
          await view3d()?.with3d(() => undefined);
        } catch (e) { out.set([text(e)], true); } finally { busy = false; state(); }
      }

      async function refresh(): Promise<void> {
        const id = docStore.activeId;
        if (!id) { meshes = []; paintList(); state(); return; }
        try {
          const r = await req<{ meshes: MeshRow[] }>('GET', docUrl(id, 'meshes'));
          meshes = r.meshes;
          for (const h of [...checked]) if (!meshes.some((m) => m.handle === h)) checked.delete(h);
          paintList();
        } catch { meshes = []; paintList(); }
        if (!limits && id) { try { limits = await req<Limits>('GET', docUrl(id, 'meshes/limits')); } catch { limits = null; } }
        state();
      }

      body.append(pick.root, sRep.root, sRed.root, sRem.root, sSec.root, sBool.root, sBrep.root, results.root);
      modeSync();
      state();

      let timer = 0;
      const later = (): void => { window.clearTimeout(timer); timer = window.setTimeout(() => { void refresh(); }, 120); };
      events.on('doc', (e) => { if (e.id === docStore.activeId) later(); });
      docStore.onChange(later);
      document.addEventListener('formcad:selection', () => {
        const vp = view3d()?.vp;
        if (!vp) return;
        let changed = false;
        for (const h of vp.sel.bodies) if (meshes.some((m) => m.handle === h) && !checked.has(h)) { checked.add(h); changed = true; }
        if (changed) { paintList(); state(); }
      });
      later();
      return { show: later };
    },
  };
}
