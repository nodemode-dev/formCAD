import { pickPath } from '../ui/file-dialogs';
import { t } from '../ui/i18n';
import { toast } from '../ui/toast';
import {
  arr, button, buttons, checkCtl, docApi, dockPanel, f3, fillSelect, guard, msgLine, nn, numberCtl, obj, reportBox, section, selectCtl, str,
  table, textCtl, type Json,
} from './kit';

const CLASSES: Array<readonly [string, string]> = [['', 'No class'], ['critical', 'Critical'], ['major', 'Major'], ['minor', 'Minor'], ['key', 'Key']];

export const inspectSpec = (): ReturnType<typeof dockPanel> => dockPanel({
  id: 'inspect', label: 'Inspection', icon: 'inspect', order: 49, note: 'Open a part, assembly or drawing to inspect.', need: () => true,
  build(live) {
    let items: Json[] = [];
    let views: Json[] = [];
    let sel = '';
    let viewSel = '';

    const sItems = section('Characteristics');
    const tab = table([{ key: 'n', label: 'No', w: '30px', right: true }, { key: 'label', label: 'Characteristic' }, { key: 'req', label: 'Requirement', w: '92px' }, { key: 'act', label: 'Actual', w: '56px', right: true }, { key: 'res', label: 'Result', w: '50px' }], 176);
    const msg = msgLine();
    sItems.body.append(tab.el, msg.el, buttons(button('Collect from PMI and dimensions', () => { void act('collect'); }, 'primary'), button('Renumber', () => { void act('renumber'); }), button('Place balloons', () => { void act('balloons'); })));

    const sEdit = section('Selected characteristic');
    const eLabel = textCtl('Label');
    const eNom = numberCtl('Nominal', 0);
    const ePlus = numberCtl('Plus', 0);
    const eMinus = numberCtl('Minus', 0);
    const eUnit = textCtl('Unit', 'mm');
    const eCls = selectCtl('Class', CLASSES);
    const eAct = textCtl('Actual values (comma separated)');
    const eKind = selectCtl('Kind', [['dimension', 'Dimension'], ['tolerance', 'Tolerance'], ['note', 'Note']]);
    sEdit.body.append(eKind.el, eLabel.el, eNom.el, ePlus.el, eMinus.el, eUnit.el, eCls.el, eAct.el,
      buttons(button('Add new', () => { void add(); }, 'primary'), button('Update selected', () => { void update(); }), button('Delete', () => { void del(); }, 'danger')));

    const sRep = section('Report');
    const pn = textCtl('Part number');
    const pname = textCtl('Part name');
    const rev = textCtl('Revision');
    const org = textCtl('Organisation');
    const rep = reportBox(4);
    sRep.body.append(pn.el, pname.el, rev.el, org.el, buttons(button('Save form', () => { void saveForm(); })), rep.el,
      buttons(button('Export report', () => { void exportReport(); }, 'primary'), button('Import results CSV', () => { void importResults(); })));

    const sMbd = section('Model-based views');
    const vTab = table([{ key: 'name', label: 'View' }, { key: 'cam', label: 'Camera', w: '64px' }, { key: 'n', label: 'Items', w: '44px', right: true }], 96);
    const vName = textCtl('View name');
    const vCam = selectCtl('Camera', []);
    const vBal = checkCtl('Show balloons', false);
    const mbdRep = reportBox(4);
    sMbd.body.append(vTab.el, vName.el, vCam.el, vBal.el,
      buttons(button('Add view', () => { void addView(); }, 'primary'), button('Assign by facing', () => { void assign(); }), button('Delete view', () => { void delView(); }, 'danger')), mbdRep.el);

    live.append(sItems.root, sEdit.root, sRep.root, sMbd.root);

    async function act(what: string): Promise<void> {
      const r = await guard(() => docApi('POST', `inspection/${what}`, what === 'renumber' ? {} : undefined));
      if (!r) return;
      msg.set(what === 'collect' ? `${nn(r.added)} ${t('added')}, ${nn(r.updated)} ${t('updated')}, ${nn(r.lost)} ${t('lost')}` : what === 'balloons' ? `${t('Balloons')}: ${nn(r.placed, nn(r.count))}` : t('Renumbered.'));
    }

    const requirement = (i: Json): string => {
      const lo = i.lower; const up = i.upper;
      if (typeof lo === 'number' && typeof up === 'number') return `${f3(lo, 3)} to ${f3(up, 3)}`;
      return typeof i.nominal === 'number' ? f3(i.nominal, 3) : '';
    };

    const fromForm = (): Json => {
      const o: Json = { label: eLabel.get(), unit: eUnit.get() || 'mm', class: eCls.get() };
      const nom = eNom.get(); const pl = ePlus.get(); const mi = eMinus.get();
      if (nom !== null) o.nominal = nom;
      if (pl !== null) o.plus = pl;
      if (mi !== null) o.minus = mi;
      const a = eAct.get();
      if (a) o.actuals = a.split(/[,;\s]+/).filter(Boolean).map(Number).filter((n) => Number.isFinite(n));
      return o;
    };

    async function add(): Promise<void> {
      const o = fromForm();
      if (!o.label) { msg.set(t('Give the characteristic a label.'), true); return; }
      await guard(() => docApi('POST', 'inspection', { ...o, kind: eKind.get() }));
    }

    async function update(): Promise<void> {
      if (!sel) return;
      await guard(() => docApi('PATCH', `inspection/${encodeURIComponent(sel)}`, fromForm()));
    }

    async function del(): Promise<void> {
      if (!sel) return;
      await guard(() => docApi('DELETE', `inspection/${encodeURIComponent(sel)}`));
      sel = '';
    }

    async function saveForm(): Promise<void> {
      const f: Record<string, string> = {};
      for (const [k, c] of [['Part number', pn], ['Part name', pname], ['Revision', rev], ['Organisation', org]] as const) if (c.get()) f[k] = c.get();
      await guard(() => docApi('PUT', 'inspection/form', { form1: f }));
    }

    async function exportReport(): Promise<void> {
      const p = await pickPath('save', t('Save the inspection report'), 'inspection-report.html', [{ name: 'HTML page', extensions: ['html'] }, { name: 'CSV table', extensions: ['csv'] }], t('Save'));
      if (!p) return;
      const r = await guard(() => docApi('POST', 'inspection/export', { file: p }));
      if (r) toast(`${t('Report written')}: ${str(r.path)}`, 'info');
    }

    async function importResults(): Promise<void> {
      const p = await pickPath('open', t('Choose a results table'), '', [{ name: 'CSV table', extensions: ['csv', 'txt'] }], t('Choose'));
      if (!p) return;
      const r = await guard(() => docApi('POST', 'inspection/import', { file: p }));
      if (r) msg.set(`${t('Results imported')}: ${nn(r.updated, nn(r.matched))}`);
    }

    tab.pick((k) => {
      sel = k;
      const i = items.find((x) => str(x.id) === k);
      if (!i) return;
      eLabel.set(str(i.label)); eNom.set(typeof i.nominal === 'number' ? i.nominal : null); ePlus.set(typeof i.plus === 'number' ? i.plus : null); eMinus.set(typeof i.minus === 'number' ? i.minus : null);
      eUnit.set(str(i.unit)); eCls.set(str(i.class)); eAct.set(Array.isArray(i.actuals) ? (i.actuals as number[]).join(', ') : '');
    });
    vTab.pick((k) => { viewSel = k; const v = views.find((x) => str(x.id) === k); if (v) { vName.set(str(v.name)); vCam.set(str(v.camera)); vBal.set(!!v.balloons); } });

    async function addView(): Promise<void> {
      await guard(() => docApi('POST', 'mbd/views', { name: vName.get() || undefined, camera: vCam.get(), balloons: vBal.get() }));
    }
    async function assign(): Promise<void> { if (viewSel) await guard(() => docApi('POST', `mbd/views/${encodeURIComponent(viewSel)}/assign`, { rule: 'facing' })); }
    async function delView(): Promise<void> { if (viewSel) { await guard(() => docApi('DELETE', `mbd/views/${encodeURIComponent(viewSel)}`)); viewSel = ''; } }

    async function load(): Promise<void> {
      const [ins, rp, mb, mr] = await Promise.all([docApi('GET', 'inspection'), docApi('GET', 'inspection/report'), docApi('GET', 'mbd'), docApi('GET', 'mbd/report')]);
      items = arr(ins.items);
      const resByNo = new Map(arr(rp.rows).map((r) => [str(r.id), r]));
      tab.set(items.map((i) => {
        const r = resByNo.get(str(i.id));
        const a = Array.isArray(i.actuals) ? (i.actuals as number[]) : [];
        return { key: str(i.id), cells: [String(nn(i.n)), str(i.label), requirement(i), a.length ? f3(a[0], 3) + (a.length > 1 ? '+' : '') : '', str(r?.result)], tone: str(r?.result) };
      }));
      tab.empty(items.length ? '' : t('No characteristics yet: collect them or add one.'));
      const f1 = obj(rp.form1);
      pn.set(str(f1['Part number'])); pname.set(str(f1['Part name'])); rev.set(str(f1['Revision'])); org.set(str(f1.Organisation));
      const c = obj(rp.counts);
      rep.set([`${str(rp.title)}`, `${nn(rp.total)} ${t('characteristics')}: ${nn(c.pass)} ${t('pass')}, ${nn(c.fail)} ${t('fail')}, ${nn(c.pending)} ${t('pending')}`, `${t('Overall')}: ${str(rp.overall)}`, '']);
      views = arr(mb.views);
      fillSelect(vCam.input as HTMLSelectElement, (Array.isArray(mb.cameras) ? (mb.cameras as string[]).slice().sort((a, b) => Number(b === 'iso') - Number(a === 'iso')) : []).map((c2) => [c2, c2] as const));
      vTab.set(views.map((v) => ({ key: str(v.id), cells: [str(v.name), str(v.camera), Array.isArray(v.items) ? String(v.items.length) : t('all')] })));
      vTab.empty(views.length ? '' : t('No views.'));
      const problems = arr(mr.problems);
      mbdRep.set([`${t('PMI items')}: ${nn(mr.pmi_items)}`, `${t('Shown in views')}: ${nn(mr.shown)}`, mr.complete ? t('The model definition is complete.') : t('The model definition is not complete.'), problems.length ? `${problems.length} ${t('problems')}: ${str(problems[0].message) || str(problems[0].problem) || JSON.stringify(problems[0]).slice(0, 80)}` : t('No problems.')], problems.length > 0);
    }

    return { load };
  },
});
