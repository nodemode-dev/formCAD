import * as THREE from 'three';
import { t } from '../ui/i18n';
import type { Palette } from './kit';
import type { Vec3 } from './types';

const SIZE = 124;
const MARGIN = 10;
const MID = 1.2;
const EDGE = 0.4;
const GAP = 0.03;

interface Zone {
  mesh: THREE.Mesh;
  dir: Vec3;
  rank: number;
}

const FACES: Array<{ n: Vec3; up: Vec3; label: string }> = [
  { n: [0, 0, 1], up: [0, 1, 0], label: 'TOP' },
  { n: [0, 0, -1], up: [0, -1, 0], label: 'BOTTOM' },
  { n: [0, -1, 0], up: [0, 0, 1], label: 'FRONT' },
  { n: [0, 1, 0], up: [0, 0, 1], label: 'BACK' },
  { n: [1, 0, 0], up: [0, 0, 1], label: 'RIGHT' },
  { n: [-1, 0, 0], up: [0, 0, 1], label: 'LEFT' },
];

export class ViewCube {
  readonly scene = new THREE.Scene();
  readonly camera = new THREE.OrthographicCamera(-1.85, 1.85, 1.85, -1.85, 0.1, 30);
  visible = true;
  private readonly zones: Zone[] = [];
  private readonly labels: Array<{ mesh: THREE.Mesh; label: string }> = [];
  private hot: Zone | null = null;
  private pal: Palette;
  private readonly ray = new THREE.Raycaster();

  constructor(pal: Palette) {
    this.pal = pal;
    for (let i = -1; i <= 1; i++) for (let j = -1; j <= 1; j++) for (let k = -1; k <= 1; k++) {
      const c = [i, j, k];
      const nz = c.filter((v) => v !== 0).length;
      if (!nz) continue;
      const dims = c.map((v) => (v === 0 ? MID : EDGE) - GAP) as Vec3;
      const pos = c.map((v) => v * (MID / 2 + EDGE / 2)) as Vec3;
      const mesh = new THREE.Mesh(new THREE.BoxGeometry(dims[0], dims[1], dims[2]), new THREE.MeshBasicMaterial());
      mesh.position.set(...pos);
      this.scene.add(mesh);
      this.zones.push({ mesh, dir: [i, j, k], rank: nz });
    }
    for (const f of FACES) {
      const tex = new THREE.CanvasTexture(document.createElement('canvas'));
      tex.colorSpace = THREE.SRGBColorSpace;
      const m = new THREE.Mesh(new THREE.PlaneGeometry(MID - 0.1, MID - 0.1), new THREE.MeshBasicMaterial({ map: tex, transparent: true, depthWrite: false }));
      const z = new THREE.Vector3(...f.n), y = new THREE.Vector3(...f.up), x = new THREE.Vector3().crossVectors(y, z);
      m.matrix.makeBasis(x, y, z).setPosition(z.clone().multiplyScalar(1.004));
      m.matrixAutoUpdate = false;
      this.scene.add(m);
      this.labels.push({ mesh: m, label: f.label });
    }
    this.paint();
  }

  setPalette(p: Palette): void {
    this.pal = p;
    this.paint();
  }

  private paint(): void {
    const p = this.pal;
    const base = p.cubeBase;
    const shade = (z: Zone): THREE.Color => {
      const c = base.clone();
      c.multiplyScalar(z.rank === 1 ? 1 : z.rank === 2 ? 0.8 : 0.66);
      const [a, b, d] = z.dir;
      const tilt = a * 0.04 + b * -0.07 + d * 0.1;
      c.multiplyScalar(1 + tilt);
      return c;
    };
    for (const z of this.zones) {
      const m = z.mesh.material as THREE.MeshBasicMaterial;
      m.color.copy(z === this.hot ? p.accent : shade(z));
    }
    const ink = '#' + p.cubeInk.getHexString();
    for (const l of this.labels) {
      const mat = l.mesh.material as THREE.MeshBasicMaterial;
      const tex = mat.map as THREE.CanvasTexture;
      const cv = tex.image as HTMLCanvasElement;
      cv.width = 128; cv.height = 128;
      const g = cv.getContext('2d');
      if (!g) continue;
      g.clearRect(0, 0, 128, 128);
      g.fillStyle = ink;
      g.font = '600 25px -apple-system, "Segoe UI", Inter, system-ui, sans-serif';
      g.textAlign = 'center';
      g.textBaseline = 'middle';
      g.fillText(t(l.label), 64, 66, 116);
      tex.needsUpdate = true;
    }
  }

  rect(w: number): { x: number; y: number; size: number } {
    return { x: w - SIZE - MARGIN, y: MARGIN, size: SIZE };
  }

  contains(px: number, py: number, w: number): boolean {
    if (!this.visible) return false;
    const r = this.rect(w);
    return px >= r.x && px <= r.x + r.size && py >= r.y && py <= r.y + r.size;
  }

  private cast(px: number, py: number, w: number): Zone | null {
    const r = this.rect(w);
    const nx = ((px - r.x) / r.size) * 2 - 1;
    const ny = -(((py - r.y) / r.size) * 2 - 1);
    this.ray.setFromCamera(new THREE.Vector2(nx, ny), this.camera);
    const hits = this.ray.intersectObjects(this.zones.map((z) => z.mesh), false);
    if (!hits.length) return null;
    return this.zones.find((z) => z.mesh === hits[0].object) ?? null;
  }

  hover(px: number, py: number, w: number): boolean {
    const z = this.contains(px, py, w) ? this.cast(px, py, w) : null;
    if (z === this.hot) return false;
    this.hot = z;
    this.paint();
    return true;
  }

  leave(): boolean {
    if (!this.hot) return false;
    this.hot = null;
    this.paint();
    return true;
  }

  pick(px: number, py: number, w: number): Vec3 | null {
    if (!this.contains(px, py, w)) return null;
    return this.cast(px, py, w)?.dir ?? null;
  }

  describe(px: number, py: number, w: number): string {
    const z = this.contains(px, py, w) ? this.cast(px, py, w) : null;
    if (!z) return '';
    const names: Array<[string, string]> = [['Right', 'Left'], ['Back', 'Front'], ['Top', 'Bottom']];
    const parts: string[] = [];
    z.dir.forEach((v, i) => {
      if (v > 0) parts.push(t(names[i][0])); else if (v < 0) parts.push(t(names[i][1]));
    });
    return parts.join(' ');
  }

  render(renderer: THREE.WebGLRenderer, orientation: THREE.Vector3, w: number, h: number): void {
    if (!this.visible) return;
    const r = this.rect(w);
    this.camera.position.copy(orientation).multiplyScalar(8);
    this.camera.up.set(0, 0, 1);
    this.camera.lookAt(0, 0, 0);
    this.camera.updateMatrixWorld();
    const prevAuto = renderer.autoClear;
    renderer.autoClear = false;
    renderer.setScissorTest(true);
    renderer.setViewport(r.x, h - r.y - r.size, r.size, r.size);
    renderer.setScissor(r.x, h - r.y - r.size, r.size, r.size);
    renderer.clearDepth();
    renderer.render(this.scene, this.camera);
    renderer.setScissorTest(false);
    renderer.setViewport(0, 0, w, h);
    renderer.autoClear = prevAuto;
  }

  dispose(): void {
    for (const z of this.zones) { z.mesh.geometry.dispose(); (z.mesh.material as THREE.Material).dispose(); }
    for (const l of this.labels) {
      const m = l.mesh.material as THREE.MeshBasicMaterial;
      m.map?.dispose();
      m.dispose();
      l.mesh.geometry.dispose();
    }
  }
}
