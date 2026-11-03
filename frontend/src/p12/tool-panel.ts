import type { DockPanel } from '../ui/dock';
import { el, patchList, q, setClass, setHidden, setText, setValue } from '../ui/dom';
import { t } from '../ui/i18n';
import { toast } from '../ui/toast';
import { docStore } from '../ui/doc-store';
import { button, buttons } from '../u8/ui';
import { cam, type LibTool } from './cam-store';
import { fieldForm, type FieldSpec } from './fields';
import { camUrl, fixed, guard, mini, reportBox, req, section, type Json } from './kit';

const KINDS: Array<[string, string]> = [['flat', 'Flat end mill'], ['ball', 'Ball end mill'], ['bull', 'Bull nose mill'], ['drill', 'Drill'], ['chamfer', 'Chamfer mill'], ['tapered_ball', 'Tapered ball mill'], ['engraver', 'Engraver'], ['insert', 'Turning insert'], ['thread', 'Thread tool'], ['groove', 'Grooving tool'], ['probe', 'Probe'], ['laser', 'Laser head'], ['nozzle', 'Nozzle']];
const n = (label: string, name: string, unit = 'mm'): FieldSpec => ({ name, type: 'number', label, unit });

const TOOL_SPECS: FieldSpec[] = [
  { name: 'number', type: 'int', label: 'Tool number', min: 1, max: 999 },
  { name: 'name', type: 'text', label: 'Name' },
  { name: 'kind', type: 'choice', label: 'Kind', choices: KINDS },
  n('Diameter', 'diameter'), { name: 'flutes', type: 'int', label: 'Flutes', min: 1, max: 20 },
  n('Flute length', 'flute_length'), n('Overall length', 'overall_length'), n('Shank diameter', 'shank_diameter'), n('Corner radius', 'corner_radius'),
  n('Tip angle', 'tip_angle', 'deg'), n('Taper angle', 'taper_angle', 'deg'), n('Stick-out', 'stickout'),
  { name: 'length_offset', type: 'int', label: 'Length offset number' }, { name: 'diameter_offset', type: 'int', label: 'Diameter offset number' },
  { name: 'rpm_max', type: 'number', label: 'Maximum speed', unit: 'rpm' },
  { name: 'coolant', type: 'choice', label: 'Coolant', choices: [['off', 'Off'], ['flood', 'Flood'], ['mist', 'Mist']] },
  { name: 'holder.name', type: 'text', label: 'Holder name' }, n('Collet length', 'holder.collet_length'), n('Gauge length', 'holder.gauge_length'),
  { name: 'notes', type: 'text', label: 'Notes' },
];
const CUT_SPECS: FieldSpec[] = [
  { name: 'vc', type: 'number', label: 'Cutting speed', unit: 'm/min', nullable: true },
  { name: 'fz', type: 'number', label: 'Feed per tooth', unit: 'mm', nullable: true },
  { name: 'plunge_factor', type: 'number', label: 'Plunge factor', nullable: true },
  { name: 'ramp_factor', type: 'number', label: 'Ramp factor', nullable: true },
];

const get = (o: Json, path: string): unknown => path.split('.').reduce<unknown>((c, k) => (c && typeof c === 'object' ? (c as Json)[k] : undefined), o);
function put(o: Json, path: string, v: unknown): void {
  const ks = path.split('.');
  let cur = o;
  ks.forEach((k, i) => { if (i === ks.length - 1) cur[k] = v; else { const nx = (cur[k] && typeof cur[k] === 'object' ? { ...(cur[k] as Json) } : {}) as Json; cur[k] = nx; cur = nx; } });
}

const blank = (): LibTool => ({ number: 1, name: 'New tool', kind: 'flat', diameter: 6, flutes: 2, flute_length: 18, overall_length: 60, shank_diameter: 6, corner_radius: 0, tip_angle: 118, taper_angle: 0, stickout: 30, length_offset: 1, diameter_offset: 1, rpm_max: 18000, coolant: 'off', holder: { name: '', profile: [], collet_length: 0, gauge_length: 0 }, cutting: {}, notes: '' });

const profileText = (p: unknown): string => (Array.isArray(p) ? (p as number[][]).map((r) => r.join(' ')).join('\n') : '');
const parseProfile = (s: string): number[][] => s.split('\n').map((l) => l.trim().split(/[\s,]+/).map(Number)).filter((r) => r.length >= 2 && r.every(Number.isFinite)).map((r) => [r[0], r[1]]);

export function toolPanel(): DockPanel {
  return {
    id: 'camtools', label: 'Tool library', icon: 'cam', order: 41,
    build(body) {
      body.classList.add('u8-panel', 'xw-panel');
      const note = el('<p class="u8-note"></p>');
      setText(note, t('The library is stored in your data folder and starts empty.'));
      const live = el('<div class="u8-live cm-live"></div>');
      body.append(note, live);

      let draft: LibTool = blank();
      let isNew = true;
      let material = '';

      const sLib = section('Tool library');
      const list = el('<div class="u8-list cm-list" role="listbox" aria-label="Tools"></div>');
      const empty = el('<p class="u8-note cm-empty"></p>');
      setText(empty, t('No tools yet. Fill in the form and save.'));
      sLib.body.append(list, empty);

      const sEdit = section('Tool');
      const form = fieldForm(TOOL_SPECS, (name, value) => { put(draft as unknown as Json, name, value); paintDirty(true); });
      const profile = el<HTMLTextAreaElement>('<textarea class="cv-input cm-area" spellcheck="false" rows="4" aria-label="Holder outline"></textarea>');
      profile.placeholder = t('Holder outline, one "radius height" pair per line');
      profile.addEventListener('keydown', (e) => e.stopPropagation());
      profile.addEventListener('change', () => { draft.holder = { ...(draft.holder ?? {}), profile: parseProfile(profile.value) }; paintDirty(true); });
      const dirty = el('<p class="u8-note cm-dirty"></p>');
      const msg = reportBox(2);
      sEdit.body.append(form.el, profile, dirty, msg.el, buttons(
        button('New tool', () => { draft = blank(); isNew = true; material = ''; paint(); }),
        button('Save tool', () => { void save(); }, 'primary'),
        button('Delete tool', () => { void remove(); }),
        button('Use in this document', () => { void useHere(); }),
      ));

      const sCut = section('Cutting data');
      const matSel = el<HTMLSelectElement>('<select class="cv-input cm-matsel" aria-label="Material"></select>');
      const matName = el<HTMLInputElement>('<input class="cv-input" type="text" spellcheck="false" aria-label="New material name">');
      matName.placeholder = t('Material name');
      matName.addEventListener('keydown', (e) => e.stopPropagation());
      const cutForm = fieldForm(CUT_SPECS, (name, value) => {
        if (!material) return;
        const c = { ...(draft.cutting ?? {}) } as Record<string, Json>;
        const row: Json = { ...(c[material] ?? {}) };
        if (value === null) delete row[name]; else row[name] = value;
        c[material] = row;
        draft.cutting = c as LibTool['cutting'];
        paintDirty(true);
      });
      matSel.addEventListener('change', () => { material = matSel.value; paintCut(); });
      sCut.body.append(matSel, matName, buttons(button('Add material', () => {
        const nm = matName.value.trim();
        if (!nm) return;
        draft.cutting = { ...(draft.cutting ?? {}), [nm]: { ...((draft.cutting ?? {})[nm] ?? {}) } };
        material = nm; matName.value = ''; paintDirty(true); paint();
      }), button('Remove material', () => {
        if (!material) return;
        const c = { ...(draft.cutting ?? {}) }; delete c[material]; draft.cutting = c; material = ''; paintDirty(true); paint();
      })), cutForm.el);

      const sCalc = section('Feeds and speeds');
      const calc = fieldForm([
        { name: 'diameter', type: 'number', label: 'Cutter diameter', unit: 'mm' }, { name: 'flutes', type: 'int', label: 'Flutes' },
        { name: 'vc', type: 'number', label: 'Cutting speed', unit: 'm/min', nullable: true }, { name: 'fz', type: 'number', label: 'Feed per tooth', unit: 'mm', nullable: true },
        { name: 'ae', type: 'number', label: 'Radial engagement', unit: 'mm', nullable: true }, { name: 'ap', type: 'number', label: 'Axial depth', unit: 'mm', nullable: true },
      ], () => undefined);
      calc.set({ diameter: 6, flutes: 3, vc: 200, fz: 0.05, ae: 3, ap: 6 });
      const calcOut = reportBox(5);
      sCalc.body.append(calc.el, buttons(button('Calculate', () => { void calculate(); })), calcOut.el);
      live.append(sLib.root, sEdit.root, sCut.root, sCalc.root);

      let isDirty = false;
      function paintDirty(on: boolean): void { isDirty = on; setText(dirty, on ? t('Unsaved changes.') : isNew ? t('Not saved yet.') : t('Saved.')); setClass(dirty, 'is-dirty', on); }

      async function save(): Promise<void> {
        const rec = { ...draft } as Json;
        const r = await guard(() => (isNew || !draft.id ? req<Json>('POST', camUrl('/tools'), rec) : req<Json>('PUT', camUrl(`/tools/${encodeURIComponent(String(draft.id))}`), rec)));
        if (!r) return;
        const saved = (r.tool ?? r) as LibTool;
        await cam.loadLibrary();
        draft = cam.library.find((x) => x.id && x.id === saved.id) ?? { ...draft, ...saved };
        isNew = false;
        msg.set([t('Tool saved.')]);
        paint();
      }

      async function remove(): Promise<void> {
        if (isNew || !draft.id) { draft = blank(); isNew = true; paint(); return; }
        const id = String(draft.id);
        if (await guard(() => req('DELETE', camUrl(`/tools/${encodeURIComponent(id)}`))) !== null) { await cam.loadLibrary(); draft = blank(); isNew = true; msg.set([t('Tool deleted.')]); paint(); }
      }

      async function useHere(): Promise<void> {
        if (!docStore.current()) { toast(t('Open a document first.'), 'info'); return; }
        if (isNew || !draft.id) { await save(); }
        if (!draft.id) return;
        const r = await cam.put('POST', '/tools', { id: draft.id });
        if (r !== null) msg.set([`${t('Tool')} ${draft.number} ${t('added to this document.')}`]);
      }

      async function calculate(): Promise<void> {
        const v = calc.read();
        const body: Json = {};
        for (const [k, x] of Object.entries(v)) if (x !== null) body[k] = x;
        const r = await guard(() => req<Json>('POST', camUrl('/feeds'), body));
        if (!r) return;
        const keys: Array<[string, string, string]> = [['rpm', 'Spindle speed', 'rpm'], ['vf', 'Table feed', 'mm/min'], ['fz', 'Feed per tooth', 'mm'], ['chip_thinning', 'Chip thinning factor', ''], ['removal_rate_cm3_min', 'Removal rate', 'cm3/min']];
        calcOut.set(keys.filter(([k]) => r[k] !== undefined && r[k] !== null).map(([k, l, u]) => `${t(l)} ${fixed(Number(r[k]), 4)} ${u}`.trim()));
      }

      function paintCut(): void {
        const mats = Object.keys(draft.cutting ?? {});
        const sig = mats.join('\u0001');
        if (matSel.dataset.sig !== sig) {
          matSel.dataset.sig = sig;
          matSel.replaceChildren(...mats.map((m) => { const o = document.createElement('option'); o.value = m; o.textContent = m; return o; }));
        }
        if (!mats.includes(material)) material = mats[0] ?? '';
        setValue(matSel, material);
        cutForm.el.classList.toggle('is-off', !material);
        const row = ((draft.cutting ?? {})[material] ?? {}) as Json;
        cutForm.set({ vc: row.vc ?? null, fz: row.fz ?? null, plunge_factor: row.plunge_factor ?? null, ramp_factor: row.ramp_factor ?? null });
      }

      function paint(): void {
        setHidden(empty, cam.library.length > 0);
        patchList(list, cam.library, {
          key: (x) => String(x.id ?? x.number),
          create: (x) => {
            const r = el('<div class="u8-row cm-row-t" role="option"><span class="u8-row-sub"></span><span class="u8-row-name"></span><span class="u8-badge"></span><span class="u8-acts"></span></div>');
            q(r, '.u8-acts').append(mini('x', 'Delete this tool', () => { draft = x; isNew = false; void remove(); }));
            r.addEventListener('click', () => { draft = JSON.parse(JSON.stringify(x)) as LibTool; isNew = false; paint(); });
            return r;
          },
          update: (r, x) => {
            setText(q(r, '.u8-row-sub'), `T${x.number}`);
            setText(q(r, '.u8-row-name'), x.name);
            setText(q(r, '.u8-badge'), t(KINDS.find((k) => k[0] === x.kind)?.[1] ?? x.kind));
            setClass(r, 'is-selected', !isNew && draft.id === x.id);
          },
        });
        const flat: Record<string, unknown> = {};
        for (const sp of TOOL_SPECS) flat[sp.name] = get(draft as unknown as Json, sp.name);
        form.set(flat);
        const pt = profileText(draft.holder?.profile);
        if (profile.value !== pt && document.activeElement !== profile) profile.value = pt;
        paintDirty(isDirty);
        paintCut();
      }

      cam.onChange(() => { if (!isNew && draft.id) { const cur = cam.library.find((x) => x.id === draft.id); if (cur && document.activeElement && !live.contains(document.activeElement)) draft = JSON.parse(JSON.stringify(cur)) as LibTool; } paint(); });
      void cam.loadGlobal().then(paint);
      paint();
      setHidden(note, false);
    },
  };
}
