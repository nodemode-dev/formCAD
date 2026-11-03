import { docStore } from '../ui/doc-store';
import type { DockPanel } from '../ui/dock';
import { el, patchList, q, setClass, setHidden, setText } from '../ui/dom';
import { t } from '../ui/i18n';
import { toast } from '../ui/toast';
import { button, buttons, checkCtl, selectCtl } from '../u8/ui';
import { view3d } from '../view3d/mount';
import { fieldForm, type FieldForm } from '../p12/fields';
import {
  CONTACT_SPECS, CONTACT_TYPES, CONTROL_SPECS, FIXTURE_SPECS, FIXTURE_TYPES, LOAD_SPECS, LOAD_TYPES, MATERIAL_SPECS,
  fixtureFromForm, fixtureToForm, loadFromForm, loadToForm, materialFromForm, materialToForm, optionSpecs, selectorEditor,
  type SelectorEditor,
} from './forms';
import { fillSelect, progressBar, reportBox, section } from './kit';
import { sim, type Json, type Rec } from './sim-store';

const KIND_BADGE: Record<string, string> = { study: 'ST', material: 'MA', load: 'LD', fixture: 'FX', contact: 'CT', mesh_control: 'MS' };
const KIND_NAME: Record<string, string> = { load: 'Load', fixture: 'Fixture', contact: 'Contact', mesh_control: 'Mesh control', material: 'Material', study: 'Study' };
const LINK_KEY: Record<string, string> = { load: 'loads', fixture: 'fixtures', contact: 'contacts' };

interface Row { key: string; rec: Rec; depth: number }

const typeLabel = (kind: string, type: string): string => {
  const table = kind === 'load' ? LOAD_TYPES : kind === 'fixture' ? FIXTURE_TYPES : kind === 'contact' ? CONTACT_TYPES : [];
  return table.find((r) => r[0] === type)?.[1] ?? type;
};

const pickedFaces = (body?: number): number[] => {
  const s = view3d()?.vp?.sel;
  if (!s) return [];
  return s.faces.filter((f) => body === undefined || f.body === body).map((f) => f.face);
};

const bodyOfStudy = (): number | undefined => {
  const g = sim.study()?.geometry as Json | undefined;
  return g && typeof g.body === 'number' ? g.body : undefined;
};

export function studyPanel(): DockPanel {
  return {
    id: 'sim', label: 'Simulation', icon: 'simulate', order: 44,
    build(body) {
      body.classList.add('u8-panel', 'xw-panel');
      const note = el('<p class="u8-note"></p>');
      setText(note, t('Open a part to set up a study.'));
      const live = el('<div class="u8-live cm-live"></div>');
      body.append(note, live);
      const paintShell = (): void => { const on = !!docStore.current(); setHidden(note, on); setHidden(live, !on); };

      const sTree = section('Studies');
      const list = el('<div class="u8-list sm-list" role="listbox" aria-label="Studies"></div>');
      const empty = el('<p class="u8-note cm-empty"></p>');
      const typeSel = selectCtl('Study type', []);
      const mesherNote = el('<p class="u8-note sm-mesher"></p>');
      sTree.body.append(list, empty, typeSel.el, buttons(button('New study', () => { void newStudy(); }, 'primary'), button('Delete', () => { void deleteSelected(); })), mesherNote);

      const sAdd = section('Study parts');
      const loadType = selectCtl('Load', LOAD_TYPES);
      const fixType = selectCtl('Fixture', FIXTURE_TYPES);
      const conType = selectCtl('Contact', CONTACT_TYPES);
      const libSel = selectCtl('Material from the library', []);
      const matSel = selectCtl('Study material', []);
      sAdd.body.append(
        matSel.el, libSel.el, buttons(button('Add library material', () => { void addLibrary(); })),
        loadType.el, buttons(button('Add load on the picked faces', () => { void addLoad(); })),
        fixType.el, buttons(button('Add fixture on the picked faces', () => { void addFixture(); })),
        conType.el, buttons(button('Add contact', () => { void addContact(); })),
        buttons(button('Add mesh control on the picked faces', () => { void addControl(); }), button('Use the selected body', () => { void setBody(); })),
      );
      matSel.input.addEventListener('change', () => { const s = sim.study(); if (s) void sim.update(s.id, { material: matSel.get() || null }); });

      const sEdit = section('Selected item');
      const editHost = el('<div class="sm-edit"></div>');
      const editNote = el('<p class="u8-note"></p>');
      setText(editNote, t('Select a study, material, load, fixture, contact or mesh control to edit it.'));
      sEdit.body.append(editNote, editHost);

      const sRun = section('Mesh and run');
      const meshBox = reportBox(3);
      const showMesh = checkCtl('Show the mesh in the view', false, () => { void paintMesh(); });
      const optsHost = el('<div class="sm-opts"></div>');
      const bar = progressBar();
      const runBox = reportBox(4);
      const meshBtn = button('Generate mesh', () => { void doMesh(); });
      const runBtn = button('Solve', () => { void doRun(); }, 'primary');
      sRun.body.append(meshBox.el, showMesh.el, buttons(meshBtn), optsHost, buttons(runBtn), bar.el, runBox.el);
      bar.onCancel(() => { void sim.cancel(); });

      live.append(sTree.root, sAdd.root, sEdit.root, sRun.root);

      const panes = new Map<string, { root: HTMLElement; load(r: Rec): void }>();
      const sigs = new Map<string, string>();
      let activePane = '';
      let debounce = 0;
      let lastMesh = '';
      const optForms = new Map<string, FieldForm>();

      const later = (id: string, fn: () => Json | null): void => {
        window.clearTimeout(debounce);
        debounce = window.setTimeout(() => { const f = fn(); if (f) void sim.update(id, f); }, 350);
      };

      function pane(key: string, make: () => { root: HTMLElement; load(r: Rec): void }): { root: HTMLElement; load(r: Rec): void } {
        let p = panes.get(key);
        if (!p) { p = make(); p.root.hidden = true; panes.set(key, p); editHost.appendChild(p.root); }
        return p;
      }

      function studyPane(): { root: HTMLElement; load(r: Rec): void } {
        return pane('study', () => {
          const root = el('<div class="sm-pane"></div>');
          let cur = '';
          const f = fieldForm([
            { name: 'name', type: 'text', label: 'Name' },
            { name: 'maxh_mm', type: 'number', label: 'Element size', unit: 'mm', min: 0.001, nullable: true },
          ], () => { const id = cur; later(id, () => studyFields(f)); });
          const bodyRead = el('<p class="u8-note sm-body"></p>');
          const solver = el('<p class="u8-note"></p>');
          root.append(f.el, bodyRead, solver);
          return {
            root,
            load(r) {
              cur = r.id;
              const m = (r.mesh ?? {}) as Json;
              f.set({ name: r.label ?? r.name ?? '', maxh_mm: m.maxh_mm ?? null });
              const g = (r.geometry ?? {}) as Json;
              setText(bodyRead, g.body === undefined || g.body === null ? t('No body chosen yet. Select a body in the view and use the selected body.') : `${t('Body')} ${String(g.body)}`);
              setText(solver, `${t('Study type')}: ${sim.solver(String(r.type))?.label ?? String(r.type)}`);
            },
          };
        });
      }

      function studyFields(f: FieldForm): Json | null {
        const s = sim.study();
        if (!s) return null;
        const v = f.read();
        const mesh = { ...((s.mesh ?? {}) as Json), maxh_mm: v.maxh_mm ?? null, order: 2 };
        return { name: String(v.name ?? s.label ?? ''), mesh };
      }

      function materialPane(): { root: HTMLElement; load(r: Rec): void } {
        return pane('material', () => {
          const root = el('<div class="sm-pane"></div>');
          let cur = '';
          const f = fieldForm(MATERIAL_SPECS, () => { const id = cur; later(id, () => materialFromForm(f.read())); });
          const src = el('<div class="sm-sources"></div>');
          root.append(f.el, src);
          return {
            root,
            load(r) {
              cur = r.id;
              f.set(materialToForm(r));
              const sources = Array.isArray(r.sources) ? r.sources as Json[] : [];
              patchList(src, sources, {
                key: (s) => `${String(s.field)}:${String(s.url ?? s.title ?? '')}`,
                create: () => el('<div class="sm-src"><span class="sm-src-f"></span><span class="sm-src-t"></span></div>'),
                update: (n, s) => { setText(q(n, '.sm-src-f'), String(s.field ?? '')); const tt = `${String(s.org ?? '')}: ${String(s.title ?? '')}${s.url ? ` (${String(s.url)})` : ''}`; setText(q(n, '.sm-src-t'), tt); n.title = tt; },
              });
            },
          };
        });
      }

      function sel(rec: Rec): Json | null {
        const body = bodyOfStudy();
        const faces = pickedFaces(body);
        return rec.select && typeof rec.select === 'object' ? rec.select as Json : faces.length ? { faces } : null;
      }
      void sel;

      function recordPane(kind: string, type: string): { root: HTMLElement; load(r: Rec): void } {
        return pane(`${kind}:${type}`, () => {
          const root = el('<div class="sm-pane"></div>');
          let cur = '';
          const specs = kind === 'load' ? LOAD_SPECS[type] ?? [] : kind === 'fixture' ? FIXTURE_SPECS[type] ?? [] : kind === 'contact' ? CONTACT_SPECS : kind === 'mesh_control' ? CONTROL_SPECS : [];
          const nameForm = fieldForm([{ name: 'name', type: 'text', label: 'Name' }], () => push());
          const f = fieldForm(specs, () => push());
          const editors: Record<string, SelectorEditor> = {};
          const slots = kind === 'contact' ? [['a', 'First side'], ['b', 'Second side']] : [['select', 'Faces']];
          const selHost = el('<div class="sm-sels"></div>');
          for (const [k, label] of slots) { const e = selectorEditor(label, () => pickedFaces(bodyOfStudy())); e.onChange(() => push()); editors[k] = e; selHost.appendChild(e.el); }
          const typeRead = el('<p class="u8-note"></p>');
          root.append(nameForm.el, typeRead, f.el, selHost);
          function push(): void {
            const id = cur;
            later(id, () => {
              const o: Json = { name: String(nameForm.read().name ?? '') };
              const v = f.read();
              if (kind === 'load') Object.assign(o, loadFromForm(type, v));
              else if (kind === 'fixture') Object.assign(o, fixtureFromForm(type, v));
              else if (kind === 'contact') { o.type = type; o.friction = type === 'frictional' ? v.friction ?? 0.2 : 0; }
              else Object.assign(o, v);
              for (const [k, e] of Object.entries(editors)) { const g = e.get(); if (g) o[k] = g; }
              return o;
            });
          }
          return {
            root,
            load(r) {
              cur = r.id;
              nameForm.set({ name: r.label ?? r.name ?? '' });
              setText(typeRead, `${t(KIND_NAME[kind] ?? kind)}: ${t(typeLabel(kind, type))}`);
              if (kind === 'load') f.set(loadToForm(r));
              else if (kind === 'fixture') f.set(fixtureToForm(r));
              else if (kind === 'contact') f.set({ friction: r.friction ?? 0.2 });
              else f.set({ maxh_mm: r.maxh_mm ?? null });
              if (kind === 'contact') f.show(type === 'frictional' ? null : new Set());
              for (const [k, e] of Object.entries(editors)) e.set(r[k]);
            },
          };
        });
      }

      function showPane(key: string): void {
        if (activePane === key) return;
        const prev = panes.get(activePane);
        if (prev) prev.root.hidden = true;
        activePane = key;
        const next = panes.get(key);
        if (next) next.root.hidden = false;
      }

      function syncEditor(): void {
        const rec = sim.recId ? sim.get(sim.recId) : sim.study();
        setHidden(editNote, !!rec);
        if (!rec) { showPane(''); return; }
        const key = rec.kind === 'study' ? 'study' : rec.kind === 'material' ? 'material' : `${rec.kind}:${String(rec.type ?? '')}`;
        const p = rec.kind === 'study' ? studyPane() : rec.kind === 'material' ? materialPane() : recordPane(rec.kind, String(rec.type ?? ''));
        const sig = `${rec.id}:${JSON.stringify(rec)}`;
        if (sigs.get(key) !== sig) { sigs.set(key, sig); p.load(rec); }
        showPane(key);
      }

      function rows(): Row[] {
        const out: Row[] = [];
        for (const s of sim.of('study')) {
          out.push({ key: `study:${s.id}`, rec: s, depth: 0 });
          if (s.id !== sim.studyId) continue;
          const mat = s.material ? sim.get(String(s.material)) : undefined;
          if (mat) out.push({ key: `material:${mat.id}`, rec: mat, depth: 1 });
          for (const k of ['loads', 'fixtures', 'contacts']) for (const id of sim.ids(s, k)) { const r = sim.get(id); if (r) out.push({ key: `${r.kind}:${r.id}`, rec: r, depth: 1 }); }
          const m = (s.mesh ?? {}) as Json;
          for (const id of Array.isArray(m.controls) ? (m.controls as unknown[]).map(String) : []) { const r = sim.get(id); if (r) out.push({ key: `mesh_control:${r.id}`, rec: r, depth: 1 }); }
        }
        return out;
      }

      function paintList(): void {
        const rs = rows();
        patchList(list, rs, {
          key: (r) => r.key,
          create: (r) => {
            const n = el('<div class="u8-row sm-row" role="option"><span class="u8-row-sub"></span><span class="u8-row-name"></span><span class="u8-row-sub sm-row-state"></span></div>');
            n.addEventListener('click', () => {
              const rec = sim.get(n.dataset.id ?? '');
              if (!rec) return;
              if (rec.kind === 'study') sim.select(rec.id, '');
              else sim.select(sim.studyId, rec.id);
              highlight(rec);
            });
            void r;
            return n;
          },
          update: (n, r) => {
            n.dataset.id = r.rec.id;
            const label = String(r.rec.label || r.rec.name || r.rec.id);
            const sub = r.rec.kind === 'study' ? (sim.solver(String(r.rec.type))?.label ?? String(r.rec.type ?? '')) : r.rec.kind === 'material' ? '' : typeLabel(r.rec.kind, String(r.rec.type ?? ''));
            setText(q(n, '.u8-row-sub'), KIND_BADGE[r.rec.kind] ?? '');
            const nm = q(n, '.u8-row-name');
            const text = sub ? `${label} · ${t(sub)}` : label;
            setText(nm, text);
            if (n.title !== text) n.title = text;
            setText(q(n, '.sm-row-state'), r.rec.kind === 'study' ? String(r.rec.status ?? '') : '');
            n.style.setProperty('--sm-depth', String(r.depth));
            const on = r.rec.kind === 'study' ? !sim.recId && r.rec.id === sim.studyId : r.rec.id === sim.recId;
            setClass(n, 'is-selected', on);
            n.setAttribute('aria-selected', String(on));
          },
        });
        setHidden(empty, rs.length > 0);
      }

      function highlight(rec: Rec): void {
        const vp = view3d()?.vp;
        const s = rec.select as Json | undefined;
        const b = bodyOfStudy();
        if (!vp || b === undefined || !s || !Array.isArray(s.faces)) return;
        vp.setSelection({ bodies: [], faces: (s.faces as number[]).map((face) => ({ body: b, face })), edges: [] }, false);
      }

      function paintParts(): void {
        const s = sim.study();
        const mats = sim.of('material');
        fillSelect(matSel.input as HTMLSelectElement, [['', t('No material')], ...mats.map((m) => [m.id, String(m.label || m.name || m.id)] as [string, string])]);
        if (s && document.activeElement !== matSel.input) matSel.set(String(s.material ?? ''));
        const lib = sim.library.map((m) => [String(m.id ?? m.name ?? ''), String(m.name ?? m.id ?? '')] as [string, string]);
        fillSelect(libSel.input as HTMLSelectElement, lib.length ? lib : [['', t('The library is empty')]]);
        const solvers = sim.solvers.map((r) => [r.type, r.label] as [string, string]);
        fillSelect(typeSel.input as HTMLSelectElement, solvers.length ? solvers : [['static', 'Linear static']]);
        const m = sim.mesher;
        const msg = m.available === false ? `${t('The mesher is not installed')}${m.message ? `: ${m.message}` : ''}` : m.available ? `${t('Mesher')} ${m.version ?? ''}` : '';
        setText(mesherNote, msg);
        setClass(mesherNote, 'is-bad', m.available === false);
      }

      function paintRun(): void {
        const s = sim.study();
        const info = s ? sim.meshInfo.get(s.id) : undefined;
        const lines: string[] = [];
        if (s) {
          lines.push(`${t('Status')}: ${String(s.status ?? '')}`);
          if (info) {
            const n = info.nodes, e = info.tets ?? info.elements;
            lines.push(`${t('Nodes')} ${String(n ?? '-')} · ${t('Elements')} ${String(e ?? '-')}${typeof info.volume === 'number' ? ` · ${t('Volume')} ${(info.volume as number).toPrecision(5)} mm3` : ''}`);
          } else if (s.mesh_blob) lines.push(t('Meshed.'));
          else lines.push(t('Not meshed yet.'));
        }
        meshBox.set(lines, false);
        const meshKey = s ? `${s.id}:${String(s.mesh_blob ?? '')}` : '';
        if (meshKey !== lastMesh) { lastMesh = meshKey; if (showMesh.get()) void paintMesh(); }
        const st = s ? sim.solver(String(s.type)) : undefined;
        const key = s ? String(s.type) : '';
        if (s && st && !optForms.has(key)) {
          const specs = optionSpecs(st.options);
          const form = fieldForm(specs, () => undefined);
          form.set({});
          form.el.hidden = true;
          optForms.set(key, form);
          optsHost.appendChild(form.el);
        }
        for (const [k, f] of optForms) f.el.hidden = k !== key;
        const j = sim.job;
        const mine = !!j && !!s && j.study === s.id;
        bar.set(mine ? j.progress : 0, mine ? `${j.phase || t('Solving')} · ${Math.round(j.progress * 100)} %` : '', mine && sim.running);
        const msg: string[] = [];
        if (mine && j) { msg.push(`${t('Job')} ${j.state}`); if (j.message) msg.push(j.message); }
        if (sim.error) msg.push(sim.error);
        runBox.set(msg, !!mine && (j?.state === 'error' || j?.state === 'failed'));
        const dis = !s || sim.running;
        (runBtn as HTMLButtonElement).disabled = dis;
        (meshBtn as HTMLButtonElement).disabled = dis || (!!s && sim.topo(s.id));
      }

      function repaint(): void {
        paintShell();
        if (docStore.current()) void sim.loadLibrary();
        paintList();
        paintParts();
        syncEditor();
        paintRun();
      }

      async function paintMesh(): Promise<void> {
        const layer = sim.layer;
        const s = sim.study();
        if (!layer) return;
        if (!showMesh.get() || !s) { layer.hideMesh(); return; }
        layer.setMesh(await sim.meshDisplay(s.id));
      }

      async function newStudy(): Promise<void> {
        const vp = view3d()?.vp;
        const bodyId = vp?.sel.bodies[0] ?? vp?.sel.faces[0]?.body ?? [...(vp?.bodyViews.keys() ?? [])][0];
        if (bodyId === undefined) { toast(t('Add a body first, then make a study.'), 'error'); return; }
        const type = typeSel.get() || 'static';
        const n = sim.of('study').length + 1;
        const rec = await sim.create('study', { name: `${sim.solver(type)?.label ?? type} ${n}`, type, geometry: { body: bodyId }, loads: [], fixtures: [], contacts: [], mesh: { maxh_mm: null, order: 2, controls: [] }, options: {} });
        if (rec) sim.select(rec.id, '');
      }

      async function deleteSelected(): Promise<void> {
        const rec = sim.recId ? sim.get(sim.recId) : sim.study();
        const s = sim.study();
        if (!rec) return;
        if (rec.kind !== 'study' && s) await unlink(s, rec);
        await sim.remove(rec.id);
      }

      async function unlink(s: Rec, rec: Rec): Promise<void> {
        const key = LINK_KEY[rec.kind];
        if (key) await sim.update(s.id, { [key]: sim.ids(s, key).filter((i) => i !== rec.id) });
        else if (rec.kind === 'mesh_control') { const m = (s.mesh ?? {}) as Json; await sim.update(s.id, { mesh: { ...m, controls: (Array.isArray(m.controls) ? m.controls as string[] : []).filter((i) => i !== rec.id) } }); }
        else if (rec.kind === 'material') await sim.update(s.id, { material: null });
      }

      async function setBody(): Promise<void> {
        const s = sim.study();
        const vp = view3d()?.vp;
        const b = vp?.sel.bodies[0] ?? vp?.sel.faces[0]?.body;
        if (!s || b === undefined) { toast(t('Select a body in the view first.'), 'error'); return; }
        await sim.update(s.id, { geometry: { ...((s.geometry ?? {}) as Json), body: b } });
      }

      function needFaces(): number[] | null {
        const f = pickedFaces(bodyOfStudy());
        if (!f.length) { toast(t('Pick faces of the study body in the view first.'), 'error'); return null; }
        return f;
      }

      async function attach(kind: string, fields: Json): Promise<void> {
        const s = sim.study();
        if (!s) { toast(t('Make a study first.'), 'error'); return; }
        const rec = await sim.create(kind, fields);
        if (!rec) return;
        const key = LINK_KEY[kind];
        if (key) await sim.update(s.id, { [key]: [...sim.ids(s, key), rec.id] });
        else if (kind === 'mesh_control') { const m = (s.mesh ?? {}) as Json; await sim.update(s.id, { mesh: { ...m, controls: [...(Array.isArray(m.controls) ? m.controls as string[] : []), rec.id] } }); }
        else if (kind === 'material') await sim.update(s.id, { material: rec.id });
        sim.select(s.id, rec.id);
      }

      const defaults = (specs: ReadonlyArray<{ name: string; default?: unknown }>): Json => Object.fromEntries(specs.map((sp) => [sp.name, sp.default ?? null]));
      const BODYLESS = new Set(['gravity', 'heat_load', 'temperature_field']);

      async function addLoad(): Promise<void> {
        const type = loadType.get();
        const faces = BODYLESS.has(type) ? null : needFaces();
        if (!BODYLESS.has(type) && !faces) return;
        const n = sim.of('load').length + 1;
        await attach('load', { name: `${typeLabel('load', type)} ${n}`, ...loadFromForm(type, defaults(LOAD_SPECS[type] ?? [])), select: faces ? { faces } : { all: true } });
      }

      async function addFixture(): Promise<void> {
        const type = fixType.get();
        const faces = type === 'temperature' && !pickedFaces(bodyOfStudy()).length ? [] : needFaces();
        if (!faces) return;
        const n = sim.of('fixture').length + 1;
        await attach('fixture', { name: `${typeLabel('fixture', type)} ${n}`, ...fixtureFromForm(type, defaults(FIXTURE_SPECS[type] ?? [])), select: faces.length ? { faces } : { all: true } });
      }

      async function addContact(): Promise<void> {
        const type = conType.get();
        const faces = needFaces();
        if (!faces) return;
        const n = sim.of('contact').length + 1;
        await attach('contact', { name: `${typeLabel('contact', type)} ${n}`, type, friction: type === 'frictional' ? 0.2 : 0, a: { faces }, b: { all: true } });
      }

      async function addControl(): Promise<void> {
        const f = needFaces();
        if (!f) return;
        await attach('mesh_control', { name: `${t('Mesh control')} ${sim.of('mesh_control').length + 1}`, select: { faces: f }, maxh_mm: 2 });
      }

      async function addLibrary(): Promise<void> {
        const id = libSel.get();
        const m = sim.library.find((x) => String(x.id ?? x.name) === id);
        if (!m) { toast(t('Choose a library material first.'), 'error'); return; }
        await attach('material', { name: m.name ?? id, library: m.id ?? id });
      }

      async function doMesh(): Promise<void> {
        const s = sim.study();
        if (!s) return;
        await sim.mesh(s.id);
      }

      async function doRun(): Promise<void> {
        const s = sim.study();
        if (!s) return;
        const f = optForms.get(String(s.type));
        const options = f ? Object.fromEntries(Object.entries(f.read()).filter(([, v]) => v !== null && v !== '')) : {};
        if (Object.keys(options).length) await sim.update(s.id, { options });
        await sim.run(s.id);
      }

      sim.onChange(repaint);
      document.addEventListener('formcad:view3d-created', () => { sim.schedule(0); });
      sim.schedule(0);
      void sim.loadLibrary();
      repaint();
    },
  };
}
