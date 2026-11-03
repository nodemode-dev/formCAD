import * as THREE from 'three';
import type { ViewLayer } from '../view3d/layer';
import type { Viewport3D } from '../view3d/viewport';

export type DraftClass = 'ok' | 'steep' | 'undercut';
const CLASSES: DraftClass[] = ['ok', 'steep', 'undercut'];
const TOKEN: Record<DraftClass, [string, string]> = { ok: ['--accent-color', '#3b82f6'], steep: ['--warn', '#fbbf24'], undercut: ['--danger', '#ef4444'] };

export class MoldLayer implements ViewLayer {
  readonly group = new THREE.Group();
  private readonly mats = new Map<DraftClass, THREE.MeshBasicMaterial>();
  private readonly meshes = new Map<DraftClass, THREE.Mesh>();
  private geoms: THREE.BufferGeometry[] = [];
  private key = '';

  constructor(private readonly vp: Viewport3D) {
    for (const c of CLASSES) {
      this.mats.set(c, new THREE.MeshBasicMaterial({ color: '#888888', transparent: true, opacity: 0.78, depthWrite: false, side: THREE.DoubleSide, polygonOffset: true, polygonOffsetFactor: -2, polygonOffsetUnits: -2 }));
    }
    this.group.renderOrder = 4;
    this.group.visible = false;
  }

  setColors(host: HTMLElement): void {
    const cs = getComputedStyle(host);
    for (const c of CLASSES) this.mats.get(c)?.color.set(cs.getPropertyValue(TOKEN[c][0]).trim() || TOKEN[c][1]);
  }

  get shown(): boolean { return this.group.visible; }
  setShown(on: boolean): void { if (this.group.visible !== on) { this.group.visible = on; this.vp.invalidate(); } }

  set(body: number, faces: Record<DraftClass, number[]>): boolean {
    const key = JSON.stringify([body, faces]);
    if (key === this.key) return true;
    const view = this.vp.bodyViews.get(body);
    if (!view) return false;
    this.key = key;
    for (const g of this.geoms) g.dispose();
    this.geoms = [];
    this.group.clear();
    this.meshes.clear();
    for (const c of CLASSES) {
      const ids = faces[c].map((i) => i + 1).filter((i) => view.faceIds.includes(i));
      if (!ids.length) continue;
      const g = view.facePatch(ids);
      this.geoms.push(g);
      const m = new THREE.Mesh(g, this.mats.get(c));
      this.meshes.set(c, m);
      this.group.add(m);
    }
    this.vp.invalidate();
    return true;
  }

  clear(): void {
    if (!this.key) return;
    this.key = '';
    for (const g of this.geoms) g.dispose();
    this.geoms = [];
    this.group.clear();
    this.meshes.clear();
    this.vp.invalidate();
  }

  sceneChanged(): void { this.key = ''; this.group.clear(); this.geoms = []; this.meshes.clear(); }

  dispose(): void { this.clear(); for (const m of this.mats.values()) m.dispose(); }
}

export const moldState: { layer: MoldLayer | null } = { layer: null };
