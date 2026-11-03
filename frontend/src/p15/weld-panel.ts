import { api } from '../io/api';
import { setHidden } from '../ui/dom';
import { t } from '../ui/i18n';
import { toast } from '../ui/toast';
import {
  arr, button, buttons, docApi, docId, docKind, dockPanel, f3, fillSelect, guard, msgLine, nn, numberCtl, obj, rowOf, section, selectCtl,
  str, table, textCtl, vecCtl, type Json,
} from './kit';

const CORNERS: Array<readonly [string, string]> = [['miter', 'Mitre'], ['butt', 'Butt, trim priority'], ['cope', 'Cope'], ['none', 'None']];
const SIZE_NAMES = ['w', 'h', 't', 'r', 'd', 'a', 'b'];

interface Shape { shape: string; fields: Array<{ name: string; label: string }> }

export const weldSpec = (): ReturnType<typeof dockPanel> => dockPanel({
  id: 'weld', label: 'Weldment', icon: 'weld', order: 46, note: 'Open a part to build a weldment.', need: () => docKind() !== 'assembly', kinds: ['part'],
  build(live) {
    let fid = '';
    let params: Json = {};
    let shapes: Shape[] = [];
    let sketches: Array<readonly [string, string]> = [];
    let members: Json[] = [];
    let current = '';

    const sFrame = section('Frame');
    const state = msgLine();
    const corner = selectCtl('Corner treatment', CORNERS, () => { void patch({ corner: corner.get() }); });
    const density = numberCtl('Density (kg per m3)', 7850, () => { const v = density.get(); if (v !== null) void patch({ density: v }); });
    const frameBtns = buttons(button('New frame', () => { void newFrame(); }, 'primary'), button('Delete frame', () => { void delFrame(); }, 'danger'));
    sFrame.body.append(state.el, corner.el, density.el, frameBtns);

    const sMem = section('Members');
    const mTab = table([{ key: 'id', label: 'Id', w: '44px' }, { key: 'label', label: 'Label' }, { key: 'profile', label: 'Profile' }, { key: 'len', label: 'Length', w: '58px', right: true }, { key: 'ends', label: 'Ends', w: '78px' }], 168);
    const mId = textCtl('Id');
    const mLabel = textCtl('Label');
    const mA = vecCtl('Start');
    const mB = vecCtl('End');
    const mProf = selectCtl('Profile', []);
    const sizeCtl = SIZE_NAMES.map((n) => numberCtl(n, 0));
    const sizeRow = rowOf(...sizeCtl.map((c) => c.el));
    sizeRow.classList.add('p15-sizes');
    const mMsg = msgLine();
    sMem.body.append(mTab.el, mId.el, mLabel.el, mA.el, mB.el, mProf.el, sizeRow, mMsg.el,
      buttons(button('Add member', () => { void saveMember(true); }, 'primary'), button('Update', () => { void saveMember(false); }), button('Remove', () => { void removeMember(); }, 'danger')));

    const sJ = section('Corners and joints');
    const jAt = vecCtl('Joint point');
    const jTreat = selectCtl('Treatment', CORNERS.filter((c) => c[0] !== 'none'));
    const jTab = table([{ key: 'at', label: 'At' }, { key: 'tr', label: 'Treatment', w: '90px' }], 78);
    sJ.body.append(jTab.el, jAt.el, jTreat.el, buttons(button('Set joint', () => { void setJoint(); }, 'primary'), button('Remove joint', () => { void removeJoint(); }, 'danger')));

    const sG = section('Gussets and end caps');
    const gA = selectCtl('Member one', []);
    const gB = selectCtl('Member two', []);
    const gLeg = numberCtl('Leg', 50);
    const gT = numberCtl('Thickness', 6);
    const gTab = table([{ key: 'k', label: 'Kind', w: '64px' }, { key: 'd', label: 'Detail' }, { key: 'x', label: 'Size', w: '70px', right: true }], 96);
    const cM = selectCtl('Cap member', []);
    const cEnd = selectCtl('Cap end', [['start', 'Start'], ['end', 'End']]);
    const cShape = selectCtl('Cap shape', [['match', 'Match profile'], ['rectangle', 'Rectangle'], ['circle', 'Circle']]);
    const cT = numberCtl('Cap thickness', 5);
    sG.body.append(gTab.el, gA.el, gB.el, gLeg.el, gT.el, buttons(button('Add gusset', () => { void addGusset(); }, 'primary'), button('Remove selected', () => { void removeExtra(); }, 'danger')),
      cM.el, cEnd.el, cShape.el, cT.el, buttons(button('Add end cap', () => { void addCap(); }, 'primary')));
    let extraSel = '';
    gTab.pick((k) => { extraSel = k; });

    const sCut = section('Cut list');
    const tol = numberCtl('Length tolerance', 0.01);
    const cTab = table([{ key: 'item', label: 'Item', w: '34px' }, { key: 'qty', label: 'Qty', w: '30px', right: true }, { key: 'profile', label: 'Profile' }, { key: 'len', label: 'Length', w: '58px', right: true }, { key: 'a1', label: 'A1', w: '44px', right: true }, { key: 'a2', label: 'A2', w: '44px', right: true }], 190);
    const cTot = msgLine();
    sCut.body.append(tol.el, cTab.el, cTot.el, buttons(button('Refresh', () => { void load(); }), button('Copy CSV', () => { void copyCsv(); }), button('Table in drawing', () => { void drawTable(); }, 'primary'), button('Update tables', () => { void updTables(); })));

    live.append(sFrame.root, sMem.root, sJ.root, sG.root, sCut.root);

    const findShape = (name: string): Shape | undefined => shapes.find((s) => s.shape === name);
    const paintSizes = (): void => {
      const sh = findShape(mProf.get().replace(/^sh:/, ''));
      const names = sh ? sh.fields.map((f) => f.name) : [];
      sizeCtl.forEach((c, i) => {
        const n = SIZE_NAMES[i];
        const on = names.includes(n);
        setHidden(c.el, !on);
        const lab = sh?.fields.find((f) => f.name === n)?.label ?? n;
        const span = c.el.querySelector('span');
        if (span && span.textContent !== t(lab)) span.textContent = t(lab);
      });
    };
    mProf.input.addEventListener('change', paintSizes);

    const fillForm = (m: Json | undefined): void => {
      if (!m) return;
      mId.set(str(m.id));
      mLabel.set(str(m.label));
      mA.set(Array.isArray(m.a) ? m.a as number[] : [0, 0, 0]);
      mB.set(Array.isArray(m.b) ? m.b as number[] : [0, 0, 0]);
      const p = m.profile;
      if (typeof p === 'string') mProf.set(`sk:${p}`);
      else { const o = obj(p); mProf.set(`sh:${str(o.shape)}`); sizeCtl.forEach((c, i) => { const v = o[SIZE_NAMES[i]]; if (typeof v === 'number') c.set(v); }); }
      paintSizes();
    };
    mTab.pick((k) => { current = k; fillForm(members.find((m) => str(m.id) === k)); });

    const sendParams = async (p: Json, refs?: Json): Promise<boolean> => {
      const r = await guard(() => docApi('PATCH', `part/features/${encodeURIComponent(fid)}`, refs ? { params: p, refs } : { params: p }));
      return !!r;
    };
    const patch = async (p: Json): Promise<void> => { if (fid) await sendParams(p); };

    const profileOf = (): unknown | null => {
      const v = mProf.get();
      if (v.startsWith('sk:')) return v.slice(3);
      const sh = findShape(v.slice(3));
      if (!sh) return null;
      const out: Json = { shape: sh.shape };
      for (const f of sh.fields) { const i = SIZE_NAMES.indexOf(f.name); const n = i >= 0 ? sizeCtl[i].get() : null; if (n !== null && n !== 0) out[f.name] = n; }
      return out;
    };

    const memberFromForm = (): Json | null => {
      const a = mA.get(); const b = mB.get(); const p = profileOf();
      if (!a || !b || !p || !mId.get()) { mMsg.set(t('Give an id, two points with numbers and a profile.'), true); return null; }
      mMsg.set('');
      const m: Json = { id: mId.get(), a, b, profile: p };
      if (mLabel.get()) m.label = mLabel.get();
      return m;
    };

    const sketchRefs = (list: Json[]): Json | undefined => {
      const ids = new Set<string>();
      for (const m of list) if (typeof m.profile === 'string') ids.add(m.profile);
      return ids.size ? { profiles: [...ids].map((id) => ({ kind: 'feature', id })) } : undefined;
    };

    async function saveMember(add: boolean): Promise<void> {
      const m = memberFromForm();
      if (!m) return;
      let next: Json[];
      if (add) { if (members.some((x) => str(x.id) === str(m.id))) { mMsg.set(t('That id is taken.'), true); return; } next = [...members, m]; }
      else next = members.map((x) => (str(x.id) === current ? m : x));
      if (!fid) {
        const r = await guard(() => docApi('POST', 'part/features', { type: 'weld_frame', params: { members: next }, refs: sketchRefs(next) ?? {}, label: 'Frame' }));
        if (r) { current = str(m.id); }
        return;
      }
      if (await sendParams({ members: next }, sketchRefs(next))) current = str(m.id);
    }

    async function removeMember(): Promise<void> {
      if (!fid || !current) return;
      const next = members.filter((m) => str(m.id) !== current);
      if (!next.length) { toast(t('A frame needs at least one member; delete the frame instead.'), 'error'); return; }
      await sendParams({ members: next });
      current = '';
    }

    async function newFrame(): Promise<void> {
      if (fid) { toast(t('This part already has a frame; add members to it.'), 'info'); return; }
      const m = memberFromForm();
      if (m) await saveMember(true);
    }

    async function delFrame(): Promise<void> {
      if (!fid) return;
      await guard(() => docApi('DELETE', `part/features/${encodeURIComponent(fid)}`));
    }

    const keyAt = (at: unknown): string => (Array.isArray(at) ? (at as number[]).map((n) => f3(n, 2)).join(', ') : '');

    async function setJoint(): Promise<void> {
      const at = jAt.get();
      if (!fid || !at) return;
      const list = arr(params.junctions).filter((j) => keyAt(j.at) !== keyAt(at));
      list.push({ at, treatment: jTreat.get() });
      await sendParams({ junctions: list });
    }

    async function removeJoint(): Promise<void> {
      const at = jAt.get();
      if (!fid || !at) return;
      await sendParams({ junctions: arr(params.junctions).filter((j) => keyAt(j.at) !== keyAt(at)) });
    }

    async function addGusset(): Promise<void> {
      if (!fid) return;
      const leg = gLeg.get(); const th = gT.get();
      if (!leg || !th || gA.get() === gB.get()) { toast(t('Pick two different members and give a leg and a thickness.'), 'error'); return; }
      await sendParams({ gussets: [...arr(params.gussets), { members: [gA.get(), gB.get()], leg, thickness: th }] });
    }

    async function addCap(): Promise<void> {
      const th = cT.get();
      if (!fid || !th) return;
      await sendParams({ end_caps: [...arr(params.end_caps), { member: cM.get(), end: cEnd.get(), thickness: th, shape: cShape.get() }] });
    }

    async function removeExtra(): Promise<void> {
      if (!fid || !extraSel) return;
      const [kind, idx] = extraSel.split(':');
      const i = Number(idx);
      if (kind === 'g') await sendParams({ gussets: arr(params.gussets).filter((_, k) => k !== i) });
      else await sendParams({ end_caps: arr(params.end_caps).filter((_, k) => k !== i) });
      extraSel = '';
    }

    async function copyCsv(): Promise<void> {
      const r = await guard(() => docApi<{ csv: string }>('GET', 'weld/cutlist/csv'));
      if (!r) return;
      try { await navigator.clipboard.writeText(r.csv); toast(t('Cut list copied as CSV.'), 'info'); } catch { toast(t('The clipboard is not available here.'), 'error'); }
    }

    async function drawTable(): Promise<void> {
      const id = docId();
      if (!id) return;
      await guard(() => api.runCommand(id, 'WELDCUTTABLE', { point: [0, 0], tolerance: tol.get() ?? 0.01 }));
      toast(t('Cut list table placed in the drawing at 0, 0.'), 'info');
    }

    async function updTables(): Promise<void> {
      const id = docId();
      if (id) await guard(() => api.runCommand(id, 'WELDCUTUPDATE', {}));
    }

    async function load(): Promise<void> {
      const tolV = tol.get();
      const [tree, w, sh] = await Promise.all([
        docApi('GET', 'part'),
        docApi('GET', `weld${tolV ? `?tolerance=${tolV}` : ''}`),
        shapes.length ? Promise.resolve(null) : docApi('GET', 'weld/shapes'),
      ]);
      if (sh) shapes = arr(sh.shapes).map((s) => ({ shape: str(s.shape), fields: arr(s.fields).map((f) => ({ name: str(f.name), label: str(f.label) })) }));
      const feats = arr(tree.features);
      const frame = feats.find((f) => f.type === 'weld_frame');
      sketches = feats.filter((f) => f.type === 'sketch').map((f) => [`sk:${str(f.id)}`, `${str(f.label) || str(f.id)} (sketch)`] as const);
      fillSelect(mProf.input as HTMLSelectElement, [...shapes.map((s) => [`sh:${s.shape}`, s.shape.replace('_', ' ')] as const), ...sketches]);
      paintSizes();
      fid = frame ? str(frame.id) : '';
      params = frame ? obj(frame.params) : {};
      const st = obj(frame?.state);
      members = arr(params.members);
      const err = str(st.message);
      state.set(!fid ? t('No frame yet: fill the member form and add the first member.') : `${str(frame?.label) || fid}: ${members.length} ${t('members')}, ${str(st.status)}${err ? ` - ${err}` : ''}`, !!err);
      corner.set(str(params.corner) || 'miter');
      if (typeof params.density === 'number') density.set(params.density);
      const rec = new Map(arr(w.members).map((m) => [str(m.mid), m]));
      mTab.set(members.map((m) => {
        const r = rec.get(str(m.id));
        const p = m.profile;
        return { key: str(m.id), cells: [str(m.id), str(m.label), typeof p === 'string' ? str(arr(feats.filter((f) => f.id === p))[0]?.label) || p : str(obj(p).shape), r ? f3(nn(r.length), 2) : '', r ? `${str(r.kind1)}/${str(r.kind2)}` : ''] };
      }));
      mTab.empty(members.length ? '' : t('No members.'));
      const ids = members.map((m) => [str(m.id), str(m.id)] as const);
      for (const s of [gA, gB, cM]) fillSelect(s.input as HTMLSelectElement, ids);
      const juncs = arr(params.junctions);
      jTab.set(juncs.map((j) => ({ key: keyAt(j.at), cells: [keyAt(j.at), str(j.treatment)] })));
      jTab.pick((k) => { const j = juncs.find((x) => keyAt(x.at) === k); if (j && Array.isArray(j.at)) { jAt.set(j.at as number[]); jTreat.set(str(j.treatment) || 'miter'); } });
      const extras = [
        ...arr(params.gussets).map((g, i) => ({ key: `g:${i}`, cells: ['Gusset', Array.isArray(g.members) ? (g.members as string[]).join(' + ') : '', `${f3(nn(g.leg), 1)} x ${f3(nn(g.thickness), 1)}`] })),
        ...arr(params.end_caps).map((c, i) => ({ key: `c:${i}`, cells: ['End cap', `${str(c.member)} ${str(c.end)} ${str(c.shape)}`, f3(nn(c.thickness), 1)] })),
      ];
      gTab.set(extras);
      const cl = obj(w.cutlist);
      const rows = arr(cl.rows);
      cTab.set(rows.map((r) => ({ key: `${str(r.item)}`, cells: [str(r.item), str(r.qty), str(r.profile) + (r.description ? ` (${str(r.description)})` : ''), f3(nn(r.length), 2), f3(nn(r.angle1), 1), f3(nn(r.angle2), 1)] })));
      cTab.empty(rows.length ? '' : t('The cut list is empty.'));
      const totalLen = rows.reduce((a, r) => a + nn(r.total_length), 0);
      const mass = rows.reduce((a, r) => a + nn(r.mass), 0);
      cTot.set(`${rows.length} ${t('rows')}, ${t('total length')} ${f3(totalLen, 1)}${mass ? `, ${t('mass')} ${f3(mass, 2)} kg` : ''}`);
    }

    return { load };
  },
});
