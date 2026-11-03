import { el, patchList, q, setClass, setStyleVar, setText } from '../ui/dom';
import { t } from '../ui/i18n';
import { vstore, type VVersion } from './vault-store';

const ROW = 26;
const LANE = 14;
const LANES = 5;
const NS = 'http://www.w3.org/2000/svg';

interface Edge { key: string; x0: number; y0: number; x1: number; y1: number; lane: number }

const svgEl = (name: string): SVGElement => document.createElementNS(NS, name);
const setAttr = (n: Element, name: string, value: string): void => { if (n.getAttribute(name) !== value) n.setAttribute(name, value); };

export interface GraphView { el: HTMLElement; update(): void }

export function graphView(onSelect: (id: string, compare: boolean) => void): GraphView {
  const root = el('<div class="p11-graph" role="listbox" aria-label="Version history"><div class="p11-graph-inner"><svg class="p11-graph-svg" aria-hidden="true"></svg><div class="p11-graph-rows"></div></div></div>');
  const inner = q(root, '.p11-graph-inner');
  const svg = q<SVGSVGElement>(root, 'svg');
  const rows = q(root, '.p11-graph-rows');
  const empty = el('<p class="u8-note p11-graph-empty"></p>');
  root.append(empty);
  setText(empty, t('No versions yet. Check this document in to start its history.'));

  const x = (lane: number): number => 10 + Math.min(lane, LANES - 1) * LANE;
  const y = (row: number): number => row * ROW + ROW / 2;

  const update = (): void => {
    const nodes = vstore.nodes;
    const index = new Map<string, number>();
    nodes.forEach((n, i) => index.set(n.id, i));
    const width = 14 + LANES * LANE;
    setStyleVar(inner, '--p11-gw', `${width}px`);
    setStyleVar(inner, '--p11-gh', `${Math.max(nodes.length, 1) * ROW}px`);
    setAttr(svg, 'width', String(width));
    setAttr(svg, 'height', String(Math.max(nodes.length, 1) * ROW));
    empty.hidden = nodes.length > 0;

    const edges: Edge[] = [];
    nodes.forEach((n, i) => {
      n.parents.forEach((p, k) => {
        const j = index.get(p);
        if (j === undefined) return;
        const pn = nodes[j];
        edges.push({ key: `e${n.id}${k}`, x0: x(n.lane ?? 0), y0: y(i), x1: x(pn.lane ?? 0), y1: y(j), lane: n.lane ?? 0 });
      });
    });
    const items: Array<{ kind: 'edge'; e: Edge } | { kind: 'node'; n: VVersion; i: number }> = [
      ...edges.map((e) => ({ kind: 'edge' as const, e })),
      ...nodes.map((n, i) => ({ kind: 'node' as const, n, i })),
    ];
    patchList(svg as unknown as HTMLElement, items, {
      key: (o) => (o.kind === 'edge' ? o.e.key : `n${o.n.id}`),
      create: (o) => svgEl(o.kind === 'edge' ? 'path' : 'circle') as unknown as HTMLElement,
      update: (node, o) => {
        const n = node as unknown as SVGElement;
        if (o.kind === 'edge') {
          const { x0, y0, x1, y1 } = o.e;
          const my = y0 + (y1 - y0) * 0.5;
          setAttr(n, 'd', x0 === x1 ? `M${x0} ${y0}L${x1} ${y1}` : `M${x0} ${y0}C${x0} ${my} ${x1} ${my} ${x1} ${y1}`);
          setAttr(n, 'class', `p11-edge p11-lane-${o.e.lane % 6}`);
        } else {
          setAttr(n, 'cx', String(x(o.n.lane ?? 0)));
          setAttr(n, 'cy', String(y(o.i)));
          setAttr(n, 'r', o.n.parents.length > 1 ? '5' : '4');
          setAttr(n, 'class', `p11-node p11-lane-${(o.n.lane ?? 0) % 6}${o.n.id === vstore.selected ? ' is-selected' : ''}${o.n.id === vstore.compare ? ' is-compare' : ''}`);
        }
      },
    });

    patchList(rows, nodes, {
      key: (n) => n.id,
      create: (n) => {
        const row = el('<div class="p11-grow" role="option"><span class="p11-gmsg"></span><span class="p11-gchips"></span><span class="u8-badge p11-gstate"></span><span class="p11-gwho"></span></div>');
        row.addEventListener('click', (e) => onSelect(n.id, e.shiftKey || e.ctrlKey || e.metaKey));
        return row;
      },
      update: (row, n) => {
        const msg = `${n.short} · ${n.message || t('(no message)')}`;
        const m = q(row, '.p11-gmsg');
        setText(m, msg);
        if (m.title !== msg) m.title = msg;
        const chips = [...n.branches, ...n.tags.map((tg) => `#${tg}`)].join(' ');
        setText(q(row, '.p11-gchips'), chips);
        const st = q(row, '.p11-gstate');
        setText(st, n.revision ? `${n.state} ${n.revision}` : n.state);
        st.dataset.s = n.state === 'released' ? 'fully' : n.state === 'obsolete' ? 'conflict' : n.state === 'review' ? 'under' : '';
        const who = `${n.author}`;
        setText(q(row, '.p11-gwho'), who);
        const when = new Date(n.ts * 1000).toLocaleString();
        const w = q(row, '.p11-gwho');
        if (w.title !== when) w.title = when;
        setClass(row, 'is-selected', n.id === vstore.selected);
        setClass(row, 'is-compare', n.id === vstore.compare);
      },
    });
  };
  return { el: root, update };
}
