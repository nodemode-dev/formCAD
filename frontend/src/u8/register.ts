import { commands } from '../ui/commands';
import { docStore } from '../ui/doc-store';
import { registerDockPanel } from '../ui/dock';
import { pickPath, MESH_KINDS } from '../ui/file-dialogs';
import { t } from '../ui/i18n';
import { trackWork } from '../ui/output/job-feed';
import { tellNotes } from '../ui/output/notes';
import { failure, out } from '../ui/output/output-api';
import { toast } from '../ui/toast';
import { onView3d, view3d } from '../view3d/mount';
import type { Viewport3D } from '../view3d/viewport';
import { AnalysisColors } from './analysis-colors';
import { analysisPanel } from './analysis-panel';
import { asm, isAssembly } from './asm';
import { bomPanel, checkPanel, explodePanel, insertComponent, matesPanel, treePanel } from './asm-panels';
import { DragTool } from './asm-motion';
import { GumballLayer } from './gumball';
import { docUrl, req, text } from './net';
import { Snap3dLayer } from './snap3d';

export let gumball: GumballLayer | null = null;
export let dragTool: DragTool | null = null;
export let analysis: AnalysisColors | null = null;
export let snaps: Snap3dLayer | null = null;

const has = (): boolean => !!docStore.current();
const tail = (p: string): string => p.split(/[\\/]/).pop() ?? p;

function attach(vp: Viewport3D): void {
  if (gumball) return;
  snaps = new Snap3dLayer(vp, () => vp.invalidate());
  gumball = new GumballLayer(vp, snaps);
  analysis = new AnalysisColors(vp);
  dragTool = new DragTool(vp);
  vp.addLayer(snaps);
  vp.addLayer(gumball);
  vp.addLayer(analysis);
  analysis.palette(vp.kit.palette);
  void gumball.refresh();
  void analysis.refresh();
  if (import.meta.env.DEV) Object.assign(window, { formcadU8: { gumball, analysis, snaps } });
}

document.addEventListener('formcad:view3d-created', (e) => { attach((e as CustomEvent<{ vp: Viewport3D }>).detail.vp); });
onView3d((c) => { if (c.vp) attach(c.vp); });

registerDockPanel(analysisPanel(() => analysis));
registerDockPanel(treePanel());
registerDockPanel(matesPanel(() => dragTool));
registerDockPanel(explodePanel());
registerDockPanel(checkPanel());
registerDockPanel(bomPanel());

const reveal = (id: string): void => { document.dispatchEvent(new CustomEvent('formcad:ui', { detail: { action: `panel:reveal:${id}` } })); };

const refreshGumball = (): void => { void gumball?.refresh(); };
document.addEventListener('formcad:selection', refreshGumball);
document.addEventListener('formcad:set-selection', refreshGumball);

let last: string | null = null;
docStore.onChange(() => {
  if (docStore.activeId === last) return;
  last = docStore.activeId;
  analysis?.clearAll();
  void gumball?.refresh();
  void analysis?.refresh();
});

async function meshFile(mode: 'import' | 'export'): Promise<void> {
  const id = docStore.activeId;
  if (!id) return;
  const base = (docStore.current()?.name ?? 'Model').replace(/\.[^.]+$/, '');
  const path = await pickPath(mode === 'import' ? 'open' : 'save', mode === 'import' ? 'Import Mesh' : 'Export Mesh', `${base}.stl`, MESH_KINDS, mode === 'import' ? 'Import' : 'Export');
  if (!path) return;
  try {
    if (mode === 'import') {
      const r = await trackWork(`${t('Import')} ${tail(path)}`, () => out.importFile(id, path));
      tellNotes(`${t('Imported')} ${tail(path)}.`, r.report);
      void docStore.refresh();
      await view3d()?.with3d(() => undefined);
    } else {
      const r = await trackWork(`${t('Export')} ${tail(path)}`, () => out.exportFile(id, path));
      tellNotes(`${t('Exported')} ${tail(path)}.`, r.notes);
    }
  } catch (e) {
    toast(failure(e), 'error');
  }
}

async function meshNaked(): Promise<void> {
  const id = docStore.activeId;
  const vp = view3d()?.vp;
  if (!id || !analysis) return;
  const handles = vp ? vp.sel.bodies : [];
  let all: number[][][] = [];
  try {
    const list = await req<{ meshes: Array<{ handle: number; points_only: boolean }> }>('GET', docUrl(id, 'meshes'));
    const wanted = list.meshes.filter((m) => !m.points_only && (!handles.length || handles.includes(m.handle)));
    for (const m of wanted) {
      const r = await req<{ polylines: number[][][] }>('GET', docUrl(id, `meshes/${m.handle}/naked`));
      all = all.concat(r.polylines);
    }
  } catch (e) {
    toast(text(e), 'error');
    return;
  }
  const n = analysis.setNaked(all);
  toast(n ? `${n} ${t('naked edges drawn.')}` : t('No naked edges found.'), 'info');
  await view3d()?.with3d(() => undefined);
}

commands.add(
  { id: 'u8-gumball', label: 'Gumball', group: 'Modify', run: () => { void view3d()?.with3d(() => { void gumball?.setOn(!(gumball?.state?.on ?? false)); }); }, checked: () => !!gumball?.state?.on, enabled: has },
  { id: 'u8-gumball-reset', label: 'Reset Gumball', group: 'Modify', run: () => { void gumball?.reset(); }, enabled: has },
  { id: 'u8-snap3d', label: 'Engine 3D Snaps', group: 'View', run: () => { snaps?.setEnabled(!snaps.enabled); }, checked: () => !!snaps?.enabled, enabled: has },
  { id: 'u8-analysis-open', label: 'Surface Analysis Panel', group: 'Window', run: () => document.dispatchEvent(new CustomEvent('formcad:ui', { detail: { action: 'panel:reveal:analysis3d' } })), enabled: has },
  { id: 'u8-analysis-off', label: 'Analysis Off', group: 'View', run: () => { const id = docStore.activeId; if (id) void import('../io/api').then(({ api }) => api.runCommand(id, 'analysisoff', {})).then(() => analysis?.refresh()).catch((e: unknown) => toast(text(e), 'error')); }, enabled: has },
  { id: 'u8-mesh-import', label: 'Import Mesh...', group: 'Mesh', run: () => { void meshFile('import'); }, enabled: has },
  { id: 'u8-mesh-export', label: 'Export Mesh...', group: 'Mesh', run: () => { void meshFile('export'); }, enabled: has },
  { id: 'u8-mesh-naked', label: 'Show Naked Mesh Edges', group: 'Mesh', run: () => { void meshNaked(); }, enabled: has },
  { id: 'u8-mesh-naked-off', label: 'Hide Naked Mesh Edges', group: 'Mesh', run: () => analysis?.clearNaked(), enabled: has },
  { id: 'u8-asm-insert', label: 'Insert Component...', group: 'Assembly', run: () => { void insertComponent(); }, enabled: isAssembly },
  { id: 'u8-asm-panel', label: 'Assembly Tree', group: 'Window', run: () => reveal('asm-tree'), enabled: has },
  { id: 'u8-mates-panel', label: 'Mates and Motion', group: 'Window', run: () => reveal('asm-mates'), enabled: has },
  { id: 'u8-explode-panel', label: 'Exploded View', group: 'Window', run: () => reveal('asm-explode'), enabled: has },
  { id: 'u8-check-panel', label: 'Interference Check', group: 'Window', run: () => reveal('asm-check'), enabled: has },
  { id: 'u8-bom-panel', label: 'Bill of Materials', group: 'Window', run: () => reveal('asm-bom'), enabled: has },
  { id: 'u8-asm-solve', label: 'Solve Mates', group: 'Assembly', run: () => { const id = asm.id(); if (id) void req('POST', docUrl(id, 'mates/solve')).then(() => view3d()?.refresh()).then(() => asm.schedule(0)).catch((e: unknown) => toast(text(e), 'error')); }, enabled: isAssembly },
  { id: 'u8-asm-drag', label: 'Drag Component', group: 'Assembly', run: () => { dragTool?.set(!dragTool.enabled); }, checked: () => !!dragTool?.enabled, enabled: isAssembly },
);
