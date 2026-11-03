import { onShellMounted } from '../app';
import { commands } from '../ui/commands';
import { docStore } from '../ui/doc-store';
import { registerDockPanel } from '../ui/dock';
import { onView3d } from '../view3d/mount';
import type { Viewport3D } from '../view3d/viewport';
import { additivePanel, previewView } from './additive-panel';
import { camPanel } from './cam-panel';
import { cam } from './cam-store';
import { LayerPreview } from './layer-preview';
import { nestPanel } from './nest-panel';
import { SimLayer } from './sim-layer';
import { simPanel, simView } from './sim-panel';
import { ToolpathLayer } from './toolpath-layer';
import { toolPanel } from './tool-panel';

const has = (): boolean => !!docStore.current();
const reveal = (id: string): void => { document.dispatchEvent(new CustomEvent('formcad:ui', { detail: { action: `panel:reveal:${id}` } })); };

function attach(vp: Viewport3D): void {
  if (cam.layer) return;
  const tp = new ToolpathLayer(vp);
  const sim = new SimLayer(vp);
  const lp = new LayerPreview(vp);
  tp.setColors(document.body);
  sim.setColors(document.body);
  lp.setColors(document.body);
  cam.layer = tp;
  simView.layer = sim;
  previewView.layer = lp;
  vp.addLayer(tp);
  vp.addLayer(sim);
  vp.addLayer(lp);
  cam.schedule(0);
  if (import.meta.env.DEV) Object.assign(window, { formcadP12: { cam, vp, tp, sim, lp } });
}

document.addEventListener('formcad:view3d-created', (e) => { attach((e as CustomEvent<{ vp: Viewport3D }>).detail.vp); });
onView3d((c) => { if (c.vp) attach(c.vp); });

registerDockPanel(camPanel());
registerDockPanel(toolPanel());
registerDockPanel(simPanel());
registerDockPanel(nestPanel());
registerDockPanel(additivePanel());

commands.add(
  { id: 'p12-cam-panel', label: 'Manufacture Panel', group: 'Window', run: () => reveal('cam'), enabled: has },
  { id: 'p12-tool-panel', label: 'Tool Library', group: 'Window', run: () => reveal('camtools'), enabled: has },
  { id: 'p12-sim-panel', label: 'Simulation Panel', group: 'Window', run: () => reveal('camsim'), enabled: has },
  { id: 'p12-nest-panel', label: 'Nesting and Cutting', group: 'Window', run: () => reveal('camnest'), enabled: has },
  { id: 'p12-print-panel', label: 'Print Preparation', group: 'Window', run: () => reveal('additive'), enabled: has },
  { id: 'p12-toolpaths', label: 'Toolpaths', group: 'View', run: () => { cam.layer?.setShown(!(cam.layer?.shown ?? true)); }, checked: () => cam.layer?.shown ?? true, enabled: has },
  { id: 'p12-sim-stock', label: 'Simulated Stock', group: 'View', run: () => { simView.layer?.setShown(!(simView.layer?.shown ?? false)); }, checked: () => simView.layer?.shown ?? false, enabled: has },
  { id: 'p12-layers', label: 'Layer Preview', group: 'View', run: () => { previewView.layer?.setShown(!(previewView.layer?.shown ?? false)); }, checked: () => previewView.layer?.shown ?? false, enabled: has },
);

onShellMounted((ctx) => {
  const root = ctx.hosts.root;
  const apply = (): void => {
    if (root.dataset.workspace === 'manufacture') { reveal('cam'); reveal('camtools'); reveal('camsim'); }
  };
  new MutationObserver(apply).observe(root, { attributes: true, attributeFilter: ['data-workspace'] });
  apply();
});
