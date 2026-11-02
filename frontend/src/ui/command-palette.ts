import type { CommandMeta } from '../io/api';
import type { Commands } from './commands';
import { Dialog } from './dialogs';
import { el, q, setClass, setHidden, setHtml, setText, setTitle, store, stored } from './dom';
import { icon } from './icons';
import { t } from './i18n';

export function fuzzyScore(query: string, text: string): number | null {
  const needle = Array.from(query.toLowerCase()), raw = Array.from(text), hay = raw.map((c) => c.toLowerCase()), m = needle.length, n = hay.length;
  if (!m) return 0;
  if (m > n) return null;
  const opens = (j: number): boolean => j === 0 || /[\s>\-/(.,:]/.test(raw[j - 1]) || (raw[j] !== hay[j] && raw[j - 1] === hay[j - 1] && /[a-z]/.test(hay[j - 1]));
  let prev = new Float64Array(n).fill(-Infinity), row = new Float64Array(n);
  for (let i = 0; i < m; i++) {
    let earlier = -Infinity;
    for (let j = 0; j < n; j++) {
      if (j >= 2) earlier = Math.max(earlier, prev[j - 2]);
      if (hay[j] !== needle[i]) { row[j] = -Infinity; continue; }
      const own = 1 + (opens(j) ? 5 : 0) - j * 0.01;
      const before = i === 0 ? 0 : Math.max(j >= 1 ? prev[j - 1] + 7 : -Infinity, earlier);
      row[j] = before === -Infinity ? -Infinity : before + own;
    }
    [prev, row] = [row, prev];
  }
  let best = -Infinity;
  for (let j = 0; j < n; j++) best = Math.max(best, prev[j]);
  return best === -Infinity ? null : Math.round(best) - Math.floor(n / 8);
}

export interface PaletteDeps {
  commands: Commands;
  engineCommands: () => CommandMeta[];
  refreshEngine: () => void;
  runEngine: (name: string) => void;
}

interface Hit {
  key: string;
  label: string;
  meta: string;
  icon: string;
  enabled: boolean;
  why: string;
  score: number;
  on: boolean;
  run: () => void;
}

const SHOWN = 12;
const RECENT_KEY = 'formCAD.paletteRecent';

function loadRecent(): string[] {
  try {
    const v: unknown = JSON.parse(stored(RECENT_KEY) ?? '[]');
    return Array.isArray(v) ? v.filter((x): x is string => typeof x === 'string').slice(0, SHOWN) : [];
  } catch {
    return [];
  }
}

const titleCase = (s: string): string => s.replace(/[._-]+/g, ' ').replace(/\b\w/g, (c) => c.toUpperCase());

export class CommandPalette extends Dialog {
  private readonly input = el<HTMLInputElement>('<input class="cv-input cv-palette-input" type="search" placeholder="Search commands" aria-label="Search commands" spellcheck="false" autocomplete="off">');
  private readonly list = el('<div class="cv-palette-list" role="listbox" aria-label="Commands"></div>');
  private readonly empty = el('<p class="cv-note cv-palette-empty">No command matches.</p>');
  private readonly rows: HTMLElement[] = [];
  private hits: Hit[] = [];
  private selected = 0;
  private recent: string[] = loadRecent();

  constructor(private readonly deps: PaletteDeps) {
    super('Search', 560);
    for (let i = 0; i < SHOWN; i++) {
      const row = el<HTMLButtonElement>('<button class="cv-list-row cv-palette-row" type="button" role="option" tabindex="-1" hidden><span class="cv-palette-icon"></span><span class="cv-list-name"></span><span class="cv-list-meta"></span></button>');
      row.dataset.index = String(i);
      this.rows.push(row);
      this.list.appendChild(row);
    }
    const box = el('<div class="cv-palette-box"></div>');
    box.append(this.list, this.empty);
    this.body.append(this.input, box);
    setHidden(this.empty, true);
    this.input.addEventListener('input', () => { this.selected = 0; this.render(); });
    this.input.addEventListener('keydown', (e) => {
      if (e.key === 'ArrowDown' || e.key === 'ArrowUp') {
        e.preventDefault();
        this.selected = Math.max(0, Math.min(this.hits.length - 1, this.selected + (e.key === 'ArrowDown' ? 1 : -1)));
        this.mark();
      } else if (e.key === 'Enter') {
        e.preventDefault();
        this.runHit(this.selected);
      }
    });
    this.list.addEventListener('mousedown', (e) => e.preventDefault());
    this.list.addEventListener('click', (e) => {
      const row = (e.target as HTMLElement).closest<HTMLElement>('.cv-palette-row');
      if (row) this.runHit(Number(row.dataset.index));
    });
  }

  show(): void {
    if (this.isOpen) return;
    this.deps.refreshEngine();
    this.input.value = '';
    this.selected = 0;
    this.render();
    this.open(this.input);
  }

  private runHit(i: number): void {
    const h = this.hits[i];
    if (!h?.enabled) return;
    this.recent = [h.key, ...this.recent.filter((k) => k !== h.key)].slice(0, SHOWN);
    store(RECENT_KEY, JSON.stringify(this.recent));
    this.close();
    h.run();
  }

  private render(): void {
    const query = this.input.value.trim(), hits: Hit[] = [];
    const first = (key: string): number => {
      const i = this.recent.indexOf(key);
      return query || i < 0 ? 0 : 1000 - i;
    };
    const { commands } = this.deps;
    const known = new Set<string>();
    for (const c of commands.all()) {
      known.add(c.id);
      const label = t(commands.label(c)).replace(/\.\.\.$/, '');
      if (!label) continue;
      const score = fuzzyScore(query, label) ?? fuzzyScore(query, `${label} ${c.group ?? ''}`);
      if (score === null) continue;
      const on = c.checked ? c.checked() : false;
      const keys = commands.keyLabel(c);
      hits.push({
        key: c.id,
        label,
        meta: [c.checked ? (on ? 'On' : 'Off') : '', c.group ?? '', keys].filter(Boolean).join(' · '),
        icon: c.icon ?? '',
        enabled: commands.enabled(c),
        why: t(commands.why(c)),
        score: score + first(c.id),
        on,
        run: () => { commands.run(c.id); },
      });
    }
    for (const m of this.deps.engineCommands()) {
      if (m.name.includes('.') || known.has(m.name)) continue;
      const label = m.label || titleCase(m.name);
      const names = [m.name, ...m.aliases];
      const score = Math.max(...[fuzzyScore(query, label), ...names.map((n) => fuzzyScore(query, n))].map((s) => s ?? -Infinity));
      if (!Number.isFinite(score)) continue;
      const key = `engine:${m.name}`;
      hits.push({
        key,
        label,
        meta: ['Command', m.name.toUpperCase(), m.aliases.length ? m.aliases.map((a) => a.toUpperCase()).join(', ') : ''].filter(Boolean).join(' · '),
        icon: 'cmdline',
        enabled: true,
        why: m.description,
        score: score - 1 + first(key),
        on: false,
        run: () => this.deps.runEngine(m.name),
      });
    }
    hits.sort((a, b) => b.score - a.score || a.label.localeCompare(b.label));
    this.hits = hits.slice(0, SHOWN);
    this.selected = Math.max(0, Math.min(this.selected, this.hits.length - 1));
    this.rows.forEach((row, i) => {
      const h = this.hits[i];
      setHidden(row, !h);
      if (h) this.fill(row, h);
    });
    setHidden(this.empty, this.hits.length > 0);
    this.mark();
  }

  private fill(n: HTMLElement, h: Hit): void {
    setText(q(n, '.cv-list-name'), h.label);
    setText(q(n, '.cv-list-meta'), h.meta);
    setClass(n, 'is-off', !h.enabled);
    setClass(n, 'is-on', h.on);
    setTitle(n, h.why);
    if (n.getAttribute('aria-disabled') !== String(!h.enabled)) n.setAttribute('aria-disabled', String(!h.enabled));
    setHtml(q(n, '.cv-palette-icon'), h.icon ? icon(h.icon, 16) : '', h.icon);
  }

  private mark(): void {
    this.rows.forEach((n, i) => {
      const on = i === this.selected && !n.hidden;
      setClass(n, 'is-selected', on);
      if (n.getAttribute('aria-selected') !== String(on)) n.setAttribute('aria-selected', String(on));
    });
  }
}
