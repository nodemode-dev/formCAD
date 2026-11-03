import { api } from '../io/api';
import { docStore } from '../ui/doc-store';
import type { DockPanel } from '../ui/dock';
import { el, q, setChecked, setDisabled, setHidden, setText } from '../ui/dom';
import { t } from '../ui/i18n';
import { toast } from '../ui/toast';
import { button, buttons, checkCtl, numberCtl, readout, selectCtl, type Ctl } from '../u8/ui';
import { view3d } from '../view3d/mount';
import { docUrl, fixed, lastCmdError, num, reportBox, req, runCmd, section, text, type Json } from './kit';
import { form } from './form-store';

interface Field { key: string; label: string; value: number; int?: boolean }

const PRIMS: ReadonlyArray<readonly [string, string]> = [['box', 'Box'], ['cylinder', 'Cylinder'], ['sphere', 'Sphere'], ['quadball', 'Quadball'], ['torus', 'Torus'], ['plane', 'Plane']];
const SYMS: ReadonlyArray<readonly [string, string]> = [['none', 'None'], ['x', 'Mirror X'], ['y', 'Mirror Y'], ['z', 'Mirror Z'], ['xy', 'Mirror X and Y'], ['xz', 'Mirror X and Z'], ['yz', 'Mirror Y and Z'], ['xyz', 'Mirror all three']];
const FIELDS: Record<string, Field[]> = {
  box: [{ key: 'sx', label: 'Size X', value: 20 }, { key: 'sy', label: 'Size Y', value: 20 }, { key: 'sz', label: 'Size Z', value: 20 }, { key: 'nx', label: 'Segments X', value: 2, int: true }, { key: 'ny', label: 'Segments Y', value: 2, int: true }, { key: 'nz', label: 'Segments Z', value: 2, int: true }],
  cylinder: [{ key: 'radius', label: 'Radius', value: 10 }, { key: 'height', label: 'Height', value: 20 }, { key: 'segments', label: 'Segments around', value: 8, int: true }, { key: 'height_segments', label: 'Segments along', value: 2, int: true }],
  sphere: [{ key: 'radius', label: 'Radius', value: 10 }, { key: 'segments', label: 'Segments around', value: 8, int: true }, { key: 'rings', label: 'Rings', value: 6, int: true }],
  quadball: [{ key: 'radius', label: 'Radius', value: 10 }, { key: 'spans', label: 'Spans', value: 2, int: true }],
  torus: [{ key: 'major', label: 'Major radius', value: 20 }, { key: 'minor', label: 'Minor radius', value: 6 }, { key: 'segments_major', label: 'Segments around', value: 12, int: true }, { key: 'segments_minor', label: 'Segments of the tube', value: 8, int: true }],
  plane: [{ key: 'sx', label: 'Size X', value: 40 }, { key: 'sy', label: 'Size Y', value: 40 }, { key: 'nx', label: 'Segments X', value: 4, int: true }, { key: 'ny', label: 'Segments Y', value: 4, int: true }],
};
const MIRROR_PRIMS = new Set(['box', 'cylinder']);
const FALLOFFS: ReadonlyArray<readonly [string, string]> = [['smooth', 'Smooth'], ['linear', 'Linear'], ['constant', 'Constant'], ['sharp', 'Sharp']];
const AXES: ReadonlyArray<readonly [string, string]> = [['x', 'X'], ['y', 'Y'], ['z', 'Z']];
const FILLS: ReadonlyArray<readonly [string, string]> = [['quads', 'Quads around a centre'], ['ngon', 'One face'], ['star', 'Triangle fan']];
const LEVELS: ReadonlyArray<readonly [string, string]> = [['1', 'Level 1'], ['2', 'Level 2'], ['3', 'Level 3'], ['4', 'Level 4']];

const vec = (a: number | null, b: number | null, c: number | null): number[] => [a ?? 0, b ?? 0, c ?? 0];

export function formPanel(setEditing: (on: boolean) => void): DockPanel {
  return {
    id: 'form',
    label: 'Form',
    icon: 'formCage',
    order: 41,
    build(body) {
      body.classList.add('u8-panel', 'xw-panel');

      const sActive = section('Form');
      const active = selectCtl('Active form', [['', 'None']], () => { const v = Number(active.get()); form.setActive(Number.isFinite(v) && active.get() !== '' ? v : null); });
      const editBtn = button('Edit the cage', () => setEditing(true), 'primary');
      const info = reportBox(4);
      const bInfo = button('Analyse', () => void analyse());
      sActive.body.append(active.el, buttons(editBtn, bInfo), info.el);

      const sMake = section('New form');
      const prim = selectCtl('Shape', PRIMS, () => { fieldsFor(); });
      const ox = numberCtl('Origin X', 0); const oy = numberCtl('Origin Y', 0); const oz = numberCtl('Origin Z', 0);
      const fieldHost = el('<div class="xw-fields"></div>');
      const sym = selectCtl('Symmetry', SYMS);
      const nameCtl = el('<label class="cv-field"><span></span><input class="cv-input" type="text" spellcheck="false" autocomplete="off"></label>');
      setText(q(nameCtl, 'span'), t('Name'));
      const nameIn = q<HTMLInputElement>(nameCtl, 'input');
      const fieldCtl = new Map<string, Ctl<number | null>>();
      for (const [k, list] of Object.entries(FIELDS)) for (const f of list) { const c = numberCtl(f.label, f.value); fieldCtl.set(`${k}.${f.key}`, c); fieldHost.appendChild(c.el); }
      const fieldsFor = (): void => {
        const k = prim.get();
        for (const [key, c] of fieldCtl) setHidden(c.el, !key.startsWith(`${k}.`));
        setHidden(sym.el, !MIRROR_PRIMS.has(k));
      };
      const bMake = button('Create', () => void make(), 'primary');
      sMake.body.append(prim.el, ox.el, oy.el, oz.el, fieldHost, sym.el, nameCtl, buttons(bMake));

      const sSketch = section('From a sketch');
      const height = numberCtl('Extrude height', 20);
      const spans = numberCtl('Spans along', 4);
      const segs = numberCtl('Segments around', 8);
      const axis = selectCtl('Revolve axis', AXES);
      const angle = numberCtl('Revolve angle', 360);
      const bExt = button('Extrude selected profile', () => void fromSketch('subdextrude'));
      const bRev = button('Revolve selected profile', () => void fromSketch('subdrevolve'));
      sSketch.body.append(height.el, spans.el, segs.el, axis.el, angle.el, buttons(bExt, bRev));

      const sSel = section('Selection');
      const count = readout('Selected');
      const soft = checkCtl('Soft selection', form.soft.on, () => form.setSoft({ on: soft.get() }));
      const radius = numberCtl('Soft radius', form.soft.radius, () => { const v = radius.get(); if (v !== null && v > 0) form.setSoft({ radius: v }); });
      const falloff = selectCtl('Falloff', FALLOFFS, () => form.setSoft({ falloff: falloff.get() }));
      const symSel = checkCtl('Apply the cage symmetry', form.soft.symmetry, () => form.setSoft({ symmetry: symSel.get() }));
      sSel.body.append(count.el, buttons(button('Select all', () => form.all()), button('Select none', () => form.clear())), soft.el, radius.el, falloff.el, symSel.el);

      const sMove = section('Exact edit');
      const dx = numberCtl('Move X', 0); const dy = numberCtl('Move Y', 0); const dz = numberCtl('Move Z', 0);
      const rAxis = selectCtl('Rotate about', AXES);
      const rAngle = numberCtl('Angle (deg)', 15);
      const sFactor = numberCtl('Scale factor', 1);
      const common = (): Json => ({ symmetry: form.soft.symmetry, ...form.softArgs() });
      const pivot = (): number[] | undefined => {
        const c = form.centroid();
        const off = form.cage?.offset;
        return c && off ? [c[0] - off[0], c[1] - off[1], c[2] - off[2]] : undefined;
      };
      sMove.body.append(
        dx.el, dy.el, dz.el, buttons(button('Move', () => void form.run('subdmove', { delta: vec(dx.get(), dy.get(), dz.get()), ...common() }))),
        rAxis.el, rAngle.el, buttons(button('Rotate', () => { const a = rAxis.get(); void form.run('subdrotate', { axis: a === 'x' ? [1, 0, 0] : a === 'y' ? [0, 1, 0] : [0, 0, 1], angle: rAngle.get() ?? 0, pivot: pivot(), ...common() }); })),
        sFactor.el, buttons(button('Scale', () => void form.run('subdscale', { factor: sFactor.get() ?? 1, pivot: pivot(), ...common() }))),
      );

      const sTopo = section('Shape the cage');
      const cuts = numberCtl('Cuts', 1);
      const pos = numberCtl('Position (0 to 1)', 0.5);
      const twist = numberCtl('Bridge twist', 0);
      const bspans = numberCtl('Bridge spans', 1);
      const fill = selectCtl('Fill style', FILLS);
      sTopo.body.append(
        cuts.el, pos.el, buttons(button('Insert edge', () => void form.run('subdinsertedge', { cuts: Math.max(1, Math.round(cuts.get() ?? 1)), position: pos.get() ?? 0.5 }))),
        buttons(button('Subdivide faces', () => void form.run('subddivideface', {})), button('Delete', () => void form.run('subddelete', {}), 'danger')),
        twist.el, bspans.el, buttons(button('Bridge', () => void form.run('subdbridge', { twist: Math.round(twist.get() ?? 0), spans: Math.max(1, Math.round(bspans.get() ?? 1)) }))),
        fill.el, buttons(button('Fill hole', () => void form.run('subdfillhole', form.sel.size ? { style: fill.get() } : { style: fill.get(), all: true }, form.sel.size > 0))),
      );

      const sCrease = section('Creases');
      const weight = numberCtl('Crease weight (10 is sharp)', 10);
      const amount = numberCtl('Uncrease by (blank: fully)', 0);
      amount.set(null);
      sCrease.body.append(weight.el, amount.el, buttons(
        button('Crease', () => void form.run('subdcrease', { weight: Math.min(10, Math.max(0.1, weight.get() ?? 10)) })),
        button('Uncrease', () => { const a = amount.get(); void form.run('subduncrease', a === null ? {} : { amount: a }); }),
        button('Uncrease all', () => void form.run('subduncrease', { all: true }, false)),
      ));

      const sSym = section('Symmetry');
      const mx = checkCtl('Mirror in X', false); const my = checkCtl('Mirror in Y', false); const mz = checkCtl('Mirror in Z', false);
      const at = numberCtl('Mirror position', 0);
      const rAx = selectCtl('Radial axis', AXES);
      const rCount = numberCtl('Radial copies (0: off)', 0);
      sSym.body.append(mx.el, my.el, mz.el, at.el, rAx.el, rCount.el, buttons(
        button('Apply symmetry', () => {
          const mirror = [mx.get() ? 'x' : '', my.get() ? 'y' : '', mz.get() ? 'z' : ''].filter(Boolean);
          const n = Math.round(rCount.get() ?? 0);
          void form.run('subdsymmetry', { mirror, at: at.get() ?? 0, radial: n > 1 ? { axis: rAx.get(), count: n, center: [0, 0] } : null }, false);
        }, 'primary'),
        button('Clear symmetry', () => void form.run('subdsymmetry', { clear: true }, false)),
      ));

      const sShow = section('Display');
      const level = selectCtl('Smooth level', LEVELS, () => void form.run('subddisplay', { level: Number(level.get()) }, false));
      sShow.body.append(level.el);

      const sConv = section('Convert to solid');
      const clevels = selectCtl('Refinement', [['1', '1'], ['2', '2 (default)'], ['3', '3'], ['4', '4']]);
      clevels.set('2');
      const keep = checkCtl('Keep the cage', true);
      const rep = reportBox(6);
      const bConv = button('Convert to solid', () => void convert(), 'primary');
      const contNote = el('<p class="u8-note xw-cont"></p>');
      sConv.body.append(clevels.el, keep.el, buttons(bConv), rep.el, contNote);

      body.append(sActive.root, sMake.root, sSketch.root, sSel.root, sMove.root, sTopo.root, sCrease.root, sSym.root, sShow.root, sConv.root);

      async function make(): Promise<void> {
        const k = prim.get();
        const v = (key: string): number => fieldCtl.get(`${k}.${key}`)?.get() ?? 0;
        const iv = (key: string): number => Math.max(1, Math.round(v(key)));
        const origin = vec(ox.get(), oy.get(), oz.get());
        const name = nameIn.value.trim();
        const base: Json = { origin, ...(name ? { name } : {}) };
        let args: Json;
        if (k === 'box') args = { ...base, size: [v('sx'), v('sy'), v('sz')], segments: [iv('nx'), iv('ny'), iv('nz')], symmetry: sym.get() };
        else if (k === 'cylinder') args = { ...base, radius: v('radius'), height: v('height'), segments: iv('segments'), height_segments: iv('height_segments'), symmetry: sym.get() };
        else if (k === 'sphere') args = { ...base, radius: v('radius'), segments: iv('segments'), rings: iv('rings') };
        else if (k === 'quadball') args = { ...base, radius: v('radius'), spans: iv('spans') };
        else if (k === 'torus') args = { ...base, major: v('major'), minor: v('minor'), segments_major: iv('segments_major'), segments_minor: iv('segments_minor') };
        else args = { ...base, size: [v('sx'), v('sy')], segments: [iv('nx'), iv('ny')] };
        const r = await runCmd<Json>(`subd${k}`, args);
        await adopt(r);
      }

      async function adopt(r: Json | null): Promise<void> {
        if (!r) return;
        await form.refresh();
        const handles = Array.isArray(r.handles) ? (r.handles as number[]) : [];
        if (handles.length) form.setActive(Number(handles[handles.length - 1]));
        setEditing(true);
        await view3d()?.with3d(() => undefined);
      }

      async function fromSketch(cmd: 'subdextrude' | 'subdrevolve'): Promise<void> {
        const id = docStore.activeId;
        if (!id) return;
        let handle: number | undefined;
        try { handle = (await api.getSelection(id)).handles.map(Number)[0]; } catch { handle = undefined; }
        if (handle === undefined) { toast(t('Select a closed profile (polyline or circle) first.'), 'info'); return; }
        const a = axis.get();
        const dir = a === 'x' ? [1, 0, 0] : a === 'y' ? [0, 1, 0] : [0, 0, 1];
        const args: Json = cmd === 'subdextrude'
          ? { profile: handle, height: height.get() ?? 20, spans: Math.max(1, Math.round(spans.get() ?? 4)), segments: Math.max(3, Math.round(segs.get() ?? 8)) }
          : { profile: handle, axis: { origin: [0, 0, 0], dir }, angle: angle.get() ?? 360, segments: Math.max(3, Math.round(segs.get() ?? 8)) };
        await adopt(await runCmd<Json>(cmd, args));
      }

      async function analyse(): Promise<void> {
        const id = docStore.activeId;
        if (!id || form.active === null) { info.set([t('Create or select a form first.')]); return; }
        try {
          const r = await req<Json>('POST', docUrl(id, `subd/${form.active}/analyze`), {});
          paintInfo(r);
        } catch (e) { info.set([text(e)], true); }
      }

      function paintInfo(r: Json | null): void {
        if (!r) { info.set([t('No form selected.')]); return; }
        const ev = r.extraordinary as unknown;
        const evText = ev && typeof ev === 'object' && !Array.isArray(ev) ? Object.entries(ev as Json).map(([k, v]) => `${t('valence')} ${k} x ${String(v)}`).join(', ') : String(ev ?? '-');
        const conv = r.conversion as Json | undefined;
        const reasons = Array.isArray(conv?.reasons) ? (conv?.reasons as string[]) : [];
        info.set([
          `${num(r.vertices)} ${t('vertices')} · ${num(r.faces)} ${t('faces')} · ${num(r.edges)} ${t('edges')}`,
          `${r.closed ? t('closed') : t('open')} · ${r.manifold ? t('manifold') : t('not manifold')} · ${t('creases')} ${num(r.creases)}`,
          `${t('Extraordinary vertices')}: ${evText}`,
          conv ? (conv.ready ? `${t('Can convert')}: ${num(conv.patches)} ${t('patches')}` : `${t('Cannot convert')}: ${reasons.join(' ')}`) : '',
        ]);
      }

      async function convert(): Promise<void> {
        if (form.active === null) { toast(t('Create or select a form first.'), 'info'); return; }
        setDisabled(bConv, true);
        rep.set([`${t('Converting')}...`]);
        try {
          const r = await runCmd<Json>('subdconvert', { handle: form.active, levels: Number(clevels.get()), keep: keep.get() });
          if (!r) { rep.set([lastCmdError() || t('The conversion did not complete.')], true); return; }
          const report = (r.report ?? {}) as Json;
          const bad = report.valid === false || report.closed === false;
          rep.set([
            `${t('Solid')} #${String(r.handle ?? '-')} · ${report.valid === false ? t('not valid') : t('valid')} · ${report.closed === false ? t('not closed') : t('closed')}`,
            `${num(report.faces)} ${t('faces')} · ${t('free edges')} ${num(report.free_edges)} · ${t('volume')} ${fixed(num(report.volume), 5)}`,
            `${num(report.patches)} ${t('patches')}: ${num(report.regular_patches)} ${t('regular')}, ${num(report.irregular_patches)} ${t('at extraordinary points')}`,
            `${t('Largest edge gap')} ${fixed(num(report.max_gap), 3)} · ${t('largest normal jump')} ${fixed(num(report.max_normal_angle_deg), 3)} deg`,
            `${t('Distance to the limit surface')} ${fixed(num(report.deviation_max), 3)} (rms ${fixed(num(report.deviation_rms), 3)})`,
            `${t('Relative to the diagonal')} ${fixed(num(report.deviation_relative_to_diagonal), 3)}`,
          ], bad);
          setText(contNote, typeof report.continuity_note === 'string' ? report.continuity_note : (Array.isArray(report.notes) ? (report.notes as string[]).join(' ') : ''));
          await form.refresh();
          await view3d()?.with3d(() => undefined);
        } finally { setDisabled(bConv, false); }
      }

      const paint = (): void => {
        const c = form.cage;
        const sel = active.input as HTMLSelectElement;
        const want = ['', ...form.cages.map((x) => String(x.handle))];
        const have = Array.from(sel.options).map((o) => o.value);
        if (want.join('|') !== have.join('|')) sel.replaceChildren(...want.map((v, i) => { const o = document.createElement('option'); o.value = v; o.textContent = i === 0 ? t('None') : (form.cages[i - 1].name || `#${v}`); return o; }));
        sel.value = form.active === null ? '' : String(form.active);
        const unit = form.mode === 'vertex' ? t('vertices') : form.mode === 'edge' ? t('edges') : t('faces');
        count.set(`${form.sel.size} ${unit}`);
        setChecked(soft.input as HTMLInputElement, form.soft.on);
        radius.set(form.soft.radius);
        setDisabled(editBtn, !c);
        setDisabled(bInfo, !c);
        setDisabled(bConv, !c);
        if (c) { level.set(String(c.level)); paintInfo({ ...c.summary }); }
        else paintInfo(null);
      };
      form.onChange((what) => { if (what !== 'tool') paint(); });
      fieldsFor();
      paint();
      void form.refresh();
      return { show: () => { void form.refresh(); } };
    },
  };
}
