import { el, q, setText } from '../dom';
import { t } from '../i18n';
import type { PreviewImage } from './output-api';

const SVG_NS = 'http://www.w3.org/2000/svg';

export class SheetSketch {
  readonly el: HTMLElement;
  private readonly box: HTMLElement;
  private readonly img: HTMLImageElement;
  private readonly edge: SVGPathElement;
  private readonly area: SVGPathElement;
  private readonly svg: SVGSVGElement;
  private readonly size: HTMLElement;
  private seen = '';

  constructor() {
    this.el = el('<div class="op-sketch"><div class="op-sketch-slot"><div class="op-sketch-box"><img alt="" decoding="async"></div></div><div class="op-sketch-size"></div></div>');
    this.box = q(this.el, '.op-sketch-box');
    this.img = q<HTMLImageElement>(this.el, 'img');
    this.size = q(this.el, '.op-sketch-size');
    this.svg = document.createElementNS(SVG_NS, 'svg');
    this.svg.setAttribute('class', 'op-sketch-svg');
    this.svg.setAttribute('preserveAspectRatio', 'xMidYMid meet');
    this.edge = document.createElementNS(SVG_NS, 'path');
    this.edge.setAttribute('class', 'op-sketch-edge');
    this.area = document.createElementNS(SVG_NS, 'path');
    this.area.setAttribute('class', 'op-sketch-area');
    this.svg.append(this.edge, this.area);
    this.box.appendChild(this.svg);
    setText(this.size, t('No sheet yet'));
  }

  showing(p: PreviewImage | null): void {
    if (!p || p.sheetMm.length < 2 || p.printableMm.length < 4) return;
    const [w, h] = p.sheetMm;
    const [x0, y0, x1, y1] = p.printableMm;
    const key = `${w}|${h}|${x0}|${y0}|${x1}|${y1}`;
    if (key !== this.seen) {
      this.seen = key;
      this.svg.setAttribute('viewBox', `0 0 ${w} ${h}`);
      this.edge.setAttribute('d', `M0 0H${w}V${h}H0Z`);
      this.area.setAttribute('d', `M${x0} ${y0}H${x1}V${y1}H${x0}Z`);
      setText(this.size, `${Number(w.toFixed(2))} x ${Number(h.toFixed(2))} mm`);
    }
    if (this.img.getAttribute('src') !== p.url) this.img.setAttribute('src', p.url);
  }
}
