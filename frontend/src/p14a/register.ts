import { commands } from '../ui/commands';
import { docStore } from '../ui/doc-store';
import { registerDockPanel } from '../ui/dock';
import { onView3d } from '../view3d/mount';
import type { Viewport3D } from '../view3d/viewport';
import { genPanel } from './gen-panel';
import { gen } from './gen-store';
import { harnessPanel, layerRef } from './harness-panel';
import { pipeLayerRef, pipePanel } from './pipe-panel';
import { RouteLayer } from './route-layer';
import { schemPanel } from './schem-panel';

const has = (): boolean => !!docStore.current();
const reveal = (id: string): void => { document.dispatchEvent(new CustomEvent('formcad:ui', { detail: { action: `panel:reveal:${id}` } })); };

function attach(vp: Viewport3D): void {
  if (layerRef.layer) return;
  const layer = new RouteLayer(vp);
  layer.setShown(false);
  layerRef.layer = layer;
  pipeLayerRef.layer = layer;
  vp.addLayer(layer);
  if (import.meta.env.DEV) Object.assign(window, { formcadP14a: { gen, layer } });
}

document.addEventListener('formcad:view3d-created', (e) => { attach((e as CustomEvent<{ vp: Viewport3D }>).detail.vp); });
onView3d((c) => { if (c.vp) attach(c.vp); });

registerDockPanel(genPanel());
registerDockPanel(harnessPanel());
registerDockPanel(pipePanel());
registerDockPanel(schemPanel());

commands.add(
  { id: 'p14a-gen-panel', label: 'Generative Design', group: 'Window', run: () => reveal('gen'), enabled: has },
  { id: 'p14a-harness-panel', label: 'Harness', group: 'Window', run: () => reveal('harness'), enabled: has },
  { id: 'p14a-pipe-panel', label: 'Pipes and Tubing', group: 'Window', run: () => reveal('pipes'), enabled: has },
  { id: 'p14a-schem-panel', label: 'Electrical Schematic', group: 'Window', run: () => reveal('schem'), enabled: has },
  { id: 'p14a-gen-run', label: 'Run Generative Study', group: 'Generate', run: () => { void gen.run(); }, enabled: () => has() && !!gen.study() && !gen.running },
  { id: 'p14a-gen-cancel', label: 'Cancel Generative Run', group: 'Generate', run: () => { void gen.cancel(); }, enabled: () => gen.running },
  { id: 'p14a-gen-hide', label: 'Hide Outcome in the View', group: 'Generate', run: () => { gen.hide(); gen.emit(); }, enabled: () => !!gen.shown },
  { id: 'p14a-route-show', label: 'Routes in the View', group: 'View', run: () => { const l = layerRef.layer; l?.setShown(!(l.group.visible)); }, checked: () => layerRef.layer?.group.visible ?? false, enabled: has },
);
