import type { ConstructionPlane, Vec3 } from './types';

const sub = (a: Vec3, b: Vec3): Vec3 => [a[0] - b[0], a[1] - b[1], a[2] - b[2]];
const dot = (a: Vec3, b: Vec3): number => a[0] * b[0] + a[1] * b[1] + a[2] * b[2];
const cross = (a: Vec3, b: Vec3): Vec3 => [a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0]];
const len = (a: Vec3): number => Math.hypot(a[0], a[1], a[2]);
const unit = (a: Vec3): Vec3 => { const l = len(a) || 1; return [a[0] / l, a[1] / l, a[2] / l]; };

export const WORLD_PLANES: Array<{ id: string; label: string; x: Vec3; y: Vec3 }> = [
  { id: 'top', label: 'Top', x: [1, 0, 0], y: [0, 1, 0] },
  { id: 'bottom', label: 'Bottom', x: [1, 0, 0], y: [0, -1, 0] },
  { id: 'front', label: 'Front', x: [1, 0, 0], y: [0, 0, 1] },
  { id: 'back', label: 'Back', x: [-1, 0, 0], y: [0, 0, 1] },
  { id: 'right', label: 'Right', x: [0, 1, 0], y: [0, 0, 1] },
  { id: 'left', label: 'Left', x: [0, -1, 0], y: [0, 0, 1] },
];

export function worldPlane(id: string, origin: Vec3 = [0, 0, 0]): ConstructionPlane {
  const w = WORLD_PLANES.find((p) => p.id === id) ?? WORLD_PLANES[0];
  return { name: w.label, origin, x: w.x, y: w.y, z: cross(w.x, w.y) };
}

export function planeThrough(a: Vec3, b: Vec3, c: Vec3): ConstructionPlane | null {
  const ab = sub(b, a), ac = sub(c, a);
  const n = cross(ab, ac);
  if (len(n) < 1e-9 * Math.max(1, len(ab) * len(ac))) return null;
  const x = unit(ab), z = unit(n);
  return { name: 'Three points', origin: a, x, y: cross(z, x), z };
}

export function planeOnFace(point: Vec3, normal: Vec3): ConstructionPlane {
  const z = unit(normal);
  let ref: Vec3 = [1, 0, 0];
  if (Math.abs(dot(ref, z)) > 0.95) ref = [0, 1, 0];
  const d = dot(ref, z);
  const x = unit([ref[0] - d * z[0], ref[1] - d * z[1], ref[2] - d * z[2]]);
  return { name: 'Face', origin: point, x, y: cross(z, x), z };
}

export function toLocal(p: ConstructionPlane, w: Vec3): [number, number, number] {
  const r = sub(w, p.origin);
  return [dot(r, p.x), dot(r, p.y), dot(r, p.z)];
}

export function fromLocal(p: ConstructionPlane, l: [number, number]): Vec3 {
  return [p.origin[0] + p.x[0] * l[0] + p.y[0] * l[1], p.origin[1] + p.x[1] * l[0] + p.y[1] * l[1], p.origin[2] + p.x[2] * l[0] + p.y[2] * l[1]];
}

export function rayHit(p: ConstructionPlane, o: Vec3, d: Vec3): Vec3 | null {
  const den = dot(p.z, d);
  if (Math.abs(den) < 1e-9) return null;
  const t = dot(p.z, sub(p.origin, o)) / den;
  if (t < 0) return null;
  return [o[0] + d[0] * t, o[1] + d[1] * t, o[2] + d[2] * t];
}

export function niceStep(visible: number): number {
  const raw = Math.max(visible, 1e-9) / 12;
  return Math.pow(10, Math.floor(Math.log10(raw)));
}
