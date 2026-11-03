import { setClass } from '../ui/dom';
import { curve } from './geometry';
import type { NodeView } from './node-view';
import type { NodeState, WireRecord } from './types';

const NS = 'http://www.w3.org/2000/svg';
export type WireKind = 'item' | 'list' | 'tree';

export function kindOfOutput(state: NodeState | undefined, port: string): WireKind {
  const s = state?.outputs[port];
  if (!s) return 'item';
  if (s.count > 1) return 'tree';
  if (s.items > 1) return 'list';
  return 'item';
}

export class WireView {
  readonly el: SVGPathElement;
  rec: WireRecord;
  from: NodeView | null = null;
  to: NodeView | null = null;
  private d = '';
  private kind: WireKind = 'item';
  private fromPos = '';
  private toPos = '';

  constructor(rec: WireRecord) {
    this.rec = rec;
    this.el = document.createElementNS(NS, 'path');
    this.el.setAttribute('class', 'gx-wire');
    this.el.dataset.id = rec.id;
  }

  ends(): { ax: number; ay: number; bx: number; by: number } | null {
    const a = this.from, b = this.to;
    if (!a || !b) return null;
    const oi = a.rec.outputs.findIndex((p) => p.name === this.rec.from.port);
    const ii = b.rec.inputs.findIndex((p) => p.name === this.rec.to.port);
    if (oi < 0 || ii < 0) return null;
    const p = a.outPoint(oi), r = b.inPoint(ii);
    return { ax: p.x, ay: p.y, bx: r.x, by: r.y };
  }

  route(): void {
    const e = this.ends();
    if (!e) { if (this.d !== '') { this.d = ''; this.el.removeAttribute('d'); } return; }
    const fp = `${e.ax},${e.ay}`, tp = `${e.bx},${e.by}`;
    if (fp === this.fromPos && tp === this.toPos) return;
    this.fromPos = fp;
    this.toPos = tp;
    this.d = curve(e.ax, e.ay, e.bx, e.by);
    this.el.setAttribute('d', this.d);
  }

  paint(kind: WireKind, selected: boolean, off: boolean, bad: boolean): void {
    if (kind !== this.kind) {
      setClass(this.el as unknown as Element, 'is-list', kind === 'list');
      setClass(this.el as unknown as Element, 'is-tree', kind === 'tree');
      this.kind = kind;
    }
    setClass(this.el as unknown as Element, 'is-sel', selected);
    setClass(this.el as unknown as Element, 'is-off', off);
    setClass(this.el as unknown as Element, 'is-bad', bad);
  }

  get currentKind(): WireKind { return this.kind; }
}

export function makeWireLayer(): { svg: SVGSVGElement; layer: SVGGElement; ghost: SVGPathElement } {
  const svg = document.createElementNS(NS, 'svg');
  svg.setAttribute('class', 'gx-wires');
  svg.setAttribute('aria-hidden', 'true');
  const layer = document.createElementNS(NS, 'g');
  const ghost = document.createElementNS(NS, 'path');
  ghost.setAttribute('class', 'gx-ghost');
  ghost.style.display = 'none';
  svg.append(layer, ghost);
  return { svg, layer, ghost };
}
