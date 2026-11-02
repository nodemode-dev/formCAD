import type * as THREE from 'three';
import type { InkColors } from './overlay';
import type { Palette } from './kit';
import type { Vec3 } from './types';

export type Projector = (p: Vec3) => { x: number; y: number } | null;

export interface ViewLayer {
  readonly group: THREE.Object3D;
  bounds?(): { min: Vec3; max: Vec3 } | null;
  draw?(g: CanvasRenderingContext2D, project: Projector, ink: InkColors, pal: Palette): void;
  palette?(pal: Palette): void;
  resolution?(w: number, h: number): void;
  dispose(): void;
}
