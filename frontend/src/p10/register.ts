import { onShellMounted } from '../app';
import { commands } from '../ui/commands';
import { docStore } from '../ui/doc-store';
import { registerDockPanel } from '../ui/dock';
import { onView3d, view3d } from '../view3d/mount';
import type { Viewport3D } from '../view3d/viewport';
import { FormLayer } from './form-layer';
import { formPanel } from './form-panel';
import { form } from './form-store';
import { meshPanel } from './mesh-panel';
import { attachPmi, pmiPanel } from './pmi-panel';
import { plasticPanel } from './plastic-panel';
import { runCmd } from './kit';

let formLayer: FormLayer | null = null;

const has = (): boolean => !!docStore.current();
const reveal = (id: string): void => { document.dispatchEvent(new CustomEvent('formcad:ui', { detail: { action: `panel:reveal:${id}` } })); };

function attach(vp: Viewport3D): void {
  attachPmi(vp);
  if (formLayer) return;
  formLayer = new FormLayer(vp);
  formLayer.onCommit = (op) => {
    void form.run(op.command, op.args).then(() => formLayer?.cancelPreview());
  };
  vp.addLayer(formLayer);
  if (import.meta.env.DEV) Object.assign(window, { formcadP10: { form, layer: formLayer } });
}

const setEditing = (on: boolean): void => { formLayer?.setEditing(on); };

registerDockPanel(formPanel(setEditing));
registerDockPanel(meshPanel());
registerDockPanel(pmiPanel());
registerDockPanel(plasticPanel());

document.addEventListener('formcad:view3d-created', (e) => { attach((e as CustomEvent<{ vp: Viewport3D }>).detail.vp); });
onView3d((c) => { if (c.vp) attach(c.vp); });

const PRIMS: Array<[string, string, Record<string, unknown>]> = [
  ['box', 'Form Box', { size: [20, 20, 20], segments: [2, 2, 2] }],
  ['cylinder', 'Form Cylinder', { radius: 10, height: 20, segments: 8, height_segments: 2 }],
  ['sphere', 'Form Sphere', { radius: 10, segments: 8, rings: 6 }],
  ['quadball', 'Form Quadball', { radius: 10, spans: 2 }],
  ['torus', 'Form Torus', { major: 20, minor: 6, segments_major: 12, segments_minor: 8 }],
  ['plane', 'Form Plane', { size: [40, 40], segments: [4, 4] }],
];

async function makePrimitive(kind: string, args: Record<string, unknown>): Promise<void> {
  const r = await runCmd<{ handles?: number[] }>(`subd${kind}`, { origin: [0, 0, 0], ...args });
  if (!r) return;
  await form.refresh();
  const h = r.handles?.[r.handles.length - 1];
  if (h !== undefined) form.setActive(Number(h));
  setEditing(true);
  await view3d()?.with3d(() => undefined);
}

commands.add(
  { id: 'p10-mesh-panel', label: 'Mesh Tools Panel', group: 'Mesh', run: () => reveal('meshws'), enabled: has },
  { id: 'p10-pmi-panel', label: 'Model Notes Panel', group: 'Window', run: () => reveal('pmi'), enabled: has },
  { id: 'pl-panel', label: 'Plastic Part Panel', group: 'Part', run: () => reveal('plastic'), enabled: has },
  { id: 'fm-panel', label: 'Form Panel', group: 'Form', run: () => reveal('form'), enabled: has },
  { id: 'fm-edit', label: 'Edit Form Cage', group: 'Form', run: () => setEditing(!(formLayer?.editing ?? false)), checked: () => !!formLayer?.editing, enabled: () => has() && form.on },
  { id: 'fm-move', label: 'Move Tool', group: 'Form', run: () => { setEditing(true); form.setTool('move'); }, enabled: () => has() && form.on },
  { id: 'fm-rotate', label: 'Rotate Tool', group: 'Form', run: () => { setEditing(true); form.setTool('rotate'); }, enabled: () => has() && form.on },
  { id: 'fm-scale', label: 'Scale Tool', group: 'Form', run: () => { setEditing(true); form.setTool('scale'); }, enabled: () => has() && form.on },
  { id: 'fm-convert', label: 'Convert Form to Solid', group: 'Form', run: () => { void form.run('subdconvert', { handle: form.active, levels: 2, keep: true }, false); }, enabled: () => has() && form.on },
  ...PRIMS.map(([kind, label, args]) => ({ id: `fm-${kind}`, label, group: 'Form', run: () => { void makePrimitive(kind, args); }, enabled: has })),
);

onShellMounted((ctx) => {
  const root = ctx.hosts.root;
  const apply = (): void => {
    const on = root.dataset.workspace === 'form';
    setEditing(on);
    if (on) reveal('form');
  };
  new MutationObserver(apply).observe(root, { attributes: true, attributeFilter: ['data-workspace'] });
  apply();
});
