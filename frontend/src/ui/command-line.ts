import { api, ApiError, type CommandLineState, type CommandMeta } from '../io/api';
import { anyDialogOpen } from './dialogs';
import { el, patchList, q, setClass, setHidden, setText, store, stored } from './dom';
import { icon } from './icons';
import { sysvars } from './sysvar-store';
import { toast } from './toast';

export const LINE_H = 16;
export const BAR_H = 48;
const RECALL_MAX = 200;
const RECENT_MAX = 8;
const SUGGEST_MAX = 8;
const KEYWORD_SLOTS = 16;
const LINE_CHOICES = [0, 1, 3, 5, 8, 12];
const RECALL_KEY = 'formCAD.cmdRecall';

export interface CommandLineDeps {
  activeDoc: () => string | null;
  onActiveDoc: (fn: () => void) => () => void;
  engineCommands: () => CommandMeta[];
  stage: HTMLElement;
  lines: () => number;
  setLines: (n: number) => void;
}

interface Suggestion { text: string; name: string; label: string }

const IDLE: CommandLineState = { active: false, prompt: 'Command:', options: [], defaultValue: null, history: [], rev: 0 };

function loadRecall(): string[] {
  try {
    const v: unknown = JSON.parse(stored(RECALL_KEY) ?? '[]');
    return Array.isArray(v) ? v.filter((x): x is string => typeof x === 'string').slice(-RECALL_MAX) : [];
  } catch {
    return [];
  }
}

const typing = (t: EventTarget | null): boolean => t instanceof HTMLElement && (t.isContentEditable || /^(INPUT|TEXTAREA|SELECT)$/.test(t.tagName));

export class CommandLine {
  private readonly root: HTMLElement;
  private readonly input: HTMLInputElement;
  private readonly history: HTMLElement;
  private readonly name: HTMLElement;
  private readonly pre: HTMLElement;
  private readonly post: HTMLElement;
  private readonly kw: HTMLElement;
  private readonly opts: HTMLElement;
  private readonly expand: HTMLButtonElement;
  private readonly pop: HTMLElement;
  private readonly popBody: HTMLElement;
  private readonly ac: HTMLElement;
  private readonly acRows: HTMLButtonElement[] = [];
  private readonly menu: HTMLElement;
  private readonly recentSlots: HTMLButtonElement[] = [];
  private readonly kwSlots: HTMLButtonElement[] = [];
  private readonly lineButtons = new Map<number, HTMLButtonElement>();
  private readonly dynButton: HTMLButtonElement;
  private readonly historyButton: HTMLButtonElement;
  private readonly copyButton: HTMLButtonElement;
  private readonly cache = new Map<string, CommandLineState>();
  private readonly cleared = new Map<string, number>();
  private readonly recall: string[] = loadRecall();
  private recent: string[] = [];
  private state: CommandLineState = IDLE;
  private docId: string | null = null;
  private sugs: Suggestion[] = [];
  private recallAt = -1;
  private draft = '';
  private expanded = false;
  private indexSrc: CommandMeta[] | null = null;
  private names = new Map<string, CommandMeta>();
  private aliases = new Map<string, string>();
  private sortedNames: string[] = [];
  private sortedAliases: string[] = [];
  private acKey = '';
  private busy = false;
  private hint = '';

  constructor(host: HTMLElement, private readonly deps: CommandLineDeps) {
    this.root = el(
      `<div class="cv-cmd"><div class="cv-cmd-grip" title="Drag to set the history lines" aria-hidden="true"></div>` +
      `<div class="cv-cmd-history" role="log" aria-live="polite" aria-label="Command history"></div>` +
      `<div class="cv-cmd-bar"><span class="cv-cmd-glyph">${icon('cmdline', 16)}</span><span class="cv-cmd-name"></span>` +
      `<span class="cv-cmd-pre"></span><span class="cv-cmd-kw"><span class="cv-cmd-bracket">[</span><span class="cv-cmd-opts"></span><span class="cv-cmd-bracket">]</span></span><span class="cv-cmd-post"></span>` +
      `<input class="cv-cmd-input" type="text" spellcheck="false" autocomplete="off" autocapitalize="off" aria-label="Command line">` +
      `<button class="cv-cmd-expand" type="button" title="Command history" aria-label="Command history" aria-expanded="false">${icon('chevronUp', 14)}</button></div></div>`);
    host.appendChild(this.root);
    this.input = q<HTMLInputElement>(this.root, '.cv-cmd-input');
    this.history = q(this.root, '.cv-cmd-history');
    this.name = q(this.root, '.cv-cmd-name');
    this.pre = q(this.root, '.cv-cmd-pre');
    this.post = q(this.root, '.cv-cmd-post');
    this.kw = q(this.root, '.cv-cmd-kw');
    this.opts = q(this.root, '.cv-cmd-opts');
    for (let i = 0; i < KEYWORD_SLOTS; i++) {
      const b = el<HTMLButtonElement>('<button class="cv-cmd-kw-btn" type="button" hidden></button>');
      this.kwSlots.push(b);
      this.opts.appendChild(b);
    }
    this.expand = q<HTMLButtonElement>(this.root, '.cv-cmd-expand');

    this.pop = el('<div class="cv-cmd-pop" hidden><div class="cv-cmd-pop-body" role="log" aria-label="Full command history"></div></div>');
    this.popBody = q(this.pop, '.cv-cmd-pop-body');
    this.ac = el('<div class="cv-cmd-ac" role="listbox" aria-label="Command suggestions" hidden></div>');
    for (let i = 0; i < SUGGEST_MAX; i++) {
      const row = el<HTMLButtonElement>('<button class="cv-cmd-ac-row" type="button" role="option" tabindex="-1" hidden><span class="cv-cmd-ac-text"></span><span class="cv-cmd-ac-label"></span></button>');
      row.dataset.index = String(i);
      this.acRows.push(row);
      this.ac.appendChild(row);
    }
    this.menu = el('<div class="cv-ctx cv-cmd-menu" role="menu" hidden></div>');
    const recentHead = el('<div class="cv-cmd-menu-head">Recent Commands</div>');
    this.menu.appendChild(recentHead);
    for (let i = 0; i < RECENT_MAX; i++) {
      const b = el<HTMLButtonElement>('<button class="cv-cmd-menu-item" type="button" role="menuitem" hidden></button>');
      b.addEventListener('click', () => { this.closeMenu(); if (b.dataset.cmd) void this.runCommand(b.dataset.cmd); });
      this.recentSlots.push(b);
      this.menu.appendChild(b);
    }
    this.menu.appendChild(el('<div class="cv-cmd-menu-sep"></div>'));
    this.dynButton = this.menuItem('Dynamic Input', () => { void sysvars.set('DYNMODE', sysvars.num('DYNMODE', 1) ? 0 : 1); });
    this.historyButton = this.menuItem('Command History', () => this.toggleHistory());
    const linesRow = el('<div class="cv-cmd-menu-lines"><span>Lines of Command History</span><div></div></div>');
    for (const n of LINE_CHOICES) {
      const b = el<HTMLButtonElement>('<button class="cv-cmd-menu-line" type="button" role="menuitemradio"></button>');
      setText(b, String(n));
      b.addEventListener('click', () => { this.closeMenu(); this.deps.setLines(n); });
      this.lineButtons.set(n, b);
      q(linesRow, 'div').appendChild(b);
    }
    this.menu.appendChild(linesRow);
    this.menu.appendChild(el('<div class="cv-cmd-menu-sep"></div>'));
    this.copyButton = this.menuItem('Copy History', () => { void this.copyHistory(); });
    this.menuItem('Clear Command History', () => this.clearHistory());
    const overlay = document.getElementById('overlay-root') ?? document.body;
    overlay.append(this.pop, this.ac, this.menu);

    this.input.addEventListener('keydown', (e) => this.onKey(e));
    this.input.addEventListener('input', () => { this.recallAt = -1; this.refreshSuggestions(); });
    this.input.addEventListener('blur', () => window.setTimeout(() => { if (document.activeElement !== this.input) this.hideSuggestions(); }, 120));
    this.input.addEventListener('focus', () => this.refreshSuggestions());
    this.expand.addEventListener('click', () => this.toggleHistory());
    this.history.addEventListener('click', () => this.toggleHistory());
    this.ac.addEventListener('mousedown', (e) => e.preventDefault());
    this.ac.addEventListener('click', (e) => {
      const row = (e.target as HTMLElement).closest<HTMLElement>('.cv-cmd-ac-row');
      const s = row ? this.sugs[Number(row.dataset.index)] : undefined;
      if (s) { this.clearInput(); void this.runCommand(s.name); }
    });
    this.opts.addEventListener('click', (e) => {
      const b = (e.target as HTMLElement).closest<HTMLElement>('.cv-cmd-kw-btn');
      if (b?.dataset.key) { e.stopPropagation(); void this.submit(b.dataset.key, false); }
    });
    for (const target of [this.root, this.pop]) {
      target.addEventListener('contextmenu', (e) => { e.preventDefault(); e.stopPropagation(); this.openMenu(e.clientX, e.clientY); });
    }
    this.bindGrip(q(this.root, '.cv-cmd-grip'));
    document.addEventListener('pointerdown', (e) => {
      const t = e.target as Node;
      if (!this.menu.hidden && !this.menu.contains(t)) this.closeMenu();
      if (this.expanded && !this.pop.contains(t) && !this.root.contains(t)) this.setExpanded(false);
    }, true);
    window.addEventListener('resize', () => { this.closeMenu(); this.placePop(); this.hideSuggestions(); });
    window.addEventListener('keydown', (e) => this.route(e));
    deps.onActiveDoc(() => this.switchDoc());
    this.switchDoc();
  }

  private menuItem(label: string, run: () => void): HTMLButtonElement {
    const b = el<HTMLButtonElement>('<button class="cv-cmd-menu-item" type="button" role="menuitem"></button>');
    setText(b, label);
    b.addEventListener('click', () => { this.closeMenu(); run(); });
    this.menu.appendChild(b);
    return b;
  }

  focus(): void {
    if (this.input.offsetParent !== null) this.input.focus({ preventScroll: true });
  }

  refit(): void {
    this.render();
  }

  accept(id: string, s: CommandLineState): void {
    this.apply(id, s);
  }

  private emitHint(text: string): void {
    if (text === this.hint) return;
    this.hint = text;
    document.dispatchEvent(new CustomEvent('formcad:hint', { detail: text }));
  }

  toggleHistory(): void {
    this.setExpanded(!this.expanded);
  }

  async run(name: string): Promise<void> {
    await this.runCommand(name);
  }

  private setExpanded(on: boolean): void {
    this.expanded = on;
    setHidden(this.pop, !on);
    this.expand.setAttribute('aria-expanded', String(on));
    setClass(this.expand, 'is-open', on);
    setClass(this.history, 'is-covered', on);
    if (on) { this.renderPop(); this.placePop(); }
  }

  private placePop(): void {
    if (!this.expanded) return;
    const r = this.root.getBoundingClientRect();
    const stage = this.deps.stage.getBoundingClientRect();
    const n = Math.max(3, this.visibleHistory().length);
    const h = Math.round(Math.min(Math.max(stage.height / 2, LINE_H * 3), n * LINE_H + 16));
    const set = (k: string, v: string): void => { if (this.pop.style.getPropertyValue(k) !== v) this.pop.style.setProperty(k, v); };
    set('left', `${Math.round(r.left)}px`);
    set('width', `${Math.round(r.width)}px`);
    set('bottom', `${Math.round(window.innerHeight - r.top)}px`);
    set('height', `${h}px`);
  }

  private bindGrip(grip: HTMLElement): void {
    grip.addEventListener('pointerdown', (e) => {
      if (e.button !== 0) return;
      e.preventDefault();
      const y0 = e.clientY, n0 = this.deps.lines();
      grip.setPointerCapture(e.pointerId);
      const move = (ev: PointerEvent): void => {
        const n = Math.max(0, Math.min(12, Math.round(n0 + (y0 - ev.clientY) / LINE_H)));
        if (n !== this.deps.lines()) this.deps.setLines(n);
      };
      const up = (): void => {
        grip.removeEventListener('pointermove', move);
        grip.removeEventListener('pointerup', up);
        grip.removeEventListener('pointercancel', up);
      };
      grip.addEventListener('pointermove', move);
      grip.addEventListener('pointerup', up);
      grip.addEventListener('pointercancel', up);
    });
  }

  private switchDoc(): void {
    this.docId = this.deps.activeDoc();
    this.state = (this.docId ? this.cache.get(this.docId) : undefined) ?? IDLE;
    this.clearInput();
    this.render();
  }

  private clearInput(): void {
    if (this.input.value) this.input.value = '';
    this.recallAt = -1;
    this.hideSuggestions();
  }

  private visibleHistory(): Array<{ key: string; text: string }> {
    const h = this.state.history, total = this.state.historySize ?? h.length, base = total - h.length;
    const skip = this.cleared.get(this.docId ?? '') ?? 0;
    const out: Array<{ key: string; text: string }> = [];
    h.forEach((text, i) => { if (base + i >= skip) out.push({ key: String(base + i), text }); });
    return out;
  }

  private render(): void {
    const s = this.state, has = !!this.docId;
    setText(this.name, s.active ? (s.command ?? '').toUpperCase() : '');
    setHidden(this.name, !s.active || !s.command);
    const text = has ? s.prompt : 'No drawing open';
    this.emitHint(has && s.active ? s.prompt : '');
    const open = text.indexOf('['), close = open >= 0 ? text.indexOf(']', open) : -1;
    const withOptions = s.options.length > 0 && open >= 0 && close > open;
    setText(this.pre, withOptions ? text.slice(0, open) : text);
    setText(this.post, withOptions ? text.slice(close + 1) : '');
    setHidden(this.kw, !withOptions);
    this.kwSlots.forEach((b, i) => {
      const o = withOptions ? s.options[i] : undefined;
      setHidden(b, !o);
      if (o) { b.dataset.key = o.key; setText(b, o.label); }
    });
    const placeholder = !has ? 'Open a drawing to use the command line' : s.active ? '' : 'Type a command';
    if (this.input.placeholder !== placeholder) this.input.placeholder = placeholder;
    const lines = this.deps.lines();
    const shown = this.visibleHistory().slice(Math.max(0, this.visibleHistory().length - lines));
    patchList(this.history, shown, {
      key: (l) => l.key,
      create: (l) => { const n = el('<div class="cv-cmd-line"></div>'); setText(n, l.text); return n; },
      update: (n, l) => setText(n, l.text),
    });
    setHidden(this.history, lines === 0);
    this.renderPop();
    this.placePop();
    for (const [n, b] of this.lineButtons) {
      setClass(b, 'is-chosen', n === lines);
      b.setAttribute('aria-checked', String(n === lines));
    }
    setClass(this.dynButton, 'is-chosen', sysvars.num('DYNMODE', 1) !== 0);
    setClass(this.historyButton, 'is-chosen', this.expanded);
    this.copyButton.disabled = this.visibleHistory().length === 0;
    this.recentSlots.forEach((b, i) => {
      const name = this.recent[i];
      setHidden(b, !name);
      if (name) { setText(b, name); b.dataset.cmd = name.toLowerCase(); }
    });
    const head = q(this.menu, '.cv-cmd-menu-head');
    setHidden(head, this.recent.length === 0);
  }

  private renderPop(): void {
    if (!this.expanded) return;
    const near = this.popBody.scrollHeight - this.popBody.scrollTop - this.popBody.clientHeight < LINE_H * 2;
    patchList(this.popBody, this.visibleHistory(), {
      key: (l) => l.key,
      create: (l) => { const n = el('<div class="cv-cmd-line"></div>'); setText(n, l.text); return n; },
      update: (n, l) => setText(n, l.text),
    });
    if (near) this.popBody.scrollTop = this.popBody.scrollHeight;
  }

  private apply(id: string, s: CommandLineState): void {
    this.cache.set(id, s);
    if (id === this.docId) {
      this.state = s;
      this.render();
    }
  }

  private async send(fn: (id: string) => Promise<CommandLineState>): Promise<void> {
    const id = this.docId;
    if (!id) return;
    this.busy = true;
    try {
      this.apply(id, await fn(id));
    } catch (e) {
      toast(e instanceof ApiError || e instanceof Error ? e.message : 'The engine did not answer', 'error');
    } finally {
      this.busy = false;
    }
  }

  private async runCommand(name: string): Promise<void> {
    this.remember(name.toUpperCase());
    await this.send((id) => api.runCommand(id, name));
    this.focus();
  }

  private remember(upper: string): void {
    this.recent = [upper, ...this.recent.filter((r) => r !== upper)].slice(0, RECENT_MAX);
  }

  private resolve(word: string): string | null {
    this.buildIndex();
    const w = word.toLowerCase();
    if (this.names.has(w)) return w;
    return this.aliases.get(w) ?? null;
  }

  private async submit(raw: string, typed = true): Promise<void> {
    if (!this.docId) return;
    let text = raw;
    const idle = !this.state.active;
    const single = !/\s/.test(text.trim());
    if (typed && idle && text.trim() && single && !this.resolve(text.trim())) {
      const first = this.suggestFor(text)[0];
      if (first) text = first.name;
    }
    if (typed && text.trim() && !this.state.active) {
      if (this.recall[this.recall.length - 1] !== text) {
        this.recall.push(text);
        if (this.recall.length > RECALL_MAX) this.recall.shift();
        store(RECALL_KEY, JSON.stringify(this.recall));
      }
    }
    if (idle && text.trim()) {
      const word = text.trim().split(/[\s{]/)[0].replace(/^'/, '');
      const cmd = this.resolve(word);
      if (cmd) this.remember(cmd.toUpperCase());
    }
    this.clearInput();
    await this.send((id) => api.sendInput(id, text));
  }

  private async cancel(): Promise<void> {
    this.clearInput();
    await this.send((id) => api.cancelCommand(id));
  }

  private onKey(e: KeyboardEvent): void {
    if (e.isComposing) return;
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      void this.submit(this.input.value);
      return;
    }
    if (e.key === 'Escape') {
      e.preventDefault();
      void this.cancel();
      return;
    }
    if (e.key === 'Tab' && !e.ctrlKey && !e.metaKey && !e.altKey) {
      e.preventDefault();
      this.complete();
      return;
    }
    if ((e.key === 'ArrowUp' || e.key === 'ArrowDown') && !e.ctrlKey && !e.metaKey && !e.altKey && !e.shiftKey) {
      e.preventDefault();
      this.step(e.key === 'ArrowUp' ? -1 : 1);
      return;
    }
    if (e.key === ' ' && !e.ctrlKey && !e.metaKey && !e.altKey && this.spaceSubmits(this.input.value)) {
      e.preventDefault();
      void this.submit(this.input.value);
    }
  }

  private spaceSubmits(value: string): boolean {
    if (value.includes('{')) return false;
    if (this.state.active) return this.state.kind !== 'text';
    return value.trim() !== '' && !/\s/.test(value.trim());
  }

  private step(dir: number): void {
    if (this.recallAt === -1) {
      if (dir > 0) return;
      this.draft = this.input.value;
      this.recallAt = this.recall.length;
    }
    const next = this.recallAt + dir;
    if (next < 0) return;
    if (next >= this.recall.length) {
      this.recallAt = -1;
      this.input.value = this.draft;
    } else {
      this.recallAt = next;
      this.input.value = this.recall[next] ?? '';
    }
    this.refreshSuggestions();
  }

  private complete(): void {
    const first = this.sugs[0];
    if (!first) return;
    this.input.value = first.name;
    this.refreshSuggestions();
  }

  private route(e: KeyboardEvent): void {
    if (e.defaultPrevented || anyDialogOpen() || e.target === this.input || typing(e.target)) return;
    if (e.ctrlKey || e.metaKey || e.altKey || e.isComposing) return;
    const target = e.target instanceof HTMLElement ? e.target : null;
    const onCanvas = !target || target === document.body || this.deps.stage.contains(target);
    const onButton = !!target?.closest('button, a, summary, [role="menuitem"], [role="tab"]');
    const k = e.key;
    if (k === 'Escape') {
      if (this.state.active || this.input.value) { e.preventDefault(); void this.cancel(); }
      return;
    }
    if (k === 'Enter') {
      if (onCanvas && !onButton) { e.preventDefault(); void this.submit(this.input.value); }
      return;
    }
    if (k === 'Tab') {
      if (this.sugs.length) { e.preventDefault(); this.complete(); }
      return;
    }
    if (k === 'Backspace') {
      if (this.input.value) { e.preventDefault(); this.input.value = this.input.value.slice(0, -1); this.afterEdit(); }
      return;
    }
    if (k === ' ') {
      if (onButton) return;
      if (this.input.value ? this.spaceSubmits(this.input.value) : this.state.active && this.state.kind !== 'text') {
        e.preventDefault();
        void this.submit(this.input.value);
      } else if (this.input.value) {
        e.preventDefault();
        this.input.value += ' ';
        this.afterEdit();
      }
      return;
    }
    if (k.length === 1) {
      e.preventDefault();
      this.input.value += k;
      this.afterEdit();
    }
  }

  private afterEdit(): void {
    this.recallAt = -1;
    this.focus();
    this.refreshSuggestions();
  }

  private buildIndex(): void {
    const src = this.deps.engineCommands();
    if (src === this.indexSrc) return;
    this.indexSrc = src;
    this.names = new Map();
    this.aliases = new Map();
    for (const c of src) {
      const n = c.name.toLowerCase();
      if (n.includes('.')) continue;
      this.names.set(n, c);
      for (const a of c.aliases) if (!a.includes('.')) this.aliases.set(a.toLowerCase(), n);
    }
    const byLength = (a: string, b: string): number => a.length - b.length || a.localeCompare(b);
    this.sortedNames = [...this.names.keys()].sort(byLength);
    this.sortedAliases = [...this.aliases.keys()].sort(byLength);
  }

  private suggestFor(raw: string): Suggestion[] {
    const p = raw.trim().toLowerCase();
    if (!p || /\s/.test(p) || p.includes('{')) return [];
    this.buildIndex();
    const out: Suggestion[] = [];
    const labelOf = (n: string): string => this.names.get(n)?.label ?? '';
    if (this.names.has(p)) out.push({ text: p.toUpperCase(), name: p, label: labelOf(p) });
    else {
      const target = this.aliases.get(p);
      if (target) out.push({ text: `${p.toUpperCase()} (${target.toUpperCase()})`, name: target, label: labelOf(target) });
    }
    for (const n of this.sortedNames) if (n !== p && n.startsWith(p)) out.push({ text: n.toUpperCase(), name: n, label: labelOf(n) });
    for (const a of this.sortedAliases) {
      if (a === p || !a.startsWith(p)) continue;
      const target = this.aliases.get(a) ?? a;
      out.push({ text: `${a.toUpperCase()} (${target.toUpperCase()})`, name: target, label: labelOf(target) });
    }
    return out.slice(0, SUGGEST_MAX);
  }

  private refreshSuggestions(): void {
    const value = this.input.value;
    this.sugs = this.state.active || !this.docId ? [] : this.suggestFor(value);
    if (!this.sugs.length) { this.hideSuggestions(); return; }
    this.acRows.forEach((row, i) => {
      const s = this.sugs[i];
      setHidden(row, !s);
      setClass(row, 'is-selected', i === 0);
      if (s) {
        setText(q(row, '.cv-cmd-ac-text'), s.text);
        setText(q(row, '.cv-cmd-ac-label'), s.label);
      }
    });
    setHidden(this.ac, false);
    const r = this.input.offsetParent !== null ? this.input.getBoundingClientRect() : this.root.getBoundingClientRect();
    const key = `${Math.round(r.left)}:${Math.round(r.top)}`;
    if (key !== this.acKey) {
      this.acKey = key;
      this.ac.style.left = `${Math.round(r.left)}px`;
      this.ac.style.bottom = `${Math.round(window.innerHeight - r.top + 4)}px`;
    }
  }

  private hideSuggestions(): void {
    this.sugs = [];
    setHidden(this.ac, true);
  }

  private openMenu(x: number, y: number): void {
    this.render();
    setHidden(this.menu, false);
    const w = this.menu.offsetWidth, h = this.menu.offsetHeight;
    this.menu.style.left = `${Math.max(4, Math.min(x, window.innerWidth - w - 4))}px`;
    this.menu.style.top = `${Math.max(4, Math.min(y, window.innerHeight - h - 4))}px`;
  }

  private closeMenu(): void {
    if (!this.menu.hidden) setHidden(this.menu, true);
  }

  private async copyHistory(): Promise<void> {
    const text = this.visibleHistory().map((l) => l.text).join('\n');
    if (!text) return;
    try {
      await navigator.clipboard.writeText(text);
      toast('Command history copied', 'info');
    } catch {
      toast('The clipboard is not available', 'error');
    }
  }

  private clearHistory(): void {
    if (!this.docId) return;
    this.cleared.set(this.docId, this.state.historySize ?? this.state.history.length);
    this.render();
  }

  get isBusy(): boolean {
    return this.busy;
  }
}
