import { commands } from '../ui/commands';
import { docStore } from '../ui/doc-store';
import { registerDockPanel } from '../ui/dock';
import { isAssembly } from '../u8/asm';
import { onView3d } from '../view3d/mount';
import type { Viewport3D } from '../view3d/viewport';
import { CommentLayer } from './comment-layer';
import { JointLayer } from './joint-layer';
import { jointPanel } from './joint-panel';
import { joints, jointView } from './joint-store';
import { motionPanel } from './motion-panel';
import { run } from './motion-run';
import { commentLayer, vaultPanel } from './vault-panel';
import { vstore } from './vault-store';

const has = (): boolean => !!docStore.current();
const reveal = (id: string): void => { document.dispatchEvent(new CustomEvent('formcad:ui', { detail: { action: `panel:reveal:${id}` } })); };

function attach(vp: Viewport3D): void {
  if (jointView.layer) return;
  const jl = new JointLayer(vp);
  const cl = new CommentLayer(vp);
  jointView.layer = jl;
  commentLayer.layer = cl;
  vp.addLayer(jl);
  vp.addLayer(cl);
  jl.set(joints.joints);
  cl.set(vstore.comments);
  if (import.meta.env.DEV) Object.assign(window, { formcadP11: { joints, run, vstore, vp, jointLayer: jl, commentLayer: cl } });
}

document.addEventListener('formcad:view3d-created', (e) => { attach((e as CustomEvent<{ vp: Viewport3D }>).detail.vp); });
onView3d((c) => { if (c.vp) attach(c.vp); });

registerDockPanel(jointPanel());
registerDockPanel(motionPanel());
registerDockPanel(vaultPanel());

commands.add(
  { id: 'p11-joints-panel', label: 'Joints', group: 'Window', run: () => reveal('joints'), enabled: isAssembly },
  { id: 'p11-motion-panel', label: 'Motion Study', group: 'Window', run: () => reveal('motion'), enabled: isAssembly },
  { id: 'p11-vault-panel', label: 'Vault', group: 'Window', run: () => reveal('vault'), enabled: has },
  { id: 'p11-joint-symbols', label: 'Joint Symbols', group: 'View', run: () => { jointView.layer?.setShown(!(jointView.layer?.shown ?? true)); }, checked: () => jointView.layer?.shown ?? true, enabled: isAssembly },
  { id: 'p11-run-study', label: 'Play Motion Study', group: 'Assembly', run: () => { reveal('motion'); run.play(); }, enabled: isAssembly },
);
