import { pickPath } from '../ui/file-dialogs';
import { t } from '../ui/i18n';
import { toast } from '../ui/toast';
import {
  arr, button, buttons, checkCtl, docApi, dockPanel, f3, guard, msgLine, nn, numberCtl, obj, reportBox, section, selectCtl, str, table, textCtl,
  type Json, type TRow,
} from './kit';

const SCOPES: Array<readonly [string, string]> = [['auto', 'Automatic'], ['part', 'This part'], ['assembly', 'Whole assembly']];
const PROCESSES: Array<readonly [string, string]> = [['', 'Chosen per part'], ['machining', 'Machining'], ['sheet_metal', 'Sheet metal'], ['additive', 'Additive'], ['molding', 'Molding']];
const RATE_PROCS: Array<readonly [string, string]> = [['machining', 'Machining'], ['sheet_metal', 'Sheet metal'], ['additive', 'Additive'], ['purchased', 'Purchased']];

const query = (scope: string, process: string, extra = ''): string => `scope=${encodeURIComponent(scope)}${process ? `&process=${encodeURIComponent(process)}` : ''}${extra}`;

const findingRows = (list: Json[]): TRow[] => list.map((f, i) => ({
  key: `${i}`, cells: [str(f.severity), str(f.part), str(f.message)], tone: str(f.severity === 'error' ? 'fail' : f.severity === 'warning' ? 'partial' : ''),
}));

export const costSpec = (): ReturnType<typeof dockPanel> => dockPanel({
  id: 'cost', label: 'Cost and DFM', icon: 'cost', order: 50, note: 'Open a part or assembly to estimate cost.', need: () => true,
  build(live) {
    let lines: Json[] = [];
    let rowsData: Json[] = [];
    let profile: Json = {};
    let dfmRules: Json = {};
    let ruleSel = '';

    const sEst = section('Estimate');
    const scope = selectCtl('Scope', SCOPES);
    const proc = selectCtl('Process', PROCESSES);
    const batch = numberCtl('Batch size', 100);
    const volume = numberCtl('Production volume', 1000);
    const eTab = table([{ key: 'part', label: 'Part' }, { key: 'qty', label: 'Qty', w: '30px', right: true }, { key: 'proc', label: 'Process', w: '70px' }, { key: 'unit', label: 'Unit', w: '56px', right: true }], 120);
    const lTab = table([{ key: 'l', label: 'Cost line', w: '110px' }, { key: 'a', label: 'Amount', w: '56px', right: true }, { key: 'b', label: 'Basis' }], 150);
    const eRep = reportBox(4);
    sEst.body.append(scope.el, proc.el, batch.el, volume.el, buttons(button('Estimate', () => { void load(); }, 'primary')), eTab.el, lTab.el, eRep.el);

    const sRate = section('Rates and prices');
    const cur = textCtl('Currency');
    const scrap = numberCtl('Scrap fraction', 0.05);
    const price = numberCtl('Default price per kg', 3);
    const dens = numberCtl('Fallback density (kg per m3)', 0);
    const rProc = selectCtl('Process rates for', RATE_PROCS);
    const rate = numberCtl('Machine rate per hour', 0);
    const setup = numberCtl('Setup hours', 0);
    const labour = numberCtl('Labour per hour', 0);
    const over = numberCtl('Overhead percent', 0);
    const marg = numberCtl('Margin percent', 0);
    const rMsg = msgLine();
    sRate.body.append(cur.el, scrap.el, price.el, dens.el, rProc.el, rate.el, setup.el, labour.el, over.el, marg.el, rMsg.el,
      buttons(button('Save rates', () => { void saveRates(); }, 'primary'), button('Reset to examples', () => { void resetRates(); })));
    rProc.input.addEventListener('change', () => { paintProc(); });

    const sDfm = section('DFM checks');
    const dTab = table([{ key: 's', label: 'Level', w: '56px' }, { key: 'p', label: 'Part', w: '90px' }, { key: 'm', label: 'Finding' }], 150);
    const dRep = reportBox(2);
    const tTab = table([{ key: 'k', label: 'Threshold' }, { key: 'v', label: 'Value', w: '56px', right: true }, { key: 's', label: 'Source' }], 110);
    const tVal = numberCtl('Threshold value', 0);
    sDfm.body.append(buttons(button('Run DFM checks', () => { void runDfm(); }, 'primary')), dTab.el, dRep.el, tTab.el, tVal.el, buttons(button('Set threshold', () => { void setThreshold(); })));

    const sSus = section('Sustainability');
    const sTab = table([{ key: 'p', label: 'Part' }, { key: 'm', label: 'Mass kg', w: '56px', right: true }, { key: 'f', label: 'Factor', w: '50px', right: true }, { key: 'c', label: 'kg CO2e', w: '58px', right: true }], 120);
    const sRep = reportBox(4);
    const fName = textCtl('Material');
    const fVal = numberCtl('kg CO2e per kg', 0);
    const fSrc = textCtl('Source of this factor');
    const fTab = table([{ key: 'n', label: 'Material' }, { key: 'v', label: 'Factor', w: '56px', right: true }, { key: 's', label: 'Source' }], 90);
    sSus.body.append(buttons(button('Calculate', () => { void runSus(); }, 'primary')), sTab.el, sRep.el, fTab.el, fName.el, fVal.el, fSrc.el,
      buttons(button('Set factor', () => { void setFactor(); }, 'primary'), button('Import CSV', () => { void importFactors(); }), button('Remove factor', () => { void delFactor(); }, 'danger')));
    let factors: Json = {};

    const sOut = section('Report');
    const withDfm = checkCtl('Include DFM findings', true);
    sOut.body.append(withDfm.el, buttons(button('Export report', () => { void exportReport(); }, 'primary')));

    live.append(sEst.root, sRate.root, sDfm.root, sSus.root, sOut.root);

    const opts = (): string => query(scope.get(), proc.get(), `&batch=${batch.get() ?? 100}&volume=${volume.get() ?? 1000}`);

    function paintProc(): void {
      const p = obj(obj(profile.processes)[rProc.get()]);
      rate.set(nn(p.rate_per_h)); setup.set(nn(p.setup_h)); labour.set(nn(p.labour_per_h)); over.set(nn(p.overhead_pct)); marg.set(nn(p.margin_pct));
    }

    async function saveRates(): Promise<void> {
      const body: Json = {
        currency: cur.get() || 'USD', scrap: scrap.get() ?? 0.05, default_price_per_kg: price.get() ?? 3, batch: batch.get() ?? 100, volume: volume.get() ?? 1000,
        processes: { [rProc.get()]: { rate_per_h: rate.get() ?? 0, setup_h: setup.get() ?? 0, labour_per_h: labour.get() ?? 0, overhead_pct: over.get() ?? 0, margin_pct: marg.get() ?? 0 } },
      };
      const d = dens.get();
      if (d) body.fallback_density = d;
      const r = await guard(() => docApi('PUT', 'costing/profile', body));
      rMsg.set(r ? t('Rates saved.') : t('The rates were refused.'), !r);
      if (r) await load();
    }

    async function resetRates(): Promise<void> { await guard(() => docApi('DELETE', 'costing/profile')); await load(); }

    async function runDfm(): Promise<void> {
      const r = await guard(() => docApi('GET', `costing/dfm?${query(scope.get(), proc.get())}`));
      if (!r) return;
      const all: Json[] = [];
      for (const p of arr(r.parts)) for (const f of arr(p.findings)) all.push({ ...f, part: str(f.part) || str(p.part) });
      const sm = obj(r.summary);
      dTab.set(findingRows(all));
      dTab.empty(all.length ? '' : t('No DFM findings.'));
      const skipped = arr(r.parts).flatMap((p) => (Array.isArray(p.skipped) ? p.skipped as string[] : []));
      dRep.set([`${nn(sm.errors)} ${t('errors')}, ${nn(sm.warnings)} ${t('warnings')}, ${nn(sm.info)} ${t('notes')}`, skipped[0] ?? '']);
    }

    async function setThreshold(): Promise<void> {
      const v = tVal.get();
      if (!ruleSel || v === null) return;
      await guard(() => docApi('PUT', 'costing/dfm/rules', { [ruleSel]: v }));
      await load();
    }

    tTab.pick((k) => { ruleSel = k; tVal.set(nn(obj(dfmRules[k]).value)); });

    async function runSus(): Promise<void> {
      const r = await guard(() => docApi('GET', `costing/sustainability?${query(scope.get(), proc.get())}`));
      if (!r) return;
      const rows = arr(r.rows);
      sTab.set(rows.map((x, i) => ({ key: `${i}`, cells: [`${str(x.part)} x${nn(x.qty)}`, f3(nn(x.mass_kg), 4), x.factor === null ? '-' : f3(nn(x.factor), 3), x.kg_co2e === null ? '-' : f3(nn(x.kg_co2e), 4)] })));
      sTab.empty(rows.length ? '' : t('No parts.'));
      const miss = arr(r.missing as unknown as Json[]).length ? (r.missing as unknown as string[]) : (Array.isArray(r.missing) ? r.missing as string[] : []);
      const caveats = Array.isArray(r.caveats) ? r.caveats as string[] : [];
      sRep.set([`${t('Total')}: ${f3(nn(r.total_kg_co2e), 4)} kg CO2e`, `${t('Missing')}: ${miss.length}${miss[0] ? ` - ${miss[0]}` : ''}`, caveats[0] ?? '', caveats[1] ?? ''], miss.length > 0);
    }

    async function setFactor(): Promise<void> {
      const n = fName.get(); const v = fVal.get();
      if (!n || v === null) { toast(t('Give a material and a factor.'), 'error'); return; }
      const next = { ...factors, [n]: { kg_co2e_per_kg: v, source: fSrc.get() } };
      await guard(() => docApi('PUT', 'costing/emissions', { factors: next }));
      await load();
    }

    async function delFactor(): Promise<void> {
      const n = fName.get();
      if (!n || !(n in factors)) return;
      const next = { ...factors };
      delete next[n];
      await guard(() => docApi('PUT', 'costing/emissions', { factors: next }));
      await load();
    }

    async function importFactors(): Promise<void> {
      const p = await pickPath('open', t('Choose an emission factor table'), '', [{ name: 'CSV table', extensions: ['csv'] }], t('Choose'));
      if (!p) return;
      const r = await guard(() => docApi('PUT', 'costing/emissions/import', { path: p }));
      if (r) { toast(`${nn(r.imported)} ${t('factors imported')}`, 'info'); await load(); }
    }

    fTab.pick((k) => { fName.set(k); const f = obj(factors[k]); fVal.set(nn(f.kg_co2e_per_kg)); fSrc.set(str(f.source)); });

    async function exportReport(): Promise<void> {
      const p = await pickPath('save', t('Save the cost report'), 'cost-report.html', [{ name: 'HTML page', extensions: ['html'] }, { name: 'CSV table', extensions: ['csv'] }, { name: 'JSON data', extensions: ['json'] }], t('Save'));
      if (!p) return;
      const r = await guard(() => docApi('POST', 'costing/export', { path: p, scope: scope.get(), process: proc.get(), batch: batch.get(), volume: volume.get(), dfm: withDfm.get() }));
      if (r) toast(`${t('Report written')}: ${str(r.path)}`, 'info');
    }

    eTab.pick((k) => {
      const r = rowsData.find((x) => str(x.part) === k);
      lines = arr(obj(r?.cost).lines);
      paintLines();
    });

    function paintLines(): void {
      lTab.set(lines.map((l) => ({ key: str(l.key), cells: [str(l.label), f3(nn(l.amount), 4), str(l.basis)] })));
      lTab.empty(lines.length ? '' : t('Pick a part to see its cost lines.'));
    }

    async function load(): Promise<void> {
      const [est, prof, rules, em] = await Promise.all([
        docApi('GET', `costing/estimate?${opts()}`), docApi('GET', 'costing/profile'), docApi('GET', 'costing/dfm/rules'), docApi('GET', 'costing/emissions'),
      ]);
      rowsData = arr(est.rows);
      const cur0 = str(est.currency);
      eTab.set(rowsData.map((r) => ({ key: str(r.part), cells: [str(r.part), String(nn(r.qty)), str(obj(r.cost).process), f3(nn(obj(r.cost).unit_cost), 3)] })));
      eTab.empty(rowsData.length ? '' : t('No parts to estimate.'));
      const warn = Array.isArray(est.warnings) ? est.warnings as string[] : [];
      eRep.set([`${t('Total')}: ${f3(nn(est.total), 3)} ${cur0}${est.placeholder ? ` (${t('example rates')})` : ''}`, `${nn(est.parts)} ${t('distinct parts')}, ${nn(est.units)} ${t('units')}`, `${t('Batch')} ${nn(est.batch)}, ${t('volume')} ${nn(est.volume)}`, warn[0] ?? ''], warn.length > 0);
      lines = lines.length ? lines : [];
      paintLines();
      profile = obj(prof.profile);
      cur.set(str(profile.currency)); scrap.set(nn(profile.scrap, 0.05)); price.set(nn(profile.default_price_per_kg, 3)); dens.set(nn(profile.fallback_density));
      paintProc();
      dfmRules = obj(rules.rules);
      tTab.set(Object.entries(dfmRules).map(([k, v]) => ({ key: k, cells: [k, f3(nn(obj(v).value), 3), str(obj(v).source)] })));
      factors = obj(obj(em.table).factors);
      fTab.set(Object.entries(factors).map(([k, v]) => ({ key: k, cells: [k, f3(nn(obj(v).kg_co2e_per_kg), 3), str(obj(v).source)] })));
      fTab.empty(Object.keys(factors).length ? '' : t('No factors: none ship; enter your own or import a CSV.'));
    }

    return { load };
  },
});

const KIND_FIELDS: Record<string, Array<readonly [string, string, 'text' | 'num']>> = {
  property_required: [['key', 'Property name', 'text']],
  property_matches: [['key', 'Property name', 'text'], ['equals', 'Must equal', 'text'], ['glob', 'Pattern with * and ?', 'text']],
  units: [['expect', 'Unit (mm, cm, m, in, ft)', 'text']],
  name_pattern: [['target', 'Names of (feature, body, sketch, component)', 'text'], ['glob', 'Pattern', 'text']],
  feature_forbidden: [['types', 'Feature types, comma separated', 'text']],
  feature_min_value: [['type', 'Feature type', 'text'], ['param', 'Parameter', 'text'], ['min', 'Minimum', 'num']],
  feature_max_count: [['type', 'Feature type', 'text'], ['max', 'Most allowed', 'num']],
  body_count: [['min', 'Least bodies', 'num'], ['max', 'Most bodies', 'num']],
  mass_max: [['kg', 'Most kilograms', 'num']],
  bbox_max: [['mm', 'Longest side (mm)', 'num']],
  closed_solids: [],
  material_set: [['one_of', 'Allowed materials, comma separated', 'text']],
  min_wall: [['mm', 'Thinnest wall (mm)', 'num']],
  min_hole_diameter: [['mm', 'Smallest hole (mm)', 'num']],
};

export const checkSpec = (): ReturnType<typeof dockPanel> => dockPanel({
  id: 'check', label: 'Design check', icon: 'check', order: 51, note: 'Open a part or assembly to check it against rules.', need: () => true,
  build(live) {
    let rules: Json[] = [];
    let kinds: Json = {};
    let sel = '';

    const sRun = section('Findings');
    const scope = selectCtl('Scope', SCOPES);
    const fTab = table([{ key: 's', label: 'Level', w: '56px' }, { key: 'p', label: 'Part', w: '90px' }, { key: 'm', label: 'Finding' }], 190);
    const fRep = reportBox(2);
    sRun.body.append(scope.el, buttons(button('Run design check', () => { void run(); }, 'primary')), fTab.el, fRep.el);

    const sRules = section('Rules');
    const rTab = table([{ key: 'id', label: 'Id', w: '52px' }, { key: 'kind', label: 'Rule' }, { key: 'sev', label: 'Level', w: '56px' }, { key: 'on', label: 'On', w: '30px' }], 120);
    const kind = selectCtl('Rule kind', Object.keys(KIND_FIELDS).map((k) => [k, k.replace(/_/g, ' ')] as const));
    const kindText = reportBox(2);
    const rid = textCtl('Rule id');
    const rlabel = textCtl('Label');
    const sev = selectCtl('Level', [['error', 'Error'], ['warning', 'Warning'], ['info', 'Note']]);
    const rOn = checkCtl('Enabled', true);
    const fields = Array.from({ length: 3 }, (_, i) => textCtl(`Field ${i}`));
    const rMsg = msgLine();
    sRules.body.append(rTab.el, kind.el, kindText.el, rid.el, rlabel.el, sev.el, rOn.el, ...fields.map((f) => f.el), rMsg.el,
      buttons(button('Save rule', () => { void save(); }, 'primary'), button('Remove rule', () => { void remove(); }, 'danger')));

    live.append(sRun.root, sRules.root);

    const spec = (): ReadonlyArray<readonly [string, string, 'text' | 'num']> => KIND_FIELDS[kind.get()] ?? [];
    const paintKind = (): void => {
      fields.forEach((f, i) => {
        const s = spec()[i];
        f.el.hidden = !s;
        const span = f.el.querySelector('span');
        if (s && span && span.textContent !== t(s[1])) span.textContent = t(s[1]);
      });
      const text = str(kinds[kind.get()]);
      kindText.set([text, '']);
    };
    kind.input.addEventListener('change', paintKind);

    rTab.pick((k) => {
      sel = k;
      const r = rules.find((x) => str(x.id) === k);
      if (!r) return;
      kind.set(str(r.kind)); paintKind();
      rid.set(str(r.id)); rlabel.set(str(r.label) === str(r.id) ? '' : str(r.label)); sev.set(str(r.severity)); rOn.set(r.enabled !== false);
      spec().forEach((s, i) => { const v = r[s[0]]; fields[i].set(Array.isArray(v) ? v.join(', ') : v === undefined || v === null ? '' : String(v)); });
    });

    const ruleFromForm = (): Json | null => {
      const o: Json = { id: rid.get() || `R${rules.length + 1}`, kind: kind.get(), severity: sev.get(), enabled: rOn.get() };
      if (rlabel.get()) o.label = rlabel.get();
      for (let i = 0; i < spec().length; i++) {
        const [k, , type] = spec()[i];
        const raw = fields[i].get();
        if (!raw) { if (type === 'num' || k === 'key' || k === 'expect' || k === 'type' || k === 'param' || k === 'target') { rMsg.set(`${t('Fill in')}: ${t(spec()[i][1])}`, true); return null; } continue; }
        if (type === 'num') { const n = Number(raw.replace(',', '.')); if (!Number.isFinite(n)) { rMsg.set(`${t('Needs a number')}: ${t(spec()[i][1])}`, true); return null; } o[k] = n; }
        else if (k === 'types' || k === 'one_of') o[k] = raw.split(',').map((s) => s.trim()).filter(Boolean);
        else o[k] = raw;
      }
      rMsg.set('');
      return o;
    };

    async function save(): Promise<void> {
      const o = ruleFromForm();
      if (!o) return;
      const next = [...rules.filter((r) => str(r.id) !== str(o.id)), o];
      const r = await guard(() => docApi('PUT', 'costing/rules', { rules: next }));
      if (r) { sel = str(o.id); await load(); }
    }

    async function remove(): Promise<void> {
      if (!sel) return;
      await guard(() => docApi('PUT', 'costing/rules', { rules: rules.filter((r) => str(r.id) !== sel) }));
      sel = '';
      await load();
    }

    async function run(): Promise<void> {
      const r = await guard(() => docApi('GET', `costing/check?${query(scope.get(), '')}`));
      if (!r) return;
      const list = arr(r.findings);
      fTab.set(findingRows(list));
      fTab.empty(list.length ? '' : t('No findings.'));
      const s = obj(r.summary);
      fRep.set([`${r.ok ? t('Passed') : t('Not passed')}: ${nn(s.errors)} ${t('errors')}, ${nn(s.warnings)} ${t('warnings')}, ${nn(s.info)} ${t('notes')}`, `${nn(r.enabled)} ${t('of')} ${nn(r.rules)} ${t('rules on')}, ${arr(r.parts as unknown as Json[]).length || (Array.isArray(r.parts) ? r.parts.length : 0)} ${t('parts')}`], !r.ok);
    }

    async function load(): Promise<void> {
      const r = await docApi('GET', 'costing/rules');
      rules = arr(r.rules);
      kinds = obj(r.kinds);
      rTab.set(rules.map((x) => ({ key: str(x.id), cells: [str(x.id), str(x.kind).replace(/_/g, ' '), str(x.severity), x.enabled === false ? 'no' : 'yes'] })));
      rTab.empty(rules.length ? '' : t('No rules yet: add one below.'));
      paintKind();
      await run();
    }

    return { load };
  },
});
