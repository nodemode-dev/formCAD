import type { DockPanel } from '../ui/dock';
import { el, patchList, q, setClass, setDisabled, setHidden, setText, setValue } from '../ui/dom';
import { icon } from '../ui/icons';
import { t } from '../ui/i18n';
import { toast } from '../ui/toast';
import { asm, isAssembly } from '../u8/asm';
import { button, buttons, checkCtl, fmt, numberCtl, readout, selectCtl, type Ctl } from '../u8/ui';
import { view3d } from '../view3d/mount';
import { guard, reportBox, section, text, type Json } from './kit';
import { COORD_LABEL, joints, jointView, jurl, showPoses, TYPE_COORDS, TYPE_LABEL, type Coord, type Joint, type JointType, type Link } from './joint-store';
import { req } from './kit';

interface Ref extends Json { comp: string }

const hint = (s: string): void => { document.dispatchEvent(new CustomEvent('formcad:hint', { detail: s })); };
const TYPES = (Object.keys(TYPE_LABEL) as JointType[]).map((k) => [k, TYPE_LABEL[k]] as const);
const MAX_COORDS = 3;
const DATUMS: ReadonlyArray<readonly [string, string]> = [['origin', 'Origin'], ['xy', 'XY plane'], ['yz', 'YZ plane'], ['xz', 'XZ plane'], ['x', 'X axis'], ['y', 'Y axis'], ['z', 'Z axis']];

const mini = (label: string, title: string, on: () => void): HTMLButtonElement => {
  const b = el<HTMLButtonElement>('<button class="u8-mini" type="button"></button>');
  if (label.startsWith('@')) b.innerHTML = icon(label.slice(1), 12); else b.textContent = label;
  b.title = title;
  b.addEventListener('click', (e) => { e.stopPropagation(); on(); });
  return b;
};

export async function afterChange(): Promise<void> {
  await view3d()?.refresh();
  showPoses(null);
  asm.schedule(0);
  joints.schedule(0);
}

export function coordUnit(c: { kind: string }): string { return c.kind === 'angle' ? '°' : ''; }

interface CoordRow {
  root: HTMLElement; label: HTMLElement; badge: HTMLElement; value: Ctl<number | null>; slider: HTMLInputElement;
  min: Ctl<number | null>; max: Ctl<number | null>; rest: Ctl<number | null>; lo: number; hi: number; key: string;
}

export function jointPanel(): DockPanel {
  return {
    id: 'joints', label: 'Joints', icon: 'joint', order: 33,
    build(body) {
      body.classList.add('u8-panel', 'xw-panel');
      const note = el('<p class="u8-note"></p>');
      setText(note, t('Open an assembly to add joints.'));
      const live = el('<div class="u8-live p11-live"></div>');
      body.append(note, live);
      const paintShell = (): void => { const on = isAssembly(); setHidden(note, on); setHidden(live, !on); };

      const head = el('<div class="u8-head"><span class="u8-pill" data-s=""></span> <span class="u8-note p11-stat"></span></div>');
      const pill = q(head, '.u8-pill');
      const stat = q(head, '.p11-stat');

      const sList = section('Joints');
      const list = el('<div class="u8-list p11-jlist" role="listbox" aria-label="Joints"></div>');
      const empty = el('<p class="u8-note p11-empty"></p>');
      setText(empty, t('No joints yet. Pick two components below and add one.'));
      const glyphs = checkCtl('Show joint symbols in the view', true, () => { jointView.layer?.setShown(glyphs.get()); });
      sList.body.append(list, empty, glyphs.el);

      const sNew = section('New joint');
      const type = selectCtl('Type', TYPES, () => syncNew());
      const refs: Array<Ref | null> = [null, null];
      const refRead = [readout('First'), readout('Second')];
      let picking = -1;
      const setPick = (i: number): void => {
        const vp = view3d()?.vp;
        if (!vp) return;
        picking = i;
        if (i < 0) { vp.onPick = null; hint(''); return; }
        hint(t('Pick a face or an edge on a component.'));
        vp.onPick = (s) => {
          const f = s.faces[0], e = s.edges[0];
          const bodyId = f ? f.body : e ? e.body : -1;
          const comp = bodyId >= 0 ? asm.componentOfBody(bodyId) : '';
          if (!comp) return;
          const r: Ref = f ? { comp, face: Math.max(0, f.face - 1) } : { comp, edge: Math.max(0, (e as { edge: number }).edge - 1) };
          takeRef(i, r, f ? `${comp} · ${t('face')} ${f.face}` : `${comp} · ${t('edge')} ${(e as { edge: number }).edge}`);
          setPick(-1);
        };
      };
      const takeRef = (i: number, r: Ref, label: string): void => { refs[i] = r; refRead[i].set(label); };
      const datum = selectCtl('Datum of the selected component', DATUMS);
      const originBtn = (i: number): HTMLButtonElement => button(i ? 'Use datum, second' : 'Use datum, first', () => {
        const comp = asm.selected;
        if (!comp) { toast(t('Select a component in the tree first.'), 'info'); return; }
        takeRef(i, { comp, origin: datum.get() }, `${comp} · ${t(DATUMS.find((d) => d[0] === datum.get())?.[1] ?? 'origin')}`);
      });
      const pickA = button('Pick first', () => setPick(picking === 0 ? -1 : 0));
      const pickB = button('Pick second', () => setPick(picking === 1 ? -1 : 1));
      const asBuilt = checkCtl('As built (keep the current position)', false);
      const labelIn = el('<label class="cv-field"><span></span><input class="cv-input" type="text" spellcheck="false" autocomplete="off"></label>');
      setText(q(labelIn, 'span'), t('Name'));
      const nameInput = q<HTMLInputElement>(labelIn, 'input');
      nameInput.addEventListener('keydown', (e) => e.stopPropagation());

      const limitRows: Array<{ root: HTMLElement; title: HTMLElement; min: Ctl<number | null>; max: Ctl<number | null>; rest: Ctl<number | null> }> = [];
      const limits = el('<div class="p11-limits"></div>');
      for (let i = 0; i < MAX_COORDS; i++) {
        const root = el('<div class="p11-limit"><span class="p11-limit-title"></span></div>');
        const min = numberCtl('Min', 0); min.set(null);
        const max = numberCtl('Max', 0); max.set(null);
        const rest = numberCtl('Rest', 0); rest.set(null);
        for (const c of [min, max, rest]) { c.el.classList.add('p11-mini'); root.append(c.el); }
        limitRows.push({ root, title: q(root, '.p11-limit-title'), min, max, rest });
        limits.append(root);
      }
      const out = reportBox(2);
      const addBtn = button('Add joint', () => void addJoint(), 'primary');
      sNew.body.append(type.el, labelIn, refRead[0].el, refRead[1].el, buttons(pickA, pickB), datum.el, buttons(originBtn(0), originBtn(1)), asBuilt.el, limits, buttons(addBtn), out.el);

      const syncNew = (): void => {
        const k = type.get() as JointType;
        const keys = k === 'ball' ? ['cone'] : TYPE_COORDS[k];
        limitRows.forEach((r, i) => {
          const key = keys[i];
          setClass(r.root, 'is-off', !key);
          setText(r.title, key ? (key === 'cone' ? t('Cone angle from rest') : t(COORD_LABEL[key] ?? key)) : '');
          setDisabled(r.min.input as HTMLInputElement, !key || key === 'cone');
          setDisabled(r.max.input as HTMLInputElement, !key);
          setDisabled(r.rest.input as HTMLInputElement, !key || key === 'cone');
        });
      };

      const addJoint = async (): Promise<void> => {
        if (!refs[0] || !refs[1]) { toast(t('Pick both references first.'), 'info'); return; }
        const k = type.get() as JointType;
        const lim: Record<string, Json> = {};
        const keys = k === 'ball' ? ['cone'] : TYPE_COORDS[k];
        keys.forEach((key, i) => {
          const r = limitRows[i];
          const o: Json = {};
          if (key === 'cone') { if (r.max.get() !== null) o.max = r.max.get(); } else {
            if (r.min.get() !== null) o.min = r.min.get();
            if (r.max.get() !== null) o.max = r.max.get();
            if (r.rest.get() !== null) o.rest = r.rest.get();
          }
          if (Object.keys(o).length) lim[key] = o;
        });
        const body: Json = { type: k, a: refs[0], b: refs[1], as_built: asBuilt.get() };
        if (Object.keys(lim).length) body.limits = lim;
        if (nameInput.value.trim()) body.label = nameInput.value.trim();
        const r = await guard(() => req<{ joint: Joint; moved: string[] }>('POST', jurl('joints'), body));
        if (!r) { out.set([t('The joint was refused.')], true); return; }
        out.set([`${r.joint.name} ${t('added')}`, `${r.moved?.length ?? 0} ${t('components moved')}`]);
        joints.selected = String(r.joint.id);
        nameInput.value = '';
        await afterChange();
      };

      const sSel = section('Selected joint');
      const selName = readout('Joint');
      const coords: CoordRow[] = [];
      const coordBox = el('<div class="p11-coords"></div>');
      for (let i = 0; i < MAX_COORDS; i++) {
        const root = el('<div class="p11-coord"><div class="p11-coord-top"><span class="p11-coord-label"></span><span class="u8-badge p11-coord-state"></span></div></div>');
        const value = numberCtl('Value', 0);
        const slider = el<HTMLInputElement>('<input class="u8-slider" type="range" min="0" max="1000" value="0" aria-label="Joint value">');
        const min = numberCtl('Min', 0), max = numberCtl('Max', 0), rest = numberCtl('Rest', 0);
        const lim = el('<div class="p11-limit"></div>');
        for (const c of [min, max, rest]) { c.el.classList.add('p11-mini'); lim.append(c.el); }
        root.append(value.el, slider, lim);
        const row: CoordRow = { root, label: q(root, '.p11-coord-label'), badge: q(root, '.p11-coord-state'), value, slider, min, max, rest, lo: 0, hi: 1, key: '' };
        coords.push(row);
        coordBox.append(root);
        slider.addEventListener('input', () => { const v = row.lo + ((row.hi - row.lo) * Number(slider.value)) / 1000; value.set(Number(v.toFixed(4))); void preview(row, v); });
        slider.addEventListener('change', () => void commit(row, row.lo + ((row.hi - row.lo) * Number(slider.value)) / 1000));
        value.input.addEventListener('change', () => { const v = value.get(); if (v !== null) void commit(row, v); });
        for (const c of [min, max, rest]) c.input.addEventListener('change', () => void applyLimits());
      }
      const cone = readout('Cone from rest');
      const rowBtns = buttons(
        button('Go to rest', () => { const j = joints.current(); if (j) void guard(() => req('POST', jurl(`joints/${j.id}/rest`), {})).then(() => afterChange()); }),
        button('Suppress or restore', () => { const j = joints.current(); if (j) void guard(() => req('PATCH', jurl(`joints/${j.id}`), { suppressed: !j.suppressed })).then(() => afterChange()); }),
        button('Delete joint', () => { const j = joints.current(); if (j) void guard(() => req('DELETE', jurl(`joints/${j.id}`))).then(() => { joints.selected = ''; return afterChange(); }); }, 'danger'),
      );
      const driveNote = el('<p class="u8-note p11-drive"></p>');
      sSel.body.append(selName.el, coordBox, cone.el, rowBtns, driveNote);

      let inflight = false;
      let want: { row: CoordRow; v: number } | null = null;
      const preview = async (row: CoordRow, v: number): Promise<void> => {
        const j = joints.current();
        if (!j) return;
        want = { row, v };
        if (inflight) return;
        inflight = true;
        try {
          while (want) {
            const w: { row: CoordRow; v: number } = want;
            want = null;
            const res = await req<{ ok: boolean; message: string; poses?: Record<string, number[]>; samples: Array<{ poses?: Record<string, number[]> }> }>('POST', jurl(`joints/${j.id}/drive`), { coord: w.row.key, value: w.v, commit: false, report: true });
            const p = res.poses ?? res.samples?.[0]?.poses;
            if (p) showPoses(p);
            setText(driveNote, res.message ?? '');
          }
        } catch (e) {
          setText(driveNote, text(e));
        } finally {
          inflight = false;
        }
      };
      const commit = async (row: CoordRow, v: number): Promise<void> => {
        const j = joints.current();
        if (!j) return;
        while (inflight) await new Promise((r) => window.setTimeout(r, 20));
        const res = await guard(() => req<{ ok: boolean; message: string }>('POST', jurl(`joints/${j.id}/drive`), { coord: row.key, value: v, commit: true }));
        setText(driveNote, res?.message ?? '');
        await afterChange();
      };
      const applyLimits = async (): Promise<void> => {
        const j = joints.current();
        if (!j) return;
        const lim: Record<string, Json> = {};
        coords.forEach((r) => {
          if (!r.key) return;
          lim[r.key] = { min: r.min.get(), max: r.max.get(), rest: r.rest.get() };
        });
        if (j.type === 'ball') lim.cone = { max: coords[0].max.get() };
        await guard(() => req('PATCH', jurl(`joints/${j.id}`), { limits: j.type === 'ball' ? { cone: lim.cone } : lim }));
        joints.schedule(0);
      };

      const sLink = section('Motion links');
      const linkList = el('<div class="u8-list p11-llist" aria-label="Motion links"></div>');
      const jopts = (): Array<readonly [string, string]> => joints.joints.map((j) => [String(j.id), `${j.name} · ${t(TYPE_LABEL[j.type])}`] as const);
      const firstJ = selectCtl('First joint', [['', '-']], () => fillCoords(firstJ, firstC));
      const firstC = selectCtl('First motion', [['', '-']]);
      const secondJ = selectCtl('Second joint', [['', '-']], () => fillCoords(secondJ, secondC));
      const secondC = selectCtl('Second motion', [['', '-']]);
      const ratio = numberCtl('Ratio', 1);
      const reverse = checkCtl('Reverse direction', false);
      const linkBtn = button('Add link', () => void addLink(), 'primary');
      sLink.body.append(linkList, firstJ.el, firstC.el, secondJ.el, secondC.el, ratio.el, reverse.el, buttons(linkBtn));
      const fillSelect = (c: Ctl<string>, opts: Array<readonly [string, string]>): void => {
        const sel = c.input as HTMLSelectElement;
        const keep = sel.value;
        patchList(sel, opts as Array<readonly [string, string]>, {
          key: (o) => o[0],
          create: (o) => { const n = document.createElement('option'); n.value = o[0]; return n; },
          update: (n, o) => setText(n, o[1]),
        });
        setValue(sel, opts.some((o) => o[0] === keep) ? keep : opts[0]?.[0] ?? '');
      };
      const fillCoords = (jc: Ctl<string>, cc: Ctl<string>): void => {
        const j = joints.joint(jc.get());
        fillSelect(cc, (j ? j.coords.map((c) => c.key) : []).map((k) => [k, t(COORD_LABEL[k] ?? k)] as const));
      };
      const addLink = async (): Promise<void> => {
        if (!firstJ.get() || !secondJ.get() || !firstC.get() || !secondC.get()) { toast(t('Choose both joints and their motions.'), 'info'); return; }
        const r = ratio.get();
        if (r === null) { toast(t('Type a ratio.'), 'info'); return; }
        const res = await guard(() => req('POST', jurl('jointlinks'), { first: { joint: firstJ.get(), coord: firstC.get() }, second: { joint: secondJ.get(), coord: secondC.get() }, ratio: r, reverse: reverse.get() }));
        if (res) await afterChange();
      };

      live.append(head, sList.root, sNew.root, sSel.root, sLink.root);
      syncNew();

      const rangeOf = (c: Coord): [number, number] => {
        if (c.min !== null && c.max !== null && c.max > c.min) return [c.min, c.max];
        if (c.kind === 'angle') return [c.min ?? -180, c.max ?? 180];
        const span = Math.max(50, Math.abs(c.value) * 2);
        return [c.min ?? c.value - span, c.max ?? c.value + span];
      };

      const paint = (): void => {
        paintShell();
        const st = joints.status;
        pill.dataset.s = st ? (st.state === 'conflict' ? 'fail' : 'pass') : '';
        setText(pill, st ? `${st.state} · ${st.dof} ${t('DOF')}` : '-');
        setText(stat, st ? `${t('Redundant rows')}: ${st.redundant_rows ?? 0} · ${t('Residual')}: ${fmt(st.residual ?? 0, 3)}` : '');
        setHidden(empty, joints.joints.length > 0);
        patchList(list, joints.joints, {
          key: (j) => String(j.id),
          create: (j) => {
            const row = el('<div class="u8-row p11-jrow" role="option"><span class="u8-row-sub"></span><span class="u8-row-name"></span><span class="u8-badge"></span><span class="u8-acts"></span></div>');
            q(row, '.u8-acts').append(
              mini('S', t('Suppress or restore'), () => { const cur = joints.joint(j.id); void guard(() => req('PATCH', jurl(`joints/${j.id}`), { suppressed: !(cur?.suppressed ?? false) })).then(() => afterChange()); }),
              mini('@close', t('Delete this joint'), () => { void guard(() => req('DELETE', jurl(`joints/${j.id}`))).then(() => { if (joints.selected === String(j.id)) joints.selected = ''; return afterChange(); }); }),
            );
            row.addEventListener('click', () => joints.select(String(j.id)));
            return row;
          },
          update: (row, j) => {
            setText(q(row, '.u8-row-sub'), j.name);
            const n = q(row, '.u8-row-name');
            const lbl = `${j.label && j.label !== j.name ? `${j.label} · ` : ''}${t(TYPE_LABEL[j.type])}${j.as_built ? ` · ${t('as built')}` : ''}`;
            setText(n, lbl);
            if (n.title !== lbl) n.title = lbl;
            const worst = j.coords.find((c) => c.state === 'outside') ? 'outside' : j.coords.find((c) => c.state !== 'free') ? 'limit' : 'free';
            const b = q(row, '.u8-badge');
            setText(b, j.suppressed ? t('suppressed') : `${j.dof} ${t('DOF')}`);
            b.dataset.s = j.suppressed ? 'under' : worst === 'free' ? 'fully' : worst === 'limit' ? 'under' : 'conflict';
            setClass(row, 'is-suppressed', j.suppressed);
            setClass(row, 'is-selected', joints.selected === String(j.id));
          },
        });
        jointView.layer?.set(joints.joints);
        jointView.layer?.highlight(joints.selected);

        const cur = joints.current();
        setText(q(selName.el, 'output'), cur ? `${cur.name} · ${t(TYPE_LABEL[cur.type])}` : '-');
        coords.forEach((r, i) => {
          const c = cur?.coords[i];
          setClass(r.root, 'is-off', !c);
          if (!c) { r.key = ''; return; }
          const changed = r.key !== c.key || r.lo !== rangeOf(c)[0] || r.hi !== rangeOf(c)[1];
          r.key = c.key;
          [r.lo, r.hi] = rangeOf(c);
          setText(r.label, `${t(COORD_LABEL[c.key] ?? c.key)}${coordUnit(c) ? ` (${coordUnit(c)})` : ''}`);
          setText(r.badge, c.driven ? t('driven') : c.state.replace('_', ' '));
          r.badge.dataset.s = c.state === 'free' ? 'fully' : c.state === 'outside' ? 'conflict' : 'under';
          r.value.set(Number(c.value.toFixed(4)));
          const pos = Math.round(((c.value - r.lo) / Math.max(r.hi - r.lo, 1e-9)) * 1000);
          const next = String(Math.max(0, Math.min(1000, pos)));
          if (document.activeElement !== r.slider && r.slider.value !== next) r.slider.value = next;
          void changed;
          r.min.set(c.min); r.max.set(c.max); r.rest.set(c.rest);
        });
        setHidden(cone.el, !(cur && cur.cone));
        if (cur?.cone) setText(q(cone.el, 'output'), `${fmt(cur.cone.value, 4)}° / ${cur.cone.max === null ? t('no limit') : `${fmt(cur.cone.max, 4)}°`}`);

        patchList(linkList, joints.links, {
          key: (l) => String(l.id),
          create: (l) => {
            const row = el('<div class="u8-row p11-lrow"><span class="u8-row-sub"></span><span class="u8-row-name"></span><span class="u8-badge"></span><span class="u8-acts"></span></div>');
            q(row, '.u8-acts').append(
              mini('S', t('Suppress or restore'), () => { const cur2 = joints.links.find((x) => String(x.id) === String(l.id)); void guard(() => req('PATCH', jurl(`jointlinks/${l.id}`), { suppressed: !(cur2?.suppressed ?? false) })).then(() => afterChange()); }),
              mini('@close', t('Delete this link'), () => { void guard(() => req('DELETE', jurl(`jointlinks/${l.id}`))).then(() => afterChange()); }),
            );
            return row;
          },
          update: (row, l: Link) => {
            setText(q(row, '.u8-row-sub'), l.name);
            const a = joints.joint(l.first.joint)?.name ?? String(l.first.joint);
            const b = joints.joint(l.second.joint)?.name ?? String(l.second.joint);
            const txt = `${a}.${l.first.coord} → ${b}.${l.second.coord} × ${fmt(l.reverse ? -l.ratio : l.ratio, 4)}`;
            const n = q(row, '.u8-row-name');
            setText(n, txt);
            if (n.title !== txt) n.title = txt;
            setText(q(row, '.u8-badge'), l.suppressed ? t('suppressed') : '');
            setClass(row, 'is-suppressed', l.suppressed);
          },
        });
        fillSelect(firstJ, jopts());
        fillSelect(secondJ, jopts());
        fillCoords(firstJ, firstC);
        fillCoords(secondJ, secondC);
      };
      joints.onChange(paint);
      asm.onChange(() => { paintShell(); });
      paintShell();
      return { show: () => { paintShell(); joints.schedule(0); } };
    },
  };
}
