import * as THREE from 'three';
import { FullScreenQuad } from 'three/examples/jsm/postprocessing/Pass.js';
import { DenoiseMaterial, PhysicalCamera, WebGLPathTracer } from 'three-gpu-pathtracer';
import { loadEnvironment } from './env';
import type { RenderSettings } from './net';
import type { RenderScene } from './scene';

export const TONE: Record<RenderSettings['quality']['tone_mapping'], THREE.ToneMapping> = {
  neutral: THREE.NeutralToneMapping,
  aces: THREE.ACESFilmicToneMapping,
  agx: THREE.AgXToneMapping,
  linear: THREE.LinearToneMapping,
};

export const sleep0 = (): Promise<void> => new Promise((r) => { setTimeout(r, 0); });

export class AbortedRender extends Error {
  constructor() {
    super('The render was cancelled.');
    this.name = 'AbortedRender';
  }
}

export function toRadians(deg: number): number { return THREE.MathUtils.degToRad(deg); }

export class PathEngine {
  readonly renderer: THREE.WebGLRenderer;
  readonly pt: WebGLPathTracer;
  private scene: RenderScene | null = null;
  private denoise = false;
  private dn: FullScreenQuad | null = null;
  private dnTarget: THREE.WebGLRenderTarget | null = null;
  private poseSig = '';
  readonly gpu: string;

  constructor(readonly canvas: HTMLCanvasElement | OffscreenCanvas, alpha: boolean) {
    this.renderer = new THREE.WebGLRenderer({ canvas: canvas as HTMLCanvasElement, antialias: false, alpha, preserveDrawingBuffer: true, powerPreference: 'high-performance' });
    if (!this.renderer.capabilities.isWebGL2) throw new Error('This computer cannot run the path tracer: WebGL 2 is not available.');
    this.renderer.setPixelRatio(1);
    this.renderer.setClearColor(0x000000, 0);
    const gl = this.renderer.getContext();
    const info = gl.getExtension('WEBGL_debug_renderer_info');
    this.gpu = String(info ? gl.getParameter(info.UNMASKED_RENDERER_WEBGL) : gl.getParameter(gl.RENDERER));
    this.pt = new WebGLPathTracer(this.renderer);
    this.pt.renderDelay = 0;
    this.pt.minSamples = 0;
    this.pt.fadeDuration = 0;
    this.pt.rasterizeScene = false;
    this.pt.dynamicLowRes = false;
    this.pt.renderToCanvas = false;
    this.pt.textureSize.set(1024, 1024);
    this.pt.renderToCanvasCallback = (target, renderer, quad) => {
      if (this.denoise && this.dn && this.dnTarget) {
        if (this.dnTarget.width !== target.width || this.dnTarget.height !== target.height) this.dnTarget.setSize(target.width, target.height);
        (this.dn.material as DenoiseMaterial).map = target.texture;
        const prev = renderer.getRenderTarget();
        renderer.setRenderTarget(this.dnTarget);
        this.dn.render(renderer);
        renderer.setRenderTarget(prev);
        (quad.material as unknown as { map: THREE.Texture }).map = this.dnTarget.texture;
      }
      const auto = renderer.autoClear;
      renderer.autoClear = false;
      quad.render(renderer);
      renderer.autoClear = auto;
    };
  }

  get maxEdge(): number {
    const gl = this.renderer.getContext();
    return Math.min(Number(gl.getParameter(gl.MAX_TEXTURE_SIZE)), Number(gl.getParameter(gl.MAX_RENDERBUFFER_SIZE)));
  }

  get samples(): number { return this.pt.samples; }

  get compiling(): boolean { return Boolean((this.pt as unknown as { isCompiling: boolean }).isCompiling); }

  async configure(scene: RenderScene, s: RenderSettings, camera: THREE.Camera, transparent: boolean): Promise<void> {
    this.scene = scene;
    await scene.ready();
    scene.applyGround(s.ground);
    const env = await loadEnvironment(s.environment.id, s.environment.resolution);
    const sc = scene.scene;
    sc.environment = env;
    sc.environmentIntensity = s.environment.intensity;
    const rot = new THREE.Euler(Math.PI / 2, 0, toRadians(s.environment.rotation), 'ZYX');
    sc.environmentRotation.copy(rot);
    sc.backgroundRotation.copy(rot);
    sc.backgroundIntensity = s.environment.intensity;
    sc.backgroundBlurriness = s.environment.blur;
    if (transparent) sc.background = null;
    else if (s.environment.show_background) sc.background = env;
    else sc.background = new THREE.Color(s.environment.background_color);
    this.renderer.toneMapping = TONE[s.quality.tone_mapping];
    this.renderer.toneMappingExposure = s.quality.exposure;
    const q = s.quality;
    this.pt.bounces = q.bounces;
    this.pt.transmissiveBounces = q.transmissive_bounces;
    this.pt.filterGlossyFactor = q.filter_glossy;
    this.pt.multipleImportanceSampling = true;
    this.pt.tiles.set(q.tiles, q.tiles);
    this.setDenoise(q.denoise);
    this.poseSig = scene.bodyIds.length ? this.poses(scene) : '';
    await sleep0();
    this.pt.setScene(sc, camera);
  }

  private poses(scene: RenderScene): string {
    const out: string[] = [];
    scene.root.traverse((o) => { if (o.name.startsWith('body-')) out.push(o.matrix.elements.join(',')); });
    return out.join(';');
  }

  async repose(): Promise<void> {
    const cam = this.pt.camera;
    if (!this.scene || !cam) return;
    const sig = this.poses(this.scene);
    if (sig === this.poseSig) return;
    this.poseSig = sig;
    this.scene.root.updateMatrixWorld(true);
    await sleep0();
    this.pt.setScene(this.scene.scene, cam);
  }

  setDenoise(on: boolean): void {
    this.denoise = on;
    if (on && !this.dn) {
      this.dn = new FullScreenQuad(new DenoiseMaterial());
      this.dnTarget = new THREE.WebGLRenderTarget(1, 1, { type: THREE.FloatType, format: THREE.RGBAFormat, magFilter: THREE.NearestFilter, minFilter: THREE.NearestFilter });
    }
  }

  setSize(w: number, h: number): void {
    this.renderer.setSize(w, h, false);
  }

  setCamera(camera: THREE.Camera, s: RenderSettings): THREE.Camera {
    let cam = camera;
    if (s.camera.aperture > 0 && camera instanceof THREE.PerspectiveCamera) {
      const pc = new PhysicalCamera();
      pc.copy(camera as THREE.PerspectiveCamera);
      pc.position.copy(camera.position);
      pc.quaternion.copy(camera.quaternion);
      pc.up.copy(camera.up);
      pc.bokehSize = s.camera.aperture;
      pc.focusDistance = s.camera.focus_distance ?? this.scene?.center.distanceTo(camera.position) ?? 10;
      pc.updateMatrixWorld(true);
      pc.updateProjectionMatrix();
      cam = pc;
    }
    this.pt.setCamera(cam);
    return cam;
  }

  step(): void {
    this.pt.renderSample();
  }

  show(): void {
    const keep = [this.pt.renderToCanvas, this.pt.pausePathTracing];
    this.pt.renderToCanvas = true;
    this.pt.pausePathTracing = true;
    this.pt.renderSample();
    this.pt.renderToCanvas = keep[0];
    this.pt.pausePathTracing = keep[1];
  }

  private readonly probe = new Float32Array(4);

  settle(): void {
    try {
      this.renderer.readRenderTargetPixels(this.pt.target, 0, 0, 1, 1, this.probe);
    } catch {
      this.renderer.getContext().finish();
    }
  }

  dispose(): void {
    this.pt.dispose();
    this.dn?.dispose();
    this.dnTarget?.dispose();
    this.renderer.dispose();
    this.renderer.forceContextLoss();
  }
}
