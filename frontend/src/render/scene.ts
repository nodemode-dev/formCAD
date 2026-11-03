import * as THREE from 'three';
import { DecalGeometry } from 'three/examples/jsm/geometries/DecalGeometry.js';
import type { BodyData, CameraSpec } from '../view3d/types';
import { applyAppearance, appearanceKey, physicalFrom } from './materials';
import type { Appearance, Decal, RenderBodyRow, RenderSettings } from './net';

export interface RenderInput {
  bodies: BodyData[];
  hidden?: number[];
  mmPerUnit: number;
  rows: RenderBodyRow[];
  decals: Decal[];
}

interface Entry { id: number; group: THREE.Group; mesh: THREE.Mesh; key: string; decals: THREE.Mesh[] }

export class RenderScene {
  readonly scene = new THREE.Scene();
  readonly root = new THREE.Group();
  readonly box = new THREE.Box3();
  readonly mmPerUnit: number;
  private readonly entries = new Map<number, Entry>();
  private readonly mats = new Map<string, THREE.MeshPhysicalMaterial>();
  private floor: THREE.Mesh | null = null;
  private readonly textures: THREE.Texture[] = [];

  constructor(input: RenderInput) {
    this.mmPerUnit = input.mmPerUnit || 1;
    this.scene.add(this.root);
    const rowOf = new Map(input.rows.map((r) => [r.id, r] as const));
    const hidden = new Set(input.hidden ?? []);
    for (const b of input.bodies) {
      if (hidden.has(b.id) || b.positions.length < 9 || b.indices.length < 3) continue;
      const row = rowOf.get(b.id);
      const geo = new THREE.BufferGeometry();
      geo.setAttribute('position', new THREE.BufferAttribute(b.positions, 3));
      geo.setAttribute('normal', new THREE.BufferAttribute(b.normals, 3));
      geo.setAttribute('uv', new THREE.BufferAttribute(new Float32Array((b.positions.length / 3) * 2), 2));
      geo.setIndex(new THREE.BufferAttribute(b.indices, 1));
      geo.computeBoundingBox();
      const mesh = new THREE.Mesh(geo, row ? this.material(row.appearance) : this.fallback());
      mesh.name = b.name;
      const group = new THREE.Group();
      group.name = `body-${b.id}`;
      group.add(mesh);
      this.root.add(group);
      this.entries.set(b.id, { id: b.id, group, mesh, key: row?.key ?? '', decals: [] });
      if (geo.boundingBox) this.box.union(geo.boundingBox);
    }
    for (const d of input.decals) if (d.visible) this.addDecal(d);
    this.root.updateMatrixWorld(true);
  }

  get radius(): number {
    if (this.box.isEmpty()) return 1;
    return this.box.getSize(new THREE.Vector3()).length() / 2 || 1;
  }

  get center(): THREE.Vector3 {
    return this.box.isEmpty() ? new THREE.Vector3() : this.box.getCenter(new THREE.Vector3());
  }

  get bodyIds(): number[] { return [...this.entries.keys()]; }

  private fallback(): THREE.MeshPhysicalMaterial {
    let m = this.mats.get('@fallback');
    if (!m) {
      m = new THREE.MeshPhysicalMaterial({ color: 0x9a9ca0, roughness: 0.55, metalness: 0 });
      this.mats.set('@fallback', m);
    }
    return m;
  }

  private material(a: Appearance): THREE.MeshPhysicalMaterial {
    const key = appearanceKey(a);
    let m = this.mats.get(key);
    if (!m) {
      m = physicalFrom(a, this.mmPerUnit);
      this.mats.set(key, m);
    }
    return m;
  }

  setAppearance(id: number, a: Appearance): void {
    const e = this.entries.get(id);
    if (!e) return;
    e.mesh.material = this.material(a);
  }

  repaint(id: number, a: Appearance): void {
    const e = this.entries.get(id);
    if (!e) return;
    const m = (e.mesh.material as THREE.MeshPhysicalMaterial).clone();
    applyAppearance(m, a, this.mmPerUnit);
    e.mesh.material = m;
  }

  setPose(id: number, m: THREE.Matrix4 | null): void {
    const e = this.entries.get(id);
    if (!e) return;
    if (m) { e.group.matrix.copy(m); e.group.matrixAutoUpdate = false; } else { e.group.matrix.identity(); e.group.matrixAutoUpdate = false; }
    e.group.matrixWorldNeedsUpdate = true;
  }

  setPoses(map: Map<number, THREE.Matrix4> | null | undefined): void {
    for (const id of this.entries.keys()) this.setPose(id, map?.get(id) ?? null);
    this.root.updateMatrixWorld(true);
  }

  setHidden(ids: Iterable<number> | undefined): void {
    const hide = new Set(ids ?? []);
    for (const e of this.entries.values()) e.group.visible = !hide.has(e.id);
  }

  private addDecal(d: Decal): void {
    const target = [...this.entries.values()].find((e) => e.key === d.body || e.key.startsWith(`${d.body}/`));
    if (!target) return;
    const pos = new THREE.Vector3(...d.position);
    const normal = new THREE.Vector3(...d.normal).normalize();
    const up = new THREE.Vector3(...d.up);
    if (Math.abs(up.dot(normal)) > 0.98) up.set(1, 0, 0);
    const m = new THREE.Matrix4().lookAt(new THREE.Vector3(), normal.clone().negate(), up);
    const q = new THREE.Quaternion().setFromRotationMatrix(m);
    if (d.rotation) q.multiply(new THREE.Quaternion().setFromAxisAngle(new THREE.Vector3(0, 0, 1), THREE.MathUtils.degToRad(d.rotation)));
    const eul = new THREE.Euler().setFromQuaternion(q);
    let geo: THREE.BufferGeometry;
    try {
      geo = new DecalGeometry(target.mesh, pos, eul, new THREE.Vector3(d.size[0], d.size[1], d.depth));
    } catch {
      return;
    }
    if (!geo.attributes.position || geo.attributes.position.count < 3) { geo.dispose(); return; }
    const lift = Math.max(d.depth, 1e-6) * 0.004;
    const p = geo.attributes.position as THREE.BufferAttribute;
    const n = geo.attributes.normal as THREE.BufferAttribute;
    for (let i = 0; i < p.count; i++) p.setXYZ(i, p.getX(i) + n.getX(i) * lift, p.getY(i) + n.getY(i) * lift, p.getZ(i) + n.getZ(i) * lift);
    p.needsUpdate = true;
    const mat = new THREE.MeshPhysicalMaterial({ color: d.color, roughness: d.roughness, metalness: 0, transparent: d.opacity < 1 || d.kind === 'image', opacity: d.opacity, alphaTest: d.kind === 'image' ? 0.02 : 0 });
    if (d.kind === 'image' && d.image) {
      const img = new Image();
      img.src = d.image;
      const tex = new THREE.Texture(img);
      tex.colorSpace = THREE.SRGBColorSpace;
      tex.flipY = true;
      img.onload = () => { tex.needsUpdate = true; mat.needsUpdate = true; };
      mat.map = tex;
      this.textures.push(tex);
      this.pending.push(img.decode().catch(() => undefined));
    }
    const mesh = new THREE.Mesh(geo, mat);
    mesh.name = `decal-${d.name}`;
    target.group.add(mesh);
    target.decals.push(mesh);
  }

  private readonly pending: Array<Promise<unknown>> = [];

  async ready(): Promise<void> {
    await Promise.all(this.pending);
    for (const t of this.textures) t.needsUpdate = true;
  }

  applyGround(s: RenderSettings['ground']): void {
    if (this.floor) {
      this.root.remove(this.floor);
      this.floor.geometry.dispose();
      (this.floor.material as THREE.Material).dispose();
      this.floor = null;
    }
    if (s.mode !== 'floor' || this.box.isEmpty()) return;
    const r = this.radius;
    const geo = new THREE.PlaneGeometry(r * 40, r * 40);
    geo.setAttribute('uv', new THREE.BufferAttribute(new Float32Array((geo.attributes.position.count) * 2), 2));
    const mat = new THREE.MeshPhysicalMaterial({ color: s.color, roughness: s.roughness, metalness: 0 });
    const mesh = new THREE.Mesh(geo, mat);
    mesh.position.set(this.center.x, this.center.y, this.box.min.z - r * 0.0005);
    mesh.name = 'floor';
    this.floor = mesh;
    this.root.add(mesh);
    mesh.updateMatrixWorld(true);
  }

  dispose(): void {
    for (const e of this.entries.values()) {
      e.mesh.geometry.dispose();
      for (const d of e.decals) { d.geometry.dispose(); (d.material as THREE.Material).dispose(); }
    }
    for (const m of this.mats.values()) m.dispose();
    for (const t of this.textures) t.dispose();
    if (this.floor) { this.floor.geometry.dispose(); (this.floor.material as THREE.Material).dispose(); }
    this.entries.clear();
    this.mats.clear();
  }
}

export function cameraFrom(spec: CameraSpec | null | undefined, aspect: number, scene: RenderScene, fovOverride: number | null): THREE.PerspectiveCamera | THREE.OrthographicCamera {
  const r = scene.radius;
  const c = scene.center;
  const s: CameraSpec = spec ?? {
    position: [c.x + r * 1.7, c.y - r * 1.7, c.z + r * 1.3],
    target: [c.x, c.y, c.z],
    up: [0, 0, 1],
    projection: 'perspective',
    fov: 35,
    height: r * 2.4,
  };
  let cam: THREE.PerspectiveCamera | THREE.OrthographicCamera;
  if (s.projection === 'parallel') {
    const h = s.height > 0 ? s.height : r * 2.4;
    cam = new THREE.OrthographicCamera((-h * aspect) / 2, (h * aspect) / 2, h / 2, -h / 2, r * 0.01, r * 200);
  } else {
    cam = new THREE.PerspectiveCamera(fovOverride ?? s.fov ?? 35, aspect, Math.max(r * 0.01, 1e-4), r * 200);
  }
  cam.up.set(...s.up);
  cam.position.set(...s.position);
  cam.lookAt(new THREE.Vector3(...s.target));
  cam.updateMatrixWorld(true);
  cam.updateProjectionMatrix();
  return cam;
}

export function fitCamera(scene: RenderScene, aspect: number, dir: [number, number, number] = [1, -1, 0.8]): CameraSpec {
  const r = scene.radius;
  const c = scene.center;
  const d = new THREE.Vector3(...dir).normalize();
  const fov = 35;
  const dist = (r / Math.sin(THREE.MathUtils.degToRad(Math.min(fov, fov * aspect) / 2))) * 1.05;
  return { position: [c.x + d.x * dist, c.y + d.y * dist, c.z + d.z * dist], target: [c.x, c.y, c.z], up: [0, 0, 1], projection: 'perspective', fov, height: r * 2.4 };
}
