import { diag, type DiagState } from '../../view3d/diag-store';
import { countOf, type ArgumentReport, type InvalidShape } from '../../view3d/nurbs-api';
import type { DockPanel } from '../dock';
import { el, patchList, q, setClass, setText } from '../dom';
import { t } from '../i18n';
import { buttonRow, infoRow } from './pref-rows';

interface Row { key: string; main: string; sub: string; tone: '' | 'bad' | 'warn' | 'ok' }

const num = (v: number | undefined): string => (v === undefined || v === null ? '' : v === 0 ? '0' : Math.abs(v) < 1e-3 ? v.toExponential(2) : String(Number(v.toPrecision(4))));
const statusText = (list: InvalidShape[] | undefined): string => [...new Set((list ?? []).flatMap((i) => i.statuses ?? []))].join(', ');

function section(title: string, key: string): { root: HTMLElement; list: HTMLElement } {
  const root = el(`<section class="u7-sec"><h4 class="u7-sec-title"></h4><div class="u7-list" data-k="${key}"></div></section>`);
  setText(q(root, 'h4'), t(title));
  return { root, list: q(root, '.u7-list') };
}

function paintRows(list: HTMLElement, rows: Row[], none: string): void {
  const items = rows.length ? rows : [{ key: 'none', main: none, sub: '', tone: '' as const }];
  patchList(list, items, {
    key: (r) => r.key,
    create: () => el('<div class="u7-row"><span class="u7-row-main"></span><span class="u7-row-sub"></span></div>'),
    update: (node, r) => {
      setText(q(node, '.u7-row-main'), r.main);
      setText(q(node, '.u7-row-sub'), r.sub);
      setClass(node, 'is-bad', r.tone === 'bad');
      setClass(node, 'is-warn', r.tone === 'warn');
      setClass(node, 'is-ok', r.tone === 'ok');
      setClass(node, 'is-none', r.key === 'none');
    },
  });
}

function argumentRows(args: ArgumentReport[], resultShape: { invalid?: InvalidShape[]; small_edges?: unknown[]; naked_edges?: unknown } | undefined): Row[] {
  const rows: Row[] = args.map((a, i) => ({
    key: `arg-${i}`,
    main: `${t('Argument')} ${i + 1}${a.valid ? '' : ` · ${statusText(a.invalid) || t('not valid')}`}`,
    sub: `${a.small_edges.length} ${t('small')} · ${countOf(a.naked_edges as never)} ${t('naked')}`,
    tone: a.valid ? '' : 'bad',
  }));
  if (resultShape) {
    const bad = (resultShape.invalid ?? []).length > 0;
    rows.push({ key: 'result', main: `${t('Result')}${bad ? ` · ${statusText(resultShape.invalid)}` : ''}`, sub: `${(resultShape.small_edges ?? []).length} ${t('small')} · ${countOf(resultShape.naked_edges as never)} ${t('naked')}`, tone: bad ? 'bad' : '' });
  }
  return rows;
}

export function boolDiagPanel(reveal: () => void): DockPanel {
  return {
    id: 'bool-diag',
    label: 'Boolean Diagnostics',
    icon: 'csBool',
    order: 40,
    build(body) {
      body.classList.add('u7-diag');
      const head = el('<div class="u7-head"><span class="u7-pill" data-state="none"></span><span class="u7-msg"></span></div>');
      const pill = q(head, '.u7-pill');
      const msg = q(head, '.u7-msg');
      const op = infoRow(t('Operation'));
      const fuzzy = infoRow(t('Fuzzy value used'));
      const tol = infoRow(t('Tolerance'));
      const shapes = section('Shapes checked', 'shapes');
      const selfs = section('Self-intersections', 'self');
      const smalls = section('Small edges', 'small');
      const naked = section('Naked and free edges', 'naked');
      const tries = section('Attempts', 'tries');
      const hl = buttonRow(t('Viewport'), t('Highlight edges'), () => { diag.setHighlight(!diag.state.highlight); }, 'ghost');
      const clear = buttonRow(t('Report'), t('Clear'), () => { diag.clear(); }, 'ghost');
      body.append(head, op.el, fuzzy.el, tol.el, shapes.root, selfs.root, smalls.root, naked.root, tries.root, hl.el, clear.el);
      const paint = (s: DiagState): void => {
        const r = s.report;
        const nk = s.naked;
        if (s.source === 'none') {
          pill.dataset.state = 'none';
          setText(pill, t('No report'));
          setText(msg, t('Run BOOLOP or BOOLCHECK to see the findings here.'));
          op.set('');
          fuzzy.set('');
          tol.set('');
          paintRows(shapes.list, [], t('None'));
          paintRows(selfs.list, [], t('None'));
          paintRows(smalls.list, [], t('None'));
          paintRows(naked.list, [], t('None'));
          paintRows(tries.list, [], t('None'));
          return;
        }
        if (s.source === 'naked' && nk) {
          const n = countOf(nk.naked_edges);
          const bad = (nk.check?.invalid ?? []).length > 0;
          pill.dataset.state = n || bad ? 'fail' : 'pass';
          setText(pill, n || bad ? t('Open or invalid') : t('Closed and valid'));
          setText(msg, `${n} ${t('naked edge polylines')}`);
          op.set(t('Naked edge check'));
          fuzzy.set('');
          tol.set('');
          paintRows(shapes.list, bad ? [{ key: 'inv', main: statusText(nk.check?.invalid), sub: '', tone: 'bad' }] : [], t('None'));
          paintRows(selfs.list, [], t('None'));
          paintRows(smalls.list, (nk.small_edges ?? []).map((e, i) => ({ key: `s${i}`, main: `${t('Edge')} ${(e as { index?: number }).index ?? i}`, sub: `${num((e as { length?: number }).length)} mm`, tone: 'warn' as const })), t('None'));
          paintRows(naked.list, n ? [{ key: 'n', main: `${n} ${t('highlighted in the 3D view')}`, sub: '', tone: 'bad' }] : [], t('None'));
          paintRows(tries.list, [], t('None'));
          return;
        }
        if (!r) return;
        const ok = !!r.ok;
        pill.dataset.state = ok ? 'pass' : 'fail';
        setText(pill, ok ? (s.checkOnly ? t('Checks out') : t('Done')) : t('Failed'));
        setText(msg, r.message ?? (ok ? t('No problems found.') : t('Problems were found in the arguments.')));
        op.set(`${r.op ?? ''}${s.checkOnly ? ` · ${t('check only')}` : ''}`);
        const fz = r.fuzzy_used ?? r.fuzzy;
        fuzzy.set(fz === undefined ? '' : `${num(fz)} mm${r.repaired ? ` · ${t('inputs repaired')}` : ''}`);
        tol.set(r.tol === undefined ? '' : `${num(r.tol)} mm`);
        const args = r.arguments ?? [];
        paintRows(shapes.list, argumentRows(args, r.result as never).filter((x) => x.tone === 'bad' || x.sub.length > 0), t('None'));
        const si = r.analysis?.self_intersections ?? [];
        paintRows(selfs.list, si.map((x, i) => ({ key: `si${i}`, main: x.status.replace(/^BOPAlgo_/, ''), sub: `${x.faulty_first ?? 0} / ${x.faulty_second ?? 0}`, tone: 'bad' as const })), t('None'));
        const smallFound = [...(r.analysis?.small_edges ?? []), ...args.flatMap((a) => a.small_edges), ...(r.result?.small_edges ?? [])];
        paintRows(smalls.list, smallFound.map((e, i) => ({ key: `sm${i}`, main: `${t('Edge')} ${(e as { index?: number }).index ?? i}`, sub: `${num((e as { length?: number }).length)} mm`, tone: 'warn' as const })), t('None'));
        const total = args.reduce((a, x) => a + countOf(x.naked_edges as never), 0) + countOf(r.result?.naked_edges as never);
        paintRows(naked.list, total ? [{ key: 'n', main: `${total} ${t('polylines')}`, sub: s.highlight ? t('shown in the 3D view') : t('hidden'), tone: 'bad' }] : [], t('None'));
        paintRows(tries.list, (r.ladder ?? []).map((l, i) => ({ key: `l${i}`, main: l.step, sub: `${num(l.fuzzy)} mm · ${l.has_errors ? t('errors') : t('no errors')}`, tone: l.has_errors ? 'bad' as const : 'ok' as const })), t('None'));
      };
      diag.onChange((s) => {
        paint(s);
        setText(hl.button, s.highlight ? t('Hide highlight') : t('Show highlight'));
      });
      paint(diag.state);
      setText(hl.button, t('Hide highlight'));
      let seen = diag.state.stamp;
      diag.onChange((s) => {
        if (s.stamp === seen) return;
        seen = s.stamp;
        if (s.source !== 'none') reveal();
      });
    },
  };
}
