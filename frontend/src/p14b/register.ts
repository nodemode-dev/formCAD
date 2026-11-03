import { onShellMounted } from '../app';
import { commands } from '../ui/commands';
import { docStore } from '../ui/doc-store';
import { registerDockPanel } from '../ui/dock';
import { onView3d } from '../view3d/mount';
import type { Viewport3D } from '../view3d/viewport';
import { BoardLayer } from './board-layer';
import { outPanel } from './out-panel';
import { pcbPanel } from './pcb-panel';
import { schPanel } from './sch-panel';
import { ecStage } from './stage';
import { ec } from './store';

const reveal = (id: string): void => { document.dispatchEvent(new CustomEvent('formcad:ui', { detail: { action: `panel:reveal:${id}` } })); };
const isE = (): boolean => !!docStore.current() && ec.isEcad();

function attach(vp: Viewport3D): void {
  if (ecStage.layer) return;
  const layer = new BoardLayer(vp);
  layer.colors(document.body);
  ecStage.layer = layer;
  ecStage.vp = vp;
  vp.addLayer(layer);
  if (import.meta.env.DEV) Object.assign(window, { formcadP14b: { ec, ecStage, layer, vp } });
}

document.addEventListener('formcad:view3d-created', (e) => { attach((e as CustomEvent<{ vp: Viewport3D }>).detail.vp); });
onView3d((c) => { if (c.vp) attach(c.vp); });

registerDockPanel(schPanel());
registerDockPanel(pcbPanel());
registerDockPanel(outPanel());

commands.add(
  { id: 'p14b-sch-panel', label: 'Schematic Panel', group: 'Window', run: () => reveal('ecsch'), enabled: isE },
  { id: 'p14b-pcb-panel', label: 'Board Panel', group: 'Window', run: () => reveal('ecpcb'), enabled: isE },
  { id: 'p14b-out-panel', label: 'Board Outputs Panel', group: 'Window', run: () => reveal('ecout'), enabled: isE },
  { id: 'p14b-tab-sch', label: 'Schematic Editor', group: 'Electronics', run: () => { void ecStage.show().then(() => ecStage.setTab('sch')); }, enabled: isE },
  { id: 'p14b-tab-pcb', label: 'Board Editor', group: 'Electronics', run: () => { void ecStage.show().then(() => ecStage.setTab('pcb')); }, enabled: isE },
  { id: 'p14b-tab-3d', label: '3D Board', group: 'Electronics', run: () => { void ecStage.show().then(() => ecStage.setTab('b3d')); }, enabled: isE },
  { id: 'p14b-drc', label: 'Run Design Rule Check', group: 'Electronics', run: () => { void ec.runDrc(); }, enabled: isE },
  { id: 'p14b-route', label: 'Autoroute Board', group: 'Electronics', run: () => { void ec.route({ mode: 'unrouted' }); }, enabled: () => isE() && !ec.jobRunning },
  { id: 'p14b-route-cancel', label: 'Cancel Autoroute', group: 'Electronics', run: () => { void ec.cancel(); }, enabled: () => ec.jobRunning },
);

onShellMounted((ctx) => {
  const root = ctx.hosts.root;
  ecStage.mount(ctx.hosts.stage);
  const seen = new Set<string>();
  const apply = (): void => {
    const ws = root.dataset.workspace;
    if (isE() && ws !== 'electronics' && !seen.has(ec.docId || String(docStore.activeId))) {
      seen.add(ec.docId || String(docStore.activeId));
      const sel = root.querySelector<HTMLSelectElement>('.cv-tt-select');
      if (sel) { sel.value = 'electronics'; sel.dispatchEvent(new Event('change', { bubbles: true })); }
    }
    if (root.dataset.workspace === 'electronics' && isE()) {
      void ecStage.show();
      reveal('ecsch'); reveal('ecpcb'); reveal('ecout');
    } else if (ecStage.isOpen()) void ecStage.hide();
  };
  new MutationObserver(apply).observe(root, { attributes: true, attributeFilter: ['data-workspace'] });
  docStore.onChange(() => { ec.switchDoc(); apply(); });
  apply();
});
