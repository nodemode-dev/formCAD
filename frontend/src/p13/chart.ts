import { el, q, setText } from '../ui/dom';
import { t } from '../ui/i18n';
import { SI } from './kit';
import type { Curve } from './summary';

const W = 280, H = 120, L = 6, R = 6, T = 6, B = 6;

export interface Chart { el: HTMLElement; set(c: Curve | null): void }

export function chart(): Chart {
  const root = el(`<div class="sm-chart"><svg viewBox="0 0 ${W} ${H}" preserveAspectRatio="none" role="img" aria-label="History"><rect class="sm-chart-frame" x="0.5" y="0.5" width="${W - 1}" height="${H - 1}"></rect><path class="sm-chart-line" d=""></path></svg><div class="sm-chart-ends"><span class="sm-cx0"></span><span class="sm-cx1"></span></div><div class="sm-chart-ends"><span class="sm-cy0"></span><span class="sm-cy1"></span></div><p class="u8-note sm-chart-cap"></p></div>`);
  const path = q(root, '.sm-chart-line');
  let last = '';
  return {
    el: root,
    set(c) {
      const sig = c ? `${c.id}:${c.points.length}:${c.points[c.points.length - 1]?.join(',')}` : '';
      if (sig === last) return;
      last = sig;
      if (!c || c.points.length < 2) { path.setAttribute('d', ''); for (const k of ['.sm-cx0', '.sm-cx1', '.sm-cy0', '.sm-cy1', '.sm-chart-cap']) setText(q(root, k), ''); return; }
      const xs = c.points.map((p) => p[0]), ys = c.points.map((p) => p[1]);
      const x0 = Math.min(...xs), x1 = Math.max(...xs), y0 = Math.min(...ys), y1 = Math.max(...ys);
      const sx = x1 > x0 ? (W - L - R) / (x1 - x0) : 0, sy = y1 > y0 ? (H - T - B) / (y1 - y0) : 0;
      const d = c.points.map((p, i) => `${i ? 'L' : 'M'}${(L + (p[0] - x0) * sx).toFixed(2)} ${(H - B - (p[1] - y0) * sy).toFixed(2)}`).join('');
      path.setAttribute('d', d);
      setText(q(root, '.sm-cx0'), `${t(c.xLabel)} ${SI(x0, '')}`);
      setText(q(root, '.sm-cx1'), SI(x1, ''));
      setText(q(root, '.sm-cy0'), `${t(c.yLabel)} ${SI(y0, '')}`);
      setText(q(root, '.sm-cy1'), SI(y1, ''));
      setText(q(root, '.sm-chart-cap'), t(c.label));
    },
  };
}
