import * as THREE from 'three';
import { api } from '../io/api';
import { commands } from '../ui/commands';
import { docStore } from '../ui/doc-store';
import { selection } from '../ui/panels/selection-bus';
import { toast } from '../ui/toast';
import { view3d } from './mount';

async function projectAlongView(): Promise<void> {
  const id = docStore.activeId;
  const vp = view3d()?.vp;
  if (!id) return;
  if (!vp) { toast('Open the 3D view first; the curves are projected along its view direction.', 'info'); return; }
  const handles = [...new Set<number>([...selection.handles, ...vp.sel.bodies])];
  if (handles.length < 2) { toast('Select the curves and the surfaces to project them onto first.', 'info'); return; }
  const dir = vp.camera.getWorldDirection(new THREE.Vector3());
  try {
    const state = await api.runCommand(id, 'crvproject', { handles, direction: [dir.x, dir.y, dir.z] });
    if (state.error) { toast(state.error, 'error'); return; }
    await view3d()?.with3d(() => undefined);
    toast('The curves were projected along the view direction.', 'info');
  } catch (e) {
    toast(e instanceof Error ? e.message : 'The curves could not be projected', 'error');
  }
}

commands.add({ id: 'u96-project-view', label: 'Project Curves along View', group: 'Draw', run: () => { void projectAlongView(); }, enabled: () => !!docStore.current() });
