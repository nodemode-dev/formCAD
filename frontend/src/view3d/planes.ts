import type { ConstructionPlane, Vec3 } from './types';

const sub = (a: Vec3, b: Vec3): Vec3 => [a[0] - b[0], a[1] - b[1], a[2] - b[2]];
const dot = (a: Vec3, b: Vec3): number => a[0] * b[0] + a[1] * b[1] + a[2] * b[2];

export const STARTING_PLANE: ConstructionPlane = { name: 'Top', origin: [0, 0, 0], x: [1, 0, 0], y: [0, 1, 0], z: [0, 0, 1] };

export function planeCoords(p: ConstructionPlane, w: Vec3): [number, number] {
  const r = sub(w, p.origin);
  return [dot(r, p.x), dot(r, p.y)];
}

export function rayHit(p: ConstructionPlane, o: Vec3, d: Vec3): Vec3 | null {
  const den = dot(p.z, d);
  if (Math.abs(den) < 1e-9) return null;
  const t = dot(p.z, sub(p.origin, o)) / den;
  if (t < 0) return null;
  return [o[0] + d[0] * t, o[1] + d[1] * t, o[2] + d[2] * t];
}
