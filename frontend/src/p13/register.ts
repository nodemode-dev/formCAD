import { onShellMounted } from '../app';
import { commands } from '../ui/commands';
import { docStore } from '../ui/doc-store';
import { registerDockPanel } from '../ui/dock';
import { onView3d } from '../view3d/mount';
import type { Viewport3D } from '../view3d/viewport';
import { resultPanel, resultState } from './result-panel';
import { ResultLayer } from './result-layer';
import { sim } from './sim-store';
import { studyPanel } from './study-panel';

const has = (): boolean => !!docStore.current();
const reveal = (id: string): void => { document.dispatchEvent(new CustomEvent('formcad:ui', { detail: { action: `panel:reveal:${id}` } })); };

function attach(vp: Viewport3D): void {
  if (sim.layer) return;
  const layer = new ResultLayer(vp);
  layer.setColors(document.body);
  sim.layer = layer;
  vp.addLayer(layer);
  if (import.meta.env.DEV) Object.assign(window, { formcadP13: { sim, vp, layer, resultState } });
}

document.addEventListener('formcad:view3d-created', (e) => { attach((e as CustomEvent<{ vp: Viewport3D }>).detail.vp); });
onView3d((c) => { if (c.vp) attach(c.vp); });

registerDockPanel(studyPanel());
registerDockPanel(resultPanel());

commands.add(
  { id: 'p13-study-panel', label: 'Simulation Studies', group: 'Window', run: () => reveal('sim'), enabled: has },
  { id: 'p13-result-panel', label: 'Simulation Results', group: 'Window', run: () => reveal('simresult'), enabled: has },
  { id: 'p13-mesh', label: 'Generate Study Mesh', group: 'Simulate', run: () => { const s = sim.study(); if (s) void sim.mesh(s.id); }, enabled: () => has() && !!sim.study() && !sim.running },
  { id: 'p13-solve', label: 'Solve Study', group: 'Simulate', run: () => { const s = sim.study(); if (s) void sim.run(s.id); }, enabled: () => has() && !!sim.study() && !sim.running },
  { id: 'p13-cancel', label: 'Cancel Solve', group: 'Simulate', run: () => { void sim.cancel(); }, enabled: () => sim.running },
  { id: 'p13-show-result', label: 'Simulation Result', group: 'View', run: () => { sim.layer?.setShown(!(sim.layer?.shown ?? false)); }, checked: () => sim.layer?.shown ?? false, enabled: has },
);

onShellMounted((ctx) => {
  const root = ctx.hosts.root;
  const apply = (): void => {
    if (root.dataset.workspace === 'simulate') { reveal('sim'); reveal('simresult'); }
  };
  new MutationObserver(apply).observe(root, { attributes: true, attributeFilter: ['data-workspace'] });
  apply();
});
