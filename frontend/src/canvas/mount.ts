import { onShellMounted } from '../app';
import { api } from '../io/api';
import { events } from '../io/events';
import type { CommandLineState } from '../io/api';
import { commands } from '../ui/commands';
import { docStore } from '../ui/doc-store';
import { store, stored } from '../ui/dom';
import { loadPrefs } from '../ui/prefs';
import { sysvars } from '../ui/sysvar-store';
import { toast } from '../ui/toast';
import { mountCanvas } from './index';
import { attachInteraction } from './interact';
import type { CanvasApi, CursorMode } from './types';

let canvas: CanvasApi | null = null;

export const drawingCanvas = (): CanvasApi | null => canvas;

function vector(name: string): number[] | null {
  const v = sysvars.get(name);
  return Array.isArray(v) && v.length >= 2 && v.every((n) => typeof n === 'number') ? (v as number[]) : null;
}

function modeFor(state: CommandLineState): CursorMode {
  if (state.active) return state.expect === 'selection' || state.expect === 'entity' ? 'pick' : 'point';
  return sysvars.num('PICKFIRST', 1) !== 0 ? 'pick' : 'point';
}

onShellMounted((ctx) => {
  const c = mountCanvas(ctx.hosts.canvasHost, {
    fetchDisplay: (id, since, space) => api.display(id, since, space),
    fetchPicture: (id, h) => api.underlay(id, h),
    sysvar: (name, fallback) => sysvars.num(name, fallback),
    sysvarVec: vector,
    onSysvar: (fn) => sysvars.onChange(() => fn('')),
    markerSize: () => loadPrefs().snapMarkerSize,
    systemCursor: () => loadPrefs().systemCursor,
    notify: (text) => toast(text, 'info'),
    store,
    stored,
  });
  canvas = c;
  const interact = attachInteraction(c, ctx.hosts.canvasHost);
  if (import.meta.env.DEV) Object.assign(window, { formcadCanvas: c, formcadInteract: interact });

  c.setDocument(docStore.activeId);
  let last = docStore.activeId;
  docStore.onChange(() => {
    if (docStore.activeId === last) return;
    last = docStore.activeId;
    c.setDocument(last);
  });

  events.on('doc', (e) => c.applyDocEvent({ id: e.id, rev: e.rev, reason: typeof e.reason === 'string' ? e.reason : undefined, view: e.view as never }));
  events.onState((s) => { if (s === 'open') c.refresh(); });

  document.addEventListener('formcad:command-state', (e) => {
    const d = (e as CustomEvent<{ doc: string; state: CommandLineState }>).detail;
    if (d.doc === docStore.activeId) c.setCursorMode(modeFor(d.state));
  });

  const add = (id: string, label: string, run: () => void): void => {
    if (!commands.get(id)) commands.add({ id, label, group: 'View', run });
  };
  add('zoom-extents-canvas', 'Zoom Extents', () => c.zoomExtents());
  add('toggle-viewcube', 'ViewCube', () => {
    const on = stored('formCAD.canvasView');
    let cube = true;
    try { cube = (JSON.parse(on ?? '{}') as { cube?: boolean }).cube !== false; } catch { cube = true; }
    c.setViewCubeVisible(!cube);
  });
  add('toggle-ucs-icon', 'UCS Icon', () => {
    let ucs = true;
    try { ucs = (JSON.parse(stored('formCAD.canvasView') ?? '{}') as { ucs?: boolean }).ucs !== false; } catch { ucs = true; }
    c.setUcsIconVisible(!ucs);
  });
});
