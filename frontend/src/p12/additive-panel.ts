import { events } from '../io/events';
import type { DockPanel } from '../ui/dock';
import { docStore } from '../ui/doc-store';
import { el, patchList, q, setClass, setHidden, setText } from '../ui/dom';
import { pickPath } from '../ui/file-dialogs';
import { t } from '../ui/i18n';
import { gate, MODEL } from '../ui/panel-gate';
import { toast } from '../ui/toast';
import { buffer } from '../u8/net';
import { button, buttons, checkCtl, selectCtl } from '../u8/ui';
import { view3d } from '../view3d/mount';
import { fieldForm, prettify, type FieldForm, type FieldSpec } from './fields';
import { docAdd, fillSelect, fixed, guard, mini, progressBar, reportBox, req, secs, section, text, type Json } from './kit';
import { FEATURE_NAMES, LayerPreview, parsePack, type PreviewMode } from './layer-preview';

export const previewView: { layer: LayerPreview | null } = { layer: null };

interface Profile { id: string; name: string; preset?: string; settings: Json }
interface Item { body: number; orient?: number[]; rot_z?: number; x: number; y: number; lift?: number; state?: string }
interface Plate { id: string; name: string; profile: string; bed: number[]; spacing: number; metal: boolean; items: Item[]; last: null | { hash?: string; layers?: number; filament_mm?: number; time_s?: number; support_volume_mm3?: number }; stale?: boolean }
interface Defaults { settings: Record<string, { default: unknown; min?: number | null; max?: number | null; unit?: string; kind: string; choices?: unknown; group?: string; label?: string }>; presets: Record<string, unknown> }
interface Candidate { rank: number; rotation: number[]; label: string; score: number; terms: Record<string, number> }

const PRESETS: Array<[string, string]> = [['balanced', 'Balanced'], ['quality', 'Surface quality'], ['speed', 'Print speed'], ['strength', 'Strength'], ['metal', 'Metal part']];

const state: { profiles: Profile[]; plates: Plate[]; defaults: Defaults | null; plate: string; profile: string; sliced: boolean } = { profiles: [], plates: [], defaults: null, plate: '', profile: '', sliced: false };
const subs = new Set<() => void>();
let timer = 0;
let busy = false;
let again = false;

async function refresh(): Promise<void> {
  if (busy) { again = true; return; }
  const id = docStore.activeId;
  if (!id) { if (state.plates.length || state.profiles.length) { state.plates = []; state.profiles = []; for (const f of subs) f(); } return; }
  busy = true;
  try {
    do {
      again = false;
      const d = await req<{ profiles: Profile[]; plates: Plate[] }>('GET', docAdd()).catch(() => null);
      if (id !== docStore.activeId) break;
      if (d) {
        state.profiles = d.profiles ?? [];
        state.plates = d.plates ?? [];
        if (!state.plates.some((p) => p.id === state.plate)) state.plate = state.plates[0]?.id ?? '';
        if (!state.profiles.some((p) => p.id === state.profile)) state.profile = state.plates.find((p) => p.id === state.plate)?.profile ?? state.profiles[0]?.id ?? '';
        for (const f of subs) f();
      }
      if (!state.defaults) {
        const df = await req<Defaults>('GET', docAdd('/defaults')).catch(() => null);
        if (df) { state.defaults = df; for (const f of subs) f(); }
      }
    } while (again);
  } finally { busy = false; }
}
const schedule = (delay = 150): void => { if (timer) return; timer = window.setTimeout(() => { timer = 0; void refresh(); }, delay); };
const addGate = gate(['additive'], MODEL, () => schedule(0));
events.on('doc', (e) => { if (e.id === docStore.activeId && addGate()) schedule(); });
docStore.onChange(() => { if (addGate()) schedule(50); });

export function additivePanel(): DockPanel {
  return {
    id: 'additive', label: 'Print', icon: 'layers', order: 45,
    build(body) {
      body.classList.add('u8-panel', 'xw-panel');
      const note = el('<p class="u8-note"></p>');
      setText(note, t('Open a part to prepare it for printing.'));
      const live = el('<div class="u8-live cm-live"></div>');
      body.append(note, live);
      const paintShell = (): void => { const on = !!docStore.current(); setHidden(note, on); setHidden(live, !on); };
      const plate = (): Plate | undefined => state.plates.find((p) => p.id === state.plate);
      const profile = (): Profile | undefined => state.profiles.find((p) => p.id === state.profile);
      const turl = (tail: string): string => docAdd(`/plates/${encodeURIComponent(state.plate)}${tail}`);
      const act = async <T = Json>(method: 'POST' | 'PATCH' | 'DELETE', url: string, b?: unknown): Promise<T | null> => { const r = await guard(() => req<T>(method, url, b)); schedule(0); return r; };

      const sPlates = section('Plates');
      const plist = el('<div class="u8-list cm-list" role="listbox" aria-label="Plates"></div>');
      const pempty = el('<p class="u8-note cm-empty"></p>');
      setText(pempty, t('No plates yet. A new plate takes every visible solid and mesh body.'));
      const plateForm = fieldForm([
        { name: 'name', type: 'text', label: 'Name' },
        { name: 'profile', type: 'choice', label: 'Profile', choices: [] },
        { name: 'bed', type: 'vec2', label: 'Bed size (x y)', unit: 'mm' },
        { name: 'spacing', type: 'number', label: 'Spacing', unit: 'mm', min: 0, max: 100 },
        { name: 'metal', type: 'bool', label: 'Metal part preparation' },
      ], (n, v) => { void act('PATCH', turl(''), { [n]: v }); });
      const ilist = el('<div class="u8-list cm-list is-short" role="listbox" aria-label="Plate items"></div>');
      sPlates.body.append(plist, pempty, buttons(
        button('New plate', () => { void act('POST', docAdd('/plates'), {}).then((r) => { const id = r ? String((r as Json).id ?? ((r as Json).plate as Json | undefined)?.id ?? '') : ''; if (id) { state.plate = id; } void refresh(); }); }, 'primary'),
        button('Delete plate', () => { if (state.plate) void act('DELETE', turl('')); }),
        button('Arrange', () => { void arrange(); }),
      ), plateForm.el, ilist);

      const sProf = section('Slicer profile');
      const profSel = selectCtl('Profile', [], () => { state.profile = profSel.get(); paint(); });
      const newName = el<HTMLInputElement>('<input class="cv-input" type="text" spellcheck="false" aria-label="New profile name">');
      newName.placeholder = t('New profile name');
      newName.addEventListener('keydown', (e) => e.stopPropagation());
      const presetSel = selectCtl('Start from', [['draft', 'Draft'], ['standard', 'Standard'], ['fine', 'Fine'], ['metal', 'Metal']]);
      const setBox = el('<div class="cm-scroll cm-settings"></div>');
      let setForm: FieldForm | null = null;
      sProf.body.append(profSel.el, newName, presetSel.el, buttons(
        button('New profile', () => { void act('POST', docAdd('/profiles'), { name: newName.value.trim() || 'Profile', preset: presetSel.get() }).then((r) => { const id = r ? String((r as Json).id ?? ((r as Json).profile as Json | undefined)?.id ?? '') : ''; if (id) state.profile = id; newName.value = ''; void refresh(); }); }, 'primary'),
        button('Delete profile', () => { if (state.profile) void act('DELETE', docAdd(`/profiles/${encodeURIComponent(state.profile)}`)); }),
      ), setBox);

      const sOrient = section('Orientation');
      const orientPreset = selectCtl('Aim for', PRESETS);
      const clist = el('<div class="u8-list cm-list" role="listbox" aria-label="Orientations"></div>');
      const cempty = el('<p class="u8-note cm-empty"></p>');
      setText(cempty, t('Run the study to rank orientations of the first item.'));
      const orientMsg = reportBox(2);
      let cands: Candidate[] = [];
      sOrient.body.append(orientPreset.el, buttons(button('Rank orientations', () => { void orient(); }, 'primary')), clist, cempty, orientMsg.el);

      const sSlice = section('Slice and export');
      const bar = progressBar();
      const report = reportBox(6);
      const checks = el('<div class="u8-list cm-list is-short" role="listbox" aria-label="Checks"></div>');
      const outKind = selectCtl('File', [['gcode', 'G-code'], ['3mf', '3MF build plate']]);
      const outName = el<HTMLInputElement>('<input class="cv-input cm-path" type="text" spellcheck="false" aria-label="Output file">');
      outName.placeholder = t('Output file (blank asks)');
      outName.addEventListener('keydown', (e) => e.stopPropagation());
      const gpre = el('<pre class="cm-pre" tabindex="0" aria-label="G-code"></pre>');
      sSlice.body.append(
        buttons(button('Slice', () => { void slice(); }, 'primary'), button('Check plate', () => { void runChecks(); }), button('Show G-code', () => { void gcode(); })),
        bar.el, report.el, checks, outKind.el, outName, buttons(button('Export...', () => { void exportFile(); })), gpre,
      );

      const sPrev = section('Layer preview');
      const lp = (): LayerPreview | null => previewView.layer;
      const showPrev = checkCtl('Show the layer preview', true, () => { lp()?.setShown(showPrev.get()); });
      const modeSel = selectCtl('Draw as', [['lines', 'Lines'], ['solid', 'Solid beads']], () => { lp()?.setMode(modeSel.get() as PreviewMode); applyRange(); });
      const mkSlider = (label: string): { row: HTMLElement; input: HTMLInputElement; out: HTMLElement } => {
        const row = el('<div class="cm-sliderrow"><span class="cm-sl-label"></span></div>');
        setText(q(row, '.cm-sl-label'), t(label));
        const input = el<HTMLInputElement>(`<input class="cm-slider" type="range" min="0" max="0" value="0" aria-label="${t(label)}">`);
        const out = el('<output class="cm-out"></output>');
        row.append(input, out);
        return { row, input, out };
      };
      const lo = mkSlider('Lowest layer'), hi = mkSlider('Top layer');
      const info = reportBox(3);
      const legend = el('<div class="cm-legend"></div>');
      const swatches: HTMLElement[] = [];
      FEATURE_NAMES.forEach((name, i) => {
        const r = el('<span class="cm-chip"><i class="cm-sw"></i><span></span></span>');
        setText(q(r, 'span'), t(name));
        (q(r, '.cm-sw') as HTMLElement).dataset.f = String(i);
        swatches.push(q(r, '.cm-sw'));
        legend.appendChild(r);
      });
      const showTravel = checkCtl('Show travel moves', false, () => { lp()?.setGroup('travel', showTravel.get()); });
      const showSupport = checkCtl('Show supports', true, () => { lp()?.setGroup('support', showSupport.get()); });
      const hideModel = checkCtl('Hide the model', true, () => { view3d()?.vp?.setBodiesHidden(hideModel.get() && !!lp()?.has); });
      let anim = 0;
      const playBtn = button('Play', () => {
        const l = lp();
        if (!l?.has) return;
        if (anim) { clearInterval(anim); anim = 0; setText(playBtn, t('Play')); return; }
        setText(playBtn, t('Pause'));
        if (Number(hi.input.value) >= l.layers - 1) { hi.input.value = '0'; applyRange(); }
        const step = Math.max(1, Math.round(l.layers / 120));
        anim = window.setInterval(() => {
          const v = Number(hi.input.value) + step;
          if (v >= l.layers - 1) { hi.input.value = String(l.layers - 1); applyRange(); clearInterval(anim); anim = 0; setText(playBtn, t('Play')); return; }
          hi.input.value = String(v); applyRange();
        }, 60);
      });
      playBtn.classList.add('cm-playbtn');
      sPrev.body.append(showPrev.el, modeSel.el, lo.row, hi.row, info.el, buttons(playBtn, button('Load preview', () => { void loadPreview(); })), showTravel.el, showSupport.el, hideModel.el, legend);

      live.append(sPlates.root, sProf.root, sOrient.root, sSlice.root, sPrev.root);

      function applyRange(): void {
        const l = lp();
        if (!l?.has) return;
        let a = Number(lo.input.value), b = Number(hi.input.value);
        if (a > b) { if (document.activeElement === lo.input) b = a; else a = b; lo.input.value = String(a); hi.input.value = String(b); }
        l.setRange(a, b);
        setText(lo.out, String(a + 1));
        setText(hi.out, String(b + 1));
        const li = l.layerInfo(b);
        const total = l.header?.totals;
        info.set([
          li ? `${t('Layer')} ${b + 1} ${t('of')} ${l.layers} · z ${fixed(li.z, 4)} mm` : '',
          li ? `${t('This layer')}: ${secs(li.time_s)}, ${fixed(li.filament_mm, 4)} mm ${t('filament')}` : '',
          l.currentMode === 'solid' && l.solidFrom > a ? `${t('Solid beads from layer')} ${l.solidFrom + 1}` : total ? `${t('Total')}: ${secs(total.time_s)}, ${fixed(total.filament_mm / 1000, 4)} m` : '',
        ]);
      }
      lo.input.addEventListener('input', applyRange);
      hi.input.addEventListener('input', applyRange);

      async function loadPreview(): Promise<void> {
        const l = lp();
        if (!l || !state.plate) return;
        const buf = await guard(() => buffer(turl('/layers')));
        if (!buf) { info.set([t('Slice the plate first.')]); return; }
        let pack;
        try { pack = parsePack(buf); } catch (e) { toast(text(e), 'error'); return; }
        l.setColors(document.body);
        l.load(pack);
        const p = plate();
        if (p?.bed?.length === 2) l.setBed(p.bed[0], p.bed[1]);
        const n = pack.header.layer_count;
        for (const s of [lo.input, hi.input]) { s.max = String(Math.max(0, n - 1)); }
        lo.input.value = '0'; hi.input.value = String(Math.max(0, n - 1));
        swatches.forEach((sw, i) => { sw.style.background = l.colorOf(i); });
        modeSel.input.querySelector('option[value=solid]')?.toggleAttribute('disabled', !l.solidAllowed);
        applyRange();
        view3d()?.vp?.setBodiesHidden(hideModel.get());
        fitView();
      }

      function fitView(): void {
        const vp = view3d()?.vp as unknown as { fit?: () => void; zoomExtents?: () => void } | undefined;
        vp?.zoomExtents?.();
        vp?.fit?.();
      }

      async function arrange(): Promise<void> {
        if (!state.plate) return;
        const r = await act<Json>('POST', turl('/arrange'), {});
        const rep = r?.report as Json | undefined;
        if (rep) toast(`${t('Placed')} ${String(rep.placed ?? '')}, ${t('utilisation')} ${fixed(Number(rep.utilisation ?? 0) * 100, 3)} %`, 'info');
      }

      async function orient(): Promise<void> {
        const p = plate();
        if (!p?.items.length) { toast(t('Add bodies to the plate first.'), 'info'); return; }
        const r = await guard(() => req<{ candidates: Candidate[]; evaluated: number }>('POST', docAdd('/orient'), { bodies: [p.items[0].body], preset: orientPreset.get(), profile: p.profile }));
        if (!r) return;
        cands = r.candidates ?? [];
        orientMsg.set([`${t('Evaluated')} ${r.evaluated}`, cands[0] ? `${t('Best')}: ${cands[0].label}` : '']);
        paintCands();
      }

      async function slice(): Promise<void> {
        if (!state.plate) { toast(t('Make a plate first.'), 'info'); return; }
        bar.onCancel(() => { void req('POST', docAdd('/cancel')).catch(() => undefined); });
        bar.set(0, `${t('Slicing')} · 0 %`, true);
        const r = await guard(() => req<{ summary: Json; warnings: string[]; hash: string }>('POST', turl('/slice'), {}));
        bar.set(1, '', false);
        schedule(0);
        if (!r) return;
        const s = r.summary;
        report.set([
          `${t('Layers')} ${String(s.layers)}`,
          `${t('Filament')} ${fixed(Number(s.filament_mm) / 1000, 4)} m, ${fixed(Number(s.filament_g), 4)} g`,
          `${t('Print time')} ${secs(Number(s.time_s))}`,
          `${t('Support volume')} ${fixed(Number(s.support_volume_mm3), 5)} mm3`,
          `${t('G-code lines')} ${String(s.lines)}`,
          ...(r.warnings ?? []).slice(0, 1),
        ], (r.warnings ?? []).length > 0);
        await loadPreview();
        await gcode();
      }

      async function gcode(): Promise<void> {
        if (!state.plate) return;
        const r = await req<{ lines: string[]; total: number }>('GET', turl('/gcode?from=0&count=120')).catch(() => null);
        if (!r) return;
        const shown = r.lines.join('\n');
        if (gpre.textContent !== shown) gpre.textContent = shown;
        gpre.title = `${r.total} ${t('lines')}`;
      }

      async function runChecks(): Promise<void> {
        if (!state.plate) return;
        const r = await guard(() => req<{ warnings: Array<{ kind: string; severity: string; message: string; where?: unknown }> }>('POST', turl('/checks'), {}));
        const rows = r?.warnings ?? [];
        patchList(checks, rows.map((w, i) => ({ ...w, key: `${i}:${w.kind}` })), {
          key: (w) => w.key,
          create: () => el('<div class="u8-row cm-row-i"><span class="u8-row-sub"></span><span class="u8-row-name"></span></div>'),
          update: (rr, w) => { setText(q(rr, '.u8-row-sub'), w.severity.slice(0, 1).toUpperCase()); const n = q(rr, '.u8-row-name'); setText(n, w.message); n.title = w.message; },
        });
        if (r && !rows.length) toast(t('No problems found on this plate.'), 'info');
      }

      async function exportFile(): Promise<void> {
        if (!state.plate) return;
        const kind = outKind.get();
        const name = outName.value.trim() || await pickPath('save', t('Export'), kind === '3mf' ? 'plate.3mf' : 'plate.gcode', [{ name: kind === '3mf' ? '3MF' : 'G-code', extensions: [kind === '3mf' ? '3mf' : 'gcode'] }], t('Export'));
        if (!name) return;
        const r = await guard(() => req<Json>('POST', turl('/export'), { kind, path: name }));
        if (r) toast(`${t('Wrote')} ${String(r.path ?? name)} (${String(r.bytes ?? '')} B)`, 'info');
      }

      function paintCands(): void {
        setHidden(cempty, cands.length > 0);
        patchList(clist, cands, {
          key: (c) => String(c.rank),
          create: (c) => {
            const r = el('<div class="u8-row cm-row-c" role="option"><span class="u8-row-sub"></span><span class="u8-row-name"></span><span class="u8-acts"></span></div>');
            q(r, '.u8-acts').append(mini('Use', 'Use this orientation', () => { const p = plate(); if (p?.items[0]) void act('POST', turl('/orient'), { body: p.items[0].body, rotation: c.rotation }); }));
            return r;
          },
          update: (r, c) => {
            setText(q(r, '.u8-row-sub'), `#${c.rank}`);
            const n = q(r, '.u8-row-name');
            const tm = c.terms ?? {};
            setText(n, `${c.label} · ${t('support')} ${fixed(tm.support_volume_mm3, 4)} mm3 · ${t('height')} ${fixed(tm.height_mm, 4)} mm`);
            n.title = n.textContent ?? '';
          },
        });
      }

      function paintSettings(): void {
        const df = state.defaults;
        if (!df) return;
        if (!setForm) {
          const specs: FieldSpec[] = Object.entries(df.settings).map(([k, v]) => ({ name: k, type: v.kind, default: v.default, label: v.label ?? prettify(k), min: v.min ?? null, max: v.max ?? null, unit: v.unit ?? '', choices: v.choices, group: v.group ?? '' }));
          setForm = fieldForm(specs, (name, value) => { const p = profile(); if (p) void act('PATCH', docAdd(`/profiles/${encodeURIComponent(p.id)}`), { settings: { [name]: value } }); }, { grouped: true });
          setBox.appendChild(setForm.el);
        }
        const p = profile();
        setForm.el.classList.toggle('is-off', !p);
        if (p) setForm.set(p.settings ?? {});
      }

      function paint(): void {
        paintShell();
        const pl = plate();
        setHidden(pempty, state.plates.length > 0);
        patchList(plist, state.plates, {
          key: (p) => p.id,
          create: (p) => { const r = el('<div class="u8-row cm-row-s" role="option"><span class="u8-row-sub"></span><span class="u8-row-name"></span><span class="u8-badge"></span></div>'); r.addEventListener('click', () => { state.plate = p.id; state.profile = state.plates.find((x) => x.id === p.id)?.profile ?? state.profile; paint(); }); return r; },
          update: (r, p) => {
            setText(q(r, '.u8-row-sub'), p.id);
            setText(q(r, '.u8-row-name'), `${p.name} · ${p.items.length} ${t(p.items.length === 1 ? 'item' : 'items')}`);
            const b = q(r, '.u8-badge');
            setText(b, p.last ? (p.stale ? t('stale') : t('sliced')) : t('new'));
            b.dataset.s = p.last ? (p.stale ? 'under' : 'fully') : '';
            setClass(r, 'is-selected', p.id === state.plate);
          },
        });
        plateForm.el.classList.toggle('is-off', !pl);
        const psel = plateForm.rowOf('profile')?.querySelector('select');
        if (psel) fillSelect(psel, state.profiles.map((p) => [p.id, p.name] as [string, string]));
        if (pl) plateForm.set({ name: pl.name, profile: pl.profile, bed: pl.bed, spacing: pl.spacing, metal: pl.metal });
        patchList(ilist, pl?.items ?? [], {
          key: (it) => String(it.body),
          create: (it) => { const r = el('<div class="u8-row cm-row-i"><span class="u8-row-sub"></span><span class="u8-row-name"></span><span class="u8-badge"></span></div>'); void it; return r; },
          update: (r, it) => { setText(q(r, '.u8-row-sub'), `#${it.body}`); setText(q(r, '.u8-row-name'), `x ${fixed(it.x, 4)}  y ${fixed(it.y, 4)}  rz ${fixed(it.rot_z ?? 0, 4)}`); const b = q(r, '.u8-badge'); setText(b, it.state ?? 'ok'); b.dataset.s = !it.state || it.state === 'ok' ? 'fully' : 'conflict'; },
        });
        fillSelect(profSel.input as HTMLSelectElement, state.profiles.map((p) => [p.id, p.name] as [string, string]));
        if (profSel.get() !== state.profile && document.activeElement !== profSel.input) profSel.set(state.profile);
        paintSettings();
        if (pl?.bed?.length === 2) lp()?.setBed(pl.bed[0], pl.bed[1]);
      }

      events.on('additivejob', (e) => {
        if (e.id !== docStore.activeId) return;
        if (e.state === 'progress' || e.state === 'start') { const f = Number(e.progress ?? 0); bar.set(f, `${String(e.phase ?? t('Slicing'))} · ${Math.round(f * 100)} %`, true); }
        if (e.state === 'end') bar.set(1, '', false);
      });

      subs.add(paint);
      paintShell();
      paint();
      paintCands();
      schedule(0);
      void orientMsg;
    },
  };
}
