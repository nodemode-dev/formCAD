import * as THREE from 'three';
import { token } from '../io/api';
import { asm, topOf } from '../u8/asm';
import { matrixOf } from '../u8/geo';
import { pickPath } from '../ui/file-dialogs';
import { view3d } from '../view3d/mount';
import type { FrameRenderer } from '../render/capture';
import type { Board, FrameRow } from './api';
import { StoryScene } from './scene';
import { story } from './store';
import { chooseEncoder, encode, MAX_EDGE, type VideoResult } from './video';

export interface FrameSource {
  readonly name: string;
  draw(row: FrameRow, board: Board): void | Promise<void>;
  maxEdge(): number;
  dispose(): void;
}

function deltaPoses(matrices: Record<string, number[]>): Map<number, THREE.Matrix4> {
  const out = new Map<number, THREE.Matrix4>();
  const vp = view3d()?.vp;
  if (!vp) return out;
  for (const [bid, v] of vp.bodyViews) {
    const top = topOf(v.data.instance || v.data.component || '');
    const next = matrices[top];
    const old = asm.worlds.get(top);
    if (next && old) out.set(bid, matrixOf(next).multiply(old.clone().invert()));
  }
  return out;
}

class RenderSource implements FrameSource {
  readonly name: string;
  private readonly ctx: CanvasRenderingContext2D;

  private constructor(private readonly canvas: HTMLCanvasElement, private readonly fr: FrameRenderer, private readonly mode: 'raster' | 'path', private readonly samples: number, private readonly tiles: number, private readonly fallback: FrameRow['camera'], private readonly signal?: AbortSignal) {
    const ctx = canvas.getContext('2d');
    if (!ctx) throw new Error('The video canvas could not be created.');
    this.ctx = ctx;
    this.name = mode === 'path' ? `render page, path traced ${samples} samples` : 'render page, material raster pass';
  }

  static async create(docId: string, canvas: HTMLCanvasElement, board: Board, fallback: FrameRow['camera'], signal?: AbortSignal): Promise<RenderSource> {
    const [cap, net] = await Promise.all([import('../render/capture'), import('../render/net')]);
    const [scene, st] = await Promise.all([cap.loadRenderScene(docId), net.getSettings(docId)]);
    const fr = await cap.FrameRenderer.create(scene, st.settings);
    return new RenderSource(canvas, fr, board.source === 'path' ? 'path' : 'raster', board.samples, st.settings.quality.tiles, fallback, signal);
  }

  async draw(row: FrameRow): Promise<void> {
    const cam = row.camera ?? this.fallback;
    const r = await this.fr.frame({ width: this.canvas.width, height: this.canvas.height, samples: this.samples, tiles: this.tiles, camera: cam, poses: deltaPoses(row.matrices), engine: this.mode }, { signal: this.signal });
    this.ctx.drawImage(r.canvas as CanvasImageSource, 0, 0, this.canvas.width, this.canvas.height);
  }

  maxEdge(): number { return 8192; }

  dispose(): void { this.fr.dispose(); }
}

class PlainSource implements FrameSource {
  readonly name = 'viewport raster';
  private readonly renderer: THREE.WebGLRenderer;
  private readonly scene: StoryScene;

  constructor(readonly canvas: HTMLCanvasElement, private readonly fallback: FrameRow['camera']) {
    const vp = view3d()?.vp;
    if (!vp) throw new Error('Open a 3D view first.');
    this.renderer = new THREE.WebGLRenderer({ canvas, antialias: true, alpha: false, preserveDrawingBuffer: true });
    this.renderer.localClippingEnabled = true;
    this.renderer.setPixelRatio(1);
    this.renderer.setSize(canvas.width, canvas.height, false);
    this.scene = new StoryScene(vp);
  }

  draw(row: FrameRow, board: Board): void {
    this.scene.setStyle(row.style ?? board.style);
    this.scene.setPoses(row.matrices, asm.worlds, topOf);
    const cam = row.camera ?? this.fallback;
    if (!cam) throw new Error('The storyboard has no camera and the view is not ready.');
    this.scene.render(this.renderer, cam, this.canvas.width, this.canvas.height);
  }

  maxEdge(): number {
    const gl = this.renderer.getContext();
    return gl.getParameter(gl.MAX_RENDERBUFFER_SIZE) as number;
  }

  dispose(): void {
    this.scene.dispose();
    this.renderer.dispose();
    this.renderer.forceContextLoss();
  }
}

export interface ExportReport extends Omit<VideoResult, 'bytes'> {
  path: string;
  size: number;
  source: string;
  tried: string[];
  fetchMs: number;
}

export interface ExportOptions {
  board: Board;
  path?: string;
  signal?: AbortSignal;
  progress?(done: number, total: number, phase: string): void;
}

export class ExportRefused extends Error {}

export async function exportVideo(opts: ExportOptions): Promise<ExportReport | null> {
  const { board } = opts;
  const id = story.id();
  const vp = view3d()?.vp;
  if (!id || !vp) throw new ExportRefused('Open the assembly in the 3D view first.');
  if (board.plan.frames < 1) throw new ExportRefused('The storyboard has no frames.');
  if (board.width > MAX_EDGE || board.height > MAX_EDGE) throw new ExportRefused(`The video edge is limited to ${MAX_EDGE} pixels.`);
  const choice = await chooseEncoder(board.width, board.height, board.fps);
  if ('none' in choice) throw new ExportRefused(choice.none);
  let path = opts.path ?? null;
  if (!path) {
    path = await pickPath('save', 'Export Video', `${board.name}.${choice.container}`, [{ name: choice.container === 'mp4' ? 'MP4 video' : 'WebM video', extensions: [choice.container] }], 'Export');
    if (!path) return null;
  }
  path = path.replace(/\.[^./\\]+$/, '') + `.${choice.container}`;
  const canvas = document.createElement('canvas');
  canvas.width = board.width;
  canvas.height = board.height;
  const spec = vp.getCamera();
  const source: FrameSource = board.source === 'viewport' ? new PlainSource(canvas, spec) : await RenderSource.create(id, canvas, board, spec, opts.signal);
  let fetchMs = 0;
  try {
    const cap = source.maxEdge();
    if (board.width > cap || board.height > cap) throw new ExportRefused(`This graphics driver draws at most ${cap} pixels per edge.`);
    const result = await encode({
      width: board.width, height: board.height, fps: board.fps, frames: board.plan.frames, choice, canvas, signal: opts.signal,
      progress: (d, t) => opts.progress?.(d, t, 'encode'),
      async draw(i) {
        const t0 = performance.now();
        const row = await story.row(i);
        fetchMs += performance.now() - t0;
        if (!row) throw new ExportRefused(`Frame ${i} could not be computed.`);
        await source.draw(row, board);
      },
    });
    opts.progress?.(result.frames, result.frames, 'save');
    const headers: Record<string, string> = { 'Content-Type': 'application/octet-stream' };
    const tok = token();
    if (tok) headers['X-FormCAD-Token'] = tok;
    const res = await fetch(`/api/docs/${encodeURIComponent(id)}/storyboards/${encodeURIComponent(board.name)}/video?path=${encodeURIComponent(path)}`, { method: 'PUT', headers, body: result.bytes, signal: opts.signal });
    if (!res.ok) {
      let msg = res.statusText;
      try { const j = await res.json() as { detail?: unknown }; if (typeof j.detail === 'string') msg = j.detail; } catch { /* keep status text */ }
      throw new ExportRefused(msg || `The video could not be saved (${res.status}).`);
    }
    const written = await res.json() as { path: string; bytes: number };
    return {
      container: result.container, codec: result.codec, codecString: result.codecString, frames: result.frames, seconds: result.seconds, fps: result.fps,
      width: result.width, height: result.height, ms: result.ms, path: written.path, size: written.bytes, source: source.name, tried: choice.tried, fetchMs,
    };
  } finally {
    source.dispose();
  }
}
