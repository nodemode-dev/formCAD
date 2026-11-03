import * as THREE from 'three';
import { LineSegments2 } from 'three/examples/jsm/lines/LineSegments2.js';
import { LineSegmentsGeometry } from 'three/examples/jsm/lines/LineSegmentsGeometry.js';
import { DEFAULT_BODY_COLOR, EDGES_VISIBLE, FACE_VISIBLE, type ModeKit } from './kit';
import type { BodyData, DisplayMode, Vec3 } from './types';

export class BodyView {
  readonly group = new THREE.Group();
  readonly geometry = new THREE.BufferGeometry();
  readonly mesh: THREE.Mesh;
  readonly outline: THREE.Mesh;
  readonly lines: LineSegments2;
  readonly min: Vec3 = [Infinity, Infinity, Infinity];
  readonly max: Vec3 = [-Infinity, -Infinity, -Infinity];
  readonly faceIds: number[];
  readonly edgeIds: number[];
  private faceTris: Map<number, number[]> | null = null;
  private edgeSegs: Map<number, [number, number]> | null = null;
  private readonly lineGeometry = new LineSegmentsGeometry();
  private paint: THREE.Material | null = null;

  constructor(readonly data: BodyData) {
    this.geometry.setAttribute('position', new THREE.BufferAttribute(data.positions, 3));
    this.geometry.setAttribute('normal', new THREE.BufferAttribute(data.normals, 3));
    this.geometry.setIndex(new THREE.BufferAttribute(data.indices, 1));
    const p = data.positions;
    for (let i = 0; i < p.length; i += 3) {
      for (let k = 0; k < 3; k++) {
        const v = p[i + k];
        if (v < this.min[k]) this.min[k] = v;
        if (v > this.max[k]) this.max[k] = v;
      }
    }
    const e = data.edges.positions;
    for (let i = 0; i < e.length; i += 3) {
      for (let k = 0; k < 3; k++) {
        const v = e[i + k];
        if (v < this.min[k]) this.min[k] = v;
        if (v > this.max[k]) this.max[k] = v;
      }
    }
    this.geometry.computeBoundingSphere();
    this.geometry.computeBoundingBox();
    this.mesh = new THREE.Mesh(this.geometry);
    this.outline = new THREE.Mesh(this.geometry);
    this.mesh.userData.body = data.id;
    this.outline.visible = false;
    if (e.length) this.lineGeometry.setPositions(e);
    this.lines = new LineSegments2(this.lineGeometry);
    this.lines.userData.body = data.id;
    this.group.add(this.mesh, this.outline, this.lines);
    const faces = new Set<number>();
    for (let t = 0; t < data.triFace.length; t++) faces.add(data.triFace[t]);
    this.faceIds = [...faces].sort((a, b) => a - b);
    const edges = new Set<number>();
    for (let s = 0; s < data.edges.segEdge.length; s++) edges.add(data.edges.segEdge[s]);
    this.edgeIds = [...edges].sort((a, b) => a - b);
  }

  apply(kit: ModeKit, mode: DisplayMode): void {
    const mat = kit.face(mode, this.data.color || DEFAULT_BODY_COLOR);
    this.mesh.visible = FACE_VISIBLE[mode];
    if (mat) this.mesh.material = this.paint && FACE_VISIBLE[mode] ? this.paint : mat;
    this.lines.visible = EDGES_VISIBLE[mode] && this.data.edges.segEdge.length > 0;
    this.lines.material = kit.edge(mode);
    const tech = mode === 'technical';
    this.outline.visible = tech;
    if (tech) this.outline.material = kit.outline();
    this.mesh.renderOrder = mode === 'ghosted' || mode === 'xray' ? 1 : 0;
    this.lines.renderOrder = mode === 'ghosted' || mode === 'xray' ? 2 : 1;
  }

  get vertexCount(): number { return this.data.positions.length / 3; }

  setPaint(values: Float32Array | null, mat: THREE.Material | null): void {
    if (values && mat) {
      this.geometry.setAttribute('aval', new THREE.BufferAttribute(values, values.length / this.vertexCount));
      this.paint = mat;
    } else {
      this.geometry.deleteAttribute('aval');
      this.paint = null;
    }
  }

  get painted(): boolean { return this.paint !== null; }

  setPose(m: THREE.Matrix4 | null): void {
    this.group.matrixAutoUpdate = m === null;
    if (m) this.group.matrix.copy(m); else this.group.matrix.identity();
    this.group.matrixWorldNeedsUpdate = true;
  }

  trianglesOf(face: number): number[] {
    if (!this.faceTris) {
      const map = new Map<number, number[]>();
      const tf = this.data.triFace;
      for (let t = 0; t < tf.length; t++) {
        let list = map.get(tf[t]);
        if (!list) { list = []; map.set(tf[t], list); }
        list.push(t);
      }
      this.faceTris = map;
    }
    return this.faceTris.get(face) ?? [];
  }

  segmentsOf(edge: number): [number, number] | undefined {
    if (!this.edgeSegs) {
      const map = new Map<number, [number, number]>();
      const se = this.data.edges.segEdge;
      for (let s = 0; s < se.length; s++) {
        const cur = map.get(se[s]);
        if (cur) cur[1]++; else map.set(se[s], [s, 1]);
      }
      this.edgeSegs = map;
    }
    return this.edgeSegs.get(edge);
  }

  facePatch(faces: number[]): THREE.BufferGeometry {
    const idx: number[] = [];
    const src = this.data.indices;
    for (const f of faces) for (const t of this.trianglesOf(f)) idx.push(src[t * 3], src[t * 3 + 1], src[t * 3 + 2]);
    const g = new THREE.BufferGeometry();
    g.setAttribute('position', this.geometry.getAttribute('position'));
    g.setAttribute('normal', this.geometry.getAttribute('normal'));
    g.setIndex(new THREE.BufferAttribute(new Uint32Array(idx), 1));
    return g;
  }

  edgePositions(edges: number[] | null): Float32Array {
    const e = this.data.edges.positions;
    if (!edges) return e;
    let n = 0;
    const spans: Array<[number, number]> = [];
    for (const id of edges) {
      const r = this.segmentsOf(id);
      if (r) { spans.push(r); n += r[1]; }
    }
    const out = new Float32Array(n * 6);
    let o = 0;
    for (const [s, c] of spans) {
      out.set(e.subarray(s * 6, (s + c) * 6), o);
      o += c * 6;
    }
    return out;
  }

  faceCentroid(face: number): Vec3 {
    const tris = this.trianglesOf(face);
    const p = this.data.positions, ix = this.data.indices;
    let x = 0, y = 0, z = 0, n = 0;
    for (const t of tris) {
      for (let k = 0; k < 3; k++) {
        const v = ix[t * 3 + k] * 3;
        x += p[v]; y += p[v + 1]; z += p[v + 2]; n++;
      }
    }
    return n ? [x / n, y / n, z / n] : [0, 0, 0];
  }

  dispose(): void {
    this.geometry.dispose();
    this.lineGeometry.dispose();
  }
}
