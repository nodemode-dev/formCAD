import type { DockPanel } from '../ui/dock';
import { el, patchList, q, setClass, setDisabled, setHidden, setText, setValue } from '../ui/dom';
import { t } from '../ui/i18n';
import { pickPath } from '../ui/file-dialogs';
import { toast } from '../ui/toast';
import { isAssembly } from '../u8/asm';
import { button, buttons, checkCtl, readout, selectCtl } from '../u8/ui';
import { view3d } from '../view3d/mount';
import { docStore } from '../ui/doc-store';
import { cam, frac, labelOf, toolName, type Op, type Setup, type CamJob } from './cam-store';
import { fieldForm, type FieldForm, type FieldSpec } from './fields';
import { docCam, fillSelect, guard, mini, progressBar, reportBox, req, secs, section, text, type Json } from './kit';

const MACHINES: Array<[string, string]> = [['mill3', '3-axis mill'], ['mill5', '5-axis mill'], ['lathe', 'Lathe'], ['laser', 'Sheet cutter']];
const SLOTS: Array<[string, string]> = ['G54', 'G55', 'G56', 'G57', 'G58', 'G59', 'G59.1', 'G59.2', 'G59.3'].map((c, i) => [String(i + 1), c]);
const ORIGINS: Array<[string, string]> = [['stock_top_min', 'Stock top, minimum corner'], ['stock_top_center', 'Stock top, centre'], ['stock_bottom_min', 'Stock bottom, minimum corner'], ['model', 'Model origin'], ['custom', 'Custom point']];
const STOCKS: Array<[string, string]> = [['from_model', 'Model bounds plus offsets'], ['box', 'Box'], ['cylinder', 'Cylinder'], ['tube', 'Tube']];
const GEOM_LABEL: Record<string, string> = { stock: 'Stock outline', rect: 'Rectangle', polygons: 'Polygons', entities: 'Selected curves', section: 'Section of the model', removal: 'Material to remove', points: 'Point list', model_holes: 'Holes in the model' };
const num = (label: string, name: string, unit = 'mm'): FieldSpec => ({ name, type: 'number', label, unit });

const SETUP_SPECS: FieldSpec[] = [
  { name: 'label', type: 'text', label: 'Name' },
  { name: 'machine', type: 'choice', label: 'Machine', choices: MACHINES },
  { name: 'wcs.slot', type: 'choice', label: 'Work offset', choices: SLOTS },
  { name: 'wcs.origin_on', type: 'choice', label: 'Origin at', choices: ORIGINS },
  { name: 'stock.kind', type: 'choice', label: 'Stock', choices: STOCKS },
  ...(['xmin', 'xmax', 'ymin', 'ymax', 'zmin', 'zmax'] as const).map((k) => num(`Offset ${k}`, `stock.offsets.${k}`)),
  num('Size X', 'stock.dims.0'), num('Size Y', 'stock.dims.1'), num('Size Z', 'stock.dims.2'),
  num('Diameter', 'stock.diameter'), num('Inner diameter', 'stock.inner'), num('Length', 'stock.length'),
  num('Clearance height', 'safe.clearance'), num('Retract height', 'safe.retract'), num('Feed height', 'safe.feed'),
];

const STOCK_ROWS: Record<string, string[]> = {
  from_model: ['stock.offsets.xmin', 'stock.offsets.xmax', 'stock.offsets.ymin', 'stock.offsets.ymax', 'stock.offsets.zmin', 'stock.offsets.zmax'],
  box: ['stock.dims.0', 'stock.dims.1', 'stock.dims.2'],
  cylinder: ['stock.diameter', 'stock.length'],
  tube: ['stock.diameter', 'stock.inner', 'stock.length'],
};
const STOCK_ALL = new Set(Object.values(STOCK_ROWS).flat());

const COMMON_SPECS: FieldSpec[] = [
  { name: 'label', type: 'text', label: 'Name' },
  { name: 'tool', type: 'choice', label: 'Tool', choices: [] },
  { name: 'enabled', type: 'bool', label: 'Enabled' },
  { ...num('Clearance height', 'heights.clearance'), nullable: true },
  { ...num('Retract height', 'heights.retract'), nullable: true },
  { ...num('Feed height', 'heights.feed'), nullable: true },
  { ...num('Top of cut', 'heights.top'), nullable: true },
  { ...num('Bottom of cut', 'heights.bottom'), nullable: true },
  { name: 'feeds.material', type: 'text', label: 'Material (from the tool data)' },
  { name: 'feeds.vc', type: 'number', label: 'Cutting speed', unit: 'm/min', nullable: true },
  { name: 'feeds.fz', type: 'number', label: 'Feed per tooth', unit: 'mm', nullable: true },
  { name: 'feeds.rpm', type: 'number', label: 'Spindle speed', unit: 'rpm', nullable: true },
  { ...num('Cutting feed', 'feeds.vf_cut'), unit: 'mm/min', nullable: true },
  { ...num('Plunge feed', 'feeds.vf_plunge'), unit: 'mm/min', nullable: true },
  { ...num('Ramp feed', 'feeds.vf_ramp'), unit: 'mm/min', nullable: true },
];

const GEOM_SPECS: FieldSpec[] = [
  { name: 'kind', type: 'choice', label: 'Region from', choices: [] },
  { name: 'z', type: 'number', label: 'Height', unit: 'mm', nullable: true },
  { name: 'part', type: 'choice', label: 'Part of the section', choices: [['all', 'All'], ['outer', 'Outer only'], ['holes', 'Holes only'], ['removal', 'Material to remove']] },
  { name: 'margin', type: 'number', label: 'Margin', unit: 'mm', nullable: true },
  { name: 'min', type: 'vec2', label: 'Corner min (x y)' },
  { name: 'max', type: 'vec2', label: 'Corner max (x y)' },
  { name: 'min_diameter', type: 'number', label: 'Smallest hole', unit: 'mm', nullable: true },
  { name: 'max_diameter', type: 'number', label: 'Largest hole', unit: 'mm', nullable: true },
  { name: 'handles', type: 'text', label: 'Curve handles' },
  { name: 'points', type: 'text', label: 'Points (x y, x y)' },
];
const GEOM_ROWS: Record<string, string[]> = {
  stock: ['kind'], rect: ['kind', 'z', 'min', 'max'], polygons: ['kind', 'z'], entities: ['kind', 'handles'],
  section: ['kind', 'z', 'part'], removal: ['kind', 'z', 'margin'], points: ['kind', 'z', 'points'], model_holes: ['kind', 'z', 'min_diameter', 'max_diameter'],
};

const hint = (s: string): void => { document.dispatchEvent(new CustomEvent('formcad:hint', { detail: s })); };

function getPath(o: Json, path: string): unknown {
  let cur: unknown = o;
  for (const k of path.split('.')) { if (cur === null || cur === undefined) return undefined; cur = (cur as Json)[k]; }
  return cur;
}

function setPath(o: Json, path: string, v: unknown): void {
  const keys = path.split('.');
  let cur: Json = o;
  keys.forEach((k, i) => {
    if (i === keys.length - 1) { (cur as Json)[k] = v; return; }
    const nextKey = keys[i + 1];
    const have = (cur as Json)[k];
    const next: unknown = Array.isArray(have) ? [...have] : have && typeof have === 'object' ? { ...(have as Json) } : /^\d+$/.test(nextKey) ? [0, 0, 0] : {};
    (cur as Json)[k] = next;
    cur = next as Json;
  });
}

const parsePoints = (s: string): number[][] => s.split(',').map((p) => p.trim().split(/\s+/).map(Number)).filter((p) => p.length >= 2 && p.every(Number.isFinite));
const pointsText = (p: unknown): string => (Array.isArray(p) ? (p as number[][]).map((q2) => q2.join(' ')).join(', ') : '');

export async function runJob(start: () => Promise<Json | null>, bar: ReturnType<typeof progressBar>, jobUrl: (id: string) => string, cancelUrl: (id: string) => string, label: string): Promise<{ job: CamJob | null; first: Json | null }> {
  const first = await start();
  const id = first ? String(first.job ?? first.id ?? '') : '';
  if (!first || !id) { bar.set(0, '', false); return { job: null, first }; }
  bar.onCancel(() => { void req('POST', cancelUrl(id)).catch(() => undefined); });
  bar.set(0, `${label} · 0 %`, true);
  let job: CamJob | null = null;
  for (let i = 0; i < 6000; i++) {
    job = await req<CamJob>('GET', jobUrl(id)).catch(() => null);
    if (!job) break;
    bar.set(frac(job.progress), `${job.phase || label} · ${Math.round(frac(job.progress) * 100)} %`, true);
    if (!['queued', 'running', 'start', 'progress'].includes(job.state)) break;
    await new Promise((r) => setTimeout(r, 250));
  }
  bar.set(1, '', false);
  return { job, first };
}

export function camPanel(): DockPanel {
  return {
    id: 'cam', label: 'Manufacture', icon: 'cam', order: 40,
    build(body) {
      body.classList.add('u8-panel', 'xw-panel');
      const note = el('<p class="u8-note"></p>');
      setText(note, t('Open a part or assembly to set up machining.'));
      const live = el('<div class="u8-live cm-live"></div>');
      body.append(note, live);
      const paintShell = (): void => { const on = !!docStore.current(); setHidden(note, on); setHidden(live, !on); };

      const sSetups = section('Setups');
      const sList = el('<div class="u8-list cm-list" role="listbox" aria-label="Setups"></div>');
      const sEmpty = el('<p class="u8-note cm-empty"></p>');
      setText(sEmpty, t('No setups yet. Add one to define the stock and the work offset.'));
      const newMachine = selectCtl('Machine for a new setup', MACHINES);
      const setupForm: FieldForm = fieldForm(SETUP_SPECS, (name, value) => { void patchSetup(name, value); });
      const stockSel = setupForm.rowOf('stock.kind')?.querySelector('select');
      void stockSel;
      const fixList = el('<div class="u8-list cm-list is-short" role="listbox" aria-label="Fixtures"></div>');
      const fixNote = el('<p class="u8-note cm-fixnote"></p>');
      sSetups.body.append(
        sList, sEmpty, newMachine.el,
        buttons(
          button('New setup', () => { void newSetup(); }, 'primary'),
          button('Delete setup', () => { const s = cam.setup(); if (s) void cam.put('DELETE', `/setups/${encodeURIComponent(s.id)}`); }),
        ),
        setupForm.el, fixNote, fixList,
        buttons(
          button('Add selected bodies as fixtures', () => { void fixtures(true); }),
          button('Use selected bodies as the model', () => { void model(); }),
        ),
      );

      const sOps = section('Operations');
      const oList = el('<div class="u8-list cm-list" role="listbox" aria-label="Operations"></div>');
      const oEmpty = el('<p class="u8-note cm-empty"></p>');
      setText(oEmpty, t('No operations in this setup.'));
      const kindSel = selectCtl('Operation', []);
      const toolSel = selectCtl('Tool', []);
      const opHost = el('<div class="cm-opform"></div>');
      const common = fieldForm(COMMON_SPECS, (name, value) => { void patchOp(name, value); });
      const geomForm = fieldForm(GEOM_SPECS, (name, value) => { void patchGeom(name, value); });
      const geomBox = el('<div class="cm-geom"></div>');
      const geomTitle = el('<div class="cm-group"></div>');
      setText(geomTitle, t('Geometry'));
      const useSel = button('Use the selected curves', () => { void curvesFromSelection(); });
      geomBox.append(geomTitle, geomForm.el, useSel);
      const paramBox = el('<div class="cm-params"></div>');
      const paramForms = new Map<string, FieldForm>();
      opHost.append(common.el, geomBox, paramBox);
      const opMsg = reportBox(3);
      const genBar = progressBar();
      sOps.body.append(
        oList, oEmpty, kindSel.el, toolSel.el,
        buttons(button('Add operation', () => { void addOp(); }, 'primary'), button('Generate', () => { void generate(false); }), button('Generate setup', () => { void generate(true); })),
        genBar.el, opMsg.el, opHost,
      );

      const sPath = section('Toolpath');
      const showTp = checkCtl('Show toolpaths in the view', true, () => { cam.layer?.setShown(showTp.get()); });
      const showRapid = checkCtl('Show rapid moves', true, () => { cam.layer?.setRapid(showRapid.get()); });
      const play = el<HTMLInputElement>('<input class="cm-slider" type="range" min="0" max="1000" value="1000" aria-label="Toolpath position">');
      play.addEventListener('input', () => { cam.layer?.play(Number(play.value) / 1000); setText(playRead, `${Math.round(Number(play.value) / 10)} %`); });
      const playRead = el('<output class="cm-out"></output>');
      setText(playRead, '100 %');
      const playRow = el('<div class="cm-sliderrow"><span class="cm-sl-label"></span></div>');
      setText(q(playRow, '.cm-sl-label'), t('Position'));
      playRow.append(play, playRead);
      const timeBox = reportBox(4);
      sPath.body.append(showTp.el, showRapid.el, playRow, timeBox.el, buttons(button('Cycle time', () => { void times(); })));

      const sPost = section('Post and export');
      const postSel = selectCtl('Post', []);
      const pre = el('<pre class="cm-pre" tabindex="0" aria-label="Post output"></pre>');
      const postMsg = reportBox(3);
      const outName = el<HTMLInputElement>('<input class="cv-input cm-path" type="text" spellcheck="false" aria-label="Output file">');
      outName.placeholder = t('Output file (blank asks)');
      sPost.body.append(postSel.el, buttons(button('Preview code', () => { void preview(); }), button('Export code...', () => { void exportCode(); }, 'primary')), outName, postMsg.el, pre);

      live.append(sSetups.root, sOps.root, sPath.root, sPost.root);

      const selSetup = (): Setup | undefined => cam.setup();
      const selOp = (): Op | undefined => cam.op();

      async function newSetup(): Promise<void> {
        const r = await cam.put<Json>('POST', '/setups', { machine: newMachine.get() });
        const id = r ? String((r as Json).id ?? ((r as Json).setup as Json | undefined)?.id ?? '') : '';
        await cam.refresh();
        if (id) cam.select(id);
      }

      async function patchSetup(name: string, value: unknown): Promise<void> {
        const s = selSetup();
        if (!s) return;
        const top = name.split('.')[0];
        const body: Json = {};
        if (name === 'label' || name === 'machine') body[name] = value;
        else {
          const copy: Json = JSON.parse(JSON.stringify((s as unknown as Json)[top] ?? {})) as Json;
          setPath(copy, name.split('.').slice(1).join('.'), name === 'wcs.slot' ? Number(value) : value);
          body[top] = copy;
        }
        await cam.put('PUT', `/setups/${encodeURIComponent(s.id)}`, body);
      }

      async function fixtures(add: boolean): Promise<void> {
        const s = selSetup();
        const sel = view3d()?.vp?.sel.bodies ?? [];
        if (!s || !sel.length) { toast(t('Select one or more bodies in the view first.'), 'info'); return; }
        const next = add ? Array.from(new Set([...(s.fixtures as number[]), ...sel])) : (s.fixtures as number[]).filter((h) => !sel.includes(h));
        await cam.put('PUT', `/setups/${encodeURIComponent(s.id)}`, { fixtures: next });
      }

      async function model(): Promise<void> {
        const s = selSetup();
        const sel = view3d()?.vp?.sel.bodies ?? [];
        if (!s) return;
        await cam.put('PUT', `/setups/${encodeURIComponent(s.id)}`, { bodies: sel });
      }

      async function addOp(): Promise<void> {
        const s = selSetup();
        const kind = kindSel.get();
        if (!s || !kind) return;
        const type = cam.type(kind);
        const tool = Number(toolSel.get());
        const geometry: Json = type?.geometry?.length ? { kind: type.geometry[0] } : {};
        const r = await cam.put<Json>('POST', '/ops', { setup: s.id, type: kind, tool: Number.isFinite(tool) && tool > 0 ? tool : undefined, geometry });
        const id = r ? String((r as Json).id ?? ((r as Json).op as Json | undefined)?.id ?? '') : '';
        await cam.refresh();
        if (id) cam.select(s.id, id);
      }

      async function patchOp(name: string, value: unknown): Promise<void> {
        const o = selOp();
        if (!o) return;
        const body: Json = {};
        if (name === 'label' || name === 'enabled') body[name] = value;
        else if (name === 'tool') body.tool = Number(value);
        else {
          const top = name.split('.')[0];
          const copy: Json = JSON.parse(JSON.stringify((o as unknown as Json)[top] ?? {})) as Json;
          setPath(copy, name.split('.').slice(1).join('.'), value);
          body[top] = copy;
        }
        await cam.put('PUT', `/ops/${encodeURIComponent(o.id)}`, body);
      }

      async function patchGeom(name: string, value: unknown): Promise<void> {
        const o = selOp();
        if (!o) return;
        const g: Json = { ...(o.geometry ?? {}) };
        if (name === 'handles') g.handles = String(value).split(/[\s,]+/).map(Number).filter((n) => Number.isFinite(n) && n > 0);
        else if (name === 'points') g.points = parsePoints(String(value));
        else if (value === null) delete g[name];
        else g[name] = value;
        await cam.put('PUT', `/ops/${encodeURIComponent(o.id)}`, { geometry: g });
      }

      async function curvesFromSelection(): Promise<void> {
        const o = selOp();
        const sel = view3d()?.vp?.sel.bodies ?? [];
        if (!o || !sel.length) { toast(t('Select curves in the view first.'), 'info'); return; }
        await cam.put('PUT', `/ops/${encodeURIComponent(o.id)}`, { geometry: { ...(o.geometry ?? {}), kind: 'entities', handles: sel } });
      }

      async function opParam(name: string, value: unknown): Promise<void> {
        const o = selOp();
        if (!o) return;
        await cam.put('PUT', `/ops/${encodeURIComponent(o.id)}`, { params: { ...(o.params ?? {}), [name]: value } });
      }

      async function generate(all: boolean): Promise<void> {
        const s = selSetup(), o = selOp();
        if (!s || (!all && !o)) return;
        const run = await runJob(
          () => guard(() => req<Json>('POST', docCam('/generate'), all ? { setup: s.id } : { ops: [o?.id] })),
          genBar, (id) => docCam(`/jobs/${encodeURIComponent(id)}`), (id) => docCam(`/jobs/${encodeURIComponent(id)}/cancel`), t('Generating'),
        );
        await cam.refresh();
        if (run.job?.state === 'failed') toast(run.job.message || run.job.error || t('The toolpath was not made.'), 'error');
        const results = (run.job as unknown as { results?: Record<string, { status?: string; message?: string }> } | null)?.results ?? {};
        const bad = Object.entries(results).find(([, r]) => r.status === 'failed');
        if (bad) toast(`${bad[0]}: ${bad[1].message ?? t('The toolpath was not made.')}`, 'error');
        const ids = all ? cam.opsOf(s.id).map((x) => x.id) : [o?.id ?? ''];
        for (const id of ids) if (id) void cam.showOp(id, true);
      }

      async function times(): Promise<void> {
        const r = await guard(() => req<Json>('GET', docCam('/time')));
        if (!r) return;
        const per = (r.per_op ?? r.ops ?? []) as Array<Json>;
        const total = Number(r.total_s ?? r.time_s ?? r.total ?? 0);
        const lines = [`${t('Total')} ${secs(total)}`];
        for (const p of per.slice(0, 3)) lines.push(`${String(p.op ?? p.id ?? '')} ${secs(Number(p.time_s ?? p.seconds ?? 0))}`);
        timeBox.set(lines);
      }

      const postBody = (): Json => ({ setup: cam.setupId, post: postSel.get() });

      async function preview(): Promise<void> {
        const r = await guard(() => req<Json>('POST', docCam('/preview'), postBody()));
        if (!r) return;
        const lines = String(r.text ?? '').split('\n');
        const shown = lines.slice(0, 400).join('\n');
        if (pre.textContent !== shown) pre.textContent = shown;
        const w = (r.warnings as string[] | undefined) ?? [];
        postMsg.set([`${typeof r.lines === 'number' ? r.lines : lines.length} ${t('lines')} · ${String(r.extension ?? '')}`, ...w.slice(0, 2)], w.length > 0);
      }

      async function exportCode(): Promise<void> {
        const post = cam.posts.find((p) => p.id === postSel.get());
        const ext = (post?.extension ?? '.ngc').replace(/^\./, '');
        const name = outName.value.trim() || await pickPath('save', t('Export machine code'), `program.${ext}`, [{ name: post?.name ?? 'Machine code', extensions: [ext] }], t('Export'));
        if (!name) return;
        const r = await guard(() => req<Json>('POST', docCam('/export'), { ...postBody(), out: name }));
        if (r) { postMsg.set([`${t('Wrote')} ${String(r.path ?? name)}`, `${String(r.lines ?? '')} ${t('lines')}`.trim()]); toast(t('Machine code written.'), 'info'); }
      }

      const paintForms = (): void => {
        const s = selSetup();
        const o = selOp();
        setClass(sList, 'is-empty', !cam.setups.length);
        setHidden(sEmpty, cam.setups.length > 0);
        setHidden(oEmpty, cam.opsOf().length > 0);
        setupForm.el.classList.toggle('is-off', !s);
        if (s) {
          const flat: Record<string, unknown> = {};
          for (const sp of SETUP_SPECS) {
            const v = getPath(s as unknown as Json, sp.name.replace(/^wcs\./, 'wcs.'));
            flat[sp.name] = sp.name === 'wcs.slot' ? String(v ?? 1) : sp.name === 'label' ? labelOf(s) : v;
          }
          flat.label = labelOf(s);
          const dims = (s.stock?.dims as number[] | undefined) ?? [];
          flat['stock.dims.0'] = dims[0]; flat['stock.dims.1'] = dims[1]; flat['stock.dims.2'] = dims[2];
          setupForm.set(flat);
          const kind = String(s.stock?.kind ?? 'from_model');
          const want = new Set(['label', 'machine', 'wcs.slot', 'wcs.origin_on', 'stock.kind', 'safe.clearance', 'safe.retract', 'safe.feed', ...(STOCK_ROWS[kind] ?? [])]);
          for (const n of STOCK_ALL) if (!want.has(n)) setupForm.rowOf(n)?.setAttribute('hidden', '');
          for (const n of want) setupForm.rowOf(n)?.removeAttribute('hidden');
        }
        const fx = (s?.fixtures ?? []) as number[];
        setText(fixNote, `${t('Fixtures')}: ${fx.length}${s?.bodies?.length ? ` · ${t('model bodies')}: ${s.bodies.length}` : ''}`);
        patchList(fixList, fx.map(String), {
          key: (h) => h,
          create: () => { const r = el('<div class="u8-row cm-fixrow"><span class="u8-row-sub"></span><span class="u8-row-name"></span><span class="u8-acts"></span></div>'); return r; },
          update: (r, h) => {
            setText(q(r, '.u8-row-sub'), `#${h}`);
            setText(q(r, '.u8-row-name'), t('Fixture body'));
            const acts = q(r, '.u8-acts');
            if (!acts.firstChild) acts.append(mini('x', 'Remove this fixture', () => { const cur = selSetup(); if (cur) void cam.put('PUT', `/setups/${encodeURIComponent(cur.id)}`, { fixtures: (cur.fixtures as number[]).filter((v) => String(v) !== h) }); }));
          },
        });

        const ops = cam.opsOf();
        const noOp = !o;
        opHost.classList.toggle('is-off', noOp);
        if (o) {
          const tools = cam.docTools.map((tl) => [String(tl.number), `T${tl.number} ${toolName(tl)}`] as [string, string]);
          const toolSelect = common.rowOf('tool')?.querySelector('select');
          if (toolSelect) fillSelect(toolSelect, tools.length ? tools : [['', t('No tools in this document')]]);
          const flat: Record<string, unknown> = { label: labelOf(o), tool: String(o.tool ?? ''), enabled: o.enabled };
          for (const sp of COMMON_SPECS) if (sp.name.includes('.')) flat[sp.name] = getPath(o as unknown as Json, sp.name) ?? null;
          common.set(flat);
          const type = cam.type(o.type);
          const gk = type?.geometry ?? [];
          const gsel = geomForm.rowOf('kind')?.querySelector('select');
          if (gsel) fillSelect(gsel, gk.map((k) => [k, t(GEOM_LABEL[k] ?? k)] as [string, string]));
          setHidden(geomBox, gk.length === 0);
          const g = (o.geometry ?? {}) as Json;
          geomForm.set({ ...g, kind: g.kind ?? gk[0] ?? '', handles: Array.isArray(g.handles) ? (g.handles as number[]).join(' ') : '', points: pointsText(g.points), z: g.z ?? null, margin: g.margin ?? null, min_diameter: g.min_diameter ?? null, max_diameter: g.max_diameter ?? null });
          geomForm.show(new Set(GEOM_ROWS[String(g.kind ?? gk[0])] ?? ['kind']));
          setHidden(useSel, String(g.kind ?? gk[0]) !== 'entities');
          let pf = paramForms.get(o.type);
          if (!pf && type) {
            pf = fieldForm(type.fields, (name, value) => { void opParam(name, value); }, { grouped: true });
            paramForms.set(o.type, pf);
            pf.el.hidden = true;
            paramBox.appendChild(pf.el);
          }
          for (const [k, f] of paramForms) if (f.el.hidden !== (k !== o.type)) f.el.hidden = k !== o.type;
          pf?.set((o.params ?? {}) as Record<string, unknown>);
          const st = o.state;
          opMsg.set([`${t('Status')}: ${st?.status ?? 'never'}`, st?.message ?? '', ...(st?.warnings ?? []).slice(0, 1)], st?.status === 'failed');
        } else opMsg.set([t('Select an operation to edit it.'), '', '']);

        const types = cam.registry;
        fillSelect(kindSel.input as HTMLSelectElement, types.map((r) => [r.kind, `${r.group.toUpperCase()} · ${r.label}`] as [string, string]));
        fillSelect(toolSel.input as HTMLSelectElement, [['', t('Pick on the operation')], ...cam.docTools.map((tl) => [String(tl.number), `T${tl.number} ${toolName(tl)}`] as [string, string])]);
        fillSelect(postSel.input as HTMLSelectElement, cam.posts.map((p) => [p.id, p.name] as [string, string]));
        void ops;
      };

      const paintLists = (): void => {
        patchList(sList, cam.setups, {
          key: (s) => s.id,
          create: (s) => {
            const r = el('<div class="u8-row cm-row-s" role="option"><span class="u8-row-sub"></span><span class="u8-row-name"></span><span class="u8-badge"></span></div>');
            r.addEventListener('click', () => { cam.select(s.id, ''); void cam.showSetup(s.id); });
            return r;
          },
          update: (r, s) => {
            setText(q(r, '.u8-row-sub'), s.id);
            setText(q(r, '.u8-row-name'), `${labelOf(s)} · ${t(MACHINES.find((m) => m[0] === s.machine)?.[1] ?? s.machine)}`);
            const n = (s.ops ?? []).length;
            setText(q(r, '.u8-badge'), `${n} ${t(n === 1 ? 'op' : 'ops')}`);
            setClass(r, 'is-selected', s.id === cam.setupId);
          },
        });
        patchList(oList, cam.opsOf(), {
          key: (o) => o.id,
          create: (o) => {
            const r = el('<div class="u8-row cm-row-o" role="option"><span class="u8-row-sub"></span><span class="u8-row-name"></span><span class="u8-badge"></span><span class="u8-acts"></span></div>');
            q(r, '.u8-acts').append(
              mini('On', 'Enable or disable', () => { const cur = cam.op(o.id); if (cur) void cam.put('PUT', `/ops/${encodeURIComponent(o.id)}`, { enabled: !cur.enabled }); }),
              mini('Up', 'Move earlier', () => { void cam.put('POST', `/ops/${encodeURIComponent(o.id)}/move`, { index: Math.max(0, cam.opsOf().findIndex((x) => x.id === o.id) - 1) }); }),
              mini('Dn', 'Move later', () => { void cam.put('POST', `/ops/${encodeURIComponent(o.id)}/move`, { index: cam.opsOf().findIndex((x) => x.id === o.id) + 1 }); }),
              mini('x', 'Delete this operation', () => { cam.forget(o.id); void cam.put('DELETE', `/ops/${encodeURIComponent(o.id)}`); }),
            );
            r.addEventListener('click', () => { cam.select(o.setup, o.id); });
            return r;
          },
          update: (r, o) => {
            setText(q(r, '.u8-row-sub'), o.id);
            setText(q(r, '.u8-row-name'), `${labelOf(o)} · ${cam.type(o.type)?.label ?? o.type}`);
            const b = q(r, '.u8-badge');
            const st = o.state?.status ?? 'never';
            setText(b, t(st));
            b.dataset.s = st === 'ok' ? 'fully' : st === 'stale' ? 'under' : st === 'failed' ? 'conflict' : '';
            setClass(r, 'is-selected', o.id === cam.opId);
            setClass(r, 'is-suppressed', !o.enabled);
            const on = q(r, '.u8-acts .u8-mini');
            setText(on, o.enabled ? 'On' : 'Off');
          },
        });
      };

      const paint = (): void => { paintShell(); paintLists(); paintForms(); };
      cam.onChange(paint);
      docStore.onChange(paintShell);
      paintShell();
      paint();
      void cam.loadGlobal().then(paint);
      void isAssembly;
      void setValue;
      void setDisabled;
      void checkCtl;
      void readout;
      void hint;
    },
  };
}
