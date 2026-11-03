import { t } from '../ui/i18n';
import { toast } from '../ui/toast';
import { view3d } from '../view3d/mount';
import {
  arr, button, buttons, checkCtl, docApi, dockPanel, f3, guard, msgLine, nn, numberCtl, obj, reportBox, rowOf, section, selectCtl,
  str, table, vecCtl, mini, type Json,
} from './kit';
import { moldState, type DraftClass } from './mold-layer';

const AXES: Array<[string, number[]]> = [['+X', [1, 0, 0]], ['-X', [-1, 0, 0]], ['+Y', [0, 1, 0]], ['-Y', [0, -1, 0]], ['+Z', [0, 0, 1]], ['-Z', [0, 0, -1]]];

export const moldSpec = (): ReturnType<typeof dockPanel> => dockPanel({
  id: 'mold', label: 'Mold tools', icon: 'mold', order: 47, note: 'Open a part to analyse a mold.', need: () => true,
  build(live) {
    let settings: Json = {};
    let faces: Json[] = [];
    let body: number | null = null;

    const sSet = section('Settings');
    const pull = vecCtl('Pull direction', [0, 0, 1]);
    const axisRow = rowOf(...AXES.map(([l, v]) => mini(l, `Pull along ${l}`, () => pull.set(v))));
    axisRow.classList.add('p15-axes');
    const minDraft = numberCtl('Minimum draft (deg)', 0.5);
    const grid = numberCtl('Sample grid (2 to 12)', 5);
    const height = numberCtl('Parting height (blank is automatic)', 0);
    const margin = numberCtl('Block margin (blank is automatic)', 0);
    const shrink = numberCtl('Shrinkage (percent)', 0);
    const conv = selectCtl('Shrinkage convention', [['multiply', 'Multiply by 1 + s'], ['divide', 'Divide by 1 - s']]);
    const bodyLine = msgLine();
    const setMsg = msgLine();
    sSet.body.append(pull.el, axisRow, minDraft.el, grid.el, height.el, margin.el, shrink.el, conv.el, bodyLine.el, setMsg.el,
      buttons(button('Use selected body', () => { useSelected(); }), button('Apply', () => { void apply(); }, 'primary'), button('Reset', () => { void reset(); })));

    const sAn = section('Analysis');
    const summary = reportBox(4);
    const show = checkCtl('Show draft colours', true, () => { moldState.layer?.setShown(show.get()); });
    const fTab = table([{ key: 'face', label: 'Face', w: '40px' }, { key: 'kind', label: 'Kind', w: '64px' }, { key: 'cls', label: 'Class', w: '64px' }, { key: 'draft', label: 'Draft', w: '56px', right: true }, { key: 'area', label: 'Area', w: '62px', right: true }], 150);
    const legend = rowOf();
    legend.className = 'p15-legend';
    for (const [c, label] of [['ok', 'Draft enough'], ['steep', 'Low draft'], ['undercut', 'Undercut']]) { const s = document.createElement('span'); s.className = `p15-key is-${c}`; s.textContent = t(label); legend.appendChild(s); }
    sAn.body.append(buttons(button('Analyse draft and undercuts', () => { void analyse(); }, 'primary')), summary.el, legend, show.el, fTab.el);

    const sPart = section('Parting line');
    const partRep = reportBox(5);
    sPart.body.append(buttons(button('Find parting line', () => { void parting(); }, 'primary')), partRep.el);

    const sSplit = section('Block and split');
    const keepB = checkCtl('Keep the block body', false);
    const keepP = checkCtl('Keep the part body', true);
    const splitRep = reportBox(6);
    sSplit.body.append(keepB.el, keepP.el, buttons(button('Make block', () => { void block(); }), button('Split core and cavity', () => { void split(); }, 'primary'), button('Erase mold bodies', () => { void clear(); }, 'danger')), splitRep.el);

    live.append(sSet.root, sAn.root, sPart.root, sSplit.root);

    const useSelected = (): void => {
      const s = view3d()?.vp?.sel;
      const id = s?.bodies[0] ?? s?.faces[0]?.body;
      if (id === undefined) { toast(t('Select a body in the view first.'), 'info'); return; }
      body = id;
      bodyLine.set(`${t('Body')} ${id}`);
    };

    const sendBody = (): Json => ({ ...(body !== null ? { body } : {}) });

    const paintSettings = (s: Json): void => {
      settings = s;
      const p = s.pull;
      if (Array.isArray(p)) pull.set(p as number[]);
      if (typeof s.min_draft === 'number') minDraft.set(s.min_draft);
      if (typeof s.grid === 'number') grid.set(s.grid);
      height.set(typeof s.height === 'number' ? s.height : null);
      margin.set(typeof s.margin === 'number' ? s.margin : null);
      const sh = obj(s.shrink);
      const pc = Array.isArray(sh.percent) ? (sh.percent as number[])[0] : sh.percent;
      shrink.set(typeof pc === 'number' ? pc : 0);
      conv.set(str(sh.convention) || 'multiply');
      if (body === null && typeof s.body === 'number') body = s.body;
      bodyLine.set(body !== null ? `${t('Body')} ${body}` : t('Body: automatic (the only solid)'));
    };

    async function apply(): Promise<void> {
      const pv = pull.get();
      if (!pv) { setMsg.set(t('The pull direction needs three numbers.'), true); return; }
      const h = height.get(); const m = margin.get();
      const r = await guard(() => docApi<{ settings: Json }>('PUT', 'mold/settings', {
        pull: pv, min_draft: minDraft.get() ?? 0.5, grid: Math.round(grid.get() ?? 5), height: h === null || h === 0 ? null : h,
        margin: m === null || m === 0 ? null : m, shrink: { percent: shrink.get() ?? 0, convention: conv.get(), origin: null }, ...sendBody(),
      }));
      if (r) { setMsg.set(t('Settings saved.')); paintSettings(r.settings); }
    }

    async function reset(): Promise<void> { await guard(() => docApi('DELETE', 'mold/settings')); body = null; await load(); }

    const classFaces = (list: Json[]): Record<DraftClass, number[]> => {
      const out: Record<DraftClass, number[]> = { ok: [], steep: [], undercut: [] };
      for (const f of list) { const c = str(f.class) as DraftClass; if (c in out && typeof f.face === 'number') out[c].push(f.face); }
      return out;
    };

    async function analyse(): Promise<void> {
      await apply();
      const r = await guard(() => docApi('POST', 'mold/analyze', {}));
      if (!r) return;
      faces = arr(r.faces);
      const pct = obj(r.percent_by_class);
      summary.set([
        `${t('Faces')}: ${faces.length}, ${t('area')} ${f3(nn(r.area), 1)}`,
        `${t('Draft enough')}: ${f3(nn(pct.ok), 1)} %, ${t('Low draft')}: ${f3(nn(pct.steep), 1)} %`,
        `${t('Undercut')}: ${f3(nn(pct.undercut), 1)} % (${arr(r.undercut_faces).length} ${t('faces')})`,
        r.ok ? t('No undercuts. The part can be pulled.') : t('Check the red and yellow faces.'),
      ], !r.ok);
      fTab.set(faces.map((f) => ({ key: String(nn(f.face)), cells: [String(nn(f.face)), str(f.kind), str(f.class), f3(nn(f.draft_min), 1), f3(nn(f.area), 1)], tone: str(f.class) })));
      fTab.empty(faces.length ? '' : t('No faces.'));
      const bid = typeof r.body === 'number' ? r.body : body;
      if (bid !== null && moldState.layer) { moldState.layer.set(bid, classFaces(faces)); moldState.layer.setShown(show.get()); }
    }

    async function parting(): Promise<void> {
      const r = await guard(() => docApi('POST', 'mold/parting', {}));
      if (!r) return;
      const wires = arr(r.wires);
      const holes = arr(r.through_holes);
      partRep.set([
        `${t('Height')}: ${f3(nn(r.height), 3)} (${str(r.height_source)})`,
        `${t('Planar')}: ${r.planar ? t('yes') : t('no')}, ${t('spread')} ${f3(nn(r.spread), 3)}`,
        `${t('Parting loops')}: ${wires.length}, ${t('length')} ${f3(wires.reduce((a, w) => a + nn(w.length), 0), 2)}`,
        `${t('Through holes')}: ${holes.length}`,
        arr(r.notes).map((n) => str(n)).join(' ') || str(r.wrong_side),
      ]);
    }

    function checkLines(c: Json): string[] {
      return [
        `${t('Block')} ${f3(nn(c.block), 3)}`, `${t('Part')} ${f3(nn(c.part), 3)}`, `${t('Core')} ${f3(nn(c.core), 3)}, ${t('cavity')} ${f3(nn(c.cavity), 3)}`,
        `${t('Sum')} ${f3(nn(c.sum), 3)}`, `${t('Residual')} ${nn(c.residual).toExponential(2)}, ${t('overlap')} ${f3(nn(c.overlap), 3)}`,
        c.ok ? t('Volume check passed.') : t('Volume check failed.'),
      ];
    }

    async function block(): Promise<void> {
      const r = await guard(() => docApi('POST', 'mold/block', {}));
      if (r) splitRep.set([`${t('Block made')}: ${f3(nn(r.volume), 3)}`]);
    }

    async function split(): Promise<void> {
      await apply();
      const r = await guard(() => docApi('POST', 'mold/split', { keep_block: keepB.get(), keep_part: keepP.get() }));
      if (!r) return;
      const c = obj(r.check);
      splitRep.set(checkLines(c), !c.ok);
      moldState.layer?.clear();
    }

    async function clear(): Promise<void> {
      await guard(() => docApi('DELETE', 'mold/products'));
      splitRep.set([t('Mold bodies erased.')]);
    }

    async function load(): Promise<void> {
      const r = await docApi('GET', 'mold');
      paintSettings(obj(r.settings));
      const split0 = obj(obj(r.result).split);
      if (Object.keys(split0).length && obj(split0.check).ok !== undefined) splitRep.set(checkLines(obj(split0.check)), !obj(split0.check).ok);
    }

    return { load };
  },
});
