import { docStore } from './doc-store';

export const MODEL = ['part', 'assembly', 'surface', 'form'] as const;
export const DRAWN = ['drawing', 'part', 'assembly'] as const;
export const DOCS = ['drawing', 'part', 'assembly', 'surface', 'form'] as const;

const seen = new Map<string, boolean>();
const watched = new Set<Element>();
const wakers = new Set<() => void>();
let io: IntersectionObserver | null = null;

const hostOf = (id: string): Element | null => document.querySelector(`[data-panel="${id}"]`);

const observer = (): IntersectionObserver => {
  if (!io) {
    io = new IntersectionObserver((entries) => {
      let changed = false;
      for (const e of entries) {
        const id = (e.target as HTMLElement).dataset.panel ?? '';
        if (seen.get(id) !== e.isIntersecting) { seen.set(id, e.isIntersecting); changed = true; }
      }
      if (changed) for (const w of [...wakers]) w();
    });
  }
  return io;
};

export const shown = (id: string): boolean => {
  const h = hostOf(id);
  if (!h) return false;
  if (!watched.has(h)) { watched.add(h); seen.set(id, false); observer().observe(h); }
  return seen.get(id) === true;
};

export const serves = (kinds: readonly string[] | null): boolean => {
  if (!kinds) return true;
  const k = docStore.current()?.kind;
  return !k || kinds.includes(k);
};

export function gate(panels: readonly string[], kinds: readonly string[] | null, wake: () => void): () => boolean {
  let stale = false;
  const open = (): boolean => serves(kinds) && panels.some(shown);
  const retry = (): void => { if (stale && open()) { stale = false; wake(); } };
  wakers.add(retry);
  docStore.onChange(retry);
  return () => {
    if (open()) { stale = false; return true; }
    stale = true;
    return false;
  };
}
