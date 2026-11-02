import { onShellMounted } from '../../app';
import { api } from '../../io/api';
import type { CommandLineState } from '../../io/api';
import { drawingCanvas } from '../../canvas/mount';
import { docStore } from '../doc-store';
import { sysvars } from '../sysvar-store';
import { toast } from '../toast';
import { MTextEditor } from '../panels/mtext-editor';
import { DimStyleDialog } from './dim-style-dialog';
import { exec, failure, waitCommandEnd } from './engine';
import { HatchDialog } from './hatch-dialog';
import { registerInterceptor } from './intercept';
import { MleaderStyleDialog } from './mleader-style-dialog';
import { TableStyleDialog } from './table-style-dialog';
import { TextStyleDialog } from './text-style-dialog';

let hatch: HatchDialog | null = null;
let dim: DimStyleDialog | null = null;
let text: TextStyleDialog | null = null;
let table: TableStyleDialog | null = null;
let mleader: MleaderStyleDialog | null = null;
let editor: MTextEditor | null = null;

const hatchDialog = (): HatchDialog => (hatch ??= new HatchDialog());

let state: CommandLineState | null = null;
let stateDoc = '';
let lastPick: { handle: number; kind: string } | null = null;
let opening = false;

async function selectedOfKind(kind: string): Promise<number[]> {
  const id = docStore.activeId;
  const c = drawingCanvas();
  if (!id || !c) return [];
  try {
    const sel = await api.getSelection(id);
    return sel.handles.filter((h) => c.item(h)?.kind === kind).map((h) => Number(h));
  } catch {
    return [];
  }
}

async function editHatch(): Promise<void> {
  const chosen = await selectedOfKind('hatch');
  if (chosen.length) { await hatchDialog().openEdit(chosen); return; }
  const id = docStore.activeId;
  if (!id) return;
  await exec('hatchpick', { clear: true }, true);
  const done = waitCommandEnd();
  try {
    const first = await api.sendInput(id, 'hatchpick');
    document.dispatchEvent(new CustomEvent('formcad:command-state', { detail: { doc: id, state: first } }));
    const second = await api.sendInput(id, 'H');
    document.dispatchEvent(new CustomEvent('formcad:command-state', { detail: { doc: id, state: second } }));
    await done;
    const out = await exec('hatchpick', {}, true);
    const handle = (out?.result as { hatch?: number | null } | undefined)?.hatch;
    if (handle) await hatchDialog().openEdit([handle]);
  } catch (e) {
    toast(failure(e), 'error');
  }
}

async function mtextEditorFor(handle: number): Promise<void> {
  const id = docStore.activeId;
  if (!id || !editor) return;
  await editor.openExisting(id, handle);
}

async function openPendingEditor(id: string): Promise<void> {
  if (!editor || editor.isOpen || opening) return;
  opening = true;
  try {
    const pending = await api.mtextPending(id);
    await editor.openPending(id, pending.props);
  } catch {
    opening = false;
    return;
  }
  opening = false;
}

function onState(doc: string, s: CommandLineState): void {
  state = s;
  stateDoc = doc;
  if (doc !== docStore.activeId || !editor) return;
  const cmd = String(s.command ?? '').toLowerCase();
  if (s.active && cmd === 'mtext' && s.expect === 'text' && /^enter text/i.test(s.prompt)) {
    void openPendingEditor(doc);
    return;
  }
  if (s.active && cmd === 'textedit' && s.expect === 'text' && /^enter new text/i.test(s.prompt) && lastPick?.kind === 'mtext') {
    const handle = lastPick.handle;
    lastPick = null;
    void api.cancelCommand(doc).then((next) => {
      document.dispatchEvent(new CustomEvent('formcad:command-state', { detail: { doc, state: next } }));
      return mtextEditorFor(handle);
    }).catch(() => undefined);
  }
}

async function onDouble(x: number, y: number, px: number, py: number): Promise<void> {
  const id = docStore.activeId;
  const c = drawingCanvas();
  if (!id || !c || (state?.active && stateDoc === id)) return;
  const hit = c.pickAt(px, py)[0];
  if (!hit) return;
  const kind = c.item(hit.handle)?.kind ?? '';
  if (kind === 'mtext') { await mtextEditorFor(Number(hit.handle)); return; }
  if (kind === 'hatch') { await hatchDialog().openEdit([Number(hit.handle)]); return; }
  if (kind === 'text') {
    try {
      const s = await api.sendInput(id, 'textedit');
      document.dispatchEvent(new CustomEvent('formcad:command-state', { detail: { doc: id, state: s } }));
      const p = await api.sendCanvasInput(id, { pick: { point: [x, y], handle: hit.handle } });
      document.dispatchEvent(new CustomEvent('formcad:command-state', { detail: { doc: id, state: p } }));
    } catch (e) {
      toast(failure(e), 'error');
    }
  }
}

registerInterceptor(['hatch', 'bhatch'], () => {
  if (sysvars.num('HPDLGMODE', 1) === 0) return false;
  void hatchDialog().openCreate(false);
  return true;
});
registerInterceptor(['gradient'], () => {
  if (sysvars.num('HPDLGMODE', 1) === 0) return false;
  void hatchDialog().openCreate(true);
  return true;
});
registerInterceptor(['hatchedit'], () => {
  if (sysvars.num('HPDLGMODE', 1) === 0) return false;
  void editHatch();
  return true;
});
registerInterceptor(['style'], () => { void (text ??= new TextStyleDialog()).show(); return true; });
registerInterceptor(['dimstyle', 'dimstyle.dimension'], () => { void (dim ??= new DimStyleDialog()).show(); return true; });
registerInterceptor(['tablestyle'], () => { void (table ??= new TableStyleDialog()).show(); return true; });
registerInterceptor(['mleaderstyle'], () => { void (mleader ??= new MleaderStyleDialog()).show(); return true; });
registerInterceptor(['textedit'], () => {
  const id = docStore.activeId;
  if (!id || !editor) return false;
  void selectedOfKind('mtext').then((list) => {
    if (list.length === 1) return mtextEditorFor(list[0]);
    return api.sendInput(id, 'textedit').then((s) => { document.dispatchEvent(new CustomEvent('formcad:command-state', { detail: { doc: id, state: s } })); });
  });
  return true;
});

onShellMounted((ctx) => {
  editor = new MTextEditor(ctx.hosts.canvasHost);
  hatchDialog();
  const feed = (e: Event): void => {
    const d = (e as CustomEvent<{ doc: string; state: CommandLineState }>).detail;
    if (d?.state) onState(d.doc, d.state);
  };
  document.addEventListener('formcad:cmdline-applied', feed);
  document.addEventListener('formcad:command-state', feed);
  window.setTimeout(() => {
    const c = drawingCanvas();
    if (!c) return;
    c.on('click', (p) => {
      const id = docStore.activeId;
      const hit = id ? c.pickAt(p.px, p.py)[0] : undefined;
      lastPick = hit ? { handle: Number(hit.handle), kind: c.item(hit.handle)?.kind ?? '' } : null;
    });
    c.on('dblclick', (p) => { void onDouble(p.x, p.y, p.px, p.py); });
  }, 0);
});
