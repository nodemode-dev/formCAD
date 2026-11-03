import { onShellMounted } from '../app';
import { commands } from '../ui/commands';
import { docStore } from '../ui/doc-store';
import { registerDockPanel } from '../ui/dock';
import { toast } from '../ui/toast';
import { t } from '../ui/i18n';
import { onView3d, view3d } from '../view3d/mount';
import type { Viewport3D } from '../view3d/viewport';
import { RenderDialog } from './dialog';
import { LiveRender, type LiveStats } from './live';
import { renderPanel } from './panel';
import { renderStore } from './store';
import { TurntablePreview, turntableViews } from './turntable';

let vp: Viewport3D | null = null;
let live: LiveRender | null = null;
let dialog: RenderDialog | null = null;
let watcher: ((s: LiveStats) => void) | null = null;
let on = false;

const has = (): boolean => !!docStore.current();
const reveal = (id: string): void => { document.dispatchEvent(new CustomEvent('formcad:ui', { detail: { action: `panel:reveal:${id}` } })); };

const turntable = new TurntablePreview(
  () => (vp ? vp.getCamera() : { position: [1, -1, 1], target: [0, 0, 0], up: [0, 0, 1], projection: 'perspective', fov: 35, height: 1 }),
  (c) => { vp?.setCamera(c, false); },
);

function ensureLive(): LiveRender | null {
  if (live || !vp) return live;
  live = new LiveRender(vp, () => docStore.activeId);
  live.onStats = (s) => watcher?.(s);
  return live;
}

async function setMode(next: boolean): Promise<void> {
  if (next === on) return;
  if (next) {
    await view3d()?.with3d(() => undefined);
    if (!vp) { toast(t('The 3D view is not available.'), 'error'); return; }
    if (!renderStore.settings || renderStore.docId !== docStore.activeId) await renderStore.load();
    const s = renderStore.settings;
    if (!s) { toast(t(renderStore.error || 'Open a document first.'), 'error'); return; }
    const l = ensureLive();
    if (!l) return;
    on = true;
    l.start(s);
    reveal('render');
  } else {
    on = false;
    turntable.stop();
    live?.stop();
    vp?.invalidate();
  }
}

dialog = new RenderDialog();
dialog.getView = () => (vp ? vp.getCamera() : null);

let frameCount = 0;
let frameSweep = 360;

registerDockPanel(renderPanel({
  vp: () => vp,
  live: () => ensureLive(),
  setMode,
  isOn: () => on,
  watch: (fn) => { watcher = fn; if (live) live.onStats = (s) => fn(s); },
  dialog,
  turntable,
  turntableFrames: (n, sweep) => { frameCount = n; frameSweep = sweep; },
}));

dialog.framePlan = () => {
  if (!vp || frameCount < 1) return [];
  return turntableViews(vp.getCamera(), frameCount, frameSweep).map((view) => ({ view, out: '' }));
};

const origShow = dialog.show.bind(dialog);
dialog.show = (mode) => {
  if (mode === 'image') frameCount = 0;
  origShow(mode);
};

onView3d((c) => { if (c.vp) vp = c.vp; });
document.addEventListener('formcad:view3d-created', (e) => { vp = (e as CustomEvent<{ vp: Viewport3D }>).detail.vp; });

commands.add(
  { id: 'rn-toggle', label: 'Render View', group: 'Render', run: () => { void setMode(!on); }, checked: () => on, enabled: has },
  { id: 'rn-panel', label: 'Render Panel', group: 'Render', run: () => reveal('render'), enabled: has },
  { id: 'rn-image', label: 'Render Image...', group: 'Render', run: () => { reveal('render'); void renderStore.load().then(() => { frameCount = 0; dialog?.show('image'); }); }, enabled: has },
  { id: 'rn-turntable', label: 'Render Turntable...', group: 'Render', run: () => { reveal('render'); void renderStore.load().then(() => { frameCount = 36; frameSweep = 360; dialog?.show('turntable'); }); }, enabled: has },
);

onShellMounted(() => {
  docStore.onChange(() => { if (on && !docStore.activeId) void setMode(false); });
});

if (import.meta.env.DEV) Object.assign(window, { formcadRender: { store: renderStore, setMode, live: () => live, dialog } });
