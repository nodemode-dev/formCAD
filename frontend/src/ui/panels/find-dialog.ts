import { api, type FindMatch } from '../../io/api';
import { Dialog } from '../dialogs';
import { docStore } from '../doc-store';
import { el, patchList, q, setClass, setDisabled, setHidden, setText } from '../dom';
import { toast } from '../toast';
import { failure, zoomToHandles } from './engine-run';
import { kindTitle } from './props-kinds';
import { selection } from './selection-bus';

const REPLACEABLE: Record<string, string> = { text: 'text', mtext: 'text', dimension: 'text_override' };
const escapeRx = (s: string): string => s.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');

function check(label: string, on: boolean): { row: HTMLElement; box: HTMLInputElement } {
  const row = el<HTMLElement>('<label class="cv-field cv-check"><span></span><input type="checkbox"></label>');
  setText(q(row, 'span'), label);
  const box = q<HTMLInputElement>(row, 'input');
  box.checked = on;
  return { row, box };
}

export class FindDialog extends Dialog {
  private readonly findInput = el<HTMLInputElement>('<input class="cv-input" type="text" spellcheck="false" autocomplete="off" aria-label="Find what">');
  private readonly replaceInput = el<HTMLInputElement>('<input class="cv-input" type="text" spellcheck="false" autocomplete="off" aria-label="Replace with">');
  private readonly matchCase: HTMLInputElement;
  private readonly wholeWord: HTMLInputElement;
  private readonly select: HTMLInputElement;
  private readonly summary = el<HTMLElement>('<p class="cv-note fd-summary" role="status"></p>');
  private readonly list = el<HTMLElement>('<div class="fd-list" role="listbox" aria-label="Matches"></div>');
  private readonly findBtn: HTMLButtonElement;
  private readonly replaceBtn: HTMLButtonElement;
  private readonly replaceAllBtn: HTMLButtonElement;
  private readonly zoomBtn: HTMLButtonElement;
  private matches: FindMatch[] = [];
  private current = 0;
  private busy = false;

  constructor() {
    super('Find and Replace', 480);
    this.field('Find what', this.findInput);
    this.field('Replace with', this.replaceInput);
    const a = check('Match case', false), b = check('Whole word', false), c = check('Select matching objects', true);
    this.matchCase = a.box;
    this.wholeWord = b.box;
    this.select = c.box;
    this.body.append(a.row, b.row, c.row, this.summary, this.list);
    this.zoomBtn = this.button('Zoom to', 'ghost', () => this.zoom());
    this.zoomBtn.classList.add('cv-btn-apart');
    this.button('Close', 'ghost', () => this.close());
    this.replaceAllBtn = this.button('Replace All', 'ghost', () => { void this.replaceAll(); });
    this.replaceBtn = this.button('Replace', 'ghost', () => { void this.replaceCurrent(); });
    this.findBtn = this.button('Find', 'primary', () => { void this.find(); });
    this.findInput.addEventListener('keydown', (e) => { if (e.key === 'Enter') { e.preventDefault(); void this.find(); } });
    this.replaceInput.addEventListener('keydown', (e) => { if (e.key === 'Enter') { e.preventDefault(); void this.replaceCurrent(); } });
    this.list.addEventListener('click', (e) => {
      const row = (e.target as HTMLElement).closest<HTMLElement>('[data-key]');
      if (!row) return;
      const at = this.matches.findIndex((m) => String(m.handle) === row.dataset.key);
      if (at >= 0) { this.current = at; this.paint(); this.zoom(); }
    });
    this.sync();
  }

  show(): void {
    this.open(this.findInput);
    this.findInput.select();
    this.sync();
  }

  private rx(): RegExp | null {
    const text = this.findInput.value;
    if (!text) return null;
    const word = this.wholeWord.checked;
    return new RegExp((word ? '(?<!\\w)' : '') + escapeRx(text) + (word ? '(?!\\w)' : ''), this.matchCase.checked ? 'g' : 'gi');
  }

  private sync(): void {
    const has = !!docStore.activeId && !this.busy;
    const found = this.matches.length > 0;
    setDisabled(this.findBtn, !has);
    setDisabled(this.replaceBtn, !has);
    setDisabled(this.replaceAllBtn, !has);
    setDisabled(this.zoomBtn, !found);
  }

  private paint(): void {
    const fill = (node: HTMLElement, m: FindMatch): void => {
      setText(q(node, '.fd-kind'), kindTitle(m.kind));
      setText(q(node, '.fd-handle'), `#${m.handle.toString(16).toUpperCase()}`);
      setText(q(node, '.fd-hits'), String(m.hits));
      setClass(node, 'is-current', this.matches[this.current]?.handle === m.handle);
    };
    patchList(this.list, this.matches, {
      key: (m) => String(m.handle),
      create: (m) => {
        const node = el<HTMLElement>('<button class="fd-row" type="button" role="option"><span class="fd-kind"></span><span class="fd-handle"></span><span class="fd-hits"></span></button>');
        fill(node, m);
        return node;
      },
      update: fill,
    });
    setHidden(this.list, this.matches.length === 0);
    this.sync();
  }

  private say(text: string): void {
    setText(this.summary, text);
  }

  private async find(): Promise<void> {
    const doc = docStore.activeId;
    const text = this.findInput.value;
    if (!doc || !text) { this.say(doc ? 'Enter text to find.' : 'Open a drawing first.'); return; }
    this.busy = true;
    this.sync();
    try {
      const r = await api.find(doc, { text, matchCase: this.matchCase.checked, wholeWord: this.wholeWord.checked, select: this.select.checked });
      this.matches = r.matches;
      this.current = 0;
      this.say(r.matches.length ? `${r.total} ${r.total === 1 ? 'occurrence' : 'occurrences'} in ${r.matches.length} ${r.matches.length === 1 ? 'object' : 'objects'}.` : 'No matches.');
      if (this.select.checked && r.selected) selection.select(r.selected.map(Number));
    } catch (e) {
      this.matches = [];
      this.say(failure(e));
    } finally {
      this.busy = false;
      this.paint();
    }
  }

  private async replaceCurrent(): Promise<void> {
    const doc = docStore.activeId;
    if (!doc) return;
    if (!this.matches.length) { await this.find(); return; }
    const m = this.matches[this.current];
    const field = m ? REPLACEABLE[m.kind] : undefined;
    const rx = this.rx();
    if (!m || !rx) return;
    if (!field) { toast('Use Replace All for this kind of object.', 'info'); return; }
    this.busy = true;
    this.sync();
    try {
      const p = await api.properties(doc, [m.handle]);
      const old = p.kinds[m.kind]?.props[field]?.value;
      if (typeof old !== 'string') { toast('This object has no text to replace.', 'error'); return; }
      const next = old.replace(rx, () => this.replaceInput.value);
      const r = await api.setProperties(doc, [m.handle], { [field]: next });
      if (r.locked > 0) toast('The object is on a locked layer and was not changed.', 'info');
      else this.say(`Replaced in #${m.handle.toString(16).toUpperCase()}.`);
      this.matches = this.matches.filter((x) => x.handle !== m.handle);
      this.current = Math.min(this.current, Math.max(0, this.matches.length - 1));
      const nowAt = this.matches[this.current];
      if (nowAt) zoomToHandles([nowAt.handle]);
    } catch (e) {
      this.say(failure(e));
    } finally {
      this.busy = false;
      this.paint();
    }
  }

  private async replaceAll(): Promise<void> {
    const doc = docStore.activeId;
    const text = this.findInput.value;
    if (!doc || !text) { this.say(doc ? 'Enter text to find.' : 'Open a drawing first.'); return; }
    this.busy = true;
    this.sync();
    try {
      const r = await api.find(doc, { text, replace: this.replaceInput.value, matchCase: this.matchCase.checked, wholeWord: this.wholeWord.checked });
      const n = r.hits ?? r.total, objects = r.replaced ?? r.matches.length;
      this.say(`Replaced ${n} ${n === 1 ? 'occurrence' : 'occurrences'} in ${objects} ${objects === 1 ? 'object' : 'objects'}${r.locked ? `; ${r.locked} on locked layers skipped` : ''}.`);
      this.matches = [];
      this.current = 0;
    } catch (e) {
      this.say(failure(e));
    } finally {
      this.busy = false;
      this.paint();
    }
  }

  private zoom(): void {
    const one = this.matches[this.current];
    const targets = one ? [one.handle] : this.matches.map((m) => m.handle);
    if (!zoomToHandles(targets)) toast('Nothing to zoom to.', 'info');
  }
}
