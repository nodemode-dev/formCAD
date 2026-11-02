import type { BatchData } from './batch';
import type { Chunk } from './store';
import type { Rect } from './types';

export interface PaintView {
  cx: number;
  cy: number;
  scale: number;
  width: number;
  height: number;
  dpr: number;
  contrast: number;
  bg: [number, number, number];
  visible: Rect;
}

export interface DynLayer {
  data: BatchData | null;
  ox: number;
  oy: number;
  version: number;
  uploaded: number;
  gpu: unknown;
}

export interface Painter {
  readonly kind: 'webgl2' | 'canvas2d';
  readonly retains: boolean;
  resize(cssW: number, cssH: number, dpr: number): void;
  frame(view: PaintView, chunks: Iterable<Chunk>, dyn: DynLayer[]): void;
  onLost(fn: (restored: boolean) => void): void;
  release(gpu: unknown): void;
  dispose(): void;
}

export function newDyn(): DynLayer {
  return { data: null, ox: 0, oy: 0, version: 0, uploaded: -1, gpu: null };
}
