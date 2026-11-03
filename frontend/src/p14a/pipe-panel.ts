import { docStore } from '../ui/doc-store';
import type { DockPanel } from '../ui/dock';
import { el, setHidden, setText } from '../ui/dom';
import { pickPath } from '../ui/file-dialogs';
import { t } from '../ui/i18n';
import { toast } from '../ui/toast';
import { button, buttons, selectCtl } from '../u8/ui';
import { asArr, dataTable, entityList, formGrid, guard, mm, reportBox, req, section, type Json, type RowItem } from './kit';
import { sampleArc, type RouteLayer } from './route-layer';
import { pipeFeed as feed } from './route-store';

export const pipeLayerRef: { layer: RouteLayer | null } = { layer: null };

const pointText = (p: unknown): string => {
  if (Array.isArray(p)) return p.map((n) => mm(n, 2)).join(' ');
  const o = (p ?? {}) as Json;
  return `@${String(o.component ?? '')} ${asArr<number>(o.local).map((n) => mm(n, 2)).join(' ')}`;
};
const parsePoints = (s: string): unknown[] | string => {
  const out: unknown[] = [];
  for (const [i, raw] of s.split('\n').map((x) => x.trim()).filter(Boolean).entries()) {
    const m = raw.match(/^@(\S+)\s+(.*)$/);
    const nums = (m ? m[2] : raw).split(/[\s,;]+/).filter(Boolean).map(Number);
    if (nums.length !== 3 || nums.some((n) => !Number.isFinite(n))) return `Point ${i + 1}: give x y z.`;
    out.push(m ? { component: m[1], local: nums } : nums);
  }
  return out;
};

export function pipePanel(): DockPanel {
  return {
    id: 'pipes', label: 'Pipes and tubing', icon: 'pipe', order: 49,
    build(body) {
      body.classList.add('u8-panel', 'xw-panel', 'p14-panel');
      const note = el('<p class="u8-note"></p>');
      setText(note, t('Open an assembly or part to route pipes and tubing.'));
      const live = el('<div class="u8-live cm-live"></div>');
      body.append(note, live);

      const sSpec = section('Specs');
      const specNote = el('<p class="u8-note p14-note"></p>');
      const specList = el('<div class="u8-list p14-list p14-list-s" role="listbox" aria-label="Tube specs"></div>');
      let specSel = '';
      const paintSpecs = entityList(specList, (k) => { specSel = k; paint(); fillSpecForm(); }, (k) => { void guard(() => feed.del(`/specs/${encodeURIComponent(k)}`)); });
      const spf = formGrid([
        { key: 'label', label: 'Label', kind: 'text', value: '' }, { key: 'od', label: 'Outside diameter (mm)', value: 12 }, { key: 'wall', label: 'Wall (mm)', value: 1 },
        { key: 'min_clr_factor', label: 'Smallest bend radius (x OD)', value: 1.5 }, { key: 'min_straight_factor', label: 'Smallest straight (x OD)', value: 2 }, { key: 'springback', label: 'Springback (deg)', value: 0 },
      ]);
      sSpec.body.append(specNote, specList, spf.el, buttons(button('Add spec', () => { void guard(() => feed.post('/specs', spf.get())); }, 'primary'), button('Update selected', () => { if (specSel) void guard(() => feed.put(`/specs/${encodeURIComponent(specSel)}`, spf.get())); })));

      const sRun = section('Runs');
      const runList = el('<div class="u8-list p14-list" role="listbox" aria-label="Runs"></div>');
      let runSel = '';
      const paintRuns = entityList(runList, (k) => { runSel = k; paint(); fillRunForm(); void solve(); }, (k) => { void guard(() => feed.del(`/runs/${encodeURIComponent(k)}`)).then(() => { if (runSel === k) runSel = ''; }); });
      const rf = formGrid([
        { key: 'label', label: 'Label', kind: 'text', value: '' }, { key: 'spec', label: 'Spec', kind: 'select', options: [] },
        { key: 'style', label: 'Style', kind: 'select', options: [['tube', 'Bent tube'], ['pipe', 'Pipe with fittings']] },
        { key: 'clr', label: 'Bend radius (mm, 0 = spec minimum)', value: 0 },
        { key: 'a', label: 'End A', kind: 'select', options: [['plain', 'Plain'], ['flange', 'Flange']] }, { key: 'b', label: 'End B', kind: 'select', options: [['plain', 'Plain'], ['flange', 'Flange']] },
      ]);
      const pts = el<HTMLTextAreaElement>('<textarea class="cv-input p14-pts" rows="5" spellcheck="false" aria-label="Route points, one x y z per line, or @component x y z"></textarea>');
      const ptsNote = el('<p class="u8-note p14-note"></p>');
      setText(ptsNote, t('One point per line: x y z in mm, or @component x y z for a point on a component.'));
      pts.addEventListener('keydown', (e) => e.stopPropagation());
      sRun.body.append(runList, rf.el, ptsNote, pts, buttons(button('Add run', () => { void saveRun(false); }, 'primary'), button('Update selected', () => { void saveRun(true); })));

      const sSolve = section('Solve, bender table and cut list');
      const solveBox = reportBox(4);
      const benderTab = dataTable(5);
      const cutTab = dataTable(5);
      const fitForm = formGrid([
        { key: 'type', label: 'Fitting', kind: 'select', options: [['elbow', 'Elbow'], ['tee', 'Tee'], ['reducer', 'Reducer'], ['flange', 'Flange']] },
        { key: 'od', label: 'Outside diameter (mm)', value: 20 }, { key: 'wall', label: 'Wall (mm)', value: 2 },
        { key: 'clr', label: 'Elbow radius (mm)', value: 30 }, { key: 'angle', label: 'Elbow angle (deg)', value: 90 },
        { key: 'c', label: 'Tee centre to end (mm)', value: 30 }, { key: 'branch_c', label: 'Tee branch centre to end (mm)', value: 30 },
        { key: 'od_to', label: 'Reduced diameter (mm)', value: 14 }, { key: 'length', label: 'Reducer length (mm)', value: 40 },
        { key: 'thickness', label: 'Flange thickness (mm)', value: 8 }, { key: 'flange_od', label: 'Flange diameter (mm)', value: 44 }, { key: 'bolt_circle', label: 'Bolt circle (mm)', value: 32 },
      ], () => paintFit());
      const paintFit = (): void => {
        const k = String(fitForm.ctl.type.get());
        const show: Record<string, string[]> = { elbow: ['clr', 'angle'], tee: ['c', 'branch_c'], reducer: ['od_to', 'length'], flange: ['thickness', 'flange_od', 'bolt_circle'] };
        for (const key of ['clr', 'angle', 'c', 'branch_c', 'od_to', 'length', 'thickness', 'flange_od', 'bolt_circle']) fitForm.show(key, (show[k] ?? []).includes(key));
      };
      const kindSel = selectCtl('Export', [['cutlist', 'Cut list'], ['bender', 'Bender table']]);
      sSolve.body.append(solveBox.el, benderTab.el, cutTab.el, fitForm.el, buttons(button('Make a fitting body', () => { void makeFitting(); }), button('Make the run bodies', () => { void makeBodies(); })), kindSel.el, buttons(button('Export CSV', () => { void exportCsv(); })));
      live.append(sSpec.root, sRun.root, sSolve.root);

      const specs = (): Json[] => asArr<Json>(feed.get('list').specs);
      const runs = (): Json[] => asArr<Json>(feed.get('list').runs);
      let solved: Json | null = null;
      let bender: Json | null = null;
      let solveFor = '';

      function fillSpecForm(): void {
        const s = specs().find((x) => x.id === specSel);
        if (!s) return;
        spf.set('label', s.label ?? ''); for (const k of ['od', 'wall', 'min_clr_factor', 'min_straight_factor', 'springback']) spf.set(k, s[k]);
      }
      function fillRunForm(): void {
        const r = runs().find((x) => x.id === runSel);
        if (!r) return;
        rf.set('label', r.label ?? ''); rf.set('spec', r.spec ?? ''); rf.set('style', r.style ?? 'tube'); rf.set('clr', r.clr ?? 0);
        const ends = (r.ends ?? {}) as Json;
        rf.set('a', ends.a ?? 'plain'); rf.set('b', ends.b ?? 'plain');
        pts.value = asArr(r.points).map(pointText).join('\n');
      }
      async function saveRun(update: boolean): Promise<void> {
        const v = rf.get();
        const p = parsePoints(pts.value);
        if (typeof p === 'string') { toast(t(p), 'error'); return; }
        const rec = { label: v.label ?? '', spec: v.spec ?? specs()[0]?.id ?? '', style: v.style ?? 'tube', clr: v.clr ?? null, points: p, ends: { a: v.a ?? 'plain', b: v.b ?? 'plain', a_thickness: v.a === 'flange' ? 6 : 0, b_thickness: v.b === 'flange' ? 6 : 0 } };
        if (update && !runSel) { toast(t('Select a run first.'), 'error'); return; }
        const r = await guard(() => update ? feed.put(`/runs/${encodeURIComponent(runSel)}`, rec) : feed.post('/runs', rec));
        if (r && !update && typeof r.id === 'string') { runSel = r.id; paint(); void solve(); }
        else if (r) void solve();
      }
      async function solve(): Promise<void> {
        const id = runSel;
        if (!id) { solved = null; bender = null; solveFor = ''; paint(); return; }
        try {
          const [s, b] = await Promise.all([req<Json>('GET', feed.url(`/runs/${encodeURIComponent(id)}/solve`)), req<Json>('GET', feed.url(`/runs/${encodeURIComponent(id)}/bender`))]);
          if (id !== runSel) return;
          solved = s; bender = b; solveFor = id;
        } catch (e) { solved = { error: String((e as Error).message) }; bender = null; solveFor = id; }
        paint();
      }
      async function makeFitting(): Promise<void> {
        const v = fitForm.get();
        const type = String(v.type ?? 'elbow');
        const keys: Record<string, string[]> = { elbow: ['od', 'wall', 'clr', 'angle'], tee: ['od', 'wall', 'c', 'branch_c'], reducer: ['od', 'wall', 'od_to', 'length'], flange: ['od', 'wall', 'thickness', 'flange_od', 'bolt_circle'] };
        const params = Object.fromEntries((keys[type] ?? []).filter((k) => v[k] !== undefined).map((k) => [k, v[k]]));
        const r = await guard(() => feed.post('/fittings', { type, params }));
        if (r) toast(`${t('Fitting body made')}`, 'info');
      }
      async function makeBodies(): Promise<void> {
        if (!runSel) { toast(t('Select a run first.'), 'error'); return; }
        const r = await guard(() => feed.post(`/runs/${encodeURIComponent(runSel)}/bodies`, {}));
        if (r) toast(t('Run bodies made.'), 'info');
      }
      async function exportCsv(): Promise<void> {
        const kind = kindSel.get();
        const path = await pickPath('save', t('Export the table'), `${kind}.csv`, [{ name: 'CSV table', extensions: ['csv'] }], t('Save'));
        if (!path) return;
        const r = await guard(() => feed.post('/export', { path, kind, ...(runSel ? { run: runSel } : {}) }));
        if (r) toast(`${t('Table written')}: ${String(r.path ?? path)}`, 'info');
      }

      const paint = (): void => {
        const on = !!docStore.current();
        setHidden(note, on); setHidden(live, !on);
        if (!on || !feed.has()) return;
        const l = feed.get('list');
        setText(specNote, String(((l.labels ?? {}) as Json).specs ?? ''));
        paintSpecs(specs().map((s): RowItem => ({ key: String(s.id), badge: 'SP', name: `${String(s.id)} ${String(s.label ?? '')}`.trim(), sub: `${mm(s.od, 1)} x ${mm(s.wall, 1)}`, selected: s.id === specSel })));
        paintRuns(runs().map((r): RowItem => ({ key: String(r.id), badge: r.style === 'pipe' ? 'PP' : 'TB', name: `${String(r.id)} ${String(r.label ?? '')}`.trim(), sub: `${asArr(r.points).length} pts`, selected: r.id === runSel })));
        rf.options('spec', specs().map((s) => [String(s.id), String(s.label || s.id)] as [string, string]));
        paintFit();
        const sv = solved;
        if (sv && solveFor === runSel && !sv.error) {
          const viol = asArr<Json>(sv.violations);
          solveBox.set([`${t('Developed length')} ${mm(((bender ?? {}).total ?? sv.total_length ?? sv.length) as number, 2)} mm`, `${asArr(sv.arcs).length} ${t('bends')}, ${asArr(sv.straights).length} ${t('straights')}`, viol.length ? `${t('Flags')}: ${viol.map((x) => String(x.message ?? x.code ?? x.kind ?? '')).join('; ')}` : t('No flags.'), `${t('Spec')} ${String(sv.spec)} ${mm(sv.od, 1)} x ${mm(sv.wall, 1)}`], viol.length > 0);
          benderTab.set(['Bend', 'Length', 'Rotation', 'Angle', 'Machine', 'Mark'], asArr<Json>((bender ?? {}).rows).map((r) => [String(r.bend), mm(r.length, 2), mm(r.rotation, 2), mm(r.angle, 2), mm(r.machine_angle, 2), mm(r.mark, 2)]));
        } else if (sv?.error) { solveBox.set([String(sv.error)], true); benderTab.set(['Bend'], []); }
        else { solveBox.set([t('Select a run to see its solution.')]); benderTab.set(['Bend', 'Length', 'Rotation', 'Angle', 'Machine', 'Mark'], []); }
        const cut = asArr<Json>(feed.get('cutlist').rows);
        cutTab.set(['Run', 'Piece', 'Kind', 'OD x wall', 'Length', 'Bends'], cut.map((r) => [String(r.run), String(r.piece), String(r.kind), `${mm(r.od, 1)} x ${mm(r.wall, 1)}`, mm(r.length, 1), String(r.bends)]));
        const layer = pipeLayerRef.layer;
        if (layer) {
          const lines: number[][][] = [];
          if (sv && solveFor === runSel && !sv.error) {
            for (const s of asArr<Json>(sv.straights)) lines.push([s.start as number[], s.end as number[]]);
            for (const a of asArr<Json>(sv.arcs)) lines.push(sampleArc(a.centre as number[], a.start as number[], a.end as number[]));
          }
          layer.setPipe(lines);
          layer.setShown(true);
        }
      };
      feed.onChange(() => { paint(); if (runSel && runs().some((r) => r.id === runSel)) void solve(); });
      docStore.onChange(() => { runSel = ''; specSel = ''; solved = null; bender = null; solveFor = ''; paint(); });
      paint();
      return { show: () => { feed.setActive(true); } };
    },
  };
}
