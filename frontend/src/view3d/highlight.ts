import * as THREE from 'three';
import { LineMaterial } from 'three/examples/jsm/lines/LineMaterial.js';
import { LineSegments2 } from 'three/examples/jsm/lines/LineSegments2.js';
import { LineSegmentsGeometry } from 'three/examples/jsm/lines/LineSegmentsGeometry.js';
import type { BodyView } from './body-view';
import type { Palette } from './kit';
import type { SelectionState } from './types';

type Lookup = (id: number) => BodyView | undefined;

export class Highlight {
  readonly group = new THREE.Group();
  private readonly faceMat: THREE.MeshBasicMaterial;
  private readonly bodyMat: THREE.MeshBasicMaterial;
  private readonly lineMat: LineMaterial;
  private readonly lineHot: LineMaterial;
  private owned: Array<{ dispose: () => void }> = [];
  private key = '';

  constructor(private readonly look: Lookup, color: THREE.Color, resolution: THREE.Vector2) {
    this.faceMat = new THREE.MeshBasicMaterial({ color, transparent: true, opacity: 0.5, depthWrite: false, side: THREE.DoubleSide, polygonOffset: true, polygonOffsetFactor: -2, polygonOffsetUnits: -2 });
    this.bodyMat = new THREE.MeshBasicMaterial({ color, transparent: true, opacity: 0.28, depthWrite: false, side: THREE.DoubleSide, polygonOffset: true, polygonOffsetFactor: -1, polygonOffsetUnits: -1 });
    this.lineMat = new LineMaterial({ color: color.getHex(), linewidth: 3, worldUnits: false, depthFunc: THREE.LessEqualDepth });
    this.lineHot = new LineMaterial({ color: color.getHex(), linewidth: 2.4, worldUnits: false });
    this.lineMat.resolution.copy(resolution);
    this.lineHot.resolution.copy(resolution);
    this.group.renderOrder = 5;
  }

  setColor(c: THREE.Color): void {
    this.faceMat.color.copy(c);
    this.bodyMat.color.copy(c);
    this.lineMat.color.copy(c);
    this.lineHot.color.copy(c);
  }

  setResolution(w: number, h: number): void {
    this.lineMat.resolution.set(w, h);
    this.lineHot.resolution.set(w, h);
  }

  setClip(planes: THREE.Plane[]): void {
    const list = planes.length ? planes : null;
    for (const m of [this.faceMat, this.bodyMat, this.lineMat, this.lineHot]) { m.clippingPlanes = list; m.needsUpdate = true; }
  }

  show(s: SelectionState, facesVisible: boolean, linesVisible: boolean): boolean {
    const key = JSON.stringify([s, facesVisible, linesVisible]);
    if (key === this.key) return false;
    this.key = key;
    for (const o of this.owned) o.dispose();
    this.owned = [];
    this.group.clear();
    for (const id of s.bodies) {
      const v = this.look(id);
      if (!v) continue;
      if (facesVisible) {
        const m = new THREE.Mesh(v.geometry, this.bodyMat);
        this.group.add(m);
      }
      if (linesVisible || !facesVisible) this.addLines(v.edgePositions(null), this.lineHot);
    }
    const faceBy = new Map<number, number[]>();
    for (const f of s.faces) {
      const list = faceBy.get(f.body) ?? [];
      list.push(f.face);
      faceBy.set(f.body, list);
    }
    for (const [body, faces] of faceBy) {
      const v = this.look(body);
      if (!v) continue;
      const g = v.facePatch(faces);
      this.owned.push(g);
      this.group.add(new THREE.Mesh(g, this.faceMat));
    }
    const edgeBy = new Map<number, number[]>();
    for (const e of s.edges) {
      const list = edgeBy.get(e.body) ?? [];
      list.push(e.edge);
      edgeBy.set(e.body, list);
    }
    for (const [body, edges] of edgeBy) {
      const v = this.look(body);
      if (v) this.addLines(v.edgePositions(edges), this.lineMat);
    }
    return true;
  }

  private addLines(positions: Float32Array, mat: LineMaterial): void {
    if (!positions.length) return;
    const g = new LineSegmentsGeometry();
    g.setPositions(positions);
    this.owned.push(g);
    this.group.add(new LineSegments2(g, mat));
  }

  clear(): void {
    this.show({ bodies: [], faces: [], edges: [] }, true, true);
  }

  refresh(): void {
    this.key = '';
  }

  dispose(): void {
    for (const o of this.owned) o.dispose();
    this.owned = [];
    this.faceMat.dispose();
    this.bodyMat.dispose();
    this.lineMat.dispose();
    this.lineHot.dispose();
  }
}

export function highlightColor(p: Palette, kind: 'hover' | 'select'): THREE.Color {
  return kind === 'hover' ? p.accent : p.select;
}
