import type { DockPanel } from '../ui/dock';
import { docStore } from '../ui/doc-store';
import { el, patchList, q, setClass, setHidden, setText, setValue } from '../ui/dom';
import { pickPath } from '../ui/file-dialogs';
import { t } from '../ui/i18n';
import { toast } from '../ui/toast';
import { button, buttons, selectCtl } from '../u8/ui';
import { cam, labelOf } from './cam-store';
import { fieldForm, type FieldForm, type FieldSpec } from './fields';
import { camUrl, docCam, fillSelect, fixed, guard, reportBox, req, section, type Json } from './kit';

interface Machine extends Json { id: string; name: string; c_axis: boolean; live_tools: boolean; y_axis: boolean; post: string; mode_lines: { turn: string[]; mill: string[] } }
interface Cycle { kind: string; defaults: Json; limits: Record<string, number[]> }

const SAMPLE = '{"units": "diameter", "pts": [{"z": 0, "d": 16}, {"z": -20, "d": 16, "chamfer": 1}, {"z": -20, "d": 24}, {"z": -45, "d": 24}]}';
const MODES: Array<[string, string]> = [['', 'Not assigned'], ['turn', 'Turning'], ['mill', 'Milling']];

const specOf = (name: string, v: unknown, limits: Record<string, number[]>): FieldSpec => {
  const lim = limits[name];
  if (typeof v === 'boolean') return { name, type: 'bool', label: name.replace(/_/g, ' ') };
  if (typeof v === 'string') return { name, type: 'text', label: name.replace(/_/g, ' ') };
  return { name, type: Number.isInteger(v) ? 'int' : 'number', label: name.replace(/_/g, ' '), min: lim?.[0] ?? null, max: lim?.[1] ?? null };
};

export function lathePanel(): DockPanel {
  return {
    id: 'camturn', label: 'Turning, probing and mill-turn', icon: 'cam', order: 44,
    build(body) {
      body.classList.add('u8-panel', 'xw-panel');
      const note = el('<p class="u8-note"></p>');
      setText(note, t('Open a part or assembly to check turning profiles, build probing cycles and set up a mill-turn machine.'));
      const live = el('<div class="u8-live cm-live"></div>');
      body.append(note, live);
      const paintShell = (): void => { const on = !!docStore.current(); setHidden(note, on); setHidden(live, !on); };

      const sTurn = section('Turning profile');
      const profile = el<HTMLTextAreaElement>('<textarea class="cv-input cm-area" spellcheck="false" rows="5" aria-label="Turning profile"></textarea>');
      profile.value = SAMPLE;
      profile.addEventListener('keydown', (e) => e.stopPropagation());
      const turnOut = reportBox(4);
      const thread = fieldForm([
        { name: 'pitch', type: 'number', label: 'Thread pitch', unit: 'mm', min: 0.01, max: 50 },
        { name: 'passes', type: 'int', label: 'Passes', min: 1, max: 40 },
      ], () => undefined);
      thread.set({ pitch: 1.5, passes: 6 });
      const threadOut = reportBox(3);
      sTurn.body.append(profile, buttons(button('Check profile', () => { void checkProfile(); })), turnOut.el, thread.el, buttons(button('Thread pass depths', () => { void threadDepths(); })), threadOut.el);

      const sProbe = section('Probing cycle');
      const kindSel = selectCtl('Cycle', []);
      const probeHost = el('<div class="cm-probeforms"></div>');
      const probeOut = reportBox(5);
      sProbe.body.append(kindSel.el, probeHost, buttons(button('Build cycle', () => { void buildProbe(); }, 'primary')), probeOut.el);

      const sMach = section('Mill-turn machine');
      const mList = el('<div class="u8-list cm-list is-short" role="listbox" aria-label="Mill-turn machines"></div>');
      const mEmpty = el('<p class="u8-note cm-empty"></p>');
      setText(mEmpty, t('No mill-turn machine yet. Save the form to add one.'));
      const mForm: FieldForm = fieldForm([
        { name: 'name', type: 'text', label: 'Name' },
        { name: 'c_axis', type: 'bool', label: 'C axis' },
        { name: 'live_tools', type: 'bool', label: 'Live tools' },
        { name: 'y_axis', type: 'bool', label: 'Y axis' },
        { name: 'post', type: 'text', label: 'Post' },
      ], () => undefined);
      const turnLines = el<HTMLTextAreaElement>('<textarea class="cv-input cm-area" spellcheck="false" rows="3" aria-label="Lines written when switching to turning"></textarea>');
      const millLines = el<HTMLTextAreaElement>('<textarea class="cv-input cm-area" spellcheck="false" rows="3" aria-label="Lines written when switching to milling"></textarea>');
      turnLines.placeholder = t('Lines for the change to turning, one per line');
      millLines.placeholder = t('Lines for the change to milling, one per line');
      for (const a of [turnLines, millLines]) a.addEventListener('keydown', (e) => e.stopPropagation());
      const mOut = reportBox(5);
      const mPath = el<HTMLInputElement>('<input class="cv-input cm-path" type="text" spellcheck="false" aria-label="Output file">');
      mPath.placeholder = t('Output file (blank asks)');
      mPath.addEventListener('keydown', (e) => e.stopPropagation());
      sMach.body.append(
        mList, mEmpty, mForm.el, turnLines, millLines,
        buttons(button('New machine', () => { selected = ''; paintMachine(); }), button('Save machine', () => { void saveMachine(); }, 'primary'), button('Check', () => { void checkMachine(); }), button('Export code...', () => { void exportMachine(); })),
        mPath, mOut.el,
      );

      const sAssign = section('Setup modes');
      const aList = el('<div class="u8-list cm-list" role="listbox" aria-label="Setup modes"></div>');
      const aEmpty = el('<p class="u8-note cm-empty"></p>');
      setText(aEmpty, t('No setups yet.'));
      sAssign.body.append(aList, aEmpty);

      live.append(sTurn.root, sProbe.root, sMach.root, sAssign.root);

      let machines: Machine[] = [];
      let selected = '';
      let cycles: Cycle[] = [];
      const probeForms = new Map<string, FieldForm>();

      async function checkProfile(): Promise<void> {
        let spec: Json;
        try { spec = JSON.parse(profile.value) as Json; } catch { turnOut.set([t('The profile is not valid JSON.')], true); return; }
        const r = await guard(() => req<Json>('POST', camUrl('/turning/profile'), { profile: spec }));
        if (!r) { turnOut.set([t('The profile was refused.')], true); return; }
        const pts = (r.pts as number[][] | undefined) ?? [];
        turnOut.set([`${pts.length} ${t('points')}`, `${t('Length')} ${fixed(Number(r.length), 4)} mm`, `${t('Largest diameter')} ${fixed(Number(r.max_diameter), 4)} mm`, r.monotonic ? t('The profile can be turned in one direction.') : t('The profile has undercuts.')], !r.monotonic);
      }

      async function threadDepths(): Promise<void> {
        const v = thread.read();
        const r = await guard(() => req<Json>('POST', camUrl('/turning/thread'), { pitch: v.pitch, passes: v.passes }));
        if (!r) return;
        const d = (r.pass_depths as number[] | undefined) ?? [];
        threadOut.set([`${t('Thread depth')} ${fixed(Number(r.depth), 4)} mm`, `${d.length} ${t('passes')}`, d.map((x) => fixed(x, 3)).join(', ')]);
      }

      const curKind = (): string => kindSel.get();

      async function buildProbe(): Promise<void> {
        const kind = curKind();
        const form = probeForms.get(kind);
        if (!kind || !form) return;
        const params: Json = {};
        for (const [k, v] of Object.entries(form.read())) if (v !== null && v !== undefined) params[k] = v;
        const r = await guard(() => req<Json>('POST', camUrl('/probing/build'), { kind, params }));
        if (!r) { probeOut.set([t('The cycle was refused.')], true); return; }
        const outs = Object.entries((r.outputs as Record<string, Json> | undefined) ?? {});
        probeOut.set([`${(r.moves as unknown[] | undefined)?.length ?? 0} ${t('moves')}`, ...outs.slice(0, 4).map(([k, o]) => `${k}: ${String(o.label ?? o.expr ?? '')}${o.unit ? ` (${String(o.unit)})` : ''}`)]);
      }

      function paintProbe(): void {
        const kinds = cycles.map((c) => [c.kind, c.kind.replace(/_/g, ' ')] as [string, string]);
        fillSelect(kindSel.input as HTMLSelectElement, kinds);
        for (const c of cycles) {
          if (probeForms.has(c.kind)) continue;
          const specs = Object.entries(c.defaults).map(([k, v]) => specOf(k, v, c.limits));
          const f = fieldForm(specs, () => undefined);
          f.set(c.defaults);
          f.el.classList.add('is-away');
          probeForms.set(c.kind, f);
          probeHost.append(f.el);
        }
        for (const [k, f] of probeForms) setClass(f.el, 'is-away', k !== curKind());
      }
      (kindSel.input as HTMLSelectElement).addEventListener('change', paintProbe);

      async function loadMachines(): Promise<void> {
        if (!docStore.current()) { machines = []; paintMachine(); return; }
        const r = await req<{ machines?: Machine[] }>('GET', docCam('/machines')).catch(() => null);
        if (!r) return;
        const next = r.machines ?? [];
        if (JSON.stringify(next) === JSON.stringify(machines)) return;
        machines = next;
        paintMachine();
      }

      const lines = (s: string): string[] => s.split('\n').map((x) => x.trim()).filter(Boolean);

      async function saveMachine(): Promise<void> {
        const v = mForm.read();
        const rec = { name: String(v.name ?? ''), c_axis: !!v.c_axis, live_tools: !!v.live_tools, y_axis: !!v.y_axis, post: String(v.post ?? ''), mode_lines: { turn: lines(turnLines.value), mill: lines(millLines.value) } };
        const r = await guard(() => req<Json>('PUT', docCam(`/machines/${selected ? encodeURIComponent(selected) : 'new'}`), rec));
        if (!r) return;
        selected = String(r.id ?? selected);
        mOut.set([`${t('Saved machine')} ${selected}`]);
        await loadMachines();
      }

      async function checkMachine(): Promise<void> {
        if (!selected) { mOut.set([t('Save the machine first.')], true); return; }
        const r = await guard(() => req<Json>('POST', docCam(`/machines/${encodeURIComponent(selected)}/check`)));
        if (!r) return;
        const issues = (r.issues as Array<{ level?: string; text?: string }> | undefined) ?? [];
        const rows = (r.setups as Array<{ setup: string; mode: string }> | undefined) ?? [];
        mOut.set([`${rows.length} ${t('setups')}: ${rows.map((x) => `${x.setup} ${x.mode}`).join(', ')}`, ...issues.slice(0, 4).map((i) => String(i.text ?? ''))], issues.some((i) => i.level === 'error'));
      }

      async function exportMachine(): Promise<void> {
        if (!selected) { mOut.set([t('Save the machine first.')], true); return; }
        const name = mPath.value.trim() || await pickPath('save', t('Export machine code'), 'millturn.ngc', [{ name: 'Machine code', extensions: ['ngc'] }], t('Export'));
        if (!name) return;
        const r = await guard(() => req<Json>('POST', docCam(`/machines/${encodeURIComponent(selected)}/export`), { path: name }));
        if (r) { mOut.set([`${t('Wrote')} ${String(r.path ?? name)}`, `${String(r.lines ?? '')} ${t('lines')}`.trim()]); toast(t('Machine code written.'), 'info'); }
      }

      function paintMachine(): void {
        setHidden(mEmpty, machines.length > 0);
        patchList(mList, machines, {
          key: (m) => m.id,
          create: (m) => { const r = el('<div class="u8-row" role="option"><span class="u8-row-sub"></span><span class="u8-row-name"></span></div>'); r.addEventListener('click', () => { selected = m.id; paintMachine(); }); return r; },
          update: (r, m) => { setText(q(r, '.u8-row-sub'), m.id); setText(q(r, '.u8-row-name'), m.name); setClass(r, 'is-selected', m.id === selected); },
        });
        const m = machines.find((x) => x.id === selected);
        if (document.activeElement && live.contains(document.activeElement) && mForm.el.contains(document.activeElement)) return;
        mForm.set(m ? { name: m.name, c_axis: m.c_axis, live_tools: m.live_tools, y_axis: m.y_axis, post: m.post } : { name: 'Mill-turn', c_axis: true, live_tools: true, y_axis: false, post: 'millturn_linuxcnc' });
        const tl = (m?.mode_lines?.turn ?? []).join('\n'), ml = (m?.mode_lines?.mill ?? []).join('\n');
        if (turnLines.value !== tl && document.activeElement !== turnLines) turnLines.value = tl;
        if (millLines.value !== ml && document.activeElement !== millLines) millLines.value = ml;
        paintAssign();
      }

      function paintAssign(): void {
        setHidden(aEmpty, cam.setups.length > 0);
        patchList(aList, cam.setups, {
          key: (s) => s.id,
          create: (s) => {
            const r = el('<div class="u8-row cm-assign"><span class="u8-row-sub"></span><select class="cv-input cm-asm" aria-label="Machine"></select><select class="cv-input cm-asmode" aria-label="Mode"></select></div>');
            const ms = q<HTMLSelectElement>(r, '.cm-asm'), md = q<HTMLSelectElement>(r, '.cm-asmode');
            fillSelect(md, MODES.map(([v, l]) => [v, t(l)] as [string, string]));
            const push = (): void => { void guard(() => cam.put('PUT', `/setups/${encodeURIComponent(s.id)}`, { machine_profile: ms.value && md.value ? { machine: ms.value, mode: md.value } : {} })); };
            ms.addEventListener('change', push);
            md.addEventListener('change', push);
            return r;
          },
          update: (r, s) => {
            setText(q(r, '.u8-row-sub'), `${s.id} · ${labelOf(s)}`);
            fillSelect(q<HTMLSelectElement>(r, '.cm-asm'), [['', t('No machine')], ...machines.map((m) => [m.id, m.name] as [string, string])]);
            const mp = ((s as unknown as Json).machine_profile ?? {}) as { machine?: string; mode?: string };
            const ms = q<HTMLSelectElement>(r, '.cm-asm'), md = q<HTMLSelectElement>(r, '.cm-asmode');
            if (document.activeElement !== ms) setValue(ms, mp.machine ?? '');
            if (document.activeElement !== md) setValue(md, mp.mode ?? '');
          },
        });
      }

      async function loadCycles(): Promise<void> {
        const r = await req<{ cycles?: Cycle[] }>('GET', camUrl('/probing/cycles')).catch(() => null);
        if (r?.cycles) { cycles = r.cycles; paintProbe(); }
      }

      cam.onChange(() => { paintShell(); void loadMachines(); paintAssign(); });
      docStore.onChange(() => { paintShell(); selected = ''; void loadMachines(); });
      paintShell();
      void loadCycles();
      void loadMachines();
    },
  };
}
