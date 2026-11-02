import { Renderer } from './renderer';
import type { CanvasApi, CanvasDeps } from './types';

export type { CanvasApi, CanvasDeps, CanvasEvents, CursorMode, DisplayItem, DisplayPayload, Hit, OverlayName, ViewState } from './types';

const mounted = new WeakMap<HTMLElement, CanvasApi>();

export function mountCanvas(host: HTMLElement, deps: CanvasDeps): CanvasApi {
  const existing = mounted.get(host);
  if (existing) return existing;
  const api = new Renderer(host, deps);
  mounted.set(host, api);
  return api;
}
