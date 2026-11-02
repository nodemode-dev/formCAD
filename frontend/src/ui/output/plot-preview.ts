import { Dialog } from '../dialogs';
import { el, q, setHidden, setText } from '../dom';
import { t } from '../i18n';
import { failure, previewImage, type PreviewImage } from './output-api';

export class PreviewCache {
  private last: { key: string; image: PreviewImage } | null = null;
  private seq = 0;
  private ctl: AbortController | null = null;

  async get(doc: string, request: Record<string, unknown>): Promise<PreviewImage> {
    const key = `${doc}|${JSON.stringify(request)}`;
    if (this.last?.key === key) return this.last.image;
    this.ctl?.abort();
    const ctl = new AbortController();
    this.ctl = ctl;
    const mine = ++this.seq;
    const image = await previewImage(doc, request, ctl.signal);
    if (mine !== this.seq) { URL.revokeObjectURL(image.url); throw new DOMException('stale', 'AbortError'); }
    if (this.last) URL.revokeObjectURL(this.last.image.url);
    this.last = { key, image };
    return image;
  }

  peek(doc: string, request: Record<string, unknown>): PreviewImage | null {
    return this.last?.key === `${doc}|${JSON.stringify(request)}` ? this.last.image : null;
  }
}

export const previews = new PreviewCache();

export class PlotPreview extends Dialog {
  private readonly caption: HTMLElement;
  private readonly frame: HTMLElement;
  private readonly img: HTMLImageElement;
  private readonly err: HTMLElement;
  private readonly print: HTMLButtonElement;
  private token = 0;
  private onPrint: (() => void) | null = null;

  constructor() {
    super('Plot Preview', 820);
    this.body.appendChild(el('<p class="cv-note op-prev-cap"></p>'));
    this.body.appendChild(el('<div class="op-prev-frame"><img alt="" decoding="async"><p class="op-prev-err" hidden></p></div>'));
    this.caption = q(this.body, '.op-prev-cap');
    this.frame = q(this.body, '.op-prev-frame');
    this.img = q<HTMLImageElement>(this.frame, 'img');
    this.err = q(this.frame, '.op-prev-err');
    this.button('Close', 'ghost', () => this.close());
    this.print = this.button('Print...', 'primary', () => { const run = this.onPrint; this.close(); run?.(); });
  }

  async show(doc: string, request: Record<string, unknown>, label: string, onPrint: () => void): Promise<void> {
    this.onPrint = onPrint;
    const mine = ++this.token;
    setText(this.caption, label);
    setHidden(this.err, true);
    this.print.disabled = true;
    this.open(this.print);
    try {
      const shot = await previews.get(doc, request);
      if (mine !== this.token) return;
      if (this.img.getAttribute('src') !== shot.url) this.img.setAttribute('src', shot.url);
      const land = shot.sheetMm.length > 1 && shot.sheetMm[0] >= shot.sheetMm[1] ? `, ${t('landscape')}` : '';
      setText(this.caption, `${shot.sheet}, ${Number(shot.sheetMm[0]?.toFixed(2))} x ${Number(shot.sheetMm[1]?.toFixed(2))} mm${land}, ${Math.round(shot.dpi)} dpi`);
      this.print.disabled = false;
    } catch (e) {
      if (e instanceof DOMException && e.name === 'AbortError') return;
      if (mine !== this.token) return;
      setText(this.err, failure(e));
      setHidden(this.err, false);
    }
  }
}
