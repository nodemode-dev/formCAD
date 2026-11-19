import * as THREE from 'three';
import { LineMaterial } from 'three/examples/jsm/lines/LineMaterial.js';
import type { DisplayMode } from './types';
import type { Rgba } from '../canvas/color';
import { tokenHex } from '../canvas/ink';
import { MEDIA } from '../canvas/media';

export interface Palette {
  bg: THREE.Color;
  dark: boolean;
  edgeInk: THREE.Color;
  edgeSoft: THREE.Color;
  accent: THREE.Color;
  hover: THREE.Color;
  select: THREE.Color;
  snap: THREE.Color;
  axisX: THREE.Color;
  axisY: THREE.Color;
  axisZ: THREE.Color;
  paper: THREE.Color;
  grid: THREE.Color;
  cubeBase: THREE.Color;
  cubeInk: THREE.Color;
}

export const DEFAULT_BODY_COLOR = MEDIA.body3d;
const FACE_OFFSET = { factor: 1, units: 1 };

function luminance(c: THREE.Color): number {
  return 0.2126 * c.r + 0.7152 * c.g + 0.0722 * c.b;
}

const GRAY: Rgba = [128, 128, 128, 1];

export function tokenColor(name: string, fallback: Rgba = GRAY, scope?: Element): THREE.Color {
  return new THREE.Color().setHex(tokenHex(name, fallback, scope));
}

export function readPalette(host: HTMLElement): Palette {
  const get = (name: string, fallback: Rgba = GRAY): THREE.Color => tokenColor(name, fallback, host);
  const bg = get('--canvas-bg-model', [0, 0, 0, 1]);
  const dark = luminance(bg) < 0.45;
  return {
    bg,
    dark,
    edgeInk: get('--v3d-edge-ink'),
    edgeSoft: get('--v3d-edge-soft'),
    accent: get('--accent-color'),
    hover: get('--canvas-handle'),
    select: get('--canvas-selection', [74, 143, 255, 1]),
    snap: get('--canvas-snap'),
    axisX: get('--canvas-axis-x'),
    axisY: get('--canvas-axis-y'),
    axisZ: get('--canvas-axis-z'),
    paper: get('--v3d-paper'),
    grid: get('--v3d-grid'),
    cubeBase: get('--v3d-cube-base'),
    cubeInk: get('--v3d-cube-ink'),
  };
}

export const FACE_VISIBLE: Record<DisplayMode, boolean> = {
  wireframe: false, shaded: true, shadedEdges: true, hiddenLine: true, ghosted: true, xray: true, technical: true,
};
export const EDGES_VISIBLE: Record<DisplayMode, boolean> = {
  wireframe: true, shaded: false, shadedEdges: true, hiddenLine: true, ghosted: true, xray: true, technical: true,
};
export const FACES_OCCLUDE: Record<DisplayMode, boolean> = {
  wireframe: false, shaded: true, shadedEdges: true, hiddenLine: true, ghosted: false, xray: false, technical: true,
};

export class ModeKit {
  readonly resolution = new THREE.Vector2(1, 1);
  readonly clip: THREE.Plane[] = [];
  palette: Palette;
  private readonly faces = new Map<string, THREE.Material>();
  private readonly edges = new Map<string, LineMaterial>();
  private outlineMat: THREE.MeshBasicMaterial | null = null;
  private readonly outlineWidth = { value: 1.6 };
  private readonly outlineRes = { value: new THREE.Vector2(1, 1) };

  constructor(palette: Palette) {
    this.palette = palette;
  }

  setPalette(p: Palette): void {
    this.palette = p;
    for (const m of this.faces.values()) m.dispose();
    this.faces.clear();
    this.edges.get('ink')?.color.copy(p.edgeInk);
    this.edges.get('inkTech')?.color.copy(p.edgeInk);
    this.edges.get('soft')?.color.copy(p.edgeSoft);
    this.edges.get('ghost')?.color.copy(p.edgeSoft);
    this.edges.get('xray')?.color.copy(p.edgeSoft);
    this.outlineMat?.color.copy(p.edgeInk);
  }

  setResolution(w: number, h: number): void {
    this.resolution.set(w, h);
    for (const m of this.edges.values()) m.resolution.set(w, h);
    this.outlineRes.value.set(w, h);
  }

  face(mode: DisplayMode, color: number): THREE.Material | null {
    if (!FACE_VISIBLE[mode]) return null;
    const key = `${mode}:${color}`;
    let m = this.faces.get(key);
    if (!m) {
      m = this.makeFace(mode, color);
      this.faces.set(key, m);
    }
    return m;
  }

  private makeFace(mode: DisplayMode, color: number): THREE.Material {
    const clippingPlanes = this.clip.length ? this.clip : null;
    const common = { side: THREE.DoubleSide, clippingPlanes };
    const offset = { polygonOffset: true, polygonOffsetFactor: FACE_OFFSET.factor, polygonOffsetUnits: FACE_OFFSET.units };
    switch (mode) {
      case 'hiddenLine':
        return new THREE.MeshBasicMaterial({ ...common, ...offset, colorWrite: false });
      case 'ghosted':
        return new THREE.MeshStandardMaterial({ ...common, color, roughness: 0.7, metalness: 0, transparent: true, opacity: 0.16, depthWrite: false });
      case 'xray':
        return new THREE.MeshStandardMaterial({ ...common, color, roughness: 0.55, metalness: 0.05, transparent: true, opacity: 0.42, depthWrite: false });
      case 'technical':
        return new THREE.MeshLambertMaterial({ ...common, ...offset, color: new THREE.Color(color).lerp(this.palette.paper, 0.72) });
      case 'shadedEdges':
        return new THREE.MeshStandardMaterial({ ...common, ...offset, color, roughness: 0.52, metalness: 0.06 });
      default:
        return new THREE.MeshStandardMaterial({ ...common, color, roughness: 0.52, metalness: 0.06 });
    }
  }

  edge(mode: DisplayMode): LineMaterial {
    const key = mode === 'technical' ? 'inkTech' : mode === 'shadedEdges' ? 'ink' : mode === 'ghosted' ? 'ghost' : mode === 'xray' ? 'xray' : 'soft';
    let m = this.edges.get(key);
    if (!m) {
      const p = this.palette;
      const spec: Record<string, { color: THREE.Color; width: number; opacity: number }> = {
        ink: { color: p.edgeInk, width: 1.2, opacity: 1 },
        inkTech: { color: p.edgeInk, width: 2.2, opacity: 1 },
        soft: { color: p.edgeSoft, width: 1.3, opacity: 1 },
        ghost: { color: p.edgeSoft, width: 1.1, opacity: 0.55 },
        xray: { color: p.edgeSoft, width: 1.3, opacity: 0.9 },
      };
      const s = spec[key];
      m = new LineMaterial({ color: s.color.getHex(), linewidth: s.width, worldUnits: false, transparent: s.opacity < 1, opacity: s.opacity, alphaToCoverage: false });
      m.resolution.copy(this.resolution);
      m.clippingPlanes = this.clip.length ? this.clip : null;
      this.edges.set(key, m);
    }
    return m;
  }

  outline(): THREE.MeshBasicMaterial {
    if (!this.outlineMat) {
      const m = new THREE.MeshBasicMaterial({ color: this.palette.edgeInk, side: THREE.BackSide });
      const width = this.outlineWidth;
      const res = this.outlineRes;
      m.onBeforeCompile = (shader) => {
        shader.uniforms.outlinePx = width;
        shader.uniforms.outlineRes = res;
        shader.vertexShader = shader.vertexShader
          .replace('#include <common>', '#include <common>\nuniform float outlinePx;\nuniform vec2 outlineRes;')
          .replace('#include <project_vertex>', '#include <project_vertex>\n{ vec4 cn = projectionMatrix * vec4(normalMatrix * normal, 0.0); vec2 d = cn.xy; float l = length(d); if (l > 1e-6) gl_Position.xy += (d / l) * (outlinePx * 2.0 / outlineRes) * gl_Position.w; }');
      };
      this.outlineMat = m;
    }
    return this.outlineMat;
  }

  applyClip(planes: THREE.Plane[]): void {
    this.clip.length = 0;
    this.clip.push(...planes);
    const list = planes.length ? this.clip : null;
    for (const m of this.faces.values()) { m.clippingPlanes = list; m.needsUpdate = true; }
    for (const m of this.edges.values()) { m.clippingPlanes = list; m.needsUpdate = true; }
    if (this.outlineMat) { this.outlineMat.clippingPlanes = list; this.outlineMat.needsUpdate = true; }
  }

  dispose(): void {
    for (const m of this.faces.values()) m.dispose();
    for (const m of this.edges.values()) m.dispose();
    this.outlineMat?.dispose();
    this.faces.clear();
    this.edges.clear();
  }
}
