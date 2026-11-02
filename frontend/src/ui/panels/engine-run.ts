import { drawingCanvas } from '../../canvas/mount';
import { api, ApiError } from '../../io/api';
import { docStore } from '../doc-store';
import { toast } from '../toast';

export const failure = (e: unknown): string => (e instanceof ApiError || e instanceof Error ? e.message : 'The engine did not answer');

export async function runEngineText(text: string): Promise<boolean> {
  const doc = docStore.current();
  if (!doc) return false;
  try {
    const state = await api.sendInput(doc.id, text);
    document.dispatchEvent(new CustomEvent('formcad:command-state', { detail: { doc: doc.id, state } }));
    return true;
  } catch (e) {
    toast(failure(e), 'error');
    return false;
  }
}

export function zoomToHandles(handles: number[]): boolean {
  const cv = drawingCanvas();
  if (!cv) return false;
  let x0 = Infinity, y0 = Infinity, x1 = -Infinity, y1 = -Infinity;
  for (const h of handles) {
    const it = cv.item(h);
    if (!it) continue;
    x0 = Math.min(x0, it.bounds[0]);
    y0 = Math.min(y0, it.bounds[1]);
    x1 = Math.max(x1, it.bounds[2]);
    y1 = Math.max(y1, it.bounds[3]);
  }
  if (!Number.isFinite(x0)) return false;
  const pad = Math.max(x1 - x0, y1 - y0, 1) * 0.15;
  cv.zoomWindow([x0 - pad, y0 - pad, x1 + pad, y1 + pad]);
  return true;
}
