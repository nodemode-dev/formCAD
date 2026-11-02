import { cad, type BlockRow, type XrefRow } from '../../io/api-cad';
import { api, ApiError } from '../../io/api';
import { Dialog, confirmAction } from '../dialogs';
import { docStore } from '../doc-store';
import { el, patchList, q, setClass, setDisabled, setHidden, setText } from '../dom';
import { t } from '../i18n';
import { toast } from '../toast';
import { exec } from './engine';

const text = (e: unknown): string => (e instanceof ApiError || e instanceof Error ? e.message : 'The engine did not answer');
const startInsert = async (name: string, scale = 1, rotation = 0): Promise<void> => {
  const id = docStore.activeId;
  if (!id) return;
  const words = ['insert', name];
  if (scale !== 1) words.push('S', String(scale));
  if (rotation !== 0) words.push('R', String(rotation));
  try {
    let state = null;
    for (const w of words) state = await api.sendInput(id, w);
    document.dispatchEvent(new CustomEvent('formcad:command-state', { detail: { doc: id, state } }));
  } catch (e) { toast(text(e), 'error'); }
};
const rowNode = (key: string, meta = ''): HTMLElement => {
  const n = el<HTMLElement>('<button class="cv-list-row u3-row" type="button" role="option"><span></span><span class="u3-row-name"></span><span class="cv-list-meta"></span></button>');
  n.dataset.key = key;
  setText(q(n, '.u3-row-name'), key);
  setText(q(n, '.cv-list-meta'), meta);
  return n;
};
const blockRows = async (): Promise<BlockRow[]> => {
  const id = docStore.activeId;
  if (!id) return [];
  try { return (await cad.blocks(id)).blocks.filter((b) => !b.xref && !b.anonymous); } catch (e) { toast(text(e), 'error'); return []; }
};
const listDef = { key: (b: BlockRow): string => b.name, create: (b: BlockRow): HTMLElement => rowNode(b.name, b.attributes ? `${b.attributes} att` : ''), update: (n: HTMLElement, b: BlockRow): void => { setText(q(n, '.cv-list-meta'), b.attributes ? `${b.attributes} att` : ''); } };

export class BlocksWindow extends Dialog {
  private readonly list: HTMLElement;
  private readonly empty: HTMLElement;
  constructor() {
    super('Blocks', 320);
    this.scrim.classList.add('cv-scrim-through');
    this.body.appendChild(el('<div class="u3-bw"><div class="cv-list u3-list" role="listbox"></div><div class="u3-empty" hidden></div></div>'));
    this.list = q(this.body, '.u3-list');
    this.empty = q(this.body, '.u3-empty');
    setText(this.empty, t('No blocks defined in this drawing.'));
    this.button('Close', 'primary', () => this.close());
    this.list.addEventListener('click', (e) => {
      const name = (e.target as HTMLElement).closest<HTMLElement>('[data-key]')?.dataset.key;
      if (name) void startInsert(name);
    });
  }
  async show(): Promise<void> {
    const rows = await blockRows();
    patchList(this.list, rows, listDef);
    setHidden(this.empty, rows.length > 0);
    setHidden(this.list, rows.length === 0);
    this.open();
  }
}

export class InsertDialog extends Dialog {
  private readonly list: HTMLElement;
  private readonly file: HTMLInputElement;
  private readonly scale: HTMLInputElement;
  private readonly rot: HTMLInputElement;
  private readonly screen: HTMLInputElement;
  private readonly boom: HTMLInputElement;
  private selected = '';
  constructor() {
    super('Insert', 420);
    this.body.appendChild(el(
      '<div class="u3-ins"><div class="cv-list u3-list" role="listbox"></div>' +
      '<label class="cv-field"><span>File</span><input class="cv-input u3-file" type="text" spellcheck="false"></label>' +
      '<label class="cv-field"><span>Scale</span><input class="cv-input u3-scale" type="text" value="1"></label>' +
      '<label class="cv-field"><span>Rotation</span><input class="cv-input u3-rot" type="text" value="0"></label>' +
      '<label class="cv-field cv-check"><span>Specify on screen</span><input class="u3-screen" type="checkbox" checked></label>' +
      '<label class="cv-field cv-check"><span>Explode</span><input class="u3-boom" type="checkbox"></label></div>'));
    this.list = q(this.body, '.u3-list');
    this.file = q<HTMLInputElement>(this.body, '.u3-file');
    this.scale = q<HTMLInputElement>(this.body, '.u3-scale');
    this.rot = q<HTMLInputElement>(this.body, '.u3-rot');
    this.screen = q<HTMLInputElement>(this.body, '.u3-screen');
    this.boom = q<HTMLInputElement>(this.body, '.u3-boom');
    this.file.placeholder = t('Path of a drawing file (optional)');
    this.button('Cancel', 'ghost', () => this.close());
    this.button('Insert', 'primary', () => void this.go());
    this.list.addEventListener('click', (e) => {
      const name = (e.target as HTMLElement).closest<HTMLElement>('[data-key]')?.dataset.key;
      if (name) { this.selected = name; this.file.value = ''; this.mark(); }
    });
  }
  private mark(): void { for (const n of Array.from(this.list.children) as HTMLElement[]) setClass(n, 'is-selected', n.dataset.key === this.selected); }
  async show(): Promise<void> {
    const rows = await blockRows();
    patchList(this.list, rows, listDef);
    if (!rows.some((b) => b.name === this.selected)) this.selected = rows[0]?.name ?? '';
    this.mark();
    this.open(this.file);
  }
  private async go(): Promise<void> {
    const name = this.file.value.trim() || this.selected;
    if (!name) { toast(t('Choose a block or give a file'), 'error'); return; }
    const scale = Number(this.scale.value) || 1;
    const rotation = Number(this.rot.value) || 0;
    this.close();
    if (this.screen.checked && !this.boom.checked) { await startInsert(name, scale, rotation); return; }
    const args: Record<string, unknown> = { name, scale, rotation, point: [0, 0] };
    if (this.boom.checked) args.explode = true;
    await exec('insert', args);
  }
}

interface AttRow { tag: string; value: string; prompt: string; invisible?: boolean }

export class AttributeEditor extends Dialog {
  private handle = 0;
  private readonly rows: HTMLElement;
  private readonly note: HTMLElement;
  constructor() {
    super('Edit Attributes', 460);
    this.body.appendChild(el('<div class="u3-att"><div class="u3-note"></div><div class="u3-att-rows"></div></div>'));
    this.rows = q(this.body, '.u3-att-rows');
    this.note = q(this.body, '.u3-note');
    this.button('Cancel', 'ghost', () => this.close());
    this.button('OK', 'primary', () => void this.apply());
  }
  async show(handle: number): Promise<boolean> {
    const id = docStore.activeId;
    if (!id) return false;
    try {
      const r = await cad.insertAttribs(id, handle) as { block: string; attributes: AttRow[]; constants: Array<{ tag: string; value: string }> };
      this.handle = handle;
      setText(this.note, `${t('Block')}: ${r.block}`);
      this.rows.replaceChildren(...r.attributes.map((a) => {
        const n = el<HTMLElement>('<label class="cv-field"><span></span><input class="cv-input" type="text" spellcheck="false"></label>');
        setText(q(n, 'span'), a.prompt || a.tag);
        const inp = q<HTMLInputElement>(n, 'input');
        inp.value = a.value;
        inp.dataset.tag = a.tag;
        return n;
      }));
      if (!r.attributes.length) setText(this.note, t('This block reference has no attributes.'));
      this.open(this.rows.querySelector('input'));
      return true;
    } catch { return false; }
  }
  private async apply(): Promise<void> {
    const id = docStore.activeId;
    if (!id) return;
    const values: Record<string, string> = {};
    for (const i of Array.from(this.rows.querySelectorAll<HTMLInputElement>('input'))) values[i.dataset.tag ?? ''] = i.value;
    try {
      await cad.setInsertAttribs(id, this.handle, { values });
      void docStore.refresh();
      this.close();
    } catch (e) { toast(text(e), 'error'); }
  }
}

interface DefRow { tag: string; prompt: string; default: string }

export class BlockAttributeManager extends Dialog {
  private block = '';
  private defs: DefRow[] = [];
  private selected = '';
  private readonly sel: HTMLSelectElement;
  private readonly list: HTMLElement;
  private readonly prompt: HTMLInputElement;
  private readonly dflt: HTMLInputElement;
  private readonly btns: HTMLButtonElement[] = [];
  constructor() {
    super('Block Attribute Manager', 520);
    this.body.appendChild(el(
      '<div class="u3-bm"><label class="cv-field"><span>Block</span><select class="cv-input u3-bsel"></select></label>' +
      '<div class="cv-list u3-list" role="listbox"></div>' +
      '<label class="cv-field"><span>Prompt</span><input class="cv-input u3-bprompt" type="text"></label>' +
      '<label class="cv-field"><span>Default</span><input class="cv-input u3-bdef" type="text"></label>' +
      '<div class="u3-btns"></div></div>'));
    this.sel = q<HTMLSelectElement>(this.body, '.u3-bsel');
    this.list = q(this.body, '.u3-list');
    this.prompt = q<HTMLInputElement>(this.body, '.u3-bprompt');
    this.dflt = q<HTMLInputElement>(this.body, '.u3-bdef');
    const bar = q(this.body, '.u3-btns');
    const mk = (label: string, run: () => void): void => {
      const b = el<HTMLButtonElement>('<button class="cv-btn" type="button"></button>');
      setText(b, t(label));
      b.addEventListener('click', run);
      bar.appendChild(b);
      this.btns.push(b);
    };
    mk('Apply', () => void this.op({ op: 'edit', tag: this.selected, changes: { prompt: this.prompt.value, default: this.dflt.value } }));
    mk('Move Up', () => void this.op({ op: 'up', tag: this.selected }));
    mk('Move Down', () => void this.op({ op: 'down', tag: this.selected }));
    mk('Remove', () => void this.op({ op: 'remove', tag: this.selected }));
    mk('Synchronize', () => void this.op({ op: 'sync' }));
    this.button('Close', 'primary', () => this.close());
    this.sel.addEventListener('change', () => { this.block = this.sel.value; void this.load(); });
    this.list.addEventListener('click', (e) => {
      const tag = (e.target as HTMLElement).closest<HTMLElement>('[data-key]')?.dataset.key;
      if (tag) { this.selected = tag; this.paint(); }
    });
  }
  async show(): Promise<void> {
    const rows = (await blockRows()).filter((b) => b.attributes > 0);
    this.sel.replaceChildren(...rows.map((b) => { const o = document.createElement('option'); o.value = b.name; o.textContent = b.name; return o; }));
    if (!rows.length) { toast(t('No blocks with attributes in this drawing.'), 'info'); return; }
    this.block = rows.some((b) => b.name === this.block) ? this.block : rows[0].name;
    this.sel.value = this.block;
    await this.load();
    this.open();
  }
  private async load(): Promise<void> {
    const id = docStore.activeId;
    if (!id) return;
    try {
      const r = await cad.blockAttribs(id, this.block) as { attributes: DefRow[] };
      this.defs = r.attributes;
      if (!this.defs.some((d) => d.tag === this.selected)) this.selected = this.defs[0]?.tag ?? '';
      this.paint();
    } catch (e) { toast(text(e), 'error'); }
  }
  private paint(): void {
    patchList(this.list, this.defs, {
      key: (d) => d.tag,
      create: (d) => rowNode(d.tag, d.prompt),
      update: (n, d) => { setText(q(n, '.cv-list-meta'), d.prompt); },
    });
    for (const n of Array.from(this.list.children) as HTMLElement[]) setClass(n, 'is-selected', n.dataset.key === this.selected);
    const cur = this.defs.find((d) => d.tag === this.selected);
    this.prompt.value = cur?.prompt ?? '';
    this.dflt.value = cur?.default ?? '';
    for (const b of this.btns) setDisabled(b, !cur && b !== this.btns[4]);
  }
  private async op(body: Record<string, unknown>): Promise<void> {
    const id = docStore.activeId;
    if (!id) return;
    try {
      const r = await cad.editBlockAttribs(id, this.block, body) as { attributes: DefRow[] };
      this.defs = r.attributes;
      this.paint();
      void docStore.refresh();
    } catch (e) { toast(text(e), 'error'); }
  }
}

export class EditBlockDialog extends Dialog {
  private selected = '';
  private readonly list: HTMLElement;
  private readonly name: HTMLInputElement;
  constructor() {
    super('Edit Block Definition', 380);
    this.body.appendChild(el('<div class="u3-eb"><label class="cv-field"><span>Block to create or edit</span><input class="cv-input u3-ebname" type="text" spellcheck="false"></label><div class="cv-list u3-list" role="listbox"></div></div>'));
    this.list = q(this.body, '.u3-list');
    this.name = q<HTMLInputElement>(this.body, '.u3-ebname');
    this.button('Cancel', 'ghost', () => this.close());
    this.button('OK', 'primary', () => void this.go());
    this.list.addEventListener('click', (e) => {
      const n = (e.target as HTMLElement).closest<HTMLElement>('[data-key]')?.dataset.key;
      if (n) { this.selected = n; this.name.value = n; }
    });
    this.list.addEventListener('dblclick', () => void this.go());
    this.name.addEventListener('keydown', (e) => { if (e.key === 'Enter') { e.preventDefault(); void this.go(); } });
  }
  async show(): Promise<void> {
    const rows = await blockRows();
    patchList(this.list, rows, listDef);
    this.name.value = this.selected;
    this.open(this.name);
  }
  private async go(): Promise<void> {
    const name = this.name.value.trim();
    if (!name) return;
    this.close();
    await exec('bedit', { name });
    editorBar.refresh();
  }
}

class BlockEditorBar {
  private node: HTMLElement | null = null;
  private label: HTMLElement | null = null;
  private seq = 0;
  mount(host: HTMLElement): void {
    this.node = el(
      '<div class="u3-bebar" hidden><span class="u3-bebar-name"></span>' +
      '<button class="cv-btn" type="button" data-a="save"></button><button class="cv-btn" type="button" data-a="saveas"></button><button class="cv-btn" type="button" data-a="close"></button></div>');
    this.label = q(this.node, '.u3-bebar-name');
    setText(q(this.node, '[data-a="save"]'), t('Save Block'));
    setText(q(this.node, '[data-a="saveas"]'), t('Save Block As'));
    setText(q(this.node, '[data-a="close"]'), t('Close Block Editor'));
    this.node.addEventListener('click', (e) => {
      const a = (e.target as HTMLElement).closest<HTMLElement>('[data-a]')?.dataset.a;
      if (a === 'save') void exec('bsave', {}).then(() => this.refresh());
      else if (a === 'saveas') void exec('bsaveas', {});
      else if (a === 'close') void this.close();
    });
    host.appendChild(this.node);
    docStore.onChange(() => this.refresh());
    document.addEventListener('formcad:command-state', () => this.refresh());
  }
  private async close(): Promise<void> {
    const id = docStore.activeId;
    if (!id) return;
    let dirty = false;
    try { dirty = Boolean(((await cad.blockEditor(id)) as { editor: { dirty?: boolean } }).editor.dirty); } catch { return; }
    if (!dirty) { await exec('bclose', { save: false }); this.refresh(); return; }
    const ok = await confirmAction(t('Save changes to the block?'), t('The block definition has unsaved changes.'), t('Save'), false);
    await exec('bclose', { save: ok });
    this.refresh();
  }
  refresh(): void {
    const id = docStore.activeId;
    if (!id || !this.node) return;
    const n = ++this.seq;
    void cad.blockEditor(id).then((r) => {
      if (n !== this.seq || !this.node || !this.label) return;
      const ed = (r as { editor: { open: boolean; name?: string } }).editor;
      setHidden(this.node, !ed.open);
      if (ed.open) setText(this.label, `${t('Editing block')}: ${ed.name ?? ''}`);
    }).catch(() => { /* engine busy */ });
  }
}

export const editorBar = new BlockEditorBar();

export class XrefPalette extends Dialog {
  private rows: XrefRow[] = [];
  private selected = '';
  private readonly list: HTMLElement;
  private readonly empty: HTMLElement;
  private readonly path: HTMLInputElement;
  private readonly overlay: HTMLInputElement;
  private readonly btns = new Map<string, HTMLButtonElement>();
  constructor() {
    super('External References', 640);
    this.scrim.classList.add('cv-scrim-through');
    this.body.appendChild(el(
      '<div class="u3-xr"><div class="u3-btns"></div>' +
      '<div class="u3-xr-head"><span>Reference Name</span><span>Status</span><span>Type</span><span>Saved Path</span></div>' +
      '<div class="cv-list u3-list" role="listbox"></div><div class="u3-empty" hidden></div>' +
      '<label class="cv-field"><span>Saved Path</span><input class="cv-input u3-xpath" type="text" spellcheck="false"></label>' +
      '<label class="cv-field cv-check"><span>Overlay</span><input class="u3-xover" type="checkbox"></label></div>'));
    this.list = q(this.body, '.u3-list');
    this.empty = q(this.body, '.u3-empty');
    this.path = q<HTMLInputElement>(this.body, '.u3-xpath');
    this.overlay = q<HTMLInputElement>(this.body, '.u3-xover');
    setText(this.empty, t('No external references are attached.'));
    const bar = q(this.body, '.u3-btns');
    const mk = (key: string, label: string, run: () => void): void => {
      const b = el<HTMLButtonElement>('<button class="cv-btn" type="button"></button>');
      setText(b, t(label));
      b.addEventListener('click', run);
      bar.appendChild(b);
      this.btns.set(key, b);
    };
    mk('attach', 'Attach DWG...', () => void this.attach());
    mk('reload_all', 'Reload All', () => void this.act({ action: 'reload_all' }));
    mk('reload', 'Reload', () => void this.act({ action: 'reload', name: this.selected }));
    mk('unload', 'Unload', () => void this.act({ action: 'unload', name: this.selected }));
    mk('detach', 'Detach', () => void this.detach());
    mk('bind', 'Bind', () => void this.act({ action: 'bind', name: this.selected }));
    this.button('Close', 'primary', () => this.close());
    this.list.addEventListener('click', (e) => {
      const n = (e.target as HTMLElement).closest<HTMLElement>('[data-key]')?.dataset.key;
      if (n) { this.selected = n; this.paint(); }
    });
    this.path.addEventListener('keydown', (e) => { if (e.key === 'Enter' && this.selected) { e.preventDefault(); void this.act({ action: 'path', name: this.selected, path: this.path.value.trim() }); } });
    docStore.onChange(() => { if (this.isOpen) void this.load(); });
  }
  async show(): Promise<void> { await this.load(); this.open(); }
  private async load(): Promise<void> {
    const id = docStore.activeId;
    if (!id) return;
    try {
      this.rows = (await cad.xrefs(id)).xrefs.filter((r) => !r.nested);
      if (!this.rows.some((r) => r.name === this.selected)) this.selected = this.rows[0]?.name ?? '';
      this.paint();
    } catch (e) { toast(text(e), 'error'); }
  }
  private paint(): void {
    patchList(this.list, this.rows, {
      key: (r) => r.name,
      create: (r) => { const n = rowNode(r.name, `${r.status} | ${r.type} | ${r.path}`); return n; },
      update: (n, r) => { setText(q(n, '.cv-list-meta'), `${r.status} | ${r.type} | ${r.path}`); },
    });
    for (const n of Array.from(this.list.children) as HTMLElement[]) setClass(n, 'is-selected', n.dataset.key === this.selected);
    setHidden(this.empty, this.rows.length > 0);
    const cur = this.rows.find((r) => r.name === this.selected);
    if (document.activeElement !== this.path) this.path.value = cur?.path ?? '';
    for (const [k, b] of this.btns) setDisabled(b, k !== 'attach' && k !== 'reload_all' && !cur);
  }
  private async act(body: Record<string, unknown>): Promise<void> {
    const id = docStore.activeId;
    if (!id) return;
    try {
      const r = await cad.xrefAction(id, body) as { xrefs?: XrefRow[] };
      if (r.xrefs) { this.rows = r.xrefs.filter((x) => !x.nested); this.paint(); }
      void docStore.refresh();
    } catch (e) { toast(text(e), 'error'); }
  }
  private async attach(): Promise<void> {
    const p = this.path.value.trim();
    if (!p) { toast(t('Type the path of the drawing file in Saved Path first'), 'error'); this.path.focus(); return; }
    await this.act({ action: 'attach', path: p, overlay: this.overlay.checked, point: [0, 0] });
  }
  private async detach(): Promise<void> {
    if (await confirmAction(t('Detach reference'), `${t('Detach')} ${this.selected}?`, t('Detach'), true)) await this.act({ action: 'detach', name: this.selected });
  }
}

export const attributeTarget = async (): Promise<number | null> => {
  const id = docStore.activeId;
  if (!id) return null;
  try {
    const s = await api.getSelection(id);
    for (const h of s.handles) {
      const n = Number(h);
      try { await cad.insertAttribs(id, n); return n; } catch { /* not a reference */ }
    }
  } catch { /* none */ }
  return null;
};
