import { auto } from '../../io/api-auto';
import { Dialog } from '../dialogs';
import { docStore } from '../doc-store';
import { el, q, setDisabled, store, stored } from '../dom';
import { t } from '../i18n';

const KEY = 'formCAD.lispHistory';
const KEEP = 1000;
const PER_FRAME = 60;
const RECALL = 200;

type Kind = 'in' | 'out' | 'val' | 'err' | 'note';

function loadRecall(): string[] {
  try {
    const v: unknown = JSON.parse(stored(KEY) ?? '[]');
    return Array.isArray(v) ? v.filter((x): x is string => typeof x === 'string').slice(-RECALL) : [];
  } catch {
    return [];
  }
}

export class LispConsole extends Dialog {
  private readonly log: HTMLElement;
  private readonly input: HTMLInputElement;
  private readonly recall = loadRecall();
  private at = -1;
  private draft = '';
  private busy = false;
  private queue: Array<[Kind, string]> = [];
  private frame = 0;
  fed = 0;

  constructor() {
    super('LISP Console', 640);
    this.scrim.classList.add('cv-scrim-through');
    this.body.appendChild(el('<div class="lc"><div class="lc-log" role="log" aria-live="polite" aria-label="LISP output"></div><div class="lc-bar"><span class="lc-prompt">&gt;</span><input class="lc-in" type="text" spellcheck="false" autocomplete="off" autocapitalize="off" aria-label="LISP expression"></div></div>'));
    this.log = q(this.body, '.lc-log');
    this.input = q<HTMLInputElement>(this.body, '.lc-in');
    this.input.placeholder = t('Type a LISP expression and press Enter');
    this.button('Clear', 'ghost', () => this.clear()).classList.add('cv-btn-apart');
    this.button('Close', 'primary', () => this.close());
    this.input.addEventListener('keydown', (e) => this.key(e));
    this.push('note', t('Expressions run in the active drawing. Input functions get no answers here; type those routines at the command line.'));
  }

  showFor(): void {
    this.open(this.input);
  }

  private key(e: KeyboardEvent): void {
    if (e.key === 'Enter') {
      e.preventDefault();
      void this.submit();
    } else if (e.key === 'ArrowUp' || e.key === 'ArrowDown') {
      e.preventDefault();
      if (this.recall.length === 0) return;
      if (this.at < 0) {
        if (e.key === 'ArrowDown') return;
        this.draft = this.input.value;
        this.at = this.recall.length;
      }
      this.at = Math.min(this.recall.length, Math.max(0, this.at + (e.key === 'ArrowUp' ? -1 : 1)));
      this.input.value = this.at >= this.recall.length ? this.draft : this.recall[this.at];
      if (this.at >= this.recall.length) this.at = -1;
    }
  }

  private async submit(): Promise<void> {
    const text = this.input.value.trim();
    const id = docStore.activeId;
    if (!text || this.busy) return;
    this.input.value = '';
    this.at = -1;
    if (this.recall[this.recall.length - 1] !== text) {
      this.recall.push(text);
      if (this.recall.length > RECALL) this.recall.shift();
      store(KEY, JSON.stringify(this.recall));
    }
    this.push('in', text);
    if (!id) { this.push('err', t('Open or create a drawing first.')); return; }
    this.busy = true;
    setDisabled(this.input, true);
    try {
      const code = text.startsWith('!') ? text.slice(1).trim() : text;
      const r = await auto.lisp(id, code);
      let failed = false;
      for (const line of r.lines ?? []) {
        const bad = line.startsWith('; error');
        failed ||= bad;
        this.push(bad ? 'err' : 'out', line);
      }
      if (r.error && !failed) this.push('err', `; error: ${r.error}`);
      if (!r.error && r.value) this.push('val', r.value);
    } catch (e) {
      this.push('err', e instanceof Error ? e.message : t('The engine did not answer'));
    } finally {
      this.busy = false;
      setDisabled(this.input, false);
      this.input.focus();
    }
  }

  push(kind: Kind, text: string): void {
    this.queue.push([kind, text]);
    if (!this.frame) this.frame = requestAnimationFrame(() => this.flush());
  }

  private flush(): void {
    this.frame = 0;
    const near = this.log.scrollHeight - this.log.scrollTop - this.log.clientHeight < 24;
    let n = 0;
    while (this.queue.length && n < PER_FRAME) {
      const [kind, text] = this.queue.shift() as [Kind, string];
      n++;
      const row = document.createElement('div');
      row.className = `lc-line is-${kind}`;
      row.textContent = kind === 'val' ? `=> ${text}` : kind === 'in' ? `> ${text}` : text;
      this.log.appendChild(row);
      this.fed++;
    }
    while (this.log.childElementCount > KEEP) this.log.firstElementChild?.remove();
    if (near) this.log.scrollTop = this.log.scrollHeight;
    if (this.queue.length) this.frame = requestAnimationFrame(() => this.flush());
  }

  private clear(): void {
    this.queue = [];
    while (this.log.firstChild) this.log.removeChild(this.log.firstChild);
    this.fed = 0;
  }
}
