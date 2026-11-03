import { setClass } from '../ui/dom';
import type { CameraSpec } from '../view3d/types';
import type { Viewport3D } from '../view3d/viewport';
import { PathEngine } from './engine';
import { renderBodies, decals as fetchDecals, type RenderSettings } from './net';
import { cameraFrom, RenderScene } from './scene';

export interface LiveStats { samples: number; target: number; state: 'off' | 'building' | 'tracing' | 'done' | 'failed'; message: string; scale: number }

export class LiveRender {
  readonly canvas = document.createElement('canvas');
  on = false;
  onStats: ((s: LiveStats) => void) | null = null;
  private engine: PathEngine | null = null;
  private scene: RenderScene | null = null;
  private settings: RenderSettings | null = null;
  private raf = 0;
  private camSig = '';
  private sizeSig = '';
  private sceneSig = '';
  private building = false;
  private dirty = true;
  private stats: LiveStats = { samples: 0, target: 0, state: 'off', message: '', scale: 0.5 };
  private scale = 0.5;
  private shown = 0;

  constructor(private readonly vp: Viewport3D, private readonly docId: () => string | null) {
    this.canvas.className = 'rn-canvas';
    this.canvas.setAttribute('aria-hidden', 'true');
    vp.host.insertBefore(this.canvas, vp.overlay.canvas);
  }

  get previewScale(): number { return this.scale; }

  setScale(s: number): void {
    this.scale = s;
    this.sizeSig = '';
    this.dirty = true;
  }

  apply(settings: RenderSettings): void {
    this.settings = settings;
    this.dirty = true;
    this.sceneSig = '';
  }

  invalidateScene(): void {
    this.sceneSig = '';
    this.dirty = true;
  }

  start(settings: RenderSettings): void {
    this.settings = settings;
    this.on = true;
    this.dirty = true;
    this.sceneSig = '';
    this.report('building', '');
    if (!this.raf) this.raf = requestAnimationFrame(() => this.tick());
  }

  stop(): void {
    this.on = false;
    if (this.raf) cancelAnimationFrame(this.raf);
    this.raf = 0;
    setClass(this.canvas, 'is-ready', false);
    this.engine?.dispose();
    this.engine = null;
    this.scene?.dispose();
    this.scene = null;
    this.sceneSig = '';
    this.report('off', '');
  }

  private report(state: LiveStats['state'], message: string): void {
    this.stats = { samples: this.engine?.samples ?? 0, target: this.settings?.quality.samples ?? 0, state, message, scale: this.scale };
    this.onStats?.(this.stats);
  }

  private async rebuild(): Promise<void> {
    const id = this.docId();
    const s = this.settings;
    if (!id || !s || this.building) return;
    this.building = true;
    setClass(this.canvas, 'is-ready', false);
    this.report('building', '');
    try {
      const [{ bodies: rows }, { decals }] = await Promise.all([renderBodies(id), fetchDecals(id)]);
      this.scene?.dispose();
      this.scene = new RenderScene({ bodies: this.vp.model.bodies, mmPerUnit: 1, rows, decals });
      if (!this.engine) this.engine = new PathEngine(this.canvas, false);
      const cam = cameraFrom(this.vp.getCamera(), Math.max(1, this.vp.size.w) / Math.max(1, this.vp.size.h), this.scene, s.camera.fov);
      this.applySize();
      const live: RenderSettings = { ...s, quality: { ...s.quality, tiles: 2 } };
      await this.engine.configure(this.scene, live, cam, false);
      this.camSig = '';
      this.sceneSig = `${this.vp.model.rev}:${rows.map((r) => r.appearance.name).join('|')}:${JSON.stringify(s.environment)}:${JSON.stringify(s.ground)}:${s.quality.tone_mapping}:${s.quality.exposure}:${s.quality.bounces}`;
      this.dirty = false;
      this.report('tracing', '');
    } catch (e) {
      this.report('failed', e instanceof Error ? e.message : 'The path tracer could not start.');
      this.on = false;
    } finally {
      this.building = false;
    }
  }

  private applySize(): void {
    if (!this.engine) return;
    const { w, h } = this.vp.size;
    const sig = `${w}x${h}@${this.scale}`;
    if (sig === this.sizeSig) return;
    this.sizeSig = sig;
    this.engine.setSize(Math.max(2, Math.round(w * this.scale)), Math.max(2, Math.round(h * this.scale)));
    this.camSig = '';
  }

  private tick(): void {
    this.raf = 0;
    if (!this.on) return;
    this.raf = requestAnimationFrame(() => this.tick());
    const s = this.settings;
    if (!s) return;
    const sig = `${this.vp.model.rev}:${this.vp.bodyViews.size}`;
    if (this.dirty || !this.engine || !this.scene || (this.sceneSig && !this.sceneSig.startsWith(`${this.vp.model.rev}:`))) {
      void sig;
      if (!this.building) void this.rebuild();
      return;
    }
    this.applySize();
    const spec: CameraSpec = this.vp.getCamera();
    const cs = JSON.stringify(spec);
    if (cs !== this.camSig) {
      this.camSig = cs;
      const cam = cameraFrom(spec, Math.max(1, this.vp.size.w) / Math.max(1, this.vp.size.h), this.scene, s.camera.fov);
      this.engine.setCamera(cam, s);
      setClass(this.canvas, 'is-ready', false);
      this.shown = 0;
    }
    if (this.engine.compiling) return;
    const target = s.quality.samples;
    if (this.engine.samples < target) {
      this.engine.step();
      this.engine.settle();
      const n = Math.floor(this.engine.samples);
      if (n >= 1 && n !== this.shown) {
        this.engine.show();
        this.shown = n;
        setClass(this.canvas, 'is-ready', true);
        this.report('tracing', '');
      }
    } else if (this.stats.state !== 'done') {
      this.engine.show();
      this.report('done', '');
    }
  }

  dispose(): void {
    this.stop();
    this.canvas.remove();
  }
}
