import * as THREE from 'three';
import { events } from '../io/events';
import { asm, isAssembly, topOf } from '../u8/asm';
import { docStore } from '../ui/doc-store';
import { onView3d } from '../view3d/mount';
import type { Viewport3D } from '../view3d/viewport';
import type { CameraSpec } from '../view3d/types';
import { boardApi, type Board, type BoardList, type FrameRow, type StyleId } from './api';
import { frameCamera, StoryScene } from './scene';

const CHUNK = 120;
const PREVIEW_EDGE = 960;

class Stage {
  readonly root = document.createElement('div');
  private readonly canvas = document.createElement('canvas');
  private renderer: THREE.WebGLRenderer | null = null;
  private scene: StoryScene | null = null;
  private vp: Viewport3D | null = null;
  on = false;

  constructor() {
    this.root.className = 'an1-stage';
    this.root.hidden = true;
    this.canvas.className = 'an1-stage-canvas';
    this.root.append(this.canvas);
  }

  attach(vp: Viewport3D): void {
    if (this.vp === vp) return;
    this.vp = vp;
    this.scene = null;
    vp.host.append(this.root);
  }

  show(row: FrameRow, board: Board): void {
    const vp = this.vp;
    if (!vp) return;
    this.on = true;
    if (this.root.hidden) this.root.hidden = false;
    const k = Math.min(1, PREVIEW_EDGE / Math.max(board.width, board.height));
    const w = Math.max(2, Math.round(board.width * k)), h = Math.max(2, Math.round(board.height * k));
    if (!this.renderer) {
      this.renderer = new THREE.WebGLRenderer({ canvas: this.canvas, antialias: true, alpha: false });
      this.renderer.localClippingEnabled = true;
    }
    if (this.canvas.width !== w || this.canvas.height !== h) this.renderer.setSize(w, h, false);
    this.scene ??= new StoryScene(vp);
    this.scene.setStyle(row.style ?? board.style);
    this.scene.setPoses(row.matrices, asm.worlds, topOf);
    this.scene.render(this.renderer, row.camera ?? vp.getCamera(), w, h);
  }

  measure(row: FrameRow): { center: THREE.Vector3; radius: number } | null {
    const vp = this.vp;
    if (!vp) return null;
    this.scene ??= new StoryScene(vp);
    this.scene.setPoses(row.matrices, asm.worlds, topOf);
    return this.scene.bounds();
  }

  direction(): [number, number, number] | null {
    const d = this.vp?.rig.direction();
    return d ? [d.x, d.y, d.z] : null;
  }

  hide(): void {
    this.on = false;
    if (!this.root.hidden) this.root.hidden = true;
  }
}

class StoryStore {
  list: BoardList | null = null;
  selected = '';
  shot = 0;
  frame = 0;
  playing = false;
  loading = '';
  readonly stage = new Stage();
  private readonly cache = new Map<number, FrameRow>();
  private readonly subs = new Set<() => void>();
  private running: Promise<void> | null = null;
  private again = false;
  private raf = 0;
  private fetching: Promise<void> | null = null;

  onChange(fn: () => void): void { this.subs.add(fn); }
  emit(): void { for (const f of this.subs) f(); }

  id(): string | null { return docStore.activeId; }
  board(): Board | null { return this.list?.boards[this.selected] ?? null; }

  refresh(): Promise<void> {
    if (this.running) { this.again = true; return this.running; }
    this.running = this.load().finally(() => { this.running = null; });
    return this.running;
  }

  private async load(): Promise<void> {
    do {
      this.again = false;
      const id = this.id();
      if (!id || !isAssembly()) {
        this.list = null; this.selected = ''; this.cache.clear(); this.stop(); this.stage.hide();
      } else {
        const list = await boardApi.list(id).catch(() => null);
        if (id !== this.id()) break;
        this.list = list;
        const names = Object.keys(list?.boards ?? {});
        if (!names.includes(this.selected)) { this.selected = names[0] ?? ''; this.frame = 0; }
        const b = this.board();
        if (b && !b.shots.some((s) => s.id === this.shot)) this.shot = b.shots[0]?.id ?? 0;
        this.cache.clear();
      }
      this.emit();
    } while (this.again);
  }

  select(name: string): void {
    this.selected = name;
    this.frame = 0;
    this.shot = this.board()?.shots[0]?.id ?? 0;
    this.cache.clear();
    this.emit();
  }

  async put(mutate: (b: Board) => void): Promise<void> {
    const id = this.id();
    const b = this.board();
    if (!id || !b) return;
    const next = JSON.parse(JSON.stringify(b)) as Board;
    mutate(next);
    const saved = await boardApi.put(id, b.name, next);
    if (this.list) this.list.boards = { ...this.list.boards, [b.name]: saved };
    this.selected = saved.name;
    this.cache.clear();
    this.emit();
  }

  async fetchFrom(first: number): Promise<void> {
    const id = this.id();
    const b = this.board();
    if (!id || !b) return;
    const total = b.plan.frames;
    const start = Math.max(0, Math.min(first, total - 1));
    const res = await boardApi.frames(id, b.name, start, Math.min(CHUNK, total - start));
    for (const f of res.frames) this.cache.set(f.i, f);
  }

  async row(i: number): Promise<FrameRow | null> {
    const b = this.board();
    if (!b || b.plan.frames === 0) return null;
    const at = Math.max(0, Math.min(b.plan.frames - 1, Math.round(i)));
    let hit = this.cache.get(at);
    if (hit) return hit;
    while (this.fetching) await this.fetching;
    hit = this.cache.get(at);
    if (hit) return hit;
    const run = this.fetchFrom(Math.floor(at / CHUNK) * CHUNK);
    this.fetching = run.finally(() => { this.fetching = null; });
    await run;
    return this.cache.get(at) ?? null;
  }

  async preload(signal?: AbortSignal): Promise<void> {
    const b = this.board();
    if (!b) return;
    for (let i = 0; i < b.plan.frames; i += CHUNK) {
      if (signal?.aborted) return;
      if (!this.cache.has(i)) await this.row(i);
      this.loading = `${Math.min(b.plan.frames, i + CHUNK)} / ${b.plan.frames}`;
      this.emit();
    }
    this.loading = '';
  }

  async seek(i: number): Promise<void> {
    const b = this.board();
    if (!b) return;
    this.frame = Math.max(0, Math.min(b.plan.frames - 1, Math.round(i)));
    const row = await this.row(this.frame);
    if (row) {
      this.stage.show(row, b);
      const span = b.plan.spans.find((s) => this.frame >= s.first && this.frame < s.first + s.frames);
      if (span) this.shot = span.id;
    }
    this.emit();
  }

  stop(): void {
    this.playing = false;
    if (this.raf) { cancelAnimationFrame(this.raf); this.raf = 0; }
  }

  async play(): Promise<void> {
    const b = this.board();
    if (!b || this.playing || b.plan.frames === 0) return;
    this.playing = true;
    this.emit();
    await this.preload();
    if (!this.playing) { this.emit(); return; }
    const start = this.frame >= b.plan.frames - 1 ? 0 : this.frame;
    const t0 = performance.now();
    const tick = (now: number): void => {
      if (!this.playing) return;
      const i = start + Math.floor(((now - t0) / 1000) * b.fps);
      if (i >= b.plan.frames) { this.stop(); void this.seek(b.plan.frames - 1); return; }
      const row = this.cache.get(i);
      if (row) { this.frame = i; this.stage.show(row, b); this.emit(); }
      this.raf = requestAnimationFrame(tick);
    };
    this.raf = requestAnimationFrame(tick);
  }

  async autoCamera(): Promise<void> {
    const b = this.board();
    const dir = this.stage.direction();
    if (!b || !dir) return;
    const aspect = b.width / b.height;
    const keys = new Map<number, { at: number; camera: CameraSpec }>();
    for (const [idx, shot] of b.shots.entries()) {
      const span = b.plan.spans.find((s) => s.id === shot.id);
      if (!span || span.frames === 0) continue;
      const moves = shot.explode && shot.explode.from !== shot.explode.to;
      const at = idx === 0 ? 0 : moves ? 1 : -1;
      if (at < 0) continue;
      const row = await this.row(at === 0 ? span.first : span.first + span.frames - 1);
      const m = row ? this.stage.measure(row) : null;
      if (m) keys.set(shot.id, { at, camera: frameCamera(dir, m.center, m.radius, aspect) });
    }
    await this.put((next) => {
      for (const s of next.shots) {
        const k = keys.get(s.id);
        if (k) s.camera = { keys: [k], orbit: s.camera?.orbit };
      }
    });
  }

  styleOf(row: FrameRow | null): StyleId { return row?.style ?? this.board()?.style ?? 'shaded'; }

  cached(i: number): FrameRow | undefined { return this.cache.get(i); }
}

export const story = new StoryStore();

onView3d((c) => { if (c.vp) story.stage.attach(c.vp); });
document.addEventListener('formcad:view3d-created', (e) => { story.stage.attach((e as CustomEvent<{ vp: Viewport3D }>).detail.vp); });
events.on('doc', (e) => { if (e.id === docStore.activeId) void story.refresh(); });
docStore.onChange(() => { void story.refresh(); });
