import type { CanvasDeps, DisplayItem, Handle, Prim } from './types';

export interface PicDraw {
  bitmap: ImageBitmap;
  pts: number[];
  clip: number[] | null;
  area: number[] | null;
  fade: number;
}

interface Entry {
  bitmap: ImageBitmap | null;
  failed: boolean;
  seen: number;
}

type ImgPrim = Extract<Prim, { t: 'img' }>;

const MAX_SIDE = 4096;
const KEEP_FRAMES = 600;

export class Pictures {
  private readonly cache = new Map<string, Entry>();
  private readonly last = new Map<string, string>();
  private tick = 0;

  constructor(
    private readonly deps: CanvasDeps,
    private readonly redraw: () => void,
    private readonly dropped: (b: ImageBitmap) => void,
  ) {}

  private load(key: string, docId: string, h: Handle): void {
    const e: Entry = { bitmap: null, failed: false, seen: this.tick };
    this.cache.set(key, e);
    void (async () => {
      try {
        const blob = await this.deps.fetchPicture(docId, h);
        let bmp = await createImageBitmap(blob);
        const side = Math.max(bmp.width, bmp.height);
        if (side > MAX_SIDE) {
          const k = MAX_SIDE / side;
          const small = await createImageBitmap(blob, { resizeWidth: Math.max(1, Math.round(bmp.width * k)), resizeHeight: Math.max(1, Math.round(bmp.height * k)), resizeQuality: 'high' });
          bmp.close();
          bmp = small;
        }
        if (this.cache.get(key) !== e) {
          bmp.close();
          return;
        }
        e.bitmap = bmp;
        this.last.set(`${docId}|${h}`, key);
        this.redraw();
      } catch {
        e.failed = true;
      }
    })();
  }

  private pick(docId: string, h: Handle, p: ImgPrim): ImageBitmap | null {
    const key = `${docId}|${h}|${p.v}`;
    const e = this.cache.get(key);
    if (!e) this.load(key, docId, h);
    else e.seen = this.tick;
    if (e?.bitmap) return e.bitmap;
    const prev = this.last.get(`${docId}|${h}`);
    const old = prev ? this.cache.get(prev) : undefined;
    if (old?.bitmap) {
      old.seen = this.tick;
      return old.bitmap;
    }
    return null;
  }

  list(docId: string | null, items: Iterable<DisplayItem>, hidden: (layer: string) => boolean, viewports: Array<{ items: DisplayItem[]; area: number[] }>): PicDraw[] {
    this.tick++;
    const out: PicDraw[] = [];
    if (!docId) return out;
    const add = (it: DisplayItem, area: number[] | null) => {
      if (it.h === null || it.h === undefined || !it.prims) return;
      for (const p of it.prims) {
        if (p.t !== 'img') continue;
        const bitmap = this.pick(docId, it.h, p);
        if (bitmap) out.push({ bitmap, pts: p.pts, clip: p.clip, area, fade: Math.max(0, Math.min(100, p.fade)) / 100 });
      }
    };
    for (const it of items) if (!hidden(it.layer)) add(it, null);
    for (const vp of viewports) for (const it of vp.items) if (it.kind === 'underlay') add(it, vp.area);
    if (!(this.tick % 120)) this.sweep();
    return out;
  }

  private sweep(): void {
    const live = new Set(this.last.values());
    for (const [key, e] of this.cache) {
      if (this.tick - e.seen < KEEP_FRAMES || live.has(key)) continue;
      if (e.bitmap) {
        this.dropped(e.bitmap);
        e.bitmap.close();
      }
      this.cache.delete(key);
    }
  }

  clear(): void {
    for (const e of this.cache.values()) {
      if (e.bitmap) {
        this.dropped(e.bitmap);
        e.bitmap.close();
      }
    }
    this.cache.clear();
    this.last.clear();
  }
}
