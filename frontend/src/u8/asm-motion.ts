import * as THREE from 'three';
import { toast } from '../ui/toast';
import { view3d } from '../view3d/mount';
import type { Vec3 } from '../view3d/types';
import type { Viewport3D } from '../view3d/viewport';
import { asm, isAssembly, type Poses } from './asm';
import { planeHit } from './geo';
import { docUrl, req, text } from './net';

interface DragReply { ok: boolean; message: string; moved: string[]; poses: Poses }

export class DragTool {
  enabled = false;
  private drag: { cid: string; point: Vec3; busy: boolean; want: Vec3 | null } | null = null;
  private readonly ray = new THREE.Raycaster();
  onChange: (() => void) | null = null;

  constructor(private readonly vp: Viewport3D) {
    vp.host.addEventListener('pointerdown', (e) => this.down(e), true);
  }

  set(on: boolean): void {
    this.enabled = on;
    this.vp.canvas.style.cursor = on ? 'grab' : '';
    this.onChange?.();
  }

  private rel(e: MouseEvent): { x: number; y: number } {
    const r = this.vp.canvas.getBoundingClientRect();
    return { x: e.clientX - r.left, y: e.clientY - r.top };
  }

  private down(e: PointerEvent): void {
    if (!this.enabled || e.button !== 0 || !isAssembly()) return;
    const p = this.rel(e);
    const r = this.vp.rayAt(p.x, p.y);
    this.ray.set(new THREE.Vector3(...r.origin), new THREE.Vector3(...r.direction).normalize());
    const meshes = [...this.vp.bodyViews.values()].filter((v) => v.mesh.visible).map((v) => v.mesh);
    const hit = this.ray.intersectObjects(meshes, false)[0];
    if (!hit) return;
    const body = Number(hit.object.userData.body);
    const cid = asm.componentOfBody(body);
    if (!cid) return;
    e.stopPropagation();
    e.preventDefault();
    this.drag = { cid, point: hit.point.toArray() as Vec3, busy: false, want: null };
    asm.select([cid]);
    const move = (ev: PointerEvent): void => this.move(ev);
    const up = (ev: PointerEvent): void => {
      window.removeEventListener('pointermove', move, true);
      window.removeEventListener('pointerup', up, true);
      void this.end(ev);
    };
    window.addEventListener('pointermove', move, true);
    window.addEventListener('pointerup', up, true);
  }

  private target(e: PointerEvent): Vec3 | null {
    const d = this.drag;
    if (!d) return null;
    const p = this.rel(e);
    const r = this.vp.rayAt(p.x, p.y);
    const dir = new THREE.Vector3();
    this.vp.rig.camera.getWorldDirection(dir);
    return planeHit(r, d.point, [dir.x, dir.y, dir.z]);
  }

  private move(e: PointerEvent): void {
    const d = this.drag;
    if (!d) return;
    const t = this.target(e);
    if (!t) return;
    d.want = t;
    if (!d.busy) void this.pump();
  }

  private async pump(): Promise<void> {
    const d = this.drag;
    const id = asm.id();
    if (!d || !id) return;
    d.busy = true;
    try {
      while (d.want && this.drag === d) {
        const target = d.want;
        d.want = null;
        try {
          const res = await req<DragReply>('POST', docUrl(id, 'mates/drag'), { component: d.cid, point: d.point, target, commit: false });
          if (res.ok && this.drag === d) asm.showPoses(res.poses);
        } catch (er) {
          d.want = null;
          toast(text(er), 'error');
          this.drag = null;
        }
      }
    } finally {
      d.busy = false;
    }
  }

  private async end(e: PointerEvent): Promise<void> {
    const d = this.drag;
    if (!d) return;
    const t = this.target(e) ?? d.want;
    this.drag = null;
    const id = asm.id();
    if (!id || !t) { asm.showPoses(null); return; }
    try {
      await req<DragReply>('POST', docUrl(id, 'mates/drag'), { component: d.cid, point: d.point, target: t, commit: true });
      await view3d()?.refresh();
    } catch (er) {
      toast(text(er), 'error');
    }
    asm.showPoses(null);
    asm.schedule(0);
  }
}
