import * as THREE from 'three';
import { LineMaterial } from 'three/examples/jsm/lines/LineMaterial.js';
import { LineSegments2 } from 'three/examples/jsm/lines/LineSegments2.js';
import { matrixOf } from '../u8/geo';
import { DEFAULT_BODY_COLOR } from '../view3d/kit';
import type { BodyView } from '../view3d/body-view';
import type { CameraSpec, Vec3 } from '../view3d/types';
import type { Viewport3D } from '../view3d/viewport';
import type { StyleId } from './api';

interface Parts {
  view: BodyView;
  group: THREE.Group;
  mesh: THREE.Mesh;
  hull: THREE.Mesh;
  lines: LineSegments2;
  hidden: LineSegments2;
  color: number;
}

interface Ink { ink: THREE.Color; paper: THREE.Color; bg: THREE.Color; soft: THREE.Color }

function readInk(host: HTMLElement): Ink {
  const cs = getComputedStyle(host);
  const get = (name: string, fallback: string): THREE.Color => {
    const c = new THREE.Color();
    try { c.set(cs.getPropertyValue(name).trim() || fallback); } catch { c.set(fallback); }
    return c;
  };
  const ink = get('--v3d-edge-ink', '#14171c');
  const paper = get('--canvas-paper', '#ffffff');
  return { ink, paper, bg: get('--canvas-bg-model', '#1b1e23'), soft: ink.clone().lerp(paper, 0.62) };
}

function hullMaterial(color: THREE.Color, width: { value: number }, res: { value: THREE.Vector2 }): THREE.MeshBasicMaterial {
  const m = new THREE.MeshBasicMaterial({ color, side: THREE.BackSide });
  m.onBeforeCompile = (shader) => {
    shader.uniforms.outlinePx = width;
    shader.uniforms.outlineRes = res;
    shader.vertexShader = shader.vertexShader
      .replace('#include <common>', '#include <common>\nuniform float outlinePx;\nuniform vec2 outlineRes;')
      .replace('#include <project_vertex>', '#include <project_vertex>\n{ vec4 cn = projectionMatrix * vec4(normalMatrix * normal, 0.0); vec2 d = cn.xy; float l = length(d); if (l > 1e-6) gl_Position.xy += (d / l) * (outlinePx * 2.0 / outlineRes) * gl_Position.w; }');
  };
  return m;
}

export class StoryScene {
  readonly scene = new THREE.Scene();
  private readonly world = new THREE.Group();
  private readonly hemi = new THREE.HemisphereLight(0xffffff, 0x70767f, 1.25);
  private readonly key = new THREE.DirectionalLight(0xffffff, 2.1);
  private readonly parts = new Map<number, Parts>();
  private readonly mats = new Map<string, THREE.Material>();
  private readonly res = { value: new THREE.Vector2(1, 1) };
  private readonly hullPx = { value: 1.6 };
  private readonly lineMats: LineMaterial[] = [];
  private ink: Ink;
  private style: StyleId = 'shaded';
  private rev = -1;
  private signature = '';

  constructor(private readonly vp: Viewport3D) {
    this.ink = readInk(vp.host);
    this.scene.add(this.world, this.hemi, this.key, this.key.target);
  }

  get background(): THREE.Color {
    return this.style === 'shaded' ? this.ink.bg : this.ink.paper;
  }

  setStyle(style: StyleId): void {
    if (style === this.style && this.parts.size) return;
    this.style = style;
    this.ink = readInk(this.vp.host);
    this.dropMaterials();
    for (const p of this.parts.values()) this.dress(p);
  }

  private dropMaterials(): void {
    for (const m of this.mats.values()) m.dispose();
    this.mats.clear();
    for (const m of this.lineMats) m.dispose();
    this.lineMats.length = 0;
  }

  private face(color: number): THREE.Material {
    const key = `${this.style}:${color}`;
    let m = this.mats.get(key);
    if (m) return m;
    const offset = { polygonOffset: true, polygonOffsetFactor: 1, polygonOffsetUnits: 1 };
    switch (this.style) {
      case 'white_fill':
      case 'hidden_dashed':
        m = new THREE.MeshBasicMaterial({ color: this.ink.paper, side: THREE.DoubleSide, ...offset });
        break;
      case 'flat_colour':
        m = new THREE.MeshBasicMaterial({ color, side: THREE.DoubleSide, ...offset });
        break;
      case 'outline':
        m = new THREE.MeshStandardMaterial({ color, roughness: 0.52, metalness: 0.06, side: THREE.DoubleSide, ...offset });
        break;
      default:
        m = new THREE.MeshStandardMaterial({ color, roughness: 0.52, metalness: 0.06, side: THREE.DoubleSide });
    }
    this.mats.set(key, m);
    return m;
  }

  private line(kind: 'ink' | 'hidden'): LineMaterial {
    const m = new LineMaterial({ color: (kind === 'ink' ? this.ink.ink : this.ink.soft).getHex(), linewidth: kind === 'ink' ? 1.6 : 1.1, worldUnits: false });
    if (kind === 'hidden') {
      m.dashed = true;
      m.dashSize = 4;
      m.gapSize = 3;
      m.depthFunc = THREE.GreaterDepth;
      m.depthWrite = false;
    }
    m.resolution.copy(this.res.value);
    this.lineMats.push(m);
    return m;
  }

  private dress(p: Parts): void {
    const s = this.style;
    p.mesh.material = this.face(p.color);
    const drawn = s !== 'shaded';
    p.lines.visible = drawn && p.view.data.edges.segEdge.length > 0;
    p.hull.visible = drawn && s !== 'hidden_dashed';
    p.hidden.visible = s === 'hidden_dashed' && p.view.data.edges.segEdge.length > 0;
    if (p.lines.visible) p.lines.material = this.line('ink');
    if (p.hidden.visible) p.hidden.material = this.line('hidden');
    if (p.hull.visible) {
      let hm = this.mats.get('hull');
      if (!hm) { hm = hullMaterial(this.ink.ink, this.hullPx, this.res); this.mats.set('hull', hm); }
      p.hull.material = hm;
    }
    p.lines.renderOrder = 1;
    p.hidden.renderOrder = 1;
  }

  private sync(): void {
    const rev = this.vp.model.rev;
    const ids = [...this.vp.bodyViews.keys()].join(',');
    if (rev === this.rev && ids === this.signature) return;
    this.rev = rev;
    this.signature = ids;
    for (const p of this.parts.values()) this.world.remove(p.group);
    this.parts.clear();
    for (const [id, view] of this.vp.bodyViews) {
      const group = new THREE.Group();
      group.matrixAutoUpdate = false;
      const mesh = new THREE.Mesh(view.geometry);
      const hull = new THREE.Mesh(view.geometry);
      const lines = new LineSegments2(view.lines.geometry);
      const hidden = new LineSegments2(view.lines.geometry);
      group.add(mesh, hull, lines, hidden);
      this.world.add(group);
      const p: Parts = { view, group, mesh, hull, lines, hidden, color: view.data.color || DEFAULT_BODY_COLOR };
      this.parts.set(id, p);
      this.dress(p);
      hidden.computeLineDistances();
    }
  }

  setPoses(matrices: Record<string, number[]>, worlds: Map<string, THREE.Matrix4>, topOf: (instance: string) => string): void {
    this.sync();
    for (const p of this.parts.values()) {
      const top = topOf(p.view.data.instance || p.view.data.component || '');
      const next = matrices[top];
      const old = worlds.get(top);
      p.group.visible = p.view.group.visible;
      if (next && old) p.group.matrix.copy(matrixOf(next).multiply(old.clone().invert()));
      else p.group.matrix.identity();
      p.group.matrixWorldNeedsUpdate = true;
    }
  }

  bounds(): { center: THREE.Vector3; radius: number } {
    const box = new THREE.Box3();
    const corner = new THREE.Vector3();
    for (const p of this.parts.values()) {
      const lo = p.view.min, hi = p.view.max;
      if (!Number.isFinite(lo[0])) continue;
      for (let i = 0; i < 8; i++) {
        corner.set(i & 1 ? hi[0] : lo[0], i & 2 ? hi[1] : lo[1], i & 4 ? hi[2] : lo[2]).applyMatrix4(p.group.matrix);
        box.expandByPoint(corner);
      }
    }
    if (box.isEmpty()) return { center: new THREE.Vector3(), radius: 1 };
    const sphere = box.getBoundingSphere(new THREE.Sphere());
    return { center: sphere.center, radius: Math.max(sphere.radius, 1e-3) };
  }

  camera(spec: CameraSpec, aspect: number): THREE.Camera {
    const { center, radius } = this.bounds();
    const target = new THREE.Vector3(...spec.target);
    const pos = new THREE.Vector3(...spec.position);
    const reach = pos.distanceTo(center) + radius * 1.5;
    if (spec.projection === 'parallel') {
      const h = spec.height / 2;
      const cam = new THREE.OrthographicCamera(-h * aspect, h * aspect, h, -h, 0.1, 1);
      const dir = pos.clone().sub(target).normalize();
      cam.position.copy(target).addScaledVector(dir, radius * 3);
      cam.up.set(0, 0, 1);
      cam.lookAt(target);
      cam.near = Math.max(radius * 0.01, 0.01);
      cam.far = cam.position.distanceTo(center) + radius * 3;
      cam.updateProjectionMatrix();
      cam.updateMatrixWorld();
      return cam;
    }
    const cam = new THREE.PerspectiveCamera(spec.fov, aspect, 0.1, reach);
    cam.position.copy(pos);
    cam.up.set(0, 0, 1);
    cam.lookAt(target);
    cam.near = Math.max(reach * 2e-5, pos.distanceTo(center) - radius * 1.6, radius * 1e-3);
    cam.far = reach;
    cam.updateProjectionMatrix();
    cam.updateMatrixWorld();
    return cam;
  }

  render(renderer: THREE.WebGLRenderer, spec: CameraSpec, w: number, h: number): void {
    this.sync();
    if (this.res.value.x !== w || this.res.value.y !== h) {
      this.res.value.set(w, h);
      for (const m of this.lineMats) m.resolution.set(w, h);
    }
    const cam = this.camera(spec, w / h);
    const d = cam.position.distanceTo(this.bounds().center);
    const up = new THREE.Vector3(0, 0, 1).applyQuaternion(cam.quaternion);
    const right = new THREE.Vector3(1, 0, 0).applyQuaternion(cam.quaternion);
    this.key.position.copy(cam.position).addScaledVector(up, d * 0.5).addScaledVector(right, -d * 0.35);
    this.key.target.position.copy(this.bounds().center);
    this.hemi.visible = this.key.visible = this.style === 'shaded' || this.style === 'outline';
    renderer.setClearColor(this.background, 1);
    renderer.setViewport(0, 0, w, h);
    renderer.render(this.scene, cam);
  }

  dispose(): void {
    this.dropMaterials();
    this.parts.clear();
  }
}

export function frameCamera(dir: Vec3, center: THREE.Vector3, radius: number, aspect: number, fov = 38): CameraSpec {
  const half = Math.atan(Math.tan(THREE.MathUtils.degToRad(fov) / 2) * Math.min(1, aspect));
  const dist = (radius / Math.sin(half)) * 1.08;
  const d = new THREE.Vector3(...dir).normalize();
  const pos = center.clone().addScaledVector(d, dist);
  return { position: [pos.x, pos.y, pos.z], target: [center.x, center.y, center.z], up: [0, 0, 1], projection: 'perspective', fov, height: 2 * dist * Math.tan(THREE.MathUtils.degToRad(fov) / 2) };
}

export const specOf =(position: Vec3, target: Vec3, height: number, projection: 'perspective' | 'parallel' = 'perspective'): CameraSpec => ({ position, target, up: [0, 0, 1], projection, fov: 38, height });
