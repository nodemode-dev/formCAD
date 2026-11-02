import { onShellMounted } from '../../app';
import { registerInterceptor } from '../dialogs/intercept';
import { docStore } from '../doc-store';
import { pickExportPath, pickImportPath, pickPlotPath } from '../file-dialogs';
import { t } from '../i18n';
import { toast } from '../toast';
import { followJob, trackWork } from './job-feed';
import { tellNotes } from './notes';
import { failure, out } from './output-api';
import { PageSetupManager } from './page-setup-manager';
import { PlotDialog, previewWindow } from './plot-dialog';
import { PlotStyleDialog } from './plot-style-dialog';
import { PlotterDialog } from './plotter-dialog';
import { PublishDialog } from './publish-dialog';

let plot: PlotDialog | null = null;
let setup: PageSetupManager | null = null;
let styles: PlotStyleDialog | null = null;
let plotter: PlotterDialog | null = null;
let publish: PublishDialog | null = null;

const baseName = (): string => (docStore.current()?.name ?? 'Drawing').replace(/\.[^.]+$/, '');
const tail = (p: string): string => p.split(/[\\/]/).pop() ?? p;
const ext = (p: string): string => /\.([A-Za-z0-9]+)$/.exec(p.trim())?.[1].toLowerCase() ?? '';

async function currentLayout(id: string): Promise<string> {
  try { return (await out.layouts(id)).current || 'Model'; } catch { return 'Model'; }
}

async function plotFile(id: string, path: string, kind: string): Promise<void> {
  const layout = await currentLayout(id);
  try {
    const job = await out.plot(id, { layout, path }, kind);
    const done = await followJob(job, `${t('Export')} ${tail(path)}`);
    if (done.state === 'done') toast(`${t('Exported')} ${layout} ${t('to')} ${done.path || path}`);
  } catch (e) {
    toast(failure(e), 'error');
  }
}

async function exportCommand(): Promise<void> {
  const id = docStore.activeId;
  if (!id) return;
  const path = await pickExportPath(`${baseName()}.dxf`);
  if (!path) return;
  const kind = ext(path);
  if (kind === 'pdf' || kind === 'png' || kind === 'svg') { await plotFile(id, path, kind); return; }
  try {
    const r = await trackWork(`${t('Export')} ${tail(path)}`, () => out.exportFile(id, path));
    tellNotes(`${t('Exported')} ${tail(path)}.`, r.notes);
  } catch (e) {
    toast(failure(e), 'error');
  }
}

async function exportPdfCommand(): Promise<void> {
  const id = docStore.activeId;
  if (!id) return;
  const path = await pickPlotPath(`${baseName()}.pdf`, 'pdf');
  if (path) await plotFile(id, path, 'pdf');
}

async function importCommand(): Promise<void> {
  const id = docStore.activeId;
  if (!id) return;
  const path = await pickImportPath();
  if (!path) return;
  try {
    const r = await trackWork(`${t('Import')} ${tail(path)}`, () => out.importFile(id, path));
    const n = r.added.objects;
    tellNotes(`${t('Imported')} ${n} ${t('objects from')} ${tail(path)}.`, r.report);
    void docStore.refresh();
  } catch (e) {
    toast(failure(e), 'error');
  }
}

async function previewCommand(): Promise<void> {
  const id = docStore.activeId;
  if (!id) return;
  const layout = await currentLayout(id);
  previewWindow().onClose = null;
  await previewWindow().show(id, { layout }, layout, () => { void (plot ??= new PlotDialog()).show(layout); });
}

registerInterceptor(['plot', 'print'], () => { void (plot ??= new PlotDialog()).show(); return true; });
registerInterceptor(['plotpreview', 'preview', 'pre'], () => { void previewCommand(); return true; });
registerInterceptor(['pagesetup'], () => { void (setup ??= new PageSetupManager()).show(); return true; });
registerInterceptor(['stylesmanager', 'plotstyle'], () => { void (styles ??= new PlotStyleDialog()).showFor(); return true; });
registerInterceptor(['plottermanager'], () => { void (plotter ??= new PlotterDialog()).showFor(); return true; });
registerInterceptor(['publish', 'sheetbooks'], () => { void (publish ??= new PublishDialog()).showFor(); return true; });
registerInterceptor(['export'], () => { void exportCommand(); return true; });
registerInterceptor(['exportpdf'], () => { void exportPdfCommand(); return true; });
registerInterceptor(['import'], () => { void importCommand(); return true; });
registerInterceptor(['saveas'], () => { void docStore.saveAs(); return true; });
registerInterceptor(['open'], () => { void docStore.openByPrompt(); return true; });

onShellMounted(() => {
  plot ??= new PlotDialog();
  setup ??= new PageSetupManager();
  styles ??= new PlotStyleDialog();
  plotter ??= new PlotterDialog();
  publish ??= new PublishDialog();
  previewWindow();
});
