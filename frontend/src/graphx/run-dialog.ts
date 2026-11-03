import { Dialog } from '../ui/dialogs';
import { docStore } from '../ui/doc-store';
import { el, patchList, q, setClass, setDisabled, setHidden, setText } from '../ui/dom';
import { pickPath, type FileKind } from '../ui/file-dialogs';
import { t } from '../ui/i18n';
import { toast } from '../ui/toast';
import { graphEditor } from '../graph';
import { definitionOf, exportGraph, importGraph, runHeadless, type RunOutput } from './net';

export const GRAPH_KIND: FileKind = { name: 'FormCAD graph', extensions: ['graph'] };
const tail = (p: string): string => p.split(/[\\/]/).pop() ?? p;

export async function importDialog(): Promise<void> {
  const path = await pickPath('open', 'Import Graph', '', [GRAPH_KIND], 'Import');
  if (!path) return;
  try {
    await graphEditor.store.flush();
    const res = await importGraph(path);
    await graphEditor.store.refreshList();
    await graphEditor.store.open(res.id);
    toast(`${t('Imported')} ${tail(path)}.`);
  } catch (e) { toast(e instanceof Error ? e.message : t('The import failed.'), 'error'); }
}

export async function exportDialog(): Promise<void> {
  const gid = graphEditor.gid();
  if (!gid) { toast(t('Open a graph first.')); return; }
  const name = graphEditor.record()?.name || 'graph';
  const path = await pickPath('save', 'Export Graph', `${name.replace(/[\\/:*?"<>|]+/g, '-')}.graph`, [GRAPH_KIND], 'Export');
  if (!path) return;
  try {
    await graphEditor.store.flush();
    const res = await exportGraph(gid, path);
    toast(`${t('Exported')} ${tail(res.path)}.`);
  } catch (e) { toast(e instanceof Error ? e.message : t('The export failed.'), 'error'); }
}

export class RunDialog extends Dialog {
  private readonly source: HTMLSelectElement;
  private readonly path: HTMLInputElement;
  private readonly pathRow: HTMLElement;
  private readonly doc: HTMLSelectElement;
  private readonly inputs: HTMLTextAreaElement;
  private readonly results: HTMLElement;
  private readonly note: HTMLElement;
  private readonly go: HTMLButtonElement;
  private busy = false;

  constructor() {
    super('Run Graph Headless', 520);
    this.body.appendChild(el('<p class="cv-note gp-rnote"></p>'));
    this.source = el<HTMLSelectElement>('<select class="cv-input"><option value="open"></option><option value="file"></option></select>');
    this.field('Graph', this.source);
    const row = el('<div class="cv-row-actions"></div>');
    this.path = el<HTMLInputElement>('<input class="cv-input" type="text" spellcheck="false" autocomplete="off" aria-label="Graph file path">');
    const browse = el<HTMLButtonElement>('<button class="cv-btn cv-btn-ghost" type="button"></button>');
    row.append(this.path, browse);
    this.pathRow = this.field('File', row);
    this.doc = el<HTMLSelectElement>('<select class="cv-input" aria-label="Document the graph reads"></select>');
    this.field('Document', this.doc);
    this.body.appendChild(el('<p class="cv-note gp-rdocnote"></p>'));
    setText(q(this.body, '.gp-rdocnote'), t('The graph reads this document and never changes it. Choose none to run without one.'));
    this.inputs = el<HTMLTextAreaElement>('<textarea class="cv-input gp-rinputs" spellcheck="false" aria-label="Named inputs as JSON">{}</textarea>');
    this.field('Inputs', this.inputs);
    this.note = el('<p class="cv-note gp-rmsg" role="status"></p>');
    this.results = el('<div class="gp-rres is-scroll" aria-label="Outputs"></div>');
    this.body.append(this.note, this.results);
    const opts = this.source.options;
    setText(opts[0], t('The open graph'));
    setText(opts[1], t('A graph file'));
    setText(browse, t('Browse'));
    setText(q(this.body, '.gp-rnote'), t('Runs a graph without the editor and shows its named outputs. Inputs are a JSON object keyed by input name.'));
    this.button('Close', 'ghost', () => this.close());
    this.go = this.button('Run', 'primary', () => { void this.run(); });
    this.source.addEventListener('change', () => this.mode());
    browse.addEventListener('click', () => {
      void pickPath('open', 'Run Graph File', '', [GRAPH_KIND], 'Choose').then((p) => { if (p) this.path.value = p; });
    });
    this.mode();
  }

  private mode(): void {
    setHidden(this.pathRow, this.source.value !== 'file');
  }

  private docs(): void {
    const rows = [{ id: '', name: t('None') }, ...docStore.docs.map((d) => ({ id: d.id, name: d.name }))];
    const keep = this.doc.value || (this.doc.options.length ? '' : docStore.activeId ?? '');
    patchList(this.doc, rows, {
      key: (r) => r.id,
      create: (r) => el<HTMLOptionElement>(`<option value="${r.id.replace(/"/g, '')}"></option>`),
      update: (node, r) => { setText(node, r.name); },
    });
    this.doc.value = rows.some((r) => r.id === keep) ? keep : '';
  }

  show(): void {
    this.docs();
    this.open(this.go);
  }

  private async run(): Promise<void> {
    if (this.busy) return;
    let inputs: Record<string, unknown> = {};
    try {
      const parsed: unknown = JSON.parse(this.inputs.value.trim() || '{}');
      if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed)) throw new Error('not an object');
      inputs = parsed as Record<string, unknown>;
    } catch { this.say(t('The inputs must be a JSON object.'), true); return; }
    const file = this.source.value === 'file';
    const rec = graphEditor.record();
    if (file && !this.path.value.trim()) { this.say(t('Choose a graph file first.'), true); return; }
    if (!file && !rec) { this.say(t('Open a graph first.'), true); return; }
    this.busy = true;
    setDisabled(this.go, true);
    this.say(t('Running'), false);
    try {
      await graphEditor.store.flush();
      const document = this.doc.value;
      const res = await runHeadless(file ? { graph_path: this.path.value.trim(), inputs, document } : { graph: await definitionOf(graphEditor.gid()), inputs, document });
      this.paint(res.rows);
      this.say(res.ok ? `${res.rows.length} ${t('outputs')} · ${res.digest.slice(0, 19)}` : (res.problems[0] ?? t('The graph reported errors.')), !res.ok);
    } catch (e) {
      this.say(e instanceof Error ? e.message : t('The run failed.'), true);
    } finally {
      this.busy = false;
      setDisabled(this.go, false);
    }
  }

  private say(text: string, bad: boolean): void {
    setText(this.note, text);
    setClass(this.note, 'is-bad', bad);
  }

  private paint(rows: RunOutput[]): void {
    patchList(this.results, rows, {
      key: (r) => r.name,
      create: () => el('<div class="gp-rrow"><b class="gp-rname"></b><span class="gp-rcount"></span><code class="gp-rfirst"></code></div>'),
      update: (node, r) => {
        setText(q(node, '.gp-rname'), r.name);
        setText(q(node, '.gp-rcount'), `${r.branches} ${t('branches')} · ${r.items} ${t('items')}`);
        setText(q(node, '.gp-rfirst'), r.first.join(', '));
      },
    });
  }
}
