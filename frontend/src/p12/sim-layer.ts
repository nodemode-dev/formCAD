import * as THREE from 'three';
import { parseCss } from '../canvas/color';
import { tokenHex } from '../canvas/ink';
import type { ViewLayer } from '../view3d/layer';
import type { Vec3 } from '../view3d/types';
import type { Viewport3D } from '../view3d/viewport';
import { wcsMatrix, type Wcs } from './toolpath-layer';

export interface GridInfo { nx: number; ny: number; cell: number; origin: number[] }
export interface MachineShape { radius: number; thickness: number; headR: number; headL: number }

const CLEAR = '#9ca3af';
const GOUGE = '#ef4444';
const TOOLC = '#f43f5e';
const HOLDERC = '#94a3b8';

const lathe = (profile: number[][], color: string, opacity: number): THREE.Mesh | null => {
  const pts = profile.filter((p) => p.length >= 2 && Number.isFinite(p[0]) && Number.isFinite(p[1])).map((p) => new THREE.Vector2(Math.max(0, p[0]), p[1]));
  if (pts.length < 2) return null;
  const g = new THREE.LatheGeometry(pts, 24);
  g.rotateX(Math.PI / 2);
  const m = new THREE.Mesh(g, new THREE.MeshLambertMaterial({ color, transparent: opacity < 1, opacity, side: THREE.DoubleSide }));
  m.frustumCulled = false;
  m.matrixAutoUpdate = false;
  return m;
};

export class SimLayer implements ViewLayer {
  readonly group = new THREE.Group();
  private readonly wcsGroup = new THREE.Group();
  private stock: THREE.Mesh | null = null;
  private grid: GridInfo | null = null;
  private pos: THREE.BufferAttribute | null = null;
  private col: THREE.BufferAttribute | null = null;
  private nor: THREE.BufferAttribute | null = null;
  private zmin = 0;
  private zmax = 1;
  private tool: THREE.Mesh | null = null;
  private holder: THREE.Mesh | null = null;
  private box: THREE.LineSegments | null = null;
  private clear = new THREE.Color(CLEAR);
  private gouge = new THREE.Color(GOUGE);
  patched = 0;
  toolOp = -1;

  constructor(private readonly vp: Viewport3D) {
    this.group.add(this.wcsGroup);
    this.wcsGroup.matrixAutoUpdate = false;
    this.group.visible = false;
  }

  get ready(): boolean { return !!this.stock; }
  get hasTool(): boolean { return !!this.tool; }
  get info(): GridInfo | null { return this.grid; }

  setColors(host: HTMLElement): void {
    this.clear.setHex(tokenHex('--cam-stock', parseCss(CLEAR), host));
    this.gouge.setHex(tokenHex('--cam-gouge', parseCss(GOUGE), host));
  }

  setWcs(w: Wcs | null): void { this.wcsGroup.matrix.copy(wcsMatrix(w)); this.vp.invalidate(); }

  build(grid: GridInfo, wcs: Wcs | null, zRange: [number, number]): void {
    this.dropStock();
    this.grid = grid;
    this.zmin = zRange[0];
    this.zmax = Math.max(zRange[1], zRange[0] + 1e-3);
    const { nx, ny, cell, origin } = grid;
    const n = nx * ny;
    const pos = new Float32Array(n * 3);
    for (let j = 0; j < ny; j++) for (let i = 0; i < nx; i++) {
      const k = (j * nx + i) * 3;
      pos[k] = origin[0] + i * cell; pos[k + 1] = origin[1] + j * cell; pos[k + 2] = this.zmax;
    }
    const idx = new Uint32Array(Math.max(0, (nx - 1) * (ny - 1) * 6));
    let t = 0;
    for (let j = 0; j + 1 < ny; j++) for (let i = 0; i + 1 < nx; i++) {
      const a = j * nx + i, b = a + 1, c = a + nx, d = c + 1;
      idx[t++] = a; idx[t++] = b; idx[t++] = d; idx[t++] = a; idx[t++] = d; idx[t++] = c;
    }
    const g = new THREE.BufferGeometry();
    this.pos = new THREE.BufferAttribute(pos, 3);
    this.col = new THREE.BufferAttribute(new Float32Array(n * 3), 3);
    this.nor = new THREE.BufferAttribute(new Float32Array(n * 3), 3);
    this.pos.setUsage(THREE.DynamicDrawUsage); this.col.setUsage(THREE.DynamicDrawUsage); this.nor.setUsage(THREE.DynamicDrawUsage);
    g.setAttribute('position', this.pos);
    g.setAttribute('color', this.col);
    g.setAttribute('normal', this.nor);
    g.setIndex(new THREE.BufferAttribute(idx, 1));
    const mesh = new THREE.Mesh(g, new THREE.MeshLambertMaterial({ vertexColors: true, side: THREE.DoubleSide }));
    mesh.frustumCulled = false;
    this.stock = mesh;
    this.wcsGroup.add(mesh);
    this.setWcs(wcs);
    this.buildBox(grid);
    this.group.visible = true;
  }

  private buildBox(grid: GridInfo): void {
    if (this.box) { this.wcsGroup.remove(this.box); this.box.geometry.dispose(); (this.box.material as THREE.Material).dispose(); }
    const x0 = grid.origin[0], y0 = grid.origin[1];
    const x1 = x0 + (grid.nx - 1) * grid.cell, y1 = y0 + (grid.ny - 1) * grid.cell;
    const z0 = this.zmin, z1 = this.zmax;
    const c: Vec3[] = [[x0, y0, z0], [x1, y0, z0], [x1, y1, z0], [x0, y1, z0], [x0, y0, z1], [x1, y0, z1], [x1, y1, z1], [x0, y1, z1]];
    const e = [0, 1, 1, 2, 2, 3, 3, 0, 4, 5, 5, 6, 6, 7, 7, 4, 0, 4, 1, 5, 2, 6, 3, 7];
    const v: number[] = [];
    for (const i of e) v.push(...c[i]);
    const geo = new THREE.BufferGeometry();
    geo.setAttribute('position', new THREE.Float32BufferAttribute(v, 3));
    this.box = new THREE.LineSegments(geo, new THREE.LineBasicMaterial({ color: HOLDERC, transparent: true, opacity: 0.5 }));
    this.wcsGroup.add(this.box);
  }

  show(top: Float32Array, gouge: Uint8Array | null): void {
    const grid = this.grid;
    if (!grid || !this.pos || !this.col || !this.nor || top.length < grid.nx * grid.ny) return;
    const { nx, ny, cell } = grid;
    const p = this.pos.array as Float32Array, c = this.col.array as Float32Array, nr = this.nor.array as Float32Array;
    const span = this.zmax - this.zmin;
    const lo = this.zmin;
    for (let j = 0; j < ny; j++) for (let i = 0; i < nx; i++) {
      const k = j * nx + i;
      const s = i * ny + j;
      let z = top[s];
      if (!Number.isFinite(z) || z < lo) z = lo;
      p[k * 3 + 2] = z;
      const shade = 0.55 + 0.45 * Math.max(0, Math.min(1, (z - lo) / span));
      if (gouge && gouge[s]) { c[k * 3] = this.gouge.r; c[k * 3 + 1] = this.gouge.g; c[k * 3 + 2] = this.gouge.b; }
      else { c[k * 3] = this.clear.r * shade; c[k * 3 + 1] = this.clear.g * shade; c[k * 3 + 2] = this.clear.b * shade; }
    }
    for (let j = 0; j < ny; j++) for (let i = 0; i < nx; i++) {
      const k = j * nx + i;
      const zl = p[(j * nx + Math.max(0, i - 1)) * 3 + 2], zr = p[(j * nx + Math.min(nx - 1, i + 1)) * 3 + 2];
      const zd = p[(Math.max(0, j - 1) * nx + i) * 3 + 2], zu = p[(Math.min(ny - 1, j + 1) * nx + i) * 3 + 2];
      const dx = (zr - zl) / (cell * (Math.min(nx - 1, i + 1) - Math.max(0, i - 1) || 1)), dy = (zu - zd) / (cell * (Math.min(ny - 1, j + 1) - Math.max(0, j - 1) || 1));
      const l = Math.hypot(dx, dy, 1);
      nr[k * 3] = -dx / l; nr[k * 3 + 1] = -dy / l; nr[k * 3 + 2] = 1 / l;
    }
    this.pos.needsUpdate = true; this.col.needsUpdate = true; this.nor.needsUpdate = true;
    this.patched++;
    this.vp.invalidate();
  }

  setTool(profile: number[][] | null, holder: number[][] | null): void {
    for (const m of [this.tool, this.holder]) if (m) { this.wcsGroup.remove(m); m.geometry.dispose(); (m.material as THREE.Material).dispose(); }
    this.tool = profile ? lathe(profile, TOOLC, 0.95) : null;
    this.holder = holder ? lathe(holder, HOLDERC, 0.55) : null;
    for (const m of [this.tool, this.holder]) if (m) { m.visible = false; this.wcsGroup.add(m); }
  }

  poseTool(tip: number[], axis: number[] | null): void {
    const m = new THREE.Matrix4();
    const z = new THREE.Vector3(0, 0, 1);
    const a = axis && axis.length === 3 ? new THREE.Vector3(axis[0], axis[1], axis[2]).normalize() : z;
    const q = new THREE.Quaternion().setFromUnitVectors(z, a);
    m.compose(new THREE.Vector3(tip[0], tip[1], tip[2]), q, new THREE.Vector3(1, 1, 1));
    for (const mesh of [this.tool, this.holder]) if (mesh) { mesh.matrix.copy(m); mesh.visible = true; }
    this.vp.invalidate();
  }

  private table: THREE.Mesh | null = null;
  private head: THREE.Mesh | null = null;
  machineId = '';
  machineOn = true;

  setMachine(id: string, shape: MachineShape | null, tableTop: number): void {
    for (const m of [this.table, this.head]) if (m) { this.wcsGroup.remove(m); m.geometry.dispose(); (m.material as THREE.Material).dispose(); }
    this.table = null; this.head = null;
    this.machineId = shape ? id : '';
    if (!shape) { this.vp.invalidate(); return; }
    const mat = (c: string, o: number): THREE.MeshLambertMaterial => new THREE.MeshLambertMaterial({ color: c, transparent: true, opacity: o, side: THREE.DoubleSide });
    const tg = new THREE.CylinderGeometry(shape.radius, shape.radius, shape.thickness, 40);
    tg.rotateX(Math.PI / 2);
    tg.translate(0, 0, tableTop - shape.thickness / 2);
    this.table = new THREE.Mesh(tg, mat(HOLDERC, 0.28));
    const hg = new THREE.CylinderGeometry(shape.headR, shape.headR, shape.headL, 28);
    hg.rotateX(Math.PI / 2);
    hg.translate(0, 0, shape.headL / 2);
    this.head = new THREE.Mesh(hg, mat(HOLDERC, 0.4));
    this.head.matrixAutoUpdate = false;
    this.head.frustumCulled = false;
    this.head.visible = false;
    this.table.visible = this.machineOn;
    this.wcsGroup.add(this.table, this.head);
    this.vp.invalidate();
  }

  poseMachine(tip: number[], axis: number[] | null, stick: number): void {
    if (!this.head) return;
    const z = new THREE.Vector3(0, 0, 1);
    const a = axis && axis.length === 3 ? new THREE.Vector3(axis[0], axis[1], axis[2]).normalize() : z;
    const base = new THREE.Vector3(tip[0], tip[1], tip[2]).addScaledVector(a, stick);
    this.head.matrix.compose(base, new THREE.Quaternion().setFromUnitVectors(z, a), new THREE.Vector3(1, 1, 1));
    this.head.visible = this.machineOn;
    this.vp.invalidate();
  }

  setMachineShown(on: boolean): void {
    this.machineOn = on;
    for (const m of [this.table, this.head]) if (m) m.visible = on && (m !== this.head || this.hasTool);
    this.vp.invalidate();
  }

  private points: THREE.Points | null = null;
  private cap = 0;

  showVoxels(xyz: Float32Array, wcs: Wcs | null): void {
    const n = Math.floor(xyz.length / 3);
    if (!this.points || n > this.cap) {
      if (this.points) { this.wcsGroup.remove(this.points); this.points.geometry.dispose(); (this.points.material as THREE.Material).dispose(); }
      this.cap = Math.max(n, 1024);
      const g = new THREE.BufferGeometry();
      g.setAttribute('position', new THREE.BufferAttribute(new Float32Array(this.cap * 3), 3).setUsage(THREE.DynamicDrawUsage));
      this.points = new THREE.Points(g, new THREE.PointsMaterial({ color: this.clear, size: 1.5, sizeAttenuation: false }));
      this.points.frustumCulled = false;
      this.wcsGroup.add(this.points);
    }
    const a = this.points.geometry.getAttribute('position') as THREE.BufferAttribute;
    (a.array as Float32Array).set(xyz.subarray(0, n * 3));
    a.needsUpdate = true;
    this.points.geometry.setDrawRange(0, n);
    this.setWcs(wcs);
    this.group.visible = true;
    this.patched++;
    this.vp.invalidate();
  }

  private dropStock(): void {
    if (this.stock) { this.wcsGroup.remove(this.stock); this.stock.geometry.dispose(); (this.stock.material as THREE.Material).dispose(); this.stock = null; }
    this.pos = null; this.col = null; this.nor = null; this.grid = null;
  }

  reset(): void {
    this.dropStock();
    this.setTool(null, null);
    this.setMachine('', null, 0);
    this.toolOp = -1;
    if (this.box) { this.wcsGroup.remove(this.box); this.box.geometry.dispose(); (this.box.material as THREE.Material).dispose(); this.box = null; }
    this.group.visible = false;
    this.vp.invalidate();
  }

  get shown(): boolean { return this.group.visible; }
  setShown(on: boolean): void { if (this.group.visible !== on && (this.stock || !on)) { this.group.visible = on; this.vp.invalidate(); } }
  stockMesh(): THREE.Mesh | null { return this.stock; }

  bounds(): { min: Vec3; max: Vec3 } | null { return null; }

  dispose(): void { this.reset(); }
}
