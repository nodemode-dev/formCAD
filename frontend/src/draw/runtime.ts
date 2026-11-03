import { docStore } from '../ui/doc-store';
import { selection } from '../ui/panels/selection-bus';
import { toast } from '../ui/toast';
import { t } from '../ui/i18n';
import { dv, messageOf, type ViewInfo } from './api';
import { BalloonEditor, DatumEditor, FrameEditor, SettingsDialog, TitleBlockDialog } from './editors';
import { drawStore } from './store';
import type { Tool, ToolHost } from './tool-host';
import { dimensionTool, finishTool, placeTool, runAnnot } from './tools-annot';
import { auxTool, baseTool, breakTool, cropTool, detailTool, moveDrag, projectDrag, sectionTool } from './tools-view';

const cache = new Map<string, Tool>();
let host: ToolHost | null = null;
let frameEd: FrameEditor | null = null;
let datumEd: DatumEditor | null = null;
let balloonEd: BalloonEditor | null = null;
let titleDlg: TitleBlockDialog | null = null;
let settingsDlg: SettingsDialog | null = null;
let datumCount = 0;
let balloonCount = 0;

export const setHost = (h: ToolHost): void => { host = h; };
export const toolHost = (): ToolHost | null => host;
export const activeTool = (): string => host?.active?.id ?? '';

const tool = (key: string, make: (h: ToolHost) => Tool): Tool | null => {
  if (!host) return null;
  let tl = cache.get(key);
  if (!tl) { tl = make(host); cache.set(key, tl); }
  return tl;
};

const arm = (tl: Tool | null): void => { if (tl) host?.arm(tl); };

export const armBase = (id: string): void => {
  if (!host) return;
  host.arm(baseTool(host, id));
};
export const armSection = (): void => arm(tool('section', sectionTool));
export const armDetail = (): void => arm(tool('detail', detailTool));
export const armAux = (): void => arm(tool('aux', auxTool));
export const armBreak = (): void => arm(tool('break', breakTool));
export const armCrop = (): void => arm(tool('crop', cropTool));
export const armDim = (): void => arm(tool('dim', dimensionTool));
export const armFinish = (): void => arm(tool('finish', finishTool));

export function armFrame(): void {
  arm(tool('frame', (h) => placeTool(h, {
    id: 'frame', title: 'Geometric tolerance frame', hint: 'Click where the frame goes.', tipHint: 'Click the feature the leader points at, or choose No leader.',
    done: async (at, tip) => { frameEd ??= new FrameEditor(); await frameEd.create({ point: at, ...tip }); },
  })));
}

export function armDatum(): void {
  arm(tool('datum', (h) => placeTool(h, {
    id: 'datum', title: 'Datum feature symbol', hint: 'Click where the symbol goes.', tipHint: 'Click the feature it marks, or choose No leader.',
    done: (at, tip) => { datumEd ??= new DatumEditor(); datumEd.show({ point: at, ...tip }, String.fromCharCode(65 + (datumCount++ % 26))); },
  })));
}

export function armBalloon(): void {
  arm(tool('balloon', (h) => placeTool(h, {
    id: 'balloon', title: 'Balloon', hint: 'Click where the balloon goes.', tipHint: 'Click the part edge the balloon points at.',
    done: (at, tip) => { balloonEd ??= new BalloonEditor(); balloonEd.show({ point: at, ...tip }, String(++balloonCount)); },
  })));
}

export function armBom(): void {
  arm(tool('bom', (h) => placeTool(h, {
    id: 'bom', title: 'BOM table', hint: 'Click the corner where the parts list goes.',
    done: async (at) => { const r = await runAnnot('bomtable', { point: at, source: { self: true } }); if (r?.created) { selection.select([Number(r.created)]); toast(`${r.rows} ${t('rows')}.`); } },
  })));
}

export function armTitlePlace(): void {
  arm(tool('titleplace', (h) => placeTool(h, {
    id: 'titleplace', title: 'Title block', hint: 'Click the corner where the title block goes.',
    done: async (at) => { const r = await runAnnot('titleblock', { point: at, layout: drawStore.layout }); if (r) toast(t('Title block placed.')); },
  })));
}

export async function openFrameEditor(): Promise<void> {
  const id = docStore.activeId;
  if (!id) return;
  frameEd ??= new FrameEditor();
  for (const hnd of selection.handles) if (await frameEd.edit(hnd)) return;
  toast(t('Select a geometric tolerance frame first.'));
}

export function openTitleBlock(): void {
  if (!titleDlg) { titleDlg = new TitleBlockDialog(); titleDlg.onPlace = armTitlePlace; }
  void titleDlg.show();
}

export function openSettings(): void {
  settingsDlg ??= new SettingsDialog();
  void settingsDlg.show();
}

export async function autoBalloons(v: ViewInfo | null = drawStore.selected): Promise<void> {
  if (!v) { toast(t('Select a view first.')); return; }
  const asm = docStore.current()?.kind === 'assembly';
  const r = await runAnnot('autoballoon', asm ? { view: v.handle, source: { self: true } } : { view: v.handle });
  if (r) {
    const made = (r.created as number[] | undefined)?.length ?? 0;
    const miss = (r.missing as string[] | undefined) ?? [];
    toast(`${made} ${t('balloons placed.')}${miss.length ? ` ${t('Not placed')}: ${miss.join(', ')}.` : ''}`);
  }
}

export async function viewAction(name: string, done: string): Promise<void> {
  const v = drawStore.selected;
  if (!v) { toast(t('Select a view first.')); return; }
  const r = await runAnnot(name, { view: v.handle });
  if (r) toast(`${done}${(r.created as number[] | undefined)?.length ?? 0}.`);
}

export async function updateViews(all: boolean): Promise<void> {
  const r = await drawStore.run((id) => dv.updateAll(id, all));
  if (r) toast(`${r.updated.length} ${t('views updated.')}`);
}

export async function updateOne(v: ViewInfo): Promise<void> {
  await drawStore.run((id) => dv.update(id, v.handle));
}

export async function bomUpdate(): Promise<void> {
  const r = await runAnnot('bomupdate', {});
  if (r) toast(`${r.updated} ${t('parts lists updated.')}`);
}

export const dragHandle = (kind: string, v: ViewInfo, e: PointerEvent): void => {
  if (!host) return;
  if (kind === 'move') moveDrag(host, v, e);
  else projectDrag(host, v, e);
};

export async function deleteView(v: ViewInfo, cascade: boolean): Promise<void> {
  await drawStore.run((id) => dv.remove(id, v.handle, cascade));
}

export async function sourceRelative(abs: string): Promise<string | null> {
  const cur = docStore.current();
  const base = (cur?.path ?? '').replace(/[\\/][^\\/]*$/, '');
  if (!base) { toast(t('Save the drawing first so a model file can be found beside it.'), 'error'); return null; }
  const norm = (s: string): string => s.replace(/\\/g, '/');
  if (!norm(abs).startsWith(`${norm(base)}/`)) { toast(t('The model file must be in the same folder as the drawing, or below it.'), 'error'); return null; }
  return norm(abs).slice(norm(base).length + 1);
}

export const failToast = (e: unknown): void => { toast(messageOf(e), 'error'); };
