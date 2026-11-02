import type { Camera } from './camera';
import { zoomFactorFor } from './camera';
import type { Chrome, ChromePart } from './chrome';
import type { CanvasEvents, DragInfo, PointerInfo } from './types';

export interface InputHost {
  cam: Camera;
  chrome: Chrome;
  isMac: boolean;
  zoomFactor(): number;
  setPointer(p: { px: number; py: number } | null): void;
  viewChanged(): void;
  zoomExtents(): void;
  chromeAction(part: ChromePart, button: number, px: number, py: number): void;
  hoverPart(part: ChromePart): void;
  emit<K extends keyof CanvasEvents>(k: K, v: CanvasEvents[K]): void;
}

const DRAG_PX = 4;
const DOUBLE_MS = 400;

export function bindInput(el: HTMLElement, h: InputHost): () => void {
  let panning = false;
  let lastX = 0;
  let lastY = 0;
  let lastMiddle = 0;
  let down: { button: number; px: number; py: number; x: number; y: number; dragging: boolean; id: number } | null = null;
  let exclusive = false;

  const local = (e: MouseEvent): { px: number; py: number } => {
    const r = el.getBoundingClientRect();
    return { px: e.clientX - r.left, py: e.clientY - r.top };
  };

  const info = (e: MouseEvent, px: number, py: number): PointerInfo => {
    const [x, y] = h.cam.toWorld(px, py);
    return { x, y, px, py, button: e.button, shift: e.shiftKey, ctrl: e.ctrlKey || e.metaKey, alt: e.altKey };
  };

  const onDown = (e: PointerEvent): void => {
    const { px, py } = local(e);
    if (e.button === 1) {
      e.preventDefault();
      el.setPointerCapture(e.pointerId);
      const now = performance.now();
      if (now - lastMiddle < DOUBLE_MS) {
        lastMiddle = 0;
        h.zoomExtents();
        return;
      }
      lastMiddle = now;
      panning = true;
      lastX = e.clientX;
      lastY = e.clientY;
      return;
    }
    if (e.button !== 0 && e.button !== 2) return;
    const part = h.chrome.hit(px, py);
    if (h.chrome.menuOpen || part) {
      e.preventDefault();
      exclusive = true;
      h.chromeAction(part, e.button, px, py);
      return;
    }
    exclusive = false;
    el.setPointerCapture(e.pointerId);
    const [x, y] = h.cam.toWorld(px, py);
    down = { button: e.button, px, py, x, y, dragging: false, id: e.pointerId };
  };

  const onMove = (e: PointerEvent): void => {
    const { px, py } = local(e);
    if (panning) {
      h.cam.panBy(e.clientX - lastX, e.clientY - lastY);
      lastX = e.clientX;
      lastY = e.clientY;
      h.setPointer({ px, py });
      h.viewChanged();
      return;
    }
    const part = h.chrome.hit(px, py);
    h.hoverPart(part);
    if (h.chrome.menuOpen) h.chrome.menuHover(px, py);
    h.setPointer({ px, py });
    if (down && !exclusive) {
      if (!down.dragging && Math.hypot(px - down.px, py - down.py) > DRAG_PX) {
        down.dragging = true;
        h.emit('drag', dragInfo(e, px, py, 'start'));
      } else if (down.dragging) {
        h.emit('drag', dragInfo(e, px, py, 'move'));
      }
    }
  };

  const dragInfo = (e: MouseEvent, px: number, py: number, phase: DragInfo['phase']): DragInfo => {
    const base = info(e, px, py);
    return { ...base, button: down?.button ?? 0, phase, x0: down?.x ?? base.x, y0: down?.y ?? base.y, px0: down?.px ?? px, py0: down?.py ?? py };
  };

  const onUp = (e: PointerEvent): void => {
    const { px, py } = local(e);
    if (e.button === 1) {
      panning = false;
      if (el.hasPointerCapture(e.pointerId)) el.releasePointerCapture(e.pointerId);
      return;
    }
    if (exclusive) {
      exclusive = false;
      return;
    }
    const d = down;
    if (!d || d.button !== e.button) return;
    down = null;
    if (el.hasPointerCapture(e.pointerId)) el.releasePointerCapture(e.pointerId);
    if (d.dragging) h.emit('drag', { ...dragInfo(e, px, py, 'end'), button: d.button, x0: d.x, y0: d.y, px0: d.px, py0: d.py });
    else h.emit('click', info(e, d.px, d.py));
  };

  const onLeave = (): void => {
    if (down || panning) return;
    h.hoverPart(null);
    h.setPointer(null);
  };

  const onWheel = (e: WheelEvent): void => {
    e.preventDefault();
    const { px, py } = local(e);
    const cam = h.cam;
    if (e.ctrlKey) {
      cam.zoomAt(Math.exp(-e.deltaY * 0.01), px, py);
    } else if (h.isMac && e.deltaMode === 0) {
      cam.panBy(-e.deltaX, -e.deltaY);
    } else if (e.shiftKey) {
      cam.panBy(-(e.deltaY || e.deltaX), 0);
    } else {
      let d = -e.deltaY;
      d = e.deltaMode === 1 ? d * 16 : e.deltaMode === 2 ? d * cam.heightPx : d * 0.5;
      d = Math.max(-150, Math.min(150, d));
      cam.zoomAt(zoomFactorFor(d, h.zoomFactor()), px, py);
    }
    h.setPointer({ px, py });
    h.viewChanged();
  };

  const onDouble = (e: MouseEvent): void => {
    if (e.button !== 0) return;
    const { px, py } = local(e);
    if (h.chrome.hit(px, py)) return;
    h.emit('dblclick', info(e, px, py));
  };

  const onMenu = (e: Event): void => e.preventDefault();
  const onAux = (e: MouseEvent): void => { if (e.button === 1) e.preventDefault(); };

  el.addEventListener('pointerdown', onDown);
  el.addEventListener('pointermove', onMove);
  el.addEventListener('pointerup', onUp);
  el.addEventListener('pointercancel', onUp);
  el.addEventListener('pointerleave', onLeave);
  el.addEventListener('wheel', onWheel, { passive: false });
  el.addEventListener('dblclick', onDouble);
  el.addEventListener('contextmenu', onMenu);
  el.addEventListener('auxclick', onAux);
  el.addEventListener('mousedown', onAux);

  return () => {
    el.removeEventListener('pointerdown', onDown);
    el.removeEventListener('pointermove', onMove);
    el.removeEventListener('pointerup', onUp);
    el.removeEventListener('pointercancel', onUp);
    el.removeEventListener('pointerleave', onLeave);
    el.removeEventListener('wheel', onWheel);
    el.removeEventListener('dblclick', onDouble);
    el.removeEventListener('contextmenu', onMenu);
    el.removeEventListener('auxclick', onAux);
    el.removeEventListener('mousedown', onAux);
  };
}
