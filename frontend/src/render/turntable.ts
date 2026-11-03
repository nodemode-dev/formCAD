import type { CameraSpec } from '../view3d/types';

export const MAX_TURNTABLE_FRAMES = 360;

export function rotated(base: CameraSpec, rad: number): CameraSpec {
  const tx = base.target[0], ty = base.target[1];
  const dx = base.position[0] - tx, dy = base.position[1] - ty;
  const c = Math.cos(rad), s = Math.sin(rad);
  return { ...base, position: [tx + dx * c - dy * s, ty + dx * s + dy * c, base.position[2]], target: [...base.target], up: [...base.up] };
}

export function turntableViews(base: CameraSpec, frames: number, sweep: number): CameraSpec[] {
  const n = Math.max(1, Math.min(MAX_TURNTABLE_FRAMES, Math.round(frames)));
  const out: CameraSpec[] = [];
  for (let i = 0; i < n; i++) out.push(rotated(base, (sweep * Math.PI / 180) * (i / n)));
  return out;
}

export class TurntablePreview {
  private raf = 0;
  private t0 = 0;
  on = false;

  constructor(private readonly get: () => CameraSpec, private readonly set: (c: CameraSpec) => void) {}

  start(seconds: number, sweep: number): void {
    if (this.on) return;
    this.on = true;
    const base = this.get();
    this.t0 = performance.now();
    const loop = (): void => {
      if (!this.on) return;
      const k = ((performance.now() - this.t0) / 1000 / Math.max(0.5, seconds)) % 1;
      this.set(rotated(base, (sweep * Math.PI / 180) * k));
      this.raf = requestAnimationFrame(loop);
    };
    this.raf = requestAnimationFrame(loop);
  }

  stop(): void {
    this.on = false;
    if (this.raf) cancelAnimationFrame(this.raf);
    this.raf = 0;
  }
}
