import * as THREE from 'three';
import type { BodyView } from './body-view';
import type { Rig } from './rig';
import type { SnapHit, SnapKind, SnapPoint, Vec3 } from './types';

export interface FaceHit { body: BodyView; face: number; triangle: number; point: Vec3; normal: Vec3; distance: number; depth: number }
export interface EdgeHit { body: BodyView; edge: number; point: Vec3; distance: number; depth: number }

const PRIORITY: Record<SnapKind, number> = { vertex: 0, midpoint: 1, center: 2, other: 3 };
export const SNAP_LABEL: Record<SnapKind, string> = { vertex: 'Endpoint', midpoint: 'Midpoint', center: 'Center', other: 'Point' };

export class Picker {
  private readonly caster = new THREE.Raycaster();
  private readonly m = new Float64Array(16);
  private readonly v = new Float64Array(16);
  private w = 1;
  private h = 1;

  constructor(private readonly rig: Rig, private readonly bodies: () => BodyView[], private readonly snapPoints: () => SnapPoint[]) {
    this.caster.params.Line = { threshold: 0 };
  }

  sync(w: number, h: number): void {
    this.w = w;
    this.h = h;
    const cam = this.rig.camera;
    cam.updateMatrixWorld();
    const pm = cam.projectionMatrix.elements;
    const vm = cam.matrixWorldInverse.elements;
    const m = this.m;
    for (let c = 0; c < 4; c++) for (let r = 0; r < 4; r++) {
      let s = 0;
      for (let k = 0; k < 4; k++) s += pm[k * 4 + r] * vm[c * 4 + k];
      m[c * 4 + r] = s;
    }
    for (let i = 0; i < 16; i++) this.v[i] = vm[i];
  }

  depthOf(p: Vec3): number {
    const v = this.v;
    return -(v[2] * p[0] + v[6] * p[1] + v[10] * p[2] + v[14]);
  }

  project(p: Vec3): { x: number; y: number; w: number; z: number } | null {
    const m = this.m;
    const cw = m[3] * p[0] + m[7] * p[1] + m[11] * p[2] + m[15];
    const cx = m[0] * p[0] + m[4] * p[1] + m[8] * p[2] + m[12];
    const cy = m[1] * p[0] + m[5] * p[1] + m[9] * p[2] + m[13];
    const cz = m[2] * p[0] + m[6] * p[1] + m[10] * p[2] + m[14];
    if (cw <= 1e-9) return null;
    return { x: (cx / cw * 0.5 + 0.5) * this.w, y: (1 - (cy / cw * 0.5 + 0.5)) * this.h, w: cw, z: cz / cw };
  }

  face(px: number, py: number): FaceHit | null {
    const meshes = this.bodies().filter((b) => b.mesh.visible).map((b) => b.mesh);
    if (!meshes.length) return null;
    const ray = this.rig.ndcToRay((px / this.w) * 2 - 1, -((py / this.h) * 2 - 1));
    this.caster.ray.copy(ray);
    this.caster.near = 0;
    this.caster.far = Infinity;
    const hits = this.caster.intersectObjects(meshes, false);
    if (!hits.length) return null;
    const hit = hits[0];
    const view = this.bodies().find((b) => b.mesh === hit.object);
    if (!view || hit.faceIndex === undefined || hit.faceIndex === null) return null;
    const n = hit.face ? hit.face.normal : new THREE.Vector3(0, 0, 1);
    const dir = ray.direction;
    const nn: Vec3 = n.x * dir.x + n.y * dir.y + n.z * dir.z > 0 ? [-n.x, -n.y, -n.z] : [n.x, n.y, n.z];
    const point: Vec3 = [hit.point.x, hit.point.y, hit.point.z];
    return { body: view, face: view.data.triFace[hit.faceIndex], triangle: hit.faceIndex, point, normal: nn, distance: hit.distance, depth: this.depthOf(point) };
  }

  edge(px: number, py: number, reach: number): EdgeHit | null {
    const m = this.m;
    let best: EdgeHit | null = null;
    let bestD = reach;
    const cw = this.w, ch = this.h;
    for (const b of this.bodies()) {
      if (!b.lines.visible) continue;
      const pos = b.data.edges.positions;
      const seg = b.data.edges.segEdge;
      if (!seg.length) continue;
      for (let s = 0; s < seg.length; s++) {
        const o = s * 6;
        const ax = pos[o], ay = pos[o + 1], az = pos[o + 2], bx = pos[o + 3], by = pos[o + 4], bz = pos[o + 5];
        const wa = m[3] * ax + m[7] * ay + m[11] * az + m[15];
        const wb = m[3] * bx + m[7] * by + m[11] * bz + m[15];
        if (wa <= 1e-9 && wb <= 1e-9) continue;
        let t0 = 0, t1 = 1;
        if (wa <= 1e-9) t0 = (1e-9 - wa) / (wb - wa);
        else if (wb <= 1e-9) t1 = (wa - 1e-9) / (wa - wb);
        const x0 = ax + (bx - ax) * t0, y0 = ay + (by - ay) * t0, z0 = az + (bz - az) * t0;
        const x1 = ax + (bx - ax) * t1, y1 = ay + (by - ay) * t1, z1 = az + (bz - az) * t1;
        const w0 = m[3] * x0 + m[7] * y0 + m[11] * z0 + m[15];
        const w1 = m[3] * x1 + m[7] * y1 + m[11] * z1 + m[15];
        const sx0 = (((m[0] * x0 + m[4] * y0 + m[8] * z0 + m[12]) / w0) * 0.5 + 0.5) * cw;
        const sy0 = (1 - (((m[1] * x0 + m[5] * y0 + m[9] * z0 + m[13]) / w0) * 0.5 + 0.5)) * ch;
        const sx1 = (((m[0] * x1 + m[4] * y1 + m[8] * z1 + m[12]) / w1) * 0.5 + 0.5) * cw;
        const sy1 = (1 - (((m[1] * x1 + m[5] * y1 + m[9] * z1 + m[13]) / w1) * 0.5 + 0.5)) * ch;
        if (Math.max(sx0, sx1) < px - bestD || Math.min(sx0, sx1) > px + bestD || Math.max(sy0, sy1) < py - bestD || Math.min(sy0, sy1) > py + bestD) continue;
        const dx = sx1 - sx0, dy = sy1 - sy0;
        const l2 = dx * dx + dy * dy;
        let u = l2 > 1e-12 ? ((px - sx0) * dx + (py - sy0) * dy) / l2 : 0;
        u = u < 0 ? 0 : u > 1 ? 1 : u;
        const d = Math.hypot(px - (sx0 + dx * u), py - (sy0 + dy * u));
        if (d >= bestD) continue;
        const tl = (u * w0) / ((1 - u) * w1 + u * w0);
        const tt = t0 + (t1 - t0) * (Number.isFinite(tl) ? tl : u);
        const point: Vec3 = [ax + (bx - ax) * tt, ay + (by - ay) * tt, az + (bz - az) * tt];
        bestD = d;
        best = { body: b, edge: seg[s], point, distance: d, depth: this.depthOf(point) };
      }
    }
    return best;
  }

  snapCandidates(px: number, py: number, aperture: number, enabled: (k: SnapKind) => boolean): SnapHit[] {
    const out: Array<SnapHit & { score: number }> = [];
    for (const s of this.snapPoints()) {
      if (!enabled(s.kind)) continue;
      const q = this.project(s.p);
      if (!q) continue;
      const d = Math.hypot(q.x - px, q.y - py);
      if (d > aperture) continue;
      out.push({ kind: s.kind, label: SNAP_LABEL[s.kind], p: s.p, sx: q.x, sy: q.y, body: s.body, ref: s.ref, score: d + PRIORITY[s.kind] * 2.5 });
    }
    out.sort((a, b) => a.score - b.score);
    return out;
  }

  visibleAt(hit: SnapHit, occludes: boolean): boolean {
    if (!occludes) return true;
    const f = this.face(hit.sx, hit.sy);
    if (!f) return true;
    const depth = this.depthOf(hit.p);
    return depth <= f.depth + Math.max(f.depth * 2e-3, 1e-6);
  }
}
