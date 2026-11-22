import { loadPrefs } from './prefs';
import { LANG_NAMES, LANG_PARENT, RTL_LANGS, isLang as isLangCode, type Lang } from './i18n/langs';

export type { Lang } from './i18n/langs';

type Table = Record<string, string>;

type Rows = Promise<{ default: Record<number, string> }>;

async function rows(...parts: Rows[]): Promise<Table> {
  const [{ KEYS }, ...loaded] = await Promise.all([import('./i18n/keys'), ...parts]);
  const table: Table = {};
  for (const part of loaded) {
    for (const [index, text] of Object.entries(part.default)) {
      const key = KEYS[Number(index)];
      if (key !== undefined && text) table[key] = text;
    }
  }
  return table;
}

const LOADERS: Record<Lang, () => Promise<Table>> = {
  'es': () => rows(import('./i18n/tables/es.a'), import('./i18n/tables/es.b'), import('./i18n/tables/es.c')),
  'es-MX': () => rows(import('./i18n/tables/es-MX.a'), import('./i18n/tables/es-MX.b'), import('./i18n/tables/es-MX.c')),
  'pt-BR': () => rows(import('./i18n/tables/pt-BR.a'), import('./i18n/tables/pt-BR.b'), import('./i18n/tables/pt-BR.c')),
  'fr': () => rows(import('./i18n/tables/fr.a'), import('./i18n/tables/fr.b'), import('./i18n/tables/fr.c')),
  'fr-CA': () => rows(import('./i18n/tables/fr-CA.a'), import('./i18n/tables/fr-CA.b'), import('./i18n/tables/fr-CA.c')),
  'de': () => rows(import('./i18n/tables/de.a'), import('./i18n/tables/de.b'), import('./i18n/tables/de.c')),
  'it': () => rows(import('./i18n/tables/it.a'), import('./i18n/tables/it.b'), import('./i18n/tables/it.c')),
  'nl': () => rows(import('./i18n/tables/nl.a'), import('./i18n/tables/nl.b'), import('./i18n/tables/nl.c')),
  'da': () => rows(import('./i18n/tables/da.a'), import('./i18n/tables/da.b'), import('./i18n/tables/da.c')),
  'fi': () => rows(import('./i18n/tables/fi.a'), import('./i18n/tables/fi.b'), import('./i18n/tables/fi.c')),
  'nb': () => rows(import('./i18n/tables/nb.a'), import('./i18n/tables/nb.b'), import('./i18n/tables/nb.c')),
  'sv': () => rows(import('./i18n/tables/sv.a'), import('./i18n/tables/sv.b'), import('./i18n/tables/sv.c')),
  'ru': () => rows(import('./i18n/tables/ru.a'), import('./i18n/tables/ru.b'), import('./i18n/tables/ru.c')),
  'pl': () => rows(import('./i18n/tables/pl.a'), import('./i18n/tables/pl.b'), import('./i18n/tables/pl.c')),
  'cs': () => rows(import('./i18n/tables/cs.a'), import('./i18n/tables/cs.b'), import('./i18n/tables/cs.c')),
  'hu': () => rows(import('./i18n/tables/hu.a'), import('./i18n/tables/hu.b'), import('./i18n/tables/hu.c')),
  'uk': () => rows(import('./i18n/tables/uk.a'), import('./i18n/tables/uk.b'), import('./i18n/tables/uk.c')),
  'tr': () => rows(import('./i18n/tables/tr.a'), import('./i18n/tables/tr.b'), import('./i18n/tables/tr.c')),
  'el': () => rows(import('./i18n/tables/el.a'), import('./i18n/tables/el.b'), import('./i18n/tables/el.c')),
  'sr-Latn': () => rows(import('./i18n/tables/sr-Latn.a'), import('./i18n/tables/sr-Latn.b'), import('./i18n/tables/sr-Latn.c')),
  'zh-CN': () => rows(import('./i18n/tables/zh-CN.a'), import('./i18n/tables/zh-CN.b'), import('./i18n/tables/zh-CN.c')),
  'zh-TW': () => rows(import('./i18n/tables/zh-TW.a'), import('./i18n/tables/zh-TW.b'), import('./i18n/tables/zh-TW.c')),
  'ja': () => rows(import('./i18n/tables/ja.a'), import('./i18n/tables/ja.b'), import('./i18n/tables/ja.c')),
  'ko': () => rows(import('./i18n/tables/ko.a'), import('./i18n/tables/ko.b'), import('./i18n/tables/ko.c')),
  'id': () => rows(import('./i18n/tables/id.a'), import('./i18n/tables/id.b'), import('./i18n/tables/id.c')),
  'th': () => rows(import('./i18n/tables/th.a'), import('./i18n/tables/th.b'), import('./i18n/tables/th.c')),
  'vi': () => rows(import('./i18n/tables/vi.a'), import('./i18n/tables/vi.b'), import('./i18n/tables/vi.c')),
  'ar': () => rows(import('./i18n/tables/ar.a'), import('./i18n/tables/ar.b'), import('./i18n/tables/ar.c')),
  'hi': () => rows(import('./i18n/tables/hi.a'), import('./i18n/tables/hi.b'), import('./i18n/tables/hi.c')),
};
const tables = new Map<Lang, Table>([['en', {}]]);

const saved = loadPrefs().language;
let current: Lang = 'en';
let wanted: Lang = saved;
const listeners = new Set<() => void>();

export const languages = (): ReadonlyArray<readonly [Lang, string]> => LANG_NAMES;
export const language = (): Lang => current;
export const isLang = isLangCode;

async function load(l: Lang): Promise<void> {
  for (const code of [LANG_PARENT[l], l]) {
    if (!code || tables.has(code) || code === 'en') continue;
    const loader = LOADERS[code];
    if (!loader) throw new Error(`no table for ${code}`);
    tables.set(code, await loader());
  }
}

export function t(english: string): string {
  if (current === 'en') return english;
  const tail = english.endsWith('...') ? '...' : english.endsWith(':') && !english.endsWith('::') ? ':' : '';
  const base = tail ? english.slice(0, -tail.length) : english;
  const parent = LANG_PARENT[current];
  const look = (k: string): string | undefined => tables.get(current)?.[k] ?? (parent ? tables.get(parent)?.[k] : undefined);
  const found = look(base) ?? (tail ? look(english) : undefined);
  if (found === undefined) return english;
  return tail && look(base) !== undefined ? `${found}${tail}` : found;
}

export function tn(n: number, one: string, other: string): string {
  const lang = current;
  let cat: Intl.LDMLPluralRule = n === 1 ? 'one' : 'other';
  try { if (lang !== 'en') cat = new Intl.PluralRules(lang).select(n); } catch { cat = n === 1 ? 'one' : 'other'; }
  const hit = (key: string): string | undefined => { const f = t(key); return f === key ? undefined : f; };
  const form = lang === 'en' ? (n === 1 ? one : other) : hit(`${other}#${cat}`) ?? hit(cat === 'one' ? one : other) ?? hit(other) ?? (n === 1 ? one : other);
  let shown = String(n);
  try { shown = new Intl.NumberFormat(lang === 'en' ? 'en' : lang).format(n); } catch { shown = String(n); }
  return form.replace('{n}', shown);
}

const known = (text: string): boolean => current !== 'en' && t(text) !== text;

let back: Map<string, string> | null = null;

function reverse(l: Lang): Map<string, string> | null {
  if (l === 'en') return null;
  const m = new Map<string, string>();
  for (const code of [LANG_PARENT[l], l]) {
    const table = code ? tables.get(code) : undefined;
    if (table) for (const [en, shown] of Object.entries(table)) m.set(shown, en);
  }
  return m;
}

const backOf = (s: string): string | undefined => {
  if (!back) return undefined;
  const hit = back.get(s);
  if (hit !== undefined) return hit;
  const tail = s.endsWith('...') ? '...' : s.endsWith(':') ? ':' : '';
  const base = tail ? back.get(s.slice(0, -tail.length)) : undefined;
  return base === undefined ? undefined : base + tail;
};

export async function setLanguage(l: Lang): Promise<void> {
  wanted = l;
  try { await load(l); } catch { return; }
  if (wanted !== l || l === current) return;
  const was = current;
  current = l;
  document.documentElement.lang = l;
  document.documentElement.dir = RTL_LANGS.has(l) ? 'rtl' : 'ltr';
  for (const fn of listeners) fn();
  back = reverse(was);
  translatePage();
  back = null;
}

export async function startLanguage(): Promise<void> {
  if (saved === 'en') return;
  try { await load(saved); } catch { return; }
  if (wanted !== saved) return;
  current = saved;
  document.documentElement.lang = saved;
  document.documentElement.dir = RTL_LANGS.has(saved) ? 'rtl' : 'ltr';
}

export function onLanguage(fn: () => void): () => void {
  listeners.add(fn);
  return () => { listeners.delete(fn); };
}

const ATTRS = ['title', 'aria-label', 'placeholder'] as const;
const SKIP = 'textarea, input, script, style, canvas, [contenteditable], [data-no-i18n], .cv-tab-name, .cv-tb-doc, .cv-cmdline, .cv-layer-name, .cv-home-name';
const textEn = new WeakMap<Text, { en: string; shown: string }>();
const attrEn = new WeakMap<Element, Map<string, { en: string; shown: string }>>();
let observer: MutationObserver | null = null;

const skipped = (n: Node | null): boolean => {
  const e = n instanceof Element ? n : n?.parentElement ?? null;
  return !e || !!e.closest(SKIP);
};

function translateText(node: Text): void {
  const raw = node.data, rec = textEn.get(node);
  if (rec && raw === rec.shown) {
    const next = t(rec.en);
    if (next !== raw) { rec.shown = next; node.data = next; }
    if (current === 'en' || next === rec.en) textEn.delete(node);
    return;
  }
  const trimmed = raw.trim();
  const source = trimmed ? backOf(trimmed) : undefined;
  if (source !== undefined && !skipped(node)) {
    const en = raw.replace(trimmed, source), next = raw.replace(trimmed, t(source));
    if (next === en) textEn.delete(node); else textEn.set(node, { en, shown: next });
    node.data = next;
    return;
  }
  if (!trimmed || trimmed.length > 200 || !known(trimmed) || skipped(node)) { if (rec) textEn.delete(node); return; }
  const next = raw.replace(trimmed, t(trimmed));
  textEn.set(node, { en: raw, shown: next });
  node.data = next;
}

const SKIP_ATTR = SKIP.replace('textarea, input, ', '');
const skippedAttr = (e: Element): boolean => !!e.closest(SKIP_ATTR);

function translateAttrs(node: Element): void {
  for (const a of ATTRS) {
    const v = node.getAttribute(a);
    if (v === null) continue;
    let recs = attrEn.get(node);
    const rec = recs?.get(a);
    if (rec && v === rec.shown) {
      const next = t(rec.en);
      if (next !== v) { rec.shown = next; node.setAttribute(a, next); }
      continue;
    }
    const source = backOf(v);
    if (source !== undefined && !skippedAttr(node)) {
      const next = t(source);
      if (next === source) recs?.delete(a);
      else { if (!recs) { recs = new Map(); attrEn.set(node, recs); } recs.set(a, { en: source, shown: next }); }
      node.setAttribute(a, next);
      continue;
    }
    if (!known(v) || skippedAttr(node)) { recs?.delete(a); continue; }
    if (!recs) { recs = new Map(); attrEn.set(node, recs); }
    const next = t(v);
    recs.set(a, { en: v, shown: next });
    node.setAttribute(a, next);
  }
}

function walk(root: Node): void {
  if (root instanceof Text) { translateText(root); return; }
  if (!(root instanceof Element)) return;
  if (root.closest(SKIP)) { if (root.matches('input, textarea')) translateAttrs(root); return; }
  translateAttrs(root);
  const it = document.createTreeWalker(root, NodeFilter.SHOW_ELEMENT | NodeFilter.SHOW_TEXT, {
    acceptNode: (n) => {
      if (!(n instanceof Element) || !n.matches(SKIP)) return NodeFilter.FILTER_ACCEPT;
      if (n.matches('input, textarea')) translateAttrs(n);
      return NodeFilter.FILTER_REJECT;
    },
  });
  for (let n = it.nextNode(); n; n = it.nextNode()) {
    if (n instanceof Text) translateText(n);
    else if (n instanceof Element) translateAttrs(n);
  }
}

const WATCH = { subtree: true, childList: true, characterData: true, attributes: true, attributeFilter: [...ATTRS] };

function translatePage(): void {
  if (typeof document === 'undefined') return;
  observer?.disconnect();
  walk(document.body);
  observer?.observe(document.body, WATCH);
}

export function startPageTranslator(): void {
  if (observer || typeof MutationObserver === 'undefined') return;
  observer = new MutationObserver((records) => {
    if (current === 'en') return;
    observer?.disconnect();
    for (const r of records) {
      if (r.type === 'childList') r.addedNodes.forEach((n) => walk(n));
      else if (r.type === 'characterData' && r.target instanceof Text) translateText(r.target);
      else if (r.type === 'attributes' && r.target instanceof Element) translateAttrs(r.target);
    }
    observer?.observe(document.body, WATCH);
  });
  translatePage();
}
