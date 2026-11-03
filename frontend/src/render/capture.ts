import * as THREE from 'three';
import { parseScene } from '../view3d/scene-format';
import type { CameraSpec } from '../view3d/types';
import { AbortedRender, PathEngine, sleep0 } from './engine';
import { loadEnvironment } from './env';
import { decals as fetchDecals, renderBodies, sceneBuffer, type RenderBodyRow, type RenderSettings } from './net';
import { cameraFrom, RenderScene } from './scene';

export interface FrameSpec {
  width: number;
  height: number;
  samples: number;
  tiles: number;
  camera: CameraSpec | null;
  poses?: Map<number, THREE.Matrix4> | null;
  hidden?: number[];
  engine?: 'path' | 'raster';
  transparent?: boolean;
}

export interface FrameControl {
  signal?: AbortSignal;
  onProgress?(done: number, total: number, phase: string): void;
}

export interface FrameResult {
  canvas: HTMLCanvasElement | OffscreenCanvas;
  width: number;
  height: number;
  samples: number;
  ms: number;
  tiles: number;
  bands: number;
  engine: 'path' | 'raster';
  renderer: string;
}

export const BAND_PIXELS = 8_500_000;

export async function loadRenderScene(docId: string): Promise<RenderScene> {
  const parsed = parseScene(await sceneBuffer(docId), true);
  const [{ bodies: rows }, { decals }] = await Promise.all([renderBodies(docId), fetchDecals(docId)]);
  return new RenderScene({ bodies: parsed.bodies, hidden: parsed.hidden, mmPerUnit: parsed.mmPerUnit, rows, decals });
}

export const withRows = (scene: RenderScene, rows: RenderBodyRow[]): void => {
  for (const r of rows) scene.setAppearance(r.id, r.appearance);
};

const checkAbort = (ctl?: FrameControl): void => {
  if (ctl?.signal?.aborted) throw new AbortedRender();
};

function surface(w: number, h: number): HTMLCanvasElement | OffscreenCanvas {
  if (typeof OffscreenCanvas !== 'undefined') return new OffscreenCanvas(w, h);
  const c = document.createElement('canvas');
  c.width = w;
  c.height = h;
  return c;
}

export class FrameRenderer {
  private engine: PathEngine | null = null;
  private raster: THREE.WebGLRenderer | null = null;
  private rasterCanvas: HTMLCanvasElement | null = null;
  private gl: HTMLCanvasElement;
  private configuredFor = '';
  private disposed = false;

  private constructor(readonly scene: RenderScene, readonly settings: RenderSettings) {
    this.gl = document.createElement('canvas');
  }

  static async create(scene: RenderScene, settings: RenderSettings): Promise<FrameRenderer> {
    return new FrameRenderer(scene, settings);
  }

  private bands(w: number, h: number, edge: number): { count: number; bandH: number } {
    const byPixels = Math.ceil((w * h) / BAND_PIXELS);
    const byEdge = Math.ceil(h / edge);
    const count = Math.max(1, byPixels, byEdge);
    return { count, bandH: Math.ceil(h / count) };
  }

  async frame(spec: FrameSpec, ctl?: FrameControl): Promise<FrameResult> {
    if (this.disposed) throw new Error('This renderer was disposed.');
    const t0 = performance.now();
    if ((spec.engine ?? 'path') === 'raster') return this.rasterFrame(spec, t0, ctl);
    checkAbort(ctl);
    if (!this.engine) this.engine = new PathEngine(this.gl, true);
    const eng = this.engine;
    const s = this.settings;
    const { width: w, height: h } = spec;
    if (w > eng.maxEdge) throw new Error(`This graphics driver cannot make an image ${w} pixels wide; its limit is ${eng.maxEdge}.`);
    const { count, bandH } = this.bands(w, h, eng.maxEdge);
    const camera = cameraFrom(spec.camera, w / h, this.scene, s.camera.fov);
    this.scene.setPoses(spec.poses ?? null);
    this.scene.setHidden(spec.hidden);
    eng.setSize(w, bandH);
    const transparent = !!spec.transparent;
    const key = JSON.stringify([s.environment, s.ground, s.quality.tone_mapping, s.quality.exposure, s.quality.denoise, spec.tiles, transparent]);
    ctl?.onProgress?.(0, Math.max(1, spec.samples * count), 'Preparing the scene');
    if (this.configuredFor !== key) {
      const patched: RenderSettings = { ...s, quality: { ...s.quality, tiles: spec.tiles } };
      await eng.configure(this.scene, patched, camera, transparent);
      this.configuredFor = key;
    } else {
      await eng.repose();
    }
    checkAbort(ctl);
    const dest = count > 1 ? surface(w, h) : null;
    const ctx = dest ? (dest.getContext('2d') as CanvasRenderingContext2D | OffscreenCanvasRenderingContext2D) : null;
    const steps = Math.max(1, spec.tiles * spec.tiles);
    let done = 0;
    const total = spec.samples * count;
    for (let b = 0; b < count; b++) {
      const cam = camera.clone() as THREE.PerspectiveCamera | THREE.OrthographicCamera;
      cam.position.copy(camera.position);
      cam.quaternion.copy(camera.quaternion);
      cam.up.copy(camera.up);
      cam.updateMatrixWorld(true);
      if (count > 1) {
        (cam as THREE.PerspectiveCamera).setViewOffset(w, h, 0, b * bandH, w, bandH);
      } else if ((cam as THREE.PerspectiveCamera).clearViewOffset) {
        (cam as THREE.PerspectiveCamera).clearViewOffset();
      }
      cam.updateProjectionMatrix();
      const used = eng.setCamera(cam, s);
      void used;
      let guard = 0;
      while (eng.compiling && guard++ < 6000) { await sleep0(); checkAbort(ctl); }
      let reported = 0;
      let spins = 0;
      const cap = spec.samples * steps * 4 + 100000;
      while (Math.round(eng.samples) < spec.samples && spins++ < cap) {
        eng.step();
        eng.settle();
        checkAbort(ctl);
        await sleep0();
        const n = Math.min(spec.samples, Math.floor(eng.samples));
        if (n > reported) {
          done += n - reported;
          reported = n;
          ctl?.onProgress?.(done, total, count > 1 ? `Sample ${n} of ${spec.samples}, band ${b + 1} of ${count}` : `Sample ${n} of ${spec.samples}`);
        }
      }
      if (Math.round(eng.samples) < spec.samples) throw new Error('The path tracer stopped producing samples.');
      done += spec.samples - reported;
      eng.show();
      if (ctx && dest) {
        const rows = Math.min(bandH, h - b * bandH);
        (ctx as CanvasRenderingContext2D).drawImage(this.gl, 0, 0, w, rows, 0, b * bandH, w, rows);
      }
    }
    return { canvas: dest ?? this.gl, width: w, height: h, samples: spec.samples, ms: performance.now() - t0, tiles: spec.tiles, bands: count, engine: 'path', renderer: eng.gpu };
  }

  private async rasterFrame(spec: FrameSpec, t0: number, ctl?: FrameControl): Promise<FrameResult> {
    const s = this.settings;
    if (!this.raster) {
      this.rasterCanvas = document.createElement('canvas');
      this.raster = new THREE.WebGLRenderer({ canvas: this.rasterCanvas, antialias: true, alpha: true, preserveDrawingBuffer: true });
      this.raster.setPixelRatio(1);
    }
    const r = this.raster;
    const env = await loadEnvironment(s.environment.id, s.environment.resolution);
    await this.scene.ready();
    this.scene.applyGround(s.ground);
    const sc = this.scene.scene;
    sc.environment = env;
    sc.environmentIntensity = s.environment.intensity;
    const rot = new THREE.Euler(Math.PI / 2, 0, THREE.MathUtils.degToRad(s.environment.rotation), 'ZYX');
    sc.environmentRotation.copy(rot);
    sc.backgroundRotation.copy(rot);
    sc.backgroundIntensity = s.environment.intensity;
    sc.backgroundBlurriness = s.environment.blur;
    sc.background = spec.transparent ? null : s.environment.show_background ? env : new THREE.Color(s.environment.background_color);
    r.toneMapping = { neutral: THREE.NeutralToneMapping, aces: THREE.ACESFilmicToneMapping, agx: THREE.AgXToneMapping, linear: THREE.LinearToneMapping }[s.quality.tone_mapping];
    r.toneMappingExposure = s.quality.exposure;
    this.scene.setPoses(spec.poses ?? null);
    this.scene.setHidden(spec.hidden);
    const gl = r.getContext();
    const edge = Math.min(Number(gl.getParameter(gl.MAX_TEXTURE_SIZE)), Number(gl.getParameter(gl.MAX_RENDERBUFFER_SIZE)));
    if (spec.width > edge || spec.height > edge) throw new Error(`This graphics driver cannot make an image larger than ${edge} pixels on a side in a single pass.`);
    r.setSize(spec.width, spec.height, false);
    const cam = cameraFrom(spec.camera, spec.width / spec.height, this.scene, s.camera.fov);
    checkAbort(ctl);
    r.render(sc, cam);
    ctl?.onProgress?.(1, 1, 'Raster frame');
    const info = gl.getExtension('WEBGL_debug_renderer_info');
    return { canvas: this.rasterCanvas as HTMLCanvasElement, width: spec.width, height: spec.height, samples: 1, ms: performance.now() - t0, tiles: 1, bands: 1, engine: 'raster', renderer: String(info ? gl.getParameter(info.UNMASKED_RENDERER_WEBGL) : gl.getParameter(gl.RENDERER)) };
  }

  async toPng(r: FrameResult): Promise<Blob> {
    const c = r.canvas;
    if ('convertToBlob' in c) return await (c as OffscreenCanvas).convertToBlob({ type: 'image/png' });
    return await new Promise<Blob>((res, rej) => { (c as HTMLCanvasElement).toBlob((b) => (b ? res(b) : rej(new Error('The image could not be encoded.'))), 'image/png'); });
  }

  dispose(): void {
    this.disposed = true;
    this.engine?.dispose();
    this.engine = null;
    this.raster?.dispose();
    this.raster = null;
  }
}

export async function captureFrame(scene: RenderScene, settings: RenderSettings, spec: FrameSpec, ctl?: FrameControl): Promise<Blob> {
  const fr = await FrameRenderer.create(scene, settings);
  try {
    return await fr.toPng(await fr.frame(spec, ctl));
  } finally {
    fr.dispose();
  }
}
