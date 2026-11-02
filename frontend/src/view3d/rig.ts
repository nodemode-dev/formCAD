import * as THREE from 'three';
import { OrbitControls } from 'three/examples/jsm/controls/OrbitControls.js';
import type { CameraSpec, Projection, Vec3 } from './types';

const FOV = 38;
const UP = new THREE.Vector3(0, 0, 1);

export class Rig {
  readonly persp = new THREE.PerspectiveCamera(FOV, 1, 0.1, 1000);
  readonly ortho = new THREE.OrthographicCamera(-1, 1, 1, -1, 0.1, 1000);
  readonly target = new THREE.Vector3();
  projection: Projection = 'perspective';
  radius = 100;
  center = new THREE.Vector3();
  onChange: () => void = () => undefined;
  onInteract: (on: boolean) => void = () => undefined;
  onSettled: () => void = () => undefined;
  private readonly ctlP: OrbitControls;
  private readonly ctlO: OrbitControls;
  private w = 1;
  private h = 1;
  private orthoHeight = 100;
  private anim = 0;
  private lastMid = 0;
  private lastMidAt: [number, number] = [0, 0];

  constructor(private readonly dom: HTMLElement) {
    this.persp.up.copy(UP);
    this.ortho.up.copy(UP);
    this.persp.position.set(80, -110, 70);
    this.ortho.position.copy(this.persp.position);
    this.ctlP = this.makeControls(this.persp);
    this.ctlO = this.makeControls(this.ortho);
    this.ctlO.enabled = false;
    this.fit();
    dom.addEventListener('pointerdown', (e) => this.midDouble(e), true);
  }

  private makeControls(cam: THREE.Camera): OrbitControls {
    const c = new OrbitControls(cam, this.dom);
    c.enableDamping = false;
    c.zoomToCursor = true;
    c.screenSpacePanning = true;
    c.minPolarAngle = 0;
    c.maxPolarAngle = Math.PI;
    c.rotateSpeed = 0.9;
    c.zoomSpeed = 3.2;
    c.minDistance = 1e-3;
    c.mouseButtons = { LEFT: THREE.MOUSE.ROTATE, MIDDLE: THREE.MOUSE.PAN, RIGHT: THREE.MOUSE.PAN };
    c.addEventListener('change', () => {
      if (c.enabled) { this.target.copy(c.target); this.clipRange(); this.onChange(); }
    });
    c.addEventListener('start', () => { this.cancelAnim(); this.onInteract(true); });
    c.addEventListener('end', () => { this.onInteract(false); this.onSettled(); });
    return c;
  }

  get camera(): THREE.PerspectiveCamera | THREE.OrthographicCamera {
    return this.projection === 'perspective' ? this.persp : this.ortho;
  }

  private get controls(): OrbitControls {
    return this.projection === 'perspective' ? this.ctlP : this.ctlO;
  }

  setZoomFactor(zf: number): void {
    const s = (Math.log(1 / Math.pow(1.18, Math.max(3, Math.min(100, zf)) / 60)) / Math.log(0.95));
    this.ctlP.zoomSpeed = s;
    this.ctlO.zoomSpeed = s;
  }

  setEnabled(on: boolean): void {
    this.controls.enabled = on;
  }

  size(w: number, h: number): void {
    this.w = Math.max(1, w);
    this.h = Math.max(1, h);
    this.persp.aspect = this.w / this.h;
    this.persp.updateProjectionMatrix();
    this.applyOrtho();
  }

  private applyOrtho(): void {
    const a = this.w / this.h;
    const hh = this.orthoHeight / 2;
    this.ortho.left = -hh * a;
    this.ortho.right = hh * a;
    this.ortho.top = hh;
    this.ortho.bottom = -hh;
    this.ortho.updateProjectionMatrix();
  }

  setBounds(center: Vec3, radius: number): void {
    this.center.set(...center);
    this.radius = Math.max(radius, 1e-3);
    this.clipRange();
  }

  private distance(): number {
    return this.camera.position.distanceTo(this.target);
  }

  clipRange(): void {
    const R = this.radius;
    const toCenter = this.camera.position.distanceTo(this.center);
    if (this.projection === 'perspective') {
      const far = toCenter + R * 2.2;
      const near = Math.max(far * 2e-5, toCenter - R * 1.6, R * 1e-4);
      if (this.persp.near !== near || this.persp.far !== far) { this.persp.near = near; this.persp.far = far; this.persp.updateProjectionMatrix(); }
    } else {
      const visible = this.orthoHeight / this.ortho.zoom;
      const reach = Math.max(R * 2.2, visible);
      const near = toCenter - reach - R;
      const far = toCenter + reach + R;
      if (this.ortho.near !== near || this.ortho.far !== far) { this.ortho.near = near; this.ortho.far = far; this.ortho.updateProjectionMatrix(); }
    }
  }

  fit(): void {
    this.clipRange();
  }

  visibleHeightAtTarget(): number {
    if (this.projection === 'parallel') return this.orthoHeight / this.ortho.zoom;
    return 2 * this.distance() * Math.tan(THREE.MathUtils.degToRad(FOV) / 2);
  }

  setProjection(p: Projection): void {
    if (p === this.projection) return;
    const dir = this.camera.position.clone().sub(this.target).normalize();
    const visible = this.visibleHeightAtTarget();
    this.cancelAnim();
    this.controls.enabled = false;
    this.projection = p;
    if (p === 'parallel') {
      this.orthoHeight = visible;
      this.ortho.zoom = 1;
      const d = Math.max(this.radius * 3, 1e-3);
      this.ortho.position.copy(this.target).addScaledVector(dir, d);
      this.ortho.up.copy(UP);
      this.ortho.lookAt(this.target);
      this.applyOrtho();
      this.ctlO.target.copy(this.target);
    } else {
      const d = visible / (2 * Math.tan(THREE.MathUtils.degToRad(FOV) / 2));
      this.persp.position.copy(this.target).addScaledVector(dir, d);
      this.persp.up.copy(UP);
      this.persp.lookAt(this.target);
      this.ctlP.target.copy(this.target);
    }
    this.controls.enabled = true;
    this.controls.update();
    this.clipRange();
    this.onChange();
  }

  getSpec(): CameraSpec {
    const c = this.camera;
    return {
      position: [c.position.x, c.position.y, c.position.z],
      target: [this.target.x, this.target.y, this.target.z],
      up: [0, 0, 1],
      projection: this.projection,
      fov: FOV,
      height: this.visibleHeightAtTarget(),
    };
  }

  setSpec(spec: CameraSpec, animate: boolean): void {
    if (spec.projection !== this.projection) this.setProjection(spec.projection);
    const dir = new THREE.Vector3(...spec.position).sub(new THREE.Vector3(...spec.target));
    this.moveTo(dir.normalize(), new THREE.Vector3(...spec.target), spec.height, animate);
  }

  moveTo(dir: THREE.Vector3, target: THREE.Vector3, height: number, animate: boolean): void {
    this.cancelAnim();
    const from = {
      dir: this.camera.position.clone().sub(this.target).normalize(),
      target: this.target.clone(),
      height: this.visibleHeightAtTarget(),
    };
    const to = { dir: dir.clone().normalize(), target: target.clone(), height: Math.max(height, 1e-6) };
    const reduce = window.matchMedia('(prefers-reduced-motion: reduce)').matches || document.body.classList.contains('animations-disabled');
    if (!animate || reduce) { this.place(to.dir, to.target, to.height); return; }
    const t0 = performance.now();
    const ms = 220;
    const step = (now: number): void => {
      const k = Math.min(1, (now - t0) / ms);
      const e = k * k * (3 - 2 * k);
      const d = from.dir.clone().lerp(to.dir, e);
      if (d.lengthSq() < 1e-8) d.copy(to.dir);
      const h = Math.exp(Math.log(from.height) + (Math.log(to.height) - Math.log(from.height)) * e);
      this.place(d.normalize(), from.target.clone().lerp(to.target, e), h);
      if (k < 1) this.anim = requestAnimationFrame(step);
      else { this.anim = 0; this.onSettled(); }
    };
    this.anim = requestAnimationFrame(step);
  }

  private place(dir: THREE.Vector3, target: THREE.Vector3, height: number): void {
    const c = this.camera;
    this.target.copy(target);
    if (this.projection === 'perspective') {
      const d = height / (2 * Math.tan(THREE.MathUtils.degToRad(FOV) / 2));
      c.position.copy(target).addScaledVector(dir, d);
    } else {
      this.orthoHeight = height;
      this.ortho.zoom = 1;
      c.position.copy(target).addScaledVector(dir, Math.max(this.radius * 3, 1e-3));
      this.applyOrtho();
    }
    c.up.copy(UP);
    c.lookAt(target);
    this.controls.target.copy(target);
    this.controls.update();
    this.clipRange();
    this.onChange();
  }

  private cancelAnim(): void {
    if (this.anim) { cancelAnimationFrame(this.anim); this.anim = 0; }
  }

  lookFrom(dir: Vec3, animate: boolean): void {
    const d = new THREE.Vector3(...dir).normalize();
    this.moveTo(d, this.target, this.visibleHeightAtTarget(), animate);
  }

  direction(): THREE.Vector3 {
    return this.camera.position.clone().sub(this.target).normalize();
  }

  fitBox(min: Vec3, max: Vec3, animate: boolean, dir?: THREE.Vector3): void {
    const c = new THREE.Vector3((min[0] + max[0]) / 2, (min[1] + max[1]) / 2, (min[2] + max[2]) / 2);
    const d = (dir ?? this.direction()).clone().normalize();
    const z = d.clone();
    const x = new THREE.Vector3().crossVectors(UP, z);
    if (x.lengthSq() < 1e-12) x.set(1, 0, 0);
    x.normalize();
    const y = new THREE.Vector3().crossVectors(z, x).normalize();
    const a = this.w / this.h;
    const tanV = Math.tan(THREE.MathUtils.degToRad(FOV) / 2);
    const tanH = tanV * a;
    let dist = 0, half = 0;
    const p = new THREE.Vector3();
    for (let i = 0; i < 8; i++) {
      p.set(i & 1 ? max[0] : min[0], i & 2 ? max[1] : min[1], i & 4 ? max[2] : min[2]).sub(c);
      const px = p.dot(x), py = p.dot(y), pz = p.dot(z);
      dist = Math.max(dist, pz + Math.max(Math.abs(px) / tanH, Math.abs(py) / tanV));
      half = Math.max(half, Math.abs(py), Math.abs(px) / a);
    }
    if (!(dist > 0)) { dist = 100; half = 50; }
    const height = this.projection === 'perspective' ? 2 * (dist * 1.06) * tanV : 2 * half * 1.1;
    this.moveTo(d, c, height, animate);
  }

  ndcToRay(ndcX: number, ndcY: number): THREE.Ray {
    const cam = this.camera;
    const ray = new THREE.Ray();
    cam.updateMatrixWorld();
    if (cam instanceof THREE.PerspectiveCamera) {
      ray.origin.setFromMatrixPosition(cam.matrixWorld);
      ray.direction.set(ndcX, ndcY, 0.5).unproject(cam).sub(ray.origin).normalize();
    } else {
      ray.origin.set(ndcX, ndcY, (cam.near + cam.far) / (cam.near - cam.far)).unproject(cam);
      ray.direction.set(0, 0, -1).transformDirection(cam.matrixWorld);
    }
    return ray;
  }

  private midDouble(e: PointerEvent): void {
    if (e.button !== 1) return;
    const now = performance.now();
    const near = Math.hypot(e.clientX - this.lastMidAt[0], e.clientY - this.lastMidAt[1]) < 6;
    if (near && now - this.lastMid < 380) { this.lastMid = 0; this.dom.dispatchEvent(new CustomEvent('view3d:extents')); }
    else { this.lastMid = now; this.lastMidAt = [e.clientX, e.clientY]; }
  }

  update(): void {
    this.controls.update();
  }

  dispose(): void {
    this.cancelAnim();
    this.ctlP.dispose();
    this.ctlO.dispose();
  }
}
