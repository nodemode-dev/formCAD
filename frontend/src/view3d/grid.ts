import * as THREE from 'three';
import type { Palette } from './kit';
import { planeCoords } from './planes';
import type { ConstructionPlane, GridAsk, GridLines } from './types';

const VERT = `
uniform float uExtent;
varying vec2 vLocal;
void main() {
  vLocal = position.xy * uExtent;
  gl_Position = projectionMatrix * modelViewMatrix * vec4(vLocal, 0.0, 1.0);
}`;

const FRAG = `
uniform float uStep;
uniform float uExtent;
uniform vec2 uCenter;
uniform vec3 uColor;
uniform vec3 uAxisX;
uniform vec3 uAxisY;
uniform float uAlpha;
varying vec2 vLocal;
float lines(vec2 c, float step) {
  vec2 q = c / step;
  vec2 d = max(fwidth(q), vec2(1e-6));
  vec2 g = abs(fract(q - 0.5) - 0.5) / d;
  return 1.0 - min(min(g.x, g.y), 1.0);
}
void main() {
  vec2 dq = fwidth(vLocal / uStep);
  float dens = max(dq.x, dq.y);
  float minor = lines(vLocal, uStep) * (1.0 - smoothstep(0.18, 0.4, dens));
  float major = lines(vLocal, uStep * 10.0) * (1.0 - smoothstep(0.18, 0.4, dens * 0.1));
  float a = max(minor * 0.32, major * 0.6);
  float ax = 1.0 - min(abs(vLocal.y) / max(fwidth(vLocal.y), 1e-6), 1.0);
  float ay = 1.0 - min(abs(vLocal.x) / max(fwidth(vLocal.x), 1e-6), 1.0);
  vec3 col = uColor;
  if (ax > 0.0) { col = mix(col, uAxisX, ax); a = max(a, ax * 0.85); }
  if (ay > 0.0) { col = mix(col, uAxisY, ay); a = max(a, ay * 0.85); }
  float fade = 1.0 - smoothstep(0.1, 0.7, length(vLocal - uCenter) / uExtent);
  gl_FragColor = vec4(col, a * uAlpha * fade);
  #include <colorspace_fragment>
}`;

export class ConstructionGrid {
  readonly mesh: THREE.Mesh;
  private readonly mat: THREE.ShaderMaterial;
  private plane: ConstructionPlane;
  private asked = '';
  private busy = false;
  private waiting: GridAsk | null = null;
  private seq = 0;
  ask: ((a: GridAsk) => Promise<GridLines>) | null = null;
  onLines: (() => void) | null = null;
  step = 10;

  constructor(plane: ConstructionPlane, pal: Palette) {
    this.plane = plane;
    this.mat = new THREE.ShaderMaterial({
      vertexShader: VERT,
      fragmentShader: FRAG,
      transparent: true,
      depthWrite: false,
      side: THREE.DoubleSide,
      uniforms: {
        uStep: { value: 10 },
        uExtent: { value: 1000 },
        uCenter: { value: new THREE.Vector2() },
        uColor: { value: pal.grid.clone() },
        uAxisX: { value: pal.axisX.clone() },
        uAxisY: { value: pal.axisY.clone() },
        uAlpha: { value: 0 },
      },
    });
    this.mesh = new THREE.Mesh(new THREE.PlaneGeometry(2, 2), this.mat);
    this.mesh.matrixAutoUpdate = false;
    this.mesh.frustumCulled = false;
    this.mesh.renderOrder = -1;
    this.setPlane(plane);
  }

  setPalette(pal: Palette): void {
    const u = this.mat.uniforms;
    u.uColor.value.copy(pal.grid);
    u.uAxisX.value.copy(pal.axisX);
    u.uAxisY.value.copy(pal.axisY);
  }

  setPlane(p: ConstructionPlane): void {
    this.plane = p;
    this.seq += 1;
    const x = new THREE.Vector3(...p.x), y = new THREE.Vector3(...p.y), z = new THREE.Vector3(...p.z);
    this.mesh.matrix.makeBasis(x, y, z).setPosition(...p.origin);
    this.mesh.matrixWorldNeedsUpdate = true;
  }

  fit(target: THREE.Vector3, visible: number, radius: number): void {
    const c = planeCoords(this.plane, [target.x, target.y, target.z]);
    (this.mat.uniforms.uCenter.value as THREE.Vector2).set(c[0], c[1]);
    const bin = (v: number, per: number): number => Math.round(Math.log2(Math.max(v, 1e-9)) * per);
    const key = `${this.seq}|${bin(visible, 2)}|${bin(radius, 1)}|${bin(Math.hypot(c[0], c[1]), 1)}`;
    if (key === this.asked) return;
    this.asked = key;
    this.send({ plane: this.plane, target: [target.x, target.y, target.z], visible, radius });
  }

  private send(a: GridAsk): void {
    if (!this.ask) return;
    if (this.busy) { this.waiting = a; return; }
    this.busy = true;
    const seq = this.seq;
    this.ask(a).then((g) => {
      if (seq === this.seq) this.apply(g);
    }).catch(() => undefined).finally(() => {
      this.busy = false;
      const next = this.waiting;
      this.waiting = null;
      if (next) this.send({ ...next, plane: this.plane });
    });
  }

  private apply(g: GridLines): void {
    this.mat.uniforms.uExtent.value = g.extent;
    this.mat.uniforms.uStep.value = g.step;
    this.mat.uniforms.uAlpha.value = 1;
    this.step = g.step;
    this.onLines?.();
  }

  dispose(): void {
    this.mesh.geometry.dispose();
    this.mat.dispose();
  }
}
