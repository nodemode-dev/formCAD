import * as THREE from 'three';
import type { Vec3 } from '../view3d/types';
import type { Viewport3D } from '../view3d/viewport';

export const add = (a: Vec3, b: Vec3): Vec3 => [a[0] + b[0], a[1] + b[1], a[2] + b[2]];
export const sub = (a: Vec3, b: Vec3): Vec3 => [a[0] - b[0], a[1] - b[1], a[2] - b[2]];
export const mul = (a: Vec3, k: number): Vec3 => [a[0] * k, a[1] * k, a[2] * k];
export const dot = (a: Vec3, b: Vec3): number => a[0] * b[0] + a[1] * b[1] + a[2] * b[2];
export const cross = (a: Vec3, b: Vec3): Vec3 => [a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0]];
export const len = (a: Vec3): number => Math.hypot(a[0], a[1], a[2]);

export interface Ray { origin: Vec3; direction: Vec3 }

export function lineParam(ray: Ray, point: Vec3, axis: Vec3): number | null {
  const w = sub(ray.origin, point);
  const a = dot(ray.direction, ray.direction), b = dot(ray.direction, axis), c = dot(axis, axis);
  const d = dot(ray.direction, w), e = dot(axis, w);
  const den = a * c - b * b;
  if (Math.abs(den) < 1e-12) return null;
  return (a * e - b * d) / den;
}

export function planeHit(ray: Ray, point: Vec3, normal: Vec3): Vec3 | null {
  const den = dot(ray.direction, normal);
  if (Math.abs(den) < 1e-9) return null;
  const t = dot(sub(point, ray.origin), normal) / den;
  if (t < 0) return null;
  return add(ray.origin, mul(ray.direction, t));
}

export function worldPerPixel(vp: Viewport3D, at: Vec3): number {
  const h = Math.max(vp.size.h, 1);
  if (vp.projection === 'parallel') return vp.rig.visibleHeightAtTarget() / h;
  const cam = vp.rig.camera as THREE.PerspectiveCamera;
  const d = cam.position.distanceTo(new THREE.Vector3(at[0], at[1], at[2]));
  return (2 * d * Math.tan((cam.fov * Math.PI) / 360)) / h;
}

export function matrixOf(rows: number[]): THREE.Matrix4 {
  const m = new THREE.Matrix4();
  if (rows.length === 16) m.set(...(rows as [number, number, number, number, number, number, number, number, number, number, number, number, number, number, number, number]));
  else m.set(rows[0], rows[1], rows[2], rows[3], rows[4], rows[5], rows[6], rows[7], rows[8], rows[9], rows[10], rows[11], 0, 0, 0, 1);
  return m;
}

export const hex = (c: THREE.Color): string => `#${c.getHexString()}`;
