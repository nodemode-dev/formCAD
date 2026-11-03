import { onShellMounted } from '../app';
import { commands } from '../ui/commands';
import { docStore } from '../ui/doc-store';
import { registerDockPanel } from '../ui/dock';
import { onView3d } from '../view3d/mount';
import type { Viewport3D } from '../view3d/viewport';
import { checkSpec, costSpec } from './cost-panel';
import { inspectSpec } from './inspect-panel';
import { moldState, MoldLayer } from './mold-layer';
import { moldSpec } from './mold-panel';
import { toolboxSpec } from './toolbox-panel';
import { weldSpec } from './weld-panel';

const has = (): boolean => !!docStore.current();
const reveal = (id: string): void => { document.dispatchEvent(new CustomEvent('formcad:ui', { detail: { action: `panel:reveal:${id}` } })); };

function attach(vp: Viewport3D): void {
  if (moldState.layer) return;
  const layer = new MoldLayer(vp);
  layer.setColors(document.body);
  moldState.layer = layer;
  vp.addLayer(layer);
}

document.addEventListener('formcad:view3d-created', (e) => { attach((e as CustomEvent<{ vp: Viewport3D }>).detail.vp); });
onView3d((c) => { if (c.vp) attach(c.vp); });

registerDockPanel(weldSpec());
registerDockPanel(moldSpec());
registerDockPanel(toolboxSpec());
registerDockPanel(inspectSpec());
registerDockPanel(costSpec());
registerDockPanel(checkSpec());

commands.add(
  { id: 'p15-weld-panel', label: 'Weldment', group: 'Window', run: () => reveal('weld'), enabled: has },
  { id: 'p15-mold-panel', label: 'Mold Tools', group: 'Window', run: () => reveal('mold'), enabled: has },
  { id: 'p15-toolbox-panel', label: 'Toolbox', group: 'Window', run: () => reveal('toolbox'), enabled: has },
  { id: 'p15-inspect-panel', label: 'Inspection and Model Views', group: 'Window', run: () => reveal('inspect'), enabled: has },
  { id: 'p15-cost-panel', label: 'Cost and DFM', group: 'Window', run: () => reveal('cost'), enabled: has },
  { id: 'p15-check-panel', label: 'Design Check and Sustainability', group: 'Window', run: () => reveal('check'), enabled: has },
  { id: 'p15-draft-colours', label: 'Draft and Undercut Colours', group: 'View', run: () => { moldState.layer?.setShown(!(moldState.layer?.shown ?? false)); }, checked: () => moldState.layer?.shown ?? false, enabled: has },
);

onShellMounted((ctx) => {
  const root = ctx.hosts.root;
  const apply = (): void => {
    if (root.dataset.workspace === 'produce') { reveal('weld'); reveal('mold'); reveal('toolbox'); reveal('inspect'); reveal('cost'); reveal('check'); }
  };
  new MutationObserver(apply).observe(root, { attributes: true, attributeFilter: ['data-workspace'] });
  apply();
});
