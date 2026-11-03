import { onShellMounted } from '../app';
import { events } from '../io/events';
import { registerInterceptor } from '../ui/dialogs/intercept';
import { docStore } from '../ui/doc-store';
import { el, q, setClass, setTitle } from '../ui/dom';
import { icon } from '../ui/icons';
import { t } from '../ui/i18n';
import { toast } from '../ui/toast';
import { onView3d, view3d } from '../view3d/mount';
import type { Viewport3D } from '../view3d/viewport';
import { graphBus, graphEditor, registerNodeWidget } from '../graph';
import { BakeDialog } from './bake-dialog';
import { buttonWidget, panelWidget, toggleWidget, valueListWidget } from './inputs';
import { previewScene } from './net';
import { OptimizerPanel } from './optimizer';
import { NodePalette, registerIcons } from './palette';
import { GraphPreviewLayer } from './preview-layer';
import { RunDialog, exportDialog, importDialog } from './run-dialog';
import { sliderWidget } from './slider';

for (const [kinds, factory] of [
  [['slider', 'input.slider'], sliderWidget], [['panel', 'input.panel'], panelWidget], [['toggle', 'input.toggle'], toggleWidget],
  [['button', 'input.button'], buttonWidget], [['value_list', 'input.value_list'], valueListWidget],
] as const) for (const k of kinds) registerNodeWidget(k, factory);
registerIcons();

let layer: GraphPreviewLayer | null = null;
let bake: BakeDialog | null = null;
let run: RunDialog | null = null;
let palette: NodePalette | null = null;
let optimizer: OptimizerPanel | null = null;
const buttons = new Map<string, HTMLButtonElement>();

let shownFor = '';
let fetching = false;
let again = false;
let timer = 0;

async function pullPreview(): Promise<void> {
  if (!layer) return;
  const gid = graphEditor.gid();
  if (!gid || !docStore.activeId) { layer.clear(); return; }
  if (fetching) { again = true; return; }
  fetching = true;
  try {
    if (shownFor !== gid) { shownFor = gid; layer.reset(); }
    layer.apply(await previewScene(gid));
    layer.frame();
  } catch { layer.clear(); } finally {
    fetching = false;
    if (again) { again = false; queue(); }
  }
}

function queue(): void {
  window.clearTimeout(timer);
  timer = window.setTimeout(() => { void pullPreview(); }, 30);
}

function attach(vp: Viewport3D): void {
  if (layer) return;
  layer = new GraphPreviewLayer(vp);
  vp.addLayer(layer);
  if (import.meta.env.DEV) Object.assign(window, { formcadGraphx: { layer, stats: layer.stats } });
  queue();
}

document.addEventListener('formcad:view3d-created', (e) => { attach((e as CustomEvent<{ vp: Viewport3D }>).detail.vp); });
onView3d((c) => { if (c.vp) attach(c.vp); });

events.on('graph', (e) => {
  if (e.id !== docStore.activeId || e.graph !== graphEditor.gid()) return;
  if (e.reason === 'solved') queue();
});
graphBus.on('open', (d) => {
  if (d.gid) { queue(); return; }
  if (layer && layer.bounds()) void view3d()?.with3d(() => { layer?.frame(); });
});
graphBus.on('selection', (d) => { layer?.select((d.nodes as string[] | undefined) ?? []); });
docStore.onChange(() => { if (layer && !docStore.activeId) layer.clear(); });

const guard = (): boolean => {
  if (!docStore.activeId) return false;
  if (!graphEditor.gid()) { toast(t('Open a graph first.')); return false; }
  return true;
};

const doBake = (): boolean => { if (!guard()) return true; bake ??= new BakeDialog(); void bake.show(); return true; };
const doRun = (): boolean => { if (!docStore.activeId) return false; run ??= new RunDialog(); run.show(); return true; };
const doImport = (): boolean => { if (!docStore.activeId) return false; void importDialog(); return true; };
const doExport = (): boolean => { if (!guard()) return true; void exportDialog(); return true; };
const doOptimize = (): boolean => {
  if (!guard()) return true;
  void graphEditor.show().then(() => { optimizer?.toggle(true); paintButtons(); });
  return true;
};

registerInterceptor(['graphbake'], doBake);
registerInterceptor(['graphrun'], doRun);
registerInterceptor(['graphimport'], doImport);
registerInterceptor(['graphexport'], doExport);
registerInterceptor(['graphoptimize'], doOptimize);

function paintButtons(): void {
  setClass(buttons.get('palette') ?? null, 'is-on', !!palette?.shown);
  setClass(buttons.get('optimize') ?? null, 'is-on', !!optimizer?.shown);
}

function mount(stage: HTMLElement, tries: number): void {
  const root = stage.querySelector<HTMLElement>('.gx-root');
  if (!root) {
    if (tries < 200) requestAnimationFrame(() => { mount(stage, tries + 1); });
    return;
  }
  palette = new NodePalette();
  optimizer = new OptimizerPanel();
  root.append(palette.root, optimizer.root);
  const group = el('<span class="gp-tools"></span>');
  const add = (key: string, glyph: string, label: string, run2: () => void): void => {
    const b = el<HTMLButtonElement>(`<button class="gx-btn" type="button" data-x="${key}">${icon(glyph, 16)}</button>`);
    setTitle(b, t(label));
    b.setAttribute('aria-label', t(label));
    b.addEventListener('click', run2);
    group.appendChild(b);
    buttons.set(key, b);
  };
  add('palette', 'gcPalette', 'Node palette', () => { palette?.toggle(); paintButtons(); });
  add('bake', 'gcBake', 'Bake to geometry', () => { doBake(); });
  add('optimize', 'gcOptimize', 'Optimizer', () => { optimizer?.toggle(); paintButtons(); });
  add('run', 'gcRun', 'Run headless', () => { doRun(); });
  add('import', 'importFile', 'Import graph', () => { doImport(); });
  add('export', 'exportFile', 'Export graph', () => { doExport(); });
  const head = q(root, '.gx-head');
  const grow = head.querySelector('.gx-grow');
  head.insertBefore(group, grow);
  head.insertBefore(el('<span class="gx-sep"></span>'), group);
  const sync = (): void => {
    if (palette?.shown) palette.sync();
    if (optimizer?.shown) optimizer.sync();
    const has = !!graphEditor.gid();
    for (const k of ['bake', 'optimize', 'export']) (buttons.get(k) as HTMLButtonElement).disabled = !has;
  };
  graphEditor.store.onChange((what) => { if (what === 'open' || what === 'list' || what === 'graph') sync(); });
  graphBus.on('open', () => { void graphEditor.store.ensureCatalogue().then(sync); });
  sync();
  void graphEditor.store.ensureCatalogue().then(sync).catch(() => { return; });
  if (import.meta.env.DEV) Object.assign(window, { formcadGraphEditor: graphEditor });
}

onShellMounted((ctx) => { mount(ctx.hosts.stage, 0); });
