import type { DockPanel } from '../ui/dock';
import { docStore } from '../ui/doc-store';
import { el, patchList, q, setClass, setHidden, setText } from '../ui/dom';
import { pickPath } from '../ui/file-dialogs';
import { t } from '../ui/i18n';
import { toast } from '../ui/toast';
import { button, buttons, selectCtl } from '../u8/ui';
import { cam } from './cam-store';
import { fieldForm, type FieldForm, type FieldSpec } from './fields';
import { docCam, fillSelect, fixed, guard, mini, progressBar, reportBox, req, secs, section, text, type Json } from './kit';
import { events } from '../io/events';

interface NestSummary { id: string; sheet_count?: number; utilization?: number; cut_length?: number; unplaced?: unknown[] | number; sheets?: Array<{ sheet?: number; width?: number; height?: number; utilization?: number }>; seconds?: number; passes?: number; verify?: unknown; [k: string]: unknown }
interface Shapes { sheet: number; width: number; height: number; parts: Array<{ name: string; loops: Array<{ pts: number[][]; outer: boolean }> }> }
interface Process extends Json { id: string; kind: string; kind_of?: string }
interface Plan { sheets: Array<{ sheet: number; parts: number; moves: number; stats: Json; warnings: string[]; time: unknown; toolpath: unknown[] }> }

const NS = 'http://www.w3.org/2000/svg';
const procLabel = (p: Process): string => `${p.id} · ${t(String(p.kind_of ?? p.kind))}`;
const PROC_SPECS: FieldSpec[] = [
  { name: 'kerf', type: 'number', label: 'Kerf width', unit: 'mm' },
  { name: 'feed', type: 'number', label: 'Cutting feed', unit: 'mm/min' },
  { name: 'pierce_feed', type: 'number', label: 'Pierce feed', unit: 'mm/min' },
  { name: 'power', type: 'number', label: 'Power or pressure' },
  { name: 'pierce_delay', type: 'number', label: 'Pierce delay', unit: 's' },
  { name: 'z_control', type: 'bool', label: 'Height control' },
  { name: 'z_clearance', type: 'number', label: 'Travel height', unit: 'mm' },
  { name: 'pierce_height', type: 'number', label: 'Pierce height', unit: 'mm' },
  { name: 'cut_height', type: 'number', label: 'Cut height', unit: 'mm' },
  { name: 'rapid', type: 'number', label: 'Rapid speed', unit: 'mm/min' },
  { name: 'good_side', type: 'choice', label: 'Good side', choices: [['left', 'Left of the cut'], ['right', 'Right of the cut']] },
  { name: 'lead_in.type', type: 'text', label: 'Lead-in kind' },
  { name: 'lead_in.length', type: 'number', label: 'Lead-in length', unit: 'mm' },
  { name: 'lead_in.angle', type: 'number', label: 'Lead-in angle', unit: 'deg' },
  { name: 'lead_out.type', type: 'text', label: 'Lead-out kind' },
  { name: 'lead_out.length', type: 'number', label: 'Lead-out length', unit: 'mm' },
  { name: 'small_hole_ratio', type: 'number', label: 'Small hole ratio' },
  { name: 'small_hole_factor', type: 'number', label: 'Small hole feed factor' },
  { name: 'thickness', type: 'number', label: 'Material thickness', unit: 'mm' },
  { name: 'material', type: 'text', label: 'Material' },
  { name: 'notes', type: 'text', label: 'Notes' },
];

const getp = (o: Json, path: string): unknown => path.split('.').reduce<unknown>((c, k) => (c && typeof c === 'object' ? (c as Json)[k] : undefined), o);
function setp(o: Json, path: string, v: unknown): void {
  const ks = path.split('.');
  let cur = o;
  ks.forEach((k, i) => { if (i === ks.length - 1) cur[k] = v; else { const nx = (cur[k] && typeof cur[k] === 'object' ? { ...(cur[k] as Json) } : {}) as Json; cur[k] = nx; cur = nx; } });
}

const ROT: Array<[string, string]> = [['0', 'No rotation'], ['90', 'Quarter turns'], ['45', 'Eighth turns'], ['180', 'Half turn only']];
const rotations = (step: string): number[] => { const s = Number(step); if (!s) return [0]; const out: number[] = []; for (let a = 0; a < 360; a += s) out.push(a); return out; };

export const nestState: { nests: NestSummary[]; nest: string; sheet: number; procs: Process[]; proc: string } = { nests: [], nest: '', sheet: 1, procs: [], proc: '' };

export function nestPanel(): DockPanel {
  return {
    id: 'camnest', label: 'Nesting and cutting', icon: 'cut', order: 43,
    build(body) {
      body.classList.add('u8-panel', 'xw-panel');
      const note = el('<p class="u8-note"></p>');
      setText(note, t('Open a document with closed outlines or a flat pattern to nest.'));
      const live = el('<div class="u8-live cm-live"></div>');
      body.append(note, live);
      const paintShell = (): void => { const on = !!docStore.current(); setHidden(note, on); setHidden(live, !on); };
      const nurl = (tail = ''): string => docCam(`/nests${tail}`);

      const sParts = section('Parts and sheets');
      const srcSel = selectCtl('Parts from', [['outlines', 'Closed outlines in the drawing'], ['flat', 'Flat pattern of the part'], ['dxf', 'A DXF file']]);
      const srcNote = el('<p class="u8-note cm-srcnote"></p>');
      const dxfPath = el<HTMLInputElement>('<input class="cv-input cm-path" type="text" spellcheck="false" aria-label="DXF file">');
      dxfPath.placeholder = t('DXF file path');
      dxfPath.addEventListener('keydown', (e) => e.stopPropagation());
      const form = fieldForm([
        { name: 'qty', type: 'int', label: 'Copies of each part', min: 1, max: 400 },
        { name: 'width', type: 'number', label: 'Sheet width', unit: 'mm', min: 1, max: 100000 },
        { name: 'height', type: 'number', label: 'Sheet height', unit: 'mm', min: 1, max: 100000 },
        { name: 'sheets', type: 'int', label: 'Sheets available', min: 1, max: 60 },
        { name: 'clearance', type: 'number', label: 'Space between parts', unit: 'mm', min: 0, max: 100 },
        { name: 'kerf', type: 'number', label: 'Kerf', unit: 'mm', min: 0, max: 50 },
        { name: 'margin', type: 'number', label: 'Sheet margin', unit: 'mm', min: 0, max: 200 },
        { name: 'seconds', type: 'number', label: 'Time budget', unit: 's', min: 1, max: 300 },
        { name: 'rot', type: 'choice', label: 'Turn parts by', choices: ROT },
      ], () => undefined);
      form.set({ qty: 1, width: 1250, height: 2500, sheets: 2, clearance: 3, kerf: 0, margin: 5, seconds: 10, rot: '90' });
      const bar = progressBar();
      const report = reportBox(5);
      sParts.body.append(srcSel.el, srcNote, dxfPath, form.el, buttons(button('Nest parts', () => { void run(); }, 'primary'), button('Refresh sources', () => { void sources(); })), bar.el, report.el);

      const sView = section('Nest result');
      const nlist = el('<div class="u8-list cm-list is-short" role="listbox" aria-label="Nests"></div>');
      const sheetRow = selectCtl('Sheet', [], () => { nestState.sheet = Number(sheetRow.get()) || 1; void shapes(); });
      const svg = document.createElementNS(NS, 'svg');
      svg.setAttribute('class', 'cm-nestsvg');
      svg.setAttribute('viewBox', '0 0 100 100');
      svg.setAttribute('preserveAspectRatio', 'xMidYMid meet');
      svg.setAttribute('role', 'img');
      svg.setAttribute('aria-label', t('Nest layout'));
      const g = document.createElementNS(NS, 'g');
      const sheetP = document.createElementNS(NS, 'path'); sheetP.setAttribute('class', 'cm-n-sheet');
      const partsP = document.createElementNS(NS, 'path'); partsP.setAttribute('class', 'cm-n-parts'); partsP.setAttribute('fill-rule', 'evenodd');
      const rapidP = document.createElementNS(NS, 'path'); rapidP.setAttribute('class', 'cm-n-rapid');
      const cutP = document.createElementNS(NS, 'path'); cutP.setAttribute('class', 'cm-n-cut');
      g.append(sheetP, partsP, rapidP, cutP);
      svg.appendChild(g);
      const viewReport = reportBox(3);
      sView.body.append(nlist, sheetRow.el, svg, viewReport.el, buttons(button('Delete nest', () => { if (nestState.nest) void guard(() => req('DELETE', nurl(`/${encodeURIComponent(nestState.nest)}`))).then(() => { nestState.nest = ''; void load(); }); })));

      const sProc = section('Cutting process');
      const plist = el('<div class="u8-list cm-list is-short" role="listbox" aria-label="Cutting processes"></div>');
      const kindSel = selectCtl('Kind', [['laser', 'Laser'], ['plasma', 'Plasma'], ['waterjet', 'Waterjet'], ['router', 'Router']]);
      const pform: FieldForm = fieldForm(PROC_SPECS, (n, v) => { const p = proc(); if (p) { setp(p as Json, n, v); pdirty = true; setText(pnote, t('Unsaved changes.')); } });
      const pnote = el('<p class="u8-note cm-dirty"></p>');
      let pdirty = false;
      sProc.body.append(plist, kindSel.el, buttons(
        button('New process', () => { void newProc(); }, 'primary'),
        button('Save process', () => { void saveProc(); }),
        button('Delete process', () => { const p = proc(); if (p) void guard(() => req('DELETE', docCam(`/processes/${encodeURIComponent(p.id)}`))).then(() => { nestState.proc = ''; void load(); }); }),
      ), pnote, pform.el);

      const sCode = section('Cut code');
      const procSel = selectCtl('Process', []);
      const postSel = selectCtl('Post', []);
      const orderSel = selectCtl('Cut order', [['part', 'Each part, holes first'], ['all-inner-first', 'All holes first']]);
      const planSel = selectCtl('Sheets', [['', 'All sheets']]);
      const planReport = reportBox(4);
      const outPath = el<HTMLInputElement>('<input class="cv-input cm-path" type="text" spellcheck="false" aria-label="Output file">');
      outPath.placeholder = t('Output file (blank asks)');
      outPath.addEventListener('keydown', (e) => e.stopPropagation());
      sCode.body.append(procSel.el, postSel.el, orderSel.el, planSel.el, buttons(button('Plan cutting', () => { void plan(); }), button('Export code...', () => { void exportCode(); }, 'primary')), outPath, planReport.el);

      live.append(sParts.root, sView.root, sProc.root, sCode.root);

      const proc = (): Process | undefined => nestState.procs.find((p) => p.id === nestState.proc);

      async function sources(): Promise<void> {
        if (!docStore.activeId) return;
        const s =await req<Json>('GET', docCam('/nest/sources')).catch(() => null);
        if (!s) return;
        const line = (k: string, noteKey: string): string => (s[k] ? `${k}: ${Array.isArray(s[k]) ? (s[k] as unknown[]).length : 'yes'}` : String(s[noteKey] ?? ''));
        setText(srcNote, `${line('outlines', 'outlines_note')}  ${line('flat', 'flat_note')}`.trim());
        srcNote.title = srcNote.textContent ?? '';
      }

      async function load(): Promise<void> {
        if (!docStore.activeId) return;
        const [n, p] = await Promise.all([req<{ nests: NestSummary[] }>('GET', nurl()).catch(() => null), req<{ processes?: Process[] } | Process[]>('GET', docCam('/processes')).catch(() => null)]);
        if (n) nestState.nests = n.nests ?? [];
        if (p) nestState.procs = (Array.isArray(p) ? p : p.processes ?? []) as Process[];
        if (!nestState.nests.some((x) => x.id === nestState.nest)) nestState.nest = nestState.nests[nestState.nests.length - 1]?.id ?? '';
        if (!nestState.procs.some((x) => x.id === nestState.proc)) nestState.proc = nestState.procs[0]?.id ?? '';
        paint();
        void shapes();
      }

      async function run(): Promise<void> {
        const f = form.read();
        const rot = rotations(String(f.rot ?? '90'));
        const sheet = { width: f.width, height: f.height, qty: f.sheets ?? 1 };
        const src = srcSel.get();
        const qty = Number(f.qty ?? 1);
        const request: Json = { sheets: [sheet], clearance: f.clearance ?? 0, kerf: f.kerf ?? 0, margin: f.margin ?? 5, seconds: f.seconds ?? 10, rotations: rot, wait: false };
        if (src === 'flat') request.from_flat = { qty };
        else if (src === 'dxf') request.dxf = [{ path: dxfPath.value.trim(), qty }];
        else request.from_outlines = { qty };
        const first = await guard(() => req<Json>('POST', docCam('/nest'), request));
        if (!first) return;
        const jid = String(first.job ?? '');
        if (!jid) { await load(); return; }
        bar.onCancel(() => { void req('POST', docCam(`/nest/jobs/${encodeURIComponent(jid)}/cancel`)).catch(() => undefined); });
        bar.set(0, `${t('Nesting')} · 0 %`, true);
        let job: Json | null = null;
        for (let i = 0; i < 4000; i++) {
          job = await req<Json>('GET', docCam(`/nest/jobs/${encodeURIComponent(jid)}`)).catch(() => null);
          if (!job) break;
          const pr = job.progress as Json | number | undefined;
          const fr = typeof pr === 'number' ? pr : Number((pr as Json | undefined)?.fraction ?? 0);
          bar.set(fr, `${t('Nesting')} · ${Math.round(fr * 100)} %`, true);
          if (!['queued', 'running'].includes(String(job.state))) break;
          await new Promise((r) => setTimeout(r, 300));
        }
        bar.set(1, '', false);
        if (!job) return;
        if (job.state === 'failed') { toast(String(job.error ?? job.message ?? t('The nesting failed.')), 'error'); report.set([String(job.error ?? job.message ?? '')], true); return; }
        const res = (job.result ?? {}) as NestSummary;
        if (res.id) nestState.nest = String(res.id);
        nestState.sheet = 1;
        await load();
      }

      async function shapes(): Promise<void> {
        const n = nestState.nests.find((x) => x.id === nestState.nest);
        if (!n) { sheetP.setAttribute('d', ''); partsP.setAttribute('d', ''); rapidP.setAttribute('d', ''); cutP.setAttribute('d', ''); viewReport.set([t('No nest yet.')]); return; }
        const s = await req<Shapes>('GET', nurl(`/${encodeURIComponent(n.id)}/shapes?sheet=${nestState.sheet}`)).catch(() => null);
        if (!s) return;
        const pad = Math.max(s.width, s.height) * 0.03;
        svg.setAttribute('viewBox', `${-pad} ${-pad} ${s.width + 2 * pad} ${s.height + 2 * pad}`);
        g.setAttribute('transform', `translate(0 ${s.height}) scale(1 -1)`);
        sheetP.setAttribute('d', `M0 0H${s.width}V${s.height}H0Z`);
        let d = '';
        for (const p of s.parts) for (const l of p.loops) d += `M${l.pts.map((q2) => `${q2[0]} ${q2[1]}`).join('L')}Z`;
        partsP.setAttribute('d', d);
        rapidP.setAttribute('d', '');
        cutP.setAttribute('d', '');
        svg.style.setProperty('--cm-sw', String(Math.max(s.width, s.height) / 400));
        viewReport.set([
          `${t('Sheet')} ${s.sheet} ${t('of')} ${n.sheet_count ?? '?'} · ${fixed(s.width, 5)} x ${fixed(s.height, 5)} mm`,
          `${t('Parts on this sheet')}: ${s.parts.length}`,
          `${t('Utilisation')} ${fixed(Number(n.utilization ?? 0) * (Number(n.utilization ?? 0) <= 1 ? 100 : 1), 4)} %`,
        ]);
      }

      async function newProc(): Promise<void> {
        const blank = await guard(() => req<Json>('GET', `/api/cam/processes/blank?kind=${encodeURIComponent(kindSel.get())}`));
        if (!blank) return;
        const r = await guard(() => req<Json>('POST', docCam('/processes'), blank));
        if (r) { nestState.proc = String(r.id ?? ''); await load(); }
      }

      async function saveProc(): Promise<void> {
        const p = proc();
        if (!p) return;
        const r = await guard(() => req<Json>('PUT', docCam(`/processes/${encodeURIComponent(p.id)}`), p));
        if (r) { pdirty = false; setText(pnote, t('Saved.')); await load(); }
      }

      const cutBody = (): Json => ({ process: procSel.get(), order: orderSel.get(), ...(planSel.get() ? { sheet: Number(planSel.get()) } : {}) });

      async function plan(): Promise<void> {
        if (!nestState.nest || !procSel.get()) { toast(t('Nest the parts and add a process first.'), 'info'); return; }
        const r = await guard(() => req<Plan>('POST', nurl(`/${encodeURIComponent(nestState.nest)}/plan`), cutBody()));
        if (!r) return;
        const s0 = r.sheets.find((s) => s.sheet === nestState.sheet) ?? r.sheets[0];
        if (!s0) return;
        const st = s0.stats as Json;
        const warn = r.sheets.flatMap((s) => s.warnings ?? []);
        planReport.set([
          `${t('Sheets planned')}: ${r.sheets.length} · ${t('moves')} ${s0.moves}`,
          `${t('Cut length')} ${fixed(Number(st.cut_length ?? st.cut ?? 0), 5)} mm · ${t('pierces')} ${String(st.pierces ?? '-')}`,
          `${t('Time')} ${secs(Number((s0.time as Json | number)?.valueOf() as number) || Number(((s0.time as Json) ?? {}).total_s ?? ((s0.time as Json) ?? {}).time_s ?? 0))}`,
          ...warn.slice(0, 1),
        ], warn.length > 0);
        let rap = '', cut = '';
        let at: number[] | null = null;
        for (const m of s0.toolpath as unknown[][]) {
          const k = m[0];
          if (k !== 'rapid' && k !== 'feed' && k !== 'arc') continue;
          const to = k === 'arc' ? [Number(m[2]), Number(m[3])] : [Number(m[1]), Number(m[2])];
          if (at) { if (k === 'rapid') rap += `M${at[0]} ${at[1]}L${to[0]} ${to[1]}`; else cut += `M${at[0]} ${at[1]}L${to[0]} ${to[1]}`; }
          at = to;
        }
        rapidP.setAttribute('d', rap);
        cutP.setAttribute('d', cut);
      }

      async function exportCode(): Promise<void> {
        if (!nestState.nest || !procSel.get()) { toast(t('Nest the parts and add a process first.'), 'info'); return; }
        const name = outPath.value.trim() || await pickPath('save', t('Export cutting code'), 'sheet.nc', [{ name: 'Machine code', extensions: ['nc', 'ngc'] }], t('Export'));
        if (!name) return;
        const r = await guard(() => req<Json>('POST', nurl(`/${encodeURIComponent(nestState.nest)}/export`), { ...cutBody(), post: postSel.get(), path: name }));
        if (r) {
          const files = (r.files as Array<{ path: string; sheet: number; lines: number }> | undefined) ?? [];
          planReport.set([`${t('Wrote')} ${files.length} ${t(files.length === 1 ? 'file' : 'files')}`, ...files.slice(0, 2).map((f) => `${f.path} (${f.lines})`), `${t('Pierces')} ${String(r.pierces ?? '-')}`]);
          toast(t('Cutting code written.'), 'info');
        }
      }

      function paint(): void {
        paintShell();
        patchList(nlist, nestState.nests, {
          key: (n) => n.id,
          create: (n) => { const r = el('<div class="u8-row cm-row-s" role="option"><span class="u8-row-sub"></span><span class="u8-row-name"></span><span class="u8-acts"></span></div>'); q(r, '.u8-acts').append(mini('x', 'Delete this nest', () => { void guard(() => req('DELETE', nurl(`/${encodeURIComponent(n.id)}`))).then(() => load()); })); r.addEventListener('click', () => { nestState.nest = n.id; nestState.sheet = 1; paint(); void shapes(); }); return r; },
          update: (r, n) => { setText(q(r, '.u8-row-sub'), n.id); setText(q(r, '.u8-row-name'), `${n.sheet_count ?? '?'} ${t('sheets')} · ${fixed(Number(n.utilization ?? 0) * (Number(n.utilization ?? 0) <= 1 ? 100 : 1), 4)} %`); setClass(r, 'is-selected', n.id === nestState.nest); },
        });
        const cur = nestState.nests.find((x) => x.id === nestState.nest);
        const count = Number(cur?.sheet_count ?? 1);
        fillSelect(sheetRow.input as HTMLSelectElement, Array.from({ length: count }, (_, i) => [String(i + 1), String(i + 1)] as [string, string]));
        if (sheetRow.get() !== String(nestState.sheet)) sheetRow.set(String(nestState.sheet));
        fillSelect(planSel.input as HTMLSelectElement, [['', t('All sheets')], ...Array.from({ length: count }, (_, i) => [String(i + 1), `${t('Sheet')} ${i + 1}`] as [string, string])]);
        patchList(plist, nestState.procs, {
          key: (p) => p.id,
          create: (p) => { const r = el('<div class="u8-row cm-row-s" role="option"><span class="u8-row-sub"></span><span class="u8-row-name"></span><span class="u8-badge"></span></div>'); r.addEventListener('click', () => { nestState.proc = p.id; paint(); }); return r; },
          update: (r, p) => { setText(q(r, '.u8-row-sub'), p.id); setText(q(r, '.u8-row-name'), `${t('Kerf')} ${fixed(Number(p.kerf ?? 0), 3)} mm · ${t('feed')} ${fixed(Number(p.feed ?? 0), 4)}`); setText(q(r, '.u8-badge'), t(String(p.kind_of ?? p.kind))); setClass(r, 'is-selected', p.id === nestState.proc); },
        });
        const p = proc();
        pform.el.classList.toggle('is-off', !p);
        if (p && !pdirty) { const flat: Record<string, unknown> = {}; for (const s of PROC_SPECS) flat[s.name] = getp(p, s.name); pform.set(flat); }
        fillSelect(procSel.input as HTMLSelectElement, nestState.procs.map((x) => [x.id, procLabel(x)] as [string, string]));
        fillSelect(postSel.input as HTMLSelectElement, cam.posts.filter((x) => x.id.startsWith('cut')).map((x) => [x.id, x.name] as [string, string]));
        if (procSel.get() !== nestState.proc && document.activeElement !== procSel.input && nestState.proc) procSel.set(nestState.proc);
      }

      events.on('doc', (e) => { if (e.id === docStore.activeId) void load(); });
      docStore.onChange(() => { paintShell(); void load(); void sources(); });
      cam.onChange(paint);
      paintShell();
      paint();
      void load();
      void sources();
      void text;
    },
  };
}
