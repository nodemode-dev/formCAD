import { onShellMounted } from '../app';
import { registerDockPanel } from './dock';
import { ViewManager, NamedViewports } from './dialogs/view-dialogs';
import { registerInterceptor } from './dialogs/intercept';
import { docStore } from './doc-store';
import { sendCommand } from './dialogs/engine';
import { AttributeEditor, BlockAttributeManager, BlocksWindow, EditBlockDialog, InsertDialog, XrefPalette, attributeTarget, editorBar } from './dialogs/block-dialogs';
import './layout-tabs';
import { layersPanel } from './panels/layers-panel';
import { openLayerManager } from './panels/layer-manager';

let views: ViewManager | null = null;
let named: NamedViewports | null = null;

const openViews = (): boolean => {
  if (!docStore.activeId) return true;
  views ??= new ViewManager();
  void views.show();
  return true;
};

const openNamed = (): boolean => {
  if (!docStore.activeId) return true;
  named ??= new NamedViewports();
  void named.show();
  return true;
};

let blocksWin: BlocksWindow | null = null;
let insertDlg: InsertDialog | null = null;
let attEditor: AttributeEditor | null = null;
let battman: BlockAttributeManager | null = null;
let editBlock: EditBlockDialog | null = null;
let xrefs: XrefPalette | null = null;

const guarded = (run: () => void): (() => boolean) => () => { if (docStore.activeId) run(); return true; };

registerInterceptor(['blocks', 'blockspalette', 'insertpalette'], guarded(() => { blocksWin ??= new BlocksWindow(); void blocksWin.show(); }));
registerInterceptor(['insert', 'i', 'ddinsert'], guarded(() => { insertDlg ??= new InsertDialog(); void insertDlg.show(); }));
registerInterceptor(['battman'], guarded(() => { battman ??= new BlockAttributeManager(); void battman.show(); }));
registerInterceptor(['bedit', 'be'], guarded(() => { editBlock ??= new EditBlockDialog(); void editBlock.show(); }));
registerInterceptor(['xref', 'xr', 'externalreferences', 'xattach', 'xa'], guarded(() => { xrefs ??= new XrefPalette(); void xrefs.show(); }));
registerInterceptor(['attedit', 'ate', 'eattedit'], () => {
  if (!docStore.activeId) return true;
  void attributeTarget().then((h) => {
    if (h === null) { sendCommand('-attedit'); return; }
    attEditor ??= new AttributeEditor();
    void attEditor.show(h);
  });
  return true;
});

registerInterceptor(['layer', 'la', 'layers', 'ddlmodes'], openLayerManager);
registerInterceptor(['view', 'v', 'ddview'], openViews);

onShellMounted((ctx) => {
  const { commands } = ctx;
  const ui = (action: string): void => { document.dispatchEvent(new CustomEvent('formcad:ui', { detail: { action } })); };
  const override = (id: string, run: () => void): void => {
    const c = commands.get(id);
    if (c) c.run = run;
  };
  override('x:layer:manager', () => { openLayerManager(); });
  override('x:vports:named', () => { openNamed(); });
  override('win-layers', () => ui('panel:reveal:layers'));
  registerDockPanel(layersPanel());
  editorBar.mount(ctx.hosts.stage);
});
