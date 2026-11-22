import { setHidden } from '../ui/dom';
import { pickPath } from '../ui/file-dialogs';
import { t } from '../ui/i18n';
import { toast } from '../ui/toast';
import { asm } from '../u8/asm';
import { view3d } from '../view3d/mount';
import {
  arr, button, buttons, checkCtl, docApi, docKind, dockPanel, f3, fillSelect, globalApi, guard, msgLine, nn, numberCtl, obj, readout, reportBox,
  section, selectCtl, str, table, textCtl, type Json,
} from './kit';

interface SizeRow { id: string; status: string; source: string; note: string; values: Record<string, number> }
interface KindSpec { kind: string; group: string; label: string; params: Array<{ name: string; label: string; min: number; max: number; derived: string | null; default: number | null }>; sizes: SizeRow[] }
interface Ref { comp: string; face: number }
const POOL = 12;

export const toolboxSpec = (): ReturnType<typeof dockPanel> => dockPanel({
  id: 'toolbox', label: 'Toolbox', icon: 'toolbox', order: 48, note: 'Open a document to use the toolbox.', need: () => true, kinds: ['part', 'assembly'],
  build(live) {
    let kinds: KindSpec[] = [];
    let fams: Json[] = [];
    let famRows: Json[] = [];
    let hole: Ref | null = null;
    let seat: Ref | null = null;
    let picking = '';

    const sGen = section('Generator');
    const kind = selectCtl('Kind', []);
    const std = selectCtl('Standard size', []);
    const pc = Array.from({ length: POOL }, (_, i) => numberCtl(`Size ${i}`, 0));
    const check = reportBox(3);
    const noteLine = msgLine();
    sGen.body.append(kind.el, std.el, ...pc.map((c) => c.el), check.el, noteLine.el, buttons(button('Check size', () => { void checkSize(); }, 'primary')));

    const sIns = section('Insert');
    const srcSel = selectCtl('Source', []);
    const holeRead = readout('Hole');
    const seatRead = readout('Seat');
    const offset = numberCtl('Offset from seat', 0);
    const flip = checkCtl('Flip', false);
    const mates = checkCtl('Add mates', true);
    const label = textCtl('Label');
    const insMsg = msgLine();
    sIns.body.append(srcSel.el, buttons(button('Pick hole', () => { pickRef('hole'); }), button('Pick seat', () => { pickRef('seat'); }), button('Clear', () => { hole = null; seat = null; paintRefs(); })), holeRead.el, seatRead.el, offset.el, flip.el, mates.el, label.el, insMsg.el,
      buttons(button('Insert', () => { void insert(); }, 'primary')));

    const sLib = section('Library');
    const fTab = table([{ key: 'id', label: 'Family', w: '84px' }, { key: 'kind', label: 'Kind' }, { key: 'rows', label: 'Rows', w: '40px', right: true }], 100);
    const rTab = table([{ key: 'name', label: 'Row' }, { key: 'p', label: 'Sizes' }], 112);
    const newLabel = textCtl('New family name');
    const rowName = textCtl('Row name');
    sLib.body.append(fTab.el, rTab.el, newLabel.el, rowName.el,
      buttons(button('New family', () => { void newFamily(); }), button('Save sizes as row', () => { void saveRow(); }, 'primary')),
      buttons(button('Delete row', () => { void delRow(); }, 'danger'), button('Delete family', () => { void delFam(); }, 'danger')));
    let famSel = '';
    let rowSel = '';

    const sImp = section('Import CSV');
    const csvPath = textCtl('CSV file');
    const impFam = textCtl('Family id');
    const impUnit = selectCtl('Table unit', [['mm', 'Millimetres'], ['inch', 'Inches']]);
    const impSrc = textCtl('Source note');
    const impRep = msgLine();
    sImp.body.append(csvPath.el, buttons(button('Choose file', () => { void chooseCsv(); })), impFam.el, impUnit.el, impSrc.el, impRep.el, buttons(button('Import', () => { void importCsv(); }, 'primary')));

    live.append(sGen.root, sIns.root, sLib.root, sImp.root);

    const spec = (): KindSpec | undefined => kinds.find((k) => k.kind === kind.get());

    const paintFields = (): void => {
      const s = spec();
      pc.forEach((c, i) => {
        const p = s?.params[i];
        setHidden(c.el, !p);
        if (!p) return;
        const span = c.el.querySelector('span');
        const text = `${p.label}${p.derived ? ` (${p.derived})` : ''}`;
        if (span && span.textContent !== text) span.textContent = text;
        const input = c.input as HTMLInputElement;
        if (input.dataset.kind !== s?.kind) { input.dataset.kind = s?.kind ?? ''; c.set(p.default); }
      });
      const sel = std.input as HTMLSelectElement;
      if (sel.dataset.kind !== (s?.kind ?? '')) {
        sel.dataset.kind = s?.kind ?? '';
        fillSelect(sel, [['', t('Typed sizes')] as const, ...(s?.sizes ?? []).map((r) => [r.id, r.id] as const)]);
        sel.value = '';
      }
      setHidden(std.el, !s?.sizes.length);
      noteLine.set(s ? `${t(s.group)}: ${s.label}` : '');
    };
    kind.input.addEventListener('change', paintFields);
    std.input.addEventListener('change', () => {
      const s = spec();
      const row = s?.sizes.find((r) => r.id === std.get());
      if (!s || !row) { noteLine.set(s ? `${t(s.group)}: ${s.label}` : ''); return; }
      s.params.forEach((p, i) => { const v = row.values[p.name === 'd' ? 'nominal' : p.name]; if (typeof v === 'number') pc[i].set(v); });
      noteLine.set(`${row.id} · ${t(row.status.replace(/_/g, ' '))} · ${t('Source:')} ${row.source}${row.note ? ` ${t(row.note)}` : ''}`);
    });

    const sizes = (): Json => {
      const out: Json = {};
      spec()?.params.forEach((p, i) => { const v = pc[i].get(); if (v !== null) out[p.name] = v; });
      return out;
    };

    const source = (): Json => {
      const v = srcSel.get();
      if (v.startsWith('row:')) { const [, fam, ...rest] = v.split(':'); return { family: fam, row: rest.join(':') }; }
      return { kind: kind.get(), params: sizes() };
    };

    async function checkSize(): Promise<void> {
      const r = await guard(() => globalApi('POST', 'toolbox/check', { source: { kind: kind.get(), params: sizes() } }));
      if (!r) { check.set([t('The sizes were refused.')], true); return; }
      const prof = obj(r.profile);
      check.set([`${t('Designation')}: ${str(r.designation)}`, `${t('Volume')}: ${f3(nn(r.volume), 3)}`, Object.keys(prof).length ? t('Section profile available for weldments.') : '']);
    }

    const paintRefs = (): void => {
      holeRead.set(hole ? `${hole.comp} ${t('face')} ${hole.face + 1}` : '-');
      seatRead.set(seat ? `${seat.comp} ${t('face')} ${seat.face + 1}` : '-');
    };

    function pickRef(which: string): void {
      const vp = view3d()?.vp;
      if (!vp) return;
      picking = which;
      insMsg.set(t('Pick a face on a component.'));
      vp.onPick = (s) => {
        const f = s.faces[0];
        const comp = f ? asm.componentOfBody(f.body) : '';
        if (!f || !comp) return;
        const ref = { comp, face: Math.max(0, f.face - 1) };
        if (picking === 'hole') hole = ref; else seat = ref;
        picking = '';
        vp.onPick = null;
        insMsg.set('');
        paintRefs();
      };
    }

    async function insert(): Promise<void> {
      if (docKind() !== 'assembly') { insMsg.set(t('Open an assembly to insert parts.'), true); return; }
      const body: Json = { source: source(), mates: mates.get(), flip: flip.get(), offset: offset.get() ?? 0 };
      if (label.get()) body.label = label.get();
      if (hole) body.hole = hole; else body.at = { point: [0, 0, 0], axis: [0, 0, 1] };
      if (seat) body.seat = seat;
      const r = await guard(() => docApi('POST', 'toolbox/insert', body));
      if (r) { insMsg.set(`${t('Inserted')}: ${str(obj(r).component) || str(obj(r).label) || 'ok'}`); toast(t('Part inserted.'), 'info'); }
    }

    async function newFamily(): Promise<void> {
      const l = newLabel.get();
      if (!l) { toast(t('Give the family a name.'), 'error'); return; }
      await guard(() => globalApi('POST', 'toolbox/library', { kind: kind.get(), label: l }));
      await load();
    }

    async function saveRow(): Promise<void> {
      if (!famSel || !rowName.get()) { toast(t('Pick a family and give the row a name.'), 'error'); return; }
      await guard(() => globalApi('POST', `toolbox/library/${encodeURIComponent(famSel)}/rows`, { name: rowName.get(), params: sizes() }));
      await load();
    }

    async function delRow(): Promise<void> {
      if (!famSel || !rowSel) return;
      await guard(() => globalApi('DELETE', `toolbox/library/${encodeURIComponent(famSel)}/rows/${encodeURIComponent(rowSel)}`));
      rowSel = '';
      await load();
    }

    async function delFam(): Promise<void> {
      if (!famSel) return;
      await guard(() => globalApi('DELETE', `toolbox/library/${encodeURIComponent(famSel)}`));
      famSel = '';
      await load();
    }

    async function chooseCsv(): Promise<void> {
      const p = await pickPath('open', t('Choose a size table'), '', [{ name: 'CSV table', extensions: ['csv', 'txt'] }], t('Choose'));
      if (p) csvPath.set(p);
    }

    async function importCsv(): Promise<void> {
      if (!csvPath.get() || !impFam.get()) { impRep.set(t('Give a file and a family id.'), true); return; }
      const r = await guard(() => globalApi('POST', 'toolbox/library/import', { file: csvPath.get(), family: impFam.get(), kind: kind.get(), unit: impUnit.get(), source: impSrc.get() }));
      if (r) { impRep.set(`${t('Imported')}: ${nn(r.added, nn(r.rows))} ${t('rows')}${nn(r.skipped) ? `, ${nn(r.skipped)} ${t('skipped')}` : ''}`); await load(); } else impRep.set(t('The import was refused.'), true);
    }

    fTab.pick((k) => { famSel = k; rowSel = ''; void loadFamily(); const f = fams.find((x) => str(x.id) === k); if (f) kind.set(str(f.kind)); paintFields(); });
    rTab.pick((k) => { rowSel = k; rowName.set(k); const r = famRows.find((x) => str(x.name) === k); const p = obj(r?.params); spec()?.params.forEach((q, i) => { const v = p[q.name]; if (typeof v === 'number') pc[i].set(v); }); });

    async function loadFamily(): Promise<void> {
      if (!famSel) { famRows = []; rTab.set([]); return; }
      const f = await guard(() => globalApi('GET', `toolbox/library/${encodeURIComponent(famSel)}`));
      famRows = f ? arr(f.rows) : [];
      rTab.set(famRows.map((r) => ({ key: str(r.name), cells: [str(r.name), Object.entries(obj(r.params)).map(([k, v]) => `${k} ${typeof v === 'number' ? f3(v, 2) : str(v)}`).join(', ')] })));
      rTab.empty(famRows.length ? '' : t('No rows.'));
    }

    async function load(): Promise<void> {
      if (!kinds.length) {
        const k = await globalApi('GET', 'toolbox/kinds');
        kinds = arr(k.kinds).map((x) => ({ kind: str(x.kind), group: str(x.group), label: str(x.label), params: arr(x.params).map((p) => ({ name: str(p.name), label: str(p.label), min: nn(p.min), max: nn(p.max), derived: typeof p.derived === 'string' ? p.derived : null, default: typeof p.default === 'number' ? p.default : null })), sizes: arr(x.sizes).map((r) => ({ id: str(r.id), status: str(r.status), source: str(r.source), note: str(r.note), values: Object.fromEntries(Object.entries(obj(r.values)).filter(([, v]) => typeof v === 'number')) as Record<string, number> })) }));
        fillSelect(kind.input as HTMLSelectElement, kinds.map((x) => [x.kind, x.label] as const));
        paintFields();
      }
      const lib = await globalApi('GET', 'toolbox/library');
      fams = arr(lib.families);
      fTab.set(fams.map((f) => ({ key: str(f.id), cells: [str(f.id), `${str(f.label)} (${str(f.kind)})`, String(nn(f.rows))] })));
      fTab.empty(fams.length ? '' : t('No family yet: create one or import a CSV table.'));
      await loadFamily();
      const rows: Array<readonly [string, string]> = [['gen', t('Generator sizes')]];
      for (const f of fams) {
        const full = await guard(() => globalApi('GET', `toolbox/library/${encodeURIComponent(str(f.id))}`));
        for (const r of arr(full?.rows)) rows.push([`row:${str(f.id)}:${str(r.name)}`, `${str(f.id)}: ${str(r.name)}`]);
      }
      fillSelect(srcSel.input as HTMLSelectElement, rows);
      paintRefs();
    }

    return { load };
  },
});
