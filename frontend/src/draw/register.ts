import { onShellMounted } from '../app';
import { drawingCanvas } from '../canvas/mount';
import { idleExtras } from '../canvas/interact/menu-extra';
import { commands } from '../ui/commands';
import { registerInterceptor } from '../ui/dialogs/intercept';
import { docStore } from '../ui/doc-store';
import { selection } from '../ui/panels/selection-bus';
import { registerDockPanel } from '../ui/dock';
import { t } from '../ui/i18n';
import { dv } from './api';
import { DrawOverlay } from './overlay';
import { palettePanel } from './palette';
import { propsPanel } from './props';
import * as rt from './runtime';
import { STANDARD_VIEWS } from './state';
import { drawStore } from './store';
import { ToolHost } from './tool-host';

const inLayout = (): boolean => drawStore.inLayout;
const hasView = (): boolean => inLayout() && !!drawStore.selected;
const ui = (action: string): void => { document.dispatchEvent(new CustomEvent('formcad:ui', { detail: { action } })); };

const defs: Array<[string, string, () => void, (() => boolean)?]> = [];
for (const v of STANDARD_VIEWS) defs.push([`dw-base-${v.id}`, `${v.label} view`, () => rt.armBase(v.id)]);
defs.push(
  ['dw-section', 'Section View', () => rt.armSection()],
  ['dw-detail', 'Detail View', () => rt.armDetail()],
  ['dw-aux', 'Auxiliary View', () => rt.armAux()],
  ['dw-break', 'Break View', () => rt.armBreak()],
  ['dw-crop', 'Crop View', () => rt.armCrop()],
  ['dw-update', 'Update Out of Date Views', () => { void rt.updateViews(false); }],
  ['dw-update-all', 'Update All Views', () => { void rt.updateViews(true); }],
  ['dw-update-one', 'Update Selected View', () => { const v = drawStore.selected; if (v) void rt.updateOne(v); }, hasView],
  ['dw-delete', 'Delete Selected View', () => { const v = drawStore.selected; if (v) void rt.deleteView(v, false); }, hasView],
  ['dw-proj-third', 'Third Angle Projection', () => { void drawStore.run((id) => dv.projection(id, drawStore.layout, 'third')); }],
  ['dw-proj-first', 'First Angle Projection', () => { void drawStore.run((id) => dv.projection(id, drawStore.layout, 'first')); }],
  ['dw-dim', 'Dimension View Geometry', () => rt.armDim()],
  ['dw-frame', 'Geometric Tolerance Frame', () => rt.armFrame()],
  ['dw-frame-edit', 'Edit Geometric Tolerance Frame...', () => { void rt.openFrameEditor(); }, () => !!docStore.activeId],
  ['dw-datum', 'Datum Feature Symbol', () => rt.armDatum()],
  ['dw-finish', 'Surface Finish Mark', () => rt.armFinish()],
  ['dw-balloon', 'Balloon', () => rt.armBalloon()],
  ['dw-autoballoon', 'Auto Balloons on Selected View', () => { void rt.autoBalloons(); }, hasView],
  ['dw-bom', 'Parts List Table', () => rt.armBom()],
  ['dw-bom-update', 'Update Parts Lists', () => { void rt.bomUpdate(); }, () => !!docStore.activeId],
  ['dw-centermarks', 'Centre Marks on Selected View', () => { void rt.viewAction('centermarks', 'Centre marks: '); }, hasView],
  ['dw-hatch', 'Hatch Section View', () => { void rt.viewAction('sectionhatch', 'Hatches: '); }, hasView],
  ['dw-titleblock', 'Title Block...', () => rt.openTitleBlock(), () => !!docStore.activeId],
  ['dw-settings', 'Annotation Settings...', () => rt.openSettings(), () => !!docStore.activeId],
  ['dw-panel-views', 'Drawing Views Panel', () => ui('panel:reveal:drawviews'), () => !!docStore.activeId],
  ['dw-panel-props', 'View Properties Panel', () => ui('panel:reveal:viewprops'), () => !!docStore.activeId],
);
for (const [id, label, run, enabled] of defs) commands.add({ id, label, group: 'Drawing', run, enabled: enabled ?? inLayout });

const mine = (fn: () => void): (() => boolean) => () => {
  if (!docStore.activeId || !inLayout()) return false;
  fn();
  return true;
};

registerInterceptor(['viewbase'], mine(() => rt.armBase('front')));
registerInterceptor(['viewsection'], mine(() => rt.armSection()));
registerInterceptor(['viewdetail'], mine(() => rt.armDetail()));
registerInterceptor(['viewaux'], mine(() => rt.armAux()));
registerInterceptor(['viewbroken'], mine(() => rt.armBreak()));
registerInterceptor(['viewcrop'], mine(() => rt.armCrop()));
registerInterceptor(['viewupdate'], mine(() => { void rt.updateViews(false); }));
registerInterceptor(['viewdim'], mine(() => rt.armDim()));
registerInterceptor(['gdtframe', 'gdt', 'tolframe'], mine(() => rt.armFrame()));
registerInterceptor(['datumsym', 'datum'], mine(() => rt.armDatum()));
registerInterceptor(['balloon'], mine(() => rt.armBalloon()));
registerInterceptor(['bomtable'], mine(() => rt.armBom()));
registerInterceptor(['finishmark', 'surfacefinish'], mine(() => rt.armFinish()));
registerInterceptor(['titleblock', 'docprops'], () => { if (!docStore.activeId) return false; rt.openTitleBlock(); return true; });
registerInterceptor(['gdtstyle'], () => { if (!docStore.activeId) return false; rt.openSettings(); return true; });
registerInterceptor(['autoballoon'], mine(() => { void rt.autoBalloons(); }));
registerInterceptor(['centermarks'], mine(() => { void rt.viewAction('centermarks', 'Centre marks: '); }));
registerInterceptor(['sectionhatch'], mine(() => { void rt.viewAction('sectionhatch', 'Hatches: '); }));

const run = (id: string) => (): void => { commands.run(id); };
idleExtras.push(() => {
  if (!inLayout()) return [];
  const sel = drawStore.selected;
  return [{
    label: t('Drawing'),
    sub: [
      { label: t('Base View'), sub: STANDARD_VIEWS.slice(0, 7).map((v) => ({ label: t(v.label), run: run(`dw-base-${v.id}`) })) },
      { label: t('Section View'), run: run('dw-section') },
      { label: t('Detail View'), run: run('dw-detail') },
      { label: t('Break View'), run: run('dw-break') },
      { label: t('Crop View'), run: run('dw-crop') },
      { sep: true },
      { label: t('Update Out of Date Views'), run: run('dw-update') },
      { label: t('Update Selected View'), run: run('dw-update-one'), disabled: !sel },
      { sep: true },
      { label: t('Dimension View Geometry'), run: run('dw-dim') },
      { label: t('Geometric Tolerance Frame'), run: run('dw-frame') },
      { label: t('Datum Feature Symbol'), run: run('dw-datum') },
      { label: t('Balloon'), run: run('dw-balloon') },
      { label: t('Parts List Table'), run: run('dw-bom') },
    ],
  }];
});

registerDockPanel(palettePanel());
registerDockPanel(propsPanel());

onShellMounted((ctx) => {
  const canvas = drawingCanvas();
  if (!canvas) return;
  const overlay = new DrawOverlay(ctx.hosts.canvasHost, canvas, drawStore);
  const host = new ToolHost({ canvas, overlay, store: drawStore, host: ctx.hosts.canvasHost });
  overlay.hooks = {
    badge: (v) => { void rt.updateOne(v); },
    tag: (v) => { selection.select([v.handle]); },
    handleDown: (kind, v, e) => rt.dragHandle(kind, v, e),
  };
  rt.setHost(host);
  document.dispatchEvent(new CustomEvent('formcad:draw-host'));
  let lastDoc = docStore.activeId;
  docStore.onChange(() => { if (docStore.activeId !== lastDoc) { lastDoc = docStore.activeId; host.disarm(); } });
  let shown = false;
  drawStore.onChange(() => { if (!shown && drawStore.inLayout) { shown = true; ui('panel:reveal:drawviews'); } });
  if (import.meta.env.DEV) Object.assign(window, { formcadDraw: { store: drawStore, host, rt } });
});
