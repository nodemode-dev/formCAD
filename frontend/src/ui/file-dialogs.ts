import { PathDialog, type FileKind } from './output/path-dialog';

export type { FileKind } from './output/path-dialog';

const FCAD: FileKind = { name: 'FormCAD project', extensions: ['fcad'] };
const DXF: FileKind = { name: 'DXF drawing', extensions: ['dxf'] };
const DWG: FileKind = { name: 'DWG drawing (needs a converter)', extensions: ['dwg'] };
const DWT: FileKind = { name: 'Drawing template', extensions: ['dwt'] };
const SVG: FileKind = { name: 'SVG image', extensions: ['svg', 'svgz'] };
const PNG: FileKind = { name: 'PNG image', extensions: ['png'] };
const PDF: FileKind = { name: 'PDF document', extensions: ['pdf'] };

export const OPEN_KINDS: FileKind[] = [{ name: 'All drawings', extensions: ['fcad', 'dxf', 'dwg', 'dwt', 'svg', 'svgz'] }, FCAD, DXF, DWG, DWT, SVG];
export const SAVE_KINDS: FileKind[] = [FCAD, DXF, DWG, DWT];
export const EXPORT_KINDS: FileKind[] = [DXF, DWG, DWT, SVG, PNG, PDF];
export const IMPORT_KINDS: FileKind[] = [{ name: 'All importable files', extensions: ['dxf', 'dwg', 'svg', 'svgz'] }, DXF, DWG, SVG];
export const PLOT_KINDS: Record<string, FileKind> = { pdf: PDF, png: PNG, svg: { name: 'SVG image', extensions: ['svg'] } };

const native = (): boolean => '__TAURI_INTERNALS__' in window;
let pathDialog: PathDialog | null = null;

export async function pickPath(mode: 'open' | 'save', title: string, suggested: string, kinds: FileKind[], okLabel: string): Promise<string | null> {
  if (native()) {
    try {
      const dlg = await import('@tauri-apps/plugin-dialog');
      if (mode === 'open') {
        const picked = await dlg.open({ multiple: false, directory: false, title, filters: kinds });
        return typeof picked === 'string' ? picked : null;
      }
      return (await dlg.save({ title, defaultPath: suggested, filters: kinds })) ?? null;
    } catch {
      return null;
    }
  }
  pathDialog ??= new PathDialog();
  return pathDialog.ask(title, suggested, kinds, mode === 'save', okLabel);
}

export const pickOpenPath = (): Promise<string | null> => pickPath('open', 'Open', '', OPEN_KINDS, 'Open');
export const pickSavePath = (suggested: string): Promise<string | null> => pickPath('save', 'Save As', suggested, SAVE_KINDS, 'Save');
export const pickImportPath = (): Promise<string | null> => pickPath('open', 'Import', '', IMPORT_KINDS, 'Import');
export const pickLayoutTemplatePath = (): Promise<string | null> => pickPath('open', 'Layout From Template', '', [{ name: 'Layout templates', extensions: ['fcad', 'dxf', 'dwt'] }, FCAD, DXF, DWT], 'Import');
export const pickExportPath =(suggested: string): Promise<string | null> => pickPath('save', 'Export', suggested, EXPORT_KINDS, 'Export');
export const pickPlotPath = (suggested: string, output: string): Promise<string | null> => pickPath('save', 'Plot to File', suggested, [PLOT_KINDS[output] ?? PDF], 'Plot');

export async function onOpenPaths(handler: (paths: string[]) => void): Promise<void> {
  if (!native()) return;
  try {
    const { listen } = await import('@tauri-apps/api/event');
    const { invoke } = await import('@tauri-apps/api/core');
    await listen<string[]>('formcad://open-paths', (e) => { if (Array.isArray(e.payload)) handler(e.payload); });
    const pending = await invoke<string[]>('take_pending_opens');
    if (pending.length) handler(pending);
  } catch {
    return;
  }
}
