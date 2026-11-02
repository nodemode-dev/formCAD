import type { AngleConvention, Vec3 } from './types';

const TILT = 1e-4;

export interface StandardView {
  id: string;
  label: string;
  dir: Vec3;
}

const norm = (v: Vec3): Vec3 => {
  const l = Math.hypot(v[0], v[1], v[2]) || 1;
  return [v[0] / l, v[1] / l, v[2] / l];
};

export const STANDARD_VIEWS: StandardView[] = [
  { id: 'front', label: 'Front', dir: [0, -1, 0] },
  { id: 'back', label: 'Back', dir: [0, 1, 0] },
  { id: 'right', label: 'Right', dir: [1, 0, 0] },
  { id: 'left', label: 'Left', dir: [-1, 0, 0] },
  { id: 'top', label: 'Top', dir: [0, -TILT, 1] },
  { id: 'bottom', label: 'Bottom', dir: [0, -TILT, -1] },
  { id: 'iso', label: 'Isometric', dir: norm([1, -1, 1]) },
  { id: 'iso2', label: 'Isometric back right', dir: norm([1, 1, 1]) },
  { id: 'iso3', label: 'Isometric back left', dir: norm([-1, 1, 1]) },
  { id: 'iso4', label: 'Isometric front left', dir: norm([-1, -1, 1]) },
];

const SWAP_FIRST: Record<string, string> = { top: 'bottom', bottom: 'top', left: 'right', right: 'left' };

export function sheetViewId(id: string, angle: AngleConvention): string {
  return angle === 'first' ? SWAP_FIRST[id] ?? id : id;
}

export function standardView(id: string, angle: AngleConvention = 'third'): StandardView {
  const want = sheetViewId(id, angle);
  return STANDARD_VIEWS.find((v) => v.id === want) ?? STANDARD_VIEWS[0];
}

export function directionFor(parts: Vec3): Vec3 {
  const d = norm(parts);
  if (Math.abs(d[0]) < 1e-9 && Math.abs(d[1]) < 1e-9) return [0, -TILT, d[2] > 0 ? 1 : -1];
  return d;
}

export const HOME_DIRECTION: Vec3 = norm([1, -1, 0.8]);
