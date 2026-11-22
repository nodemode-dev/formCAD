import { param, type ParamRow } from '../io/api-param';
import { docStore } from '../ui/doc-store';
import { el, q, setClass, setHidden, setText, setTitle } from '../ui/dom';
import { t } from '../ui/i18n';
import { icon } from '../ui/icons';
import { toast } from '../ui/toast';
import { bendField } from '../sheet/bend-field';
import { view3d, type View3dController } from '../view3d/mount';
import type { SelectionState } from '../view3d/types';
import { part, previewFeature, type Feature, type HoleRow, type HoleTable, type RefRecord, type RefSchema, type TypeSchema } from './api';
import { makeField, pretty, showWhen, slotShown, type FieldView } from './fields';
import { iconFor } from './kinds';
import { RefSlotView } from './ref-field';
import { messageOf, partStore } from './store';

type Mode = { kind: 'new'; type: string; after: string | null } | { kind: 'edit'; fid: string };

interface Form {
  type: string;
  schema: TypeSchema;
  root: HTMLElement;
  fields: Map<string, FieldView>;
  slots: Map<string, RefSlotView>;
  size?: HTMLSelectElement;
  sizeNote?: HTMLElement;
}

const STATUS_WORDS: Record<string, string> = {
  two_sources: 'Two published standards give the same value.',
  read_twice: 'Read twice from one public copy of the source; not a statement of any standard.',
  read_once: 'Read once only. Check it against your standard before use.',
  illegible_in_source: 'Not legible in the source. Type the pitch yourself.',
};

let holeCache: HoleTable | null = null;

export class FeatureEditor {
  private readonly panel: HTMLElement;
  private readonly head: HTMLElement;
  private readonly nameIn: HTMLInputElement;
  private readonly host: HTMLElement;
  private readonly msg: HTMLElement;
  private readonly state: HTMLElement;
  private readonly ok: HTMLButtonElement;
  private readonly cancel: HTMLButtonElement;
  private readonly forms = new Map<string, Form>();
  private mode: Mode | null = null;
  private form: Form | null = null;
  private timer = 0;
  private seq = 0;
  private ctl: AbortController | null = null;
  private picking: RefSlotView | null = null;
  private prevLevel: string | null = null;
  private busy = false;
  private lastBad = false;

  constructor(parent: HTMLElement) {
    this.panel = el<HTMLElement>(
      '<aside class="pp" aria-label="Feature properties" aria-hidden="true">' +
      '<header class="pp-head"><span class="pp-head-ico"></span><span class="pp-title"></span>' +
      `<button class="cv-icon-btn pp-close" type="button" aria-label="Close">${icon('close', 14)}</button></header>` +
      '<label class="pp-row pp-name"><span class="pp-lab"></span><input class="cv-input pp-in" type="text" spellcheck="false" autocomplete="off"></label>' +
      '<div class="pp-scroll"><div class="pp-host"></div></div>' +
      '<p class="pp-state" role="status"></p><p class="pp-msg" role="alert"></p>' +
      '<footer class="pp-foot"><button class="cv-btn cv-btn-ghost pp-cancel" type="button"></button><button class="cv-btn cv-btn-primary pp-ok" type="button"></button></footer></aside>');
    parent.appendChild(this.panel);
    this.head = q(this.panel, '.pp-title');
    this.nameIn = q<HTMLInputElement>(this.panel, '.pp-name input');
    this.host = q(this.panel, '.pp-host');
    this.msg = q(this.panel, '.pp-msg');
    this.state = q(this.panel, '.pp-state');
    this.ok = q<HTMLButtonElement>(this.panel, '.pp-ok');
    this.cancel = q<HTMLButtonElement>(this.panel, '.pp-cancel');
    setText(q(this.panel, '.pp-name .pp-lab'), t('Name'));
    setText(this.ok, t('OK'));
    setText(this.cancel, t('Cancel'));
    q(this.panel, '.pp-close').addEventListener('click', () => this.dismiss());
    this.cancel.addEventListener('click', () => this.dismiss());
    this.ok.addEventListener('click', () => { void this.commit(); });
    this.panel.addEventListener('keydown', (e) => {
      if (e.key === 'Escape') { e.stopPropagation(); this.dismiss(); }
      else if (e.key === 'Enter' && this.form?.type !== 'sketch' && e.target instanceof HTMLInputElement && !e.defaultPrevented) { e.preventDefault(); void this.commit(); }
    });
    partStore.onChange(() => { if (this.mode && this.form) this.refreshCandidates(); });
  }

  get isOpen(): boolean { return this.mode !== null; }
  get editing(): string | null { return this.mode?.kind === 'edit' ? this.mode.fid : null; }

  private ctrl(): View3dController | null { return view3d(); }

  private build(schema: TypeSchema): Form {
    const have = this.forms.get(schema.type);
    if (have) return have;
    const root = el<HTMLElement>('<div class="pp-form"></div>');
    const form: Form = { type: schema.type, schema, root, fields: new Map(), slots: new Map() };
    const refs = el<HTMLElement>('<div class="pp-sec pp-refs"></div>');
    const props = el<HTMLElement>('<div class="pp-sec pp-props"></div>');
    root.append(refs, props);
    const change = (): void => { this.refreshVisibility(); this.schedule(); };
    for (const r of schema.refs) {
      if (r.kind === 'plane') continue;
      const view = new RefSlotView(r, {
        change,
        togglePick: (v) => this.togglePick(v),
        candidates: (slot) => this.candidates(slot),
      });
      form.slots.set(r.name, view);
      refs.appendChild(view.row);
    }
    if (schema.type === 'hole') {
      const notice = el<HTMLElement>(`<p class="pp-note" data-hole-notice></p>`);
      setText(notice, t('Every size names its published source and how well it could be read. Check values against your own copy of the standard.'));
      props.appendChild(notice);
    }
    for (const p of schema.params) {
      if (schema.type === 'sketch') continue;
      if (schema.type === 'hole' && p.name === 'size') {
        const row = el<HTMLElement>('<label class="pp-row pp-enum"><span class="pp-lab"></span><select class="cv-input pp-in"></select></label>');
        setText(q(row, '.pp-lab'), t('Size'));
        const sel = q<HTMLSelectElement>(row, 'select');
        const note = el<HTMLElement>('<p class="pp-note pp-size-note"></p>');
        sel.addEventListener('change', () => { this.sizePicked(form); change(); });
        form.size = sel;
        form.sizeNote = note;
        form.fields.set('size', {
          row, name: 'size',
          set: (v) => { sel.value = typeof v === 'string' ? v : ''; if (sel.value !== (typeof v === 'string' ? v : '')) sel.value = ''; },
          get: () => sel.value || null,
          show: (on) => { setHidden(row, !on); setHidden(note, !on); },
          bad: () => false,
        });
        props.append(row, note);
        continue;
      }
      const bendList = (schema.type === 'bend_relief' && p.name === 'bends') || (schema.type === 'corner_relief' && p.name === 'corners');
      const f = bendList ? bendField(p, change, p.name === 'corners') : makeField(p, change);
      form.fields.set(p.name, f);
      props.appendChild(f.row);
    }
    this.forms.set(schema.type, form);
    return form;
  }

  private candidates(slot: RefSchema): Feature[] {
    const feats = partStore.features;
    const mode = this.mode;
    let limit = feats.length;
    if (mode?.kind === 'edit') limit = feats.findIndex((f) => f.id === mode.fid);
    else if (mode?.kind === 'new' && mode.after) limit = feats.findIndex((f) => f.id === mode.after) + 1;
    const before = feats.slice(0, limit < 0 ? feats.length : limit);
    if (slot.kind === 'sketch') return before.filter((f) => f.type === 'sketch');
    return before.filter((f) => f.type !== 'sketch');
  }

  private refreshCandidates(): void {
    if (!this.form) return;
    for (const v of this.form.slots.values()) v.options();
  }

  private values(): Record<string, unknown> {
    const out: Record<string, unknown> = {};
    if (!this.form) return out;
    for (const [k, f] of this.form.fields) out[k] = f.get();
    return out;
  }

  private refreshVisibility(): void {
    const form = this.form;
    if (!form) return;
    const v = this.values();
    for (const [k, f] of form.fields) f.show(showWhen(form.type, k, v));
    for (const [k, s] of form.slots) s.show(slotShown(form.type, k, v));
  }

  async openNew(type: string): Promise<void> {
    const id = docStore.activeId;
    if (!id) return;
    await this.prepare();
    const schema = partStore.types.get(type);
    if (!schema) { toast(t('This feature type is not installed.'), 'error'); return; }
    await this.leaveEdit();
    const tree = partStore.tree;
    const after = tree?.rollback ?? null;
    const form = this.build(schema);
    this.mode = { kind: 'new', type, after };
    this.form = form;
    for (const f of schema.params.map((p) => ({ p, v: form.fields.get(p.name) }))) f.v?.set(f.p.default);
    this.presetSketches(form);
    await this.fillHole(form);
    this.show(schema.label, iconFor(type), partStore.types.get(type)?.label ?? type, '');
    this.afterOpen(form);
  }

  private presetSketches(form: Form): void {
    const feats = partStore.features;
    const unused = feats.filter((f) => f.type === 'sketch' && f.children.length === 0);
    const singles = [...form.slots.values()].filter((s) => s.kind === 'sketch' && !s.slot.multi && s.slot.required);
    const picks = unused.slice(-singles.length || unused.length);
    const sel = partStore.find(partStore.selected);
    const first = sel && sel.type === 'sketch' ? [sel] : picks;
    let at = 0;
    for (const s of form.slots.values()) {
      s.load(undefined, (id) => partStore.find(id));
      if (s.kind === 'sketch' && !s.slot.multi && s.slot.required && first[at]) { s.load({ kind: 'feature', id: first[at].id }, (id) => partStore.find(id)); at++; }
      else if (s.kind === 'sketch' && s.slot.multi && s.slot.required) s.load(unused.map((u) => ({ kind: 'feature', id: u.id })), (id) => partStore.find(id));
    }
  }

  async openEdit(fid: string): Promise<void> {
    const f = partStore.find(fid);
    if (!f) return;
    await this.prepare();
    await this.leaveEdit();
    if (f.type === 'sketch') { this.openSketch(f); return; }
    const schema = partStore.types.get(f.type);
    if (!schema) { toast(t('This feature type is not installed.'), 'error'); return; }
    const form = this.build(schema);
    this.mode = { kind: 'edit', fid };
    this.ctrl()?.holdAt(fid);
    this.form = form;
    for (const p of schema.params) form.fields.get(p.name)?.set(f.params[p.name] ?? p.default);
    for (const s of form.slots.values()) s.load(f.refs[s.slot.name] as RefRecord | RefRecord[] | undefined, (id) => partStore.find(id));
    await this.fillHole(form);
    this.show(f.label, iconFor(f.type), schema.label, f.label);
    this.afterOpen(form);
    this.highlightRefs();
    partStore.selected = fid;
    document.dispatchEvent(new CustomEvent('formcad:part-select', { detail: fid }));
  }

  private async prepare(): Promise<void> {
    const c = this.ctrl();
    if (c && !c.on) await c.enter();
    if (partStore.types.size === 0) await partStore.load();
  }

  private async leaveEdit(): Promise<void> {
    if (this.mode) this.close();
  }

  private show(title: string, ico: string, kindLabel: string, name: string): void {
    const form = this.form;
    if (!form) return;
    setText(this.head, t(kindLabel));
    q(this.panel, '.pp-head-ico').innerHTML = icon(ico, 16);
    this.nameIn.value = name;
    this.nameIn.placeholder = t('Automatic name');
    setHidden(this.nameIn.closest('label') as HTMLElement, false);
    if (this.host.firstElementChild !== form.root) this.host.replaceChildren(form.root);
    setText(this.msg, '');
    setText(this.state, '');
    setClass(this.msg, 'is-on', false);
    this.refreshCandidates();
    this.refreshVisibility();
    void title;
  }

  private afterOpen(form: Form): void {
    this.panel.classList.add('is-open');
    this.panel.setAttribute('aria-hidden', 'false');
    this.schedule(60);
    const first = form.root.querySelector<HTMLElement>('input:not([type=checkbox]), select');
    first?.focus({ preventScroll: true });
  }

  private openSketch(f: Feature): void {
    const name = String(f.params.sketch ?? '');
    const form = this.sketchForm();
    this.mode = { kind: 'edit', fid: f.id };
    this.form = form;
    this.show(f.label, 'sketch', 'Sketch', f.label);
    const rows = q(form.root, '.pp-dims');
    const edit = q<HTMLButtonElement>(form.root, '.pp-edit-sketch');
    edit.onclick = () => { this.close(); document.dispatchEvent(new CustomEvent('formcad:part-sketch-edit', { detail: f.id })); };
    setText(q(form.root, '.pp-sketch-plane'), `${t('Plane')}: ${f.params.plane === 'face' ? t('A face') : f.params.plane === 'source' ? t('Reference plane') : String(f.params.plane ?? '')}`);
    void this.loadDims(rows, name);
    setHidden(this.ok, false);
    this.panel.classList.add('is-open');
    this.panel.setAttribute('aria-hidden', 'false');
  }

  private sketchForm(): Form {
    const have = this.forms.get('sketch');
    if (have) return have;
    const root = el<HTMLElement>(
      '<div class="pp-form"><div class="pp-sec"><p class="pp-note pp-sketch-plane"></p>' +
      '<button class="cv-btn pp-edit-sketch" type="button"></button></div>' +
      '<div class="pp-sec"><div class="pp-lab pp-dims-title"></div><div class="pp-dims"></div></div></div>');
    setText(q(root, '.pp-edit-sketch'), t('Edit Sketch'));
    setText(q(root, '.pp-dims-title'), t('Sketch dimensions'));
    const schema = partStore.types.get('sketch') ?? { type: 'sketch', label: 'Sketch', group: 'sketch', needs_body: false, sketch: true, params: [], refs: [], roles: [] };
    const form: Form = { type: 'sketch', schema, root, fields: new Map(), slots: new Map() };
    this.forms.set('sketch', form);
    return form;
  }

  private async loadDims(host: HTMLElement, sketch: string): Promise<void> {
    const id = docStore.activeId;
    if (!id) return;
    let rows: ParamRow[] = [];
    try { rows = (await param.list(id)).parameters.filter((r) => r.sketch === sketch); } catch { rows = []; }
    const have = new Map(Array.from(host.children).map((c) => [(c as HTMLElement).dataset.name ?? '', c as HTMLElement]));
    for (const r of rows) {
      let row = have.get(r.name);
      if (!row) {
        row = el<HTMLElement>('<label class="pp-row pp-dim"><span class="pp-lab"></span><input class="cv-input pp-in" type="text" spellcheck="false"><span class="pp-unit pp-dim-val"></span></label>');
        row.dataset.name = r.name;
        const input = q<HTMLInputElement>(row, 'input');
        const apply = (): void => {
          const v = input.value.trim();
          if (!v || v === row?.dataset.expr) return;
          const doc = docStore.activeId;
          if (!doc) return;
          setText(this.msg, '');
          param.edit(doc, r.name, { expr: v }).then(() => { partStore.refresh(0); void this.loadDims(host, sketch); }).catch((e: unknown) => { setText(this.msg, messageOf(e)); setClass(this.msg, 'is-on', true); });
        };
        input.addEventListener('change', apply);
        input.addEventListener('keydown', (e) => { if (e.key === 'Enter') apply(); });
        host.appendChild(row);
      }
      row.dataset.expr = r.expr;
      setText(q(row, '.pp-lab'), r.name);
      const input = q<HTMLInputElement>(row, 'input');
      if (document.activeElement !== input) input.value = r.expr;
      setText(q(row, '.pp-dim-val'), r.error ? '!' : r.shown);
      setHidden(row, false);
    }
    for (const [name, row] of have) if (!rows.some((r) => r.name === name)) row.remove();
  }

  private async fillHole(form: Form): Promise<void> {
    if (form.type !== 'hole' || !form.size) return;
    if (!holeCache) {
      try { holeCache = await part.holes(); } catch { holeCache = null; }
    }
    const sel = form.size;
    if (sel.options.length <= 1 && holeCache) {
      const none = document.createElement('option');
      none.value = '';
      none.textContent = t('No size from the table');
      sel.appendChild(none);
      for (const r of holeCache.sections.thread_series) {
        const o = document.createElement('option');
        o.value = r.id;
        o.textContent = `${r.id} · ${r.pitch === null ? t('no pitch') : `${t('pitch')} ${r.pitch}`} · ${t(pretty(r.status))}`;
        sel.appendChild(o);
      }
      const n = form.root.querySelector('[data-hole-notice]');
      if (n && holeCache) setTitle(n as HTMLElement, holeCache.notice);
      form.fields.get('size')?.row.after(form.sizeNote as HTMLElement);
    }
    this.sizePicked(form, false);
  }

  private sizePicked(form: Form, fill = true): void {
    const sel = form.size;
    if (!sel || !form.sizeNote) return;
    const row: HoleRow | undefined = holeCache?.sections.thread_series.find((r) => r.id === sel.value);
    const keys = row ? (row.sources?.length ? row.sources : [row.source]) : [];
    const titles = keys.map((k) => holeCache?.sources?.[k]?.title).filter((s): s is string => !!s);
    const src = titles.length ? ` ${t(titles.length > 1 ? 'Sources:' : 'Source:')} ${titles.join('; ')}` : '';
    setText(form.sizeNote, row ? t(STATUS_WORDS[row.status] ?? 'Unverified seed value.') + (row.note ? ` ${t(row.note)}` : '') + src : t('Counterbore and countersink sizes do not ship: no free published source for them was found. Type your own numbers.'));
    setClass(form.sizeNote, 'is-warn', !!row && row.status !== 'read_twice' && row.status !== 'two_sources');
    if (!row || !fill) return;
    const nom = form.fields.get('thread_nominal');
    const pit = form.fields.get('thread_pitch');
    if (nom && nom.get() === null) nom.set(row.nominal);
    if (pit && pit.get() === null && row.pitch !== null) pit.set(row.pitch);
  }

  private togglePick(view: RefSlotView): void {
    const was = this.picking;
    this.stopPick();
    if (was === view) return;
    const c = this.ctrl();
    const vp = c?.vp;
    if (!vp) return;
    this.picking = view;
    this.prevLevel = vp.level;
    vp.setLevel(view.kind === 'edge' ? 'edge' : 'face');
    view.setPicking(true);
    vp.onPick = (sel) => this.picked(view, sel);
    document.dispatchEvent(new CustomEvent('formcad:hint', { detail: t(view.kind === 'edge' ? 'Click edges in the view to add or remove them.' : 'Click faces in the view to add or remove them.') }));
    vp.canvas.focus({ preventScroll: true });
  }

  private stopPick(): void {
    const vp = this.ctrl()?.vp;
    if (this.picking) this.picking.setPicking(false);
    this.picking = null;
    if (vp) {
      vp.onPick = null;
      if (this.prevLevel) vp.setLevel(this.prevLevel as 'any' | 'body' | 'face' | 'edge');
    }
    this.prevLevel = null;
    document.dispatchEvent(new CustomEvent('formcad:hint', { detail: '' }));
  }

  private picked(view: RefSlotView, sel: SelectionState): void {
    const hits = view.kind === 'edge' ? sel.edges.map((e) => e.edge) : sel.faces.map((f) => f.face);
    for (const pid of hits) view.add({ send: { pid }, text: `${view.kind === 'edge' ? 'Edge' : 'Face'} ${pid}`, pid });
    this.highlightRefs();
  }

  private highlightRefs(): void {
    const vp = this.ctrl()?.vp;
    const form = this.form;
    if (!vp || !form) return;
    const body = partStore.tree?.body ?? 0;
    const faces: Array<{ body: number; face: number }> = [];
    const edges: Array<{ body: number; edge: number }> = [];
    for (const s of form.slots.values()) {
      for (const i of s.items) {
        if (i.pid === undefined) continue;
        if (s.kind === 'face') faces.push({ body, face: i.pid });
        else if (s.kind === 'edge') edges.push({ body, edge: i.pid });
      }
    }
    vp.setSelection({ bodies: [], faces, edges }, false);
  }

  private collect(): { params: Record<string, unknown>; refs: Record<string, unknown>; missing: string; bad: string } {
    const form = this.form;
    const out = { params: {} as Record<string, unknown>, refs: {} as Record<string, unknown>, missing: '', bad: '' };
    if (!form || !this.mode) return out;
    const isNew = this.mode.kind === 'new';
    const vals = this.values();
    for (const [k, f] of form.fields) {
      if (f.bad()) out.bad = k;
      const v = vals[k];
      if (isNew) { if (v !== null && v !== undefined) out.params[k] = v; } else out.params[k] = v;
    }
    for (const [k, s] of form.slots) {
      if (!slotShown(form.type, k, vals)) continue;
      if (s.slot.required && !s.has()) out.missing = out.missing || (s.slot.label || k);
      if (isNew ? s.has() : s.dirty) out.refs[k] = s.value();
    }
    return out;
  }

  private schedule(delay = 220): void {
    window.clearTimeout(this.timer);
    if (!this.mode || this.form?.type === 'sketch') return;
    this.timer = window.setTimeout(() => { void this.preview(); }, delay);
  }

  private clearPreview(): void {
    this.ctrl()?.vp?.setPreview(null);
  }

  private async preview(): Promise<void> {
    const mode = this.mode;
    const id = docStore.activeId;
    this.lastBad = true;
    if (!mode || !id || !this.form) return;
    const c = this.collect();
    if (c.bad) { this.say(`${t('Fix the structure in')} ${pretty(c.bad)}.`, true); return; }
    if (c.missing) { this.clearPreview(); this.say(`${t('Choose')} ${c.missing}`, true); return; }
    this.ctl?.abort();
    const ctl = new AbortController();
    this.ctl = ctl;
    const n = ++this.seq;
    setText(this.state, t('Previewing...'));
    const ask = mode.kind === 'new' ? { type: mode.type, params: c.params, refs: c.refs, after: mode.after } : { id: mode.fid, params: c.params, refs: c.refs, hold: mode.fid };
    try {
      const res = await previewFeature(id, ask, ctl.signal);
      if (n !== this.seq || this.mode !== mode) return;
      if (res.info.status === 'error') {
        this.clearPreview();
        this.say(res.info.message || t('The feature could not be built.'), true);
      } else {
        this.lastBad = false;
        this.ctrl()?.vp?.setPreview(res.model);
        this.say(res.info.warnings.join(' '), false, res.info.warnings.length > 0);
      }
      setText(this.state, '');
    } catch (e) {
      if (e instanceof DOMException && e.name === 'AbortError') return;
      if (n !== this.seq) return;
      this.clearPreview();
      this.say(messageOf(e), true);
      setText(this.state, '');
    }
  }

  private say(text: string, error: boolean, warn = false): void {
    setText(this.msg, text);
    setClass(this.msg, 'is-on', text !== '');
    setClass(this.msg, 'is-error', error);
    setClass(this.msg, 'is-warn', warn);
    setDisabledOk(this.ok, this.busy);
  }

  private async commit(): Promise<void> {
    const mode = this.mode;
    const id = docStore.activeId;
    if (!mode || !id || !this.form || this.busy) return;
    if (this.form.type === 'sketch') { this.close(); return; }
    const c = this.collect();
    if (c.bad) { this.say(`${t('Fix the structure in')} ${pretty(c.bad)}.`, true); return; }
    if (c.missing) { this.say(`${t('Choose')} ${c.missing}`, true); return; }
    window.clearTimeout(this.timer);
    this.busy = true;
    setDisabledOk(this.ok, true);
    try {
      await this.preview();
      if (this.lastBad) return;
      const label = this.nameIn.value.trim();
      const done = mode.kind === 'new'
        ? await part.add(id, { type: mode.type, params: c.params, refs: c.refs, after: mode.after, ...(label ? { label } : {}) })
        : await part.edit(id, mode.fid, { params: c.params, refs: c.refs, ...(label ? { label } : {}) });
      partStore.refresh(0);
      await this.ctrl()?.refresh();
      this.close();
      if (done.state.status === 'error') toast(`${done.label}: ${done.state.message}`, 'error');
      else partStore.selected = done.id;
    } catch (e) {
      this.say(messageOf(e), true);
    } finally {
      this.busy = false;
      setDisabledOk(this.ok, false);
    }
  }

  dismiss(): void {
    this.close();
  }

  close(): void {
    window.clearTimeout(this.timer);
    this.ctl?.abort();
    this.seq++;
    this.stopPick();
    this.clearPreview();
    const vp = this.ctrl()?.vp;
    if (vp && this.mode) vp.setSelection({ bodies: [], faces: [], edges: [] }, false);
    this.mode = null;
    this.form = null;
    this.ctrl()?.holdAt(null);
    this.panel.classList.remove('is-open');
    this.panel.setAttribute('aria-hidden', 'true');
  }

  refreshHeld(): void {
    if (this.mode) this.schedule(60);
  }
}

function setDisabledOk(b: HTMLButtonElement, off: boolean): void {
  if (b.disabled !== off) b.disabled = off;
}
