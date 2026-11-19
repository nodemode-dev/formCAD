import { css, parseCss, type Rgba } from './color';

interface Slot { gen: number; probe: HTMLElement; values: Map<string, Rgba> }

const slots = new WeakMap<Element, Slot>();
const subs = new Set<() => void>();
let gen = 0;
let wired = false;
let lastSig = '';

function slotFor(scope: Element): Slot {
  let s = slots.get(scope);
  if (!s || !s.probe.isConnected) {
    const probe = document.createElement('span');
    probe.setAttribute('aria-hidden', 'true');
    probe.style.cssText = 'position:absolute;left:0;top:0;width:0;height:0;overflow:hidden;visibility:hidden;pointer-events:none';
    scope.append(probe);
    s = { gen, probe, values: new Map() };
    slots.set(scope, s);
  }
  if (s.gen !== gen) { s.gen = gen; s.values.clear(); }
  return s;
}

export function isOled(): boolean {
  return document.documentElement.hasAttribute('data-oled');
}

export function tokenRgba(name: string, fallback: Rgba, scope: Element = document.body): Rgba {
  wire();
  const s = slotFor(scope);
  const hit = s.values.get(name);
  if (hit) return hit;
  let out = fallback;
  if (getComputedStyle(scope).getPropertyValue(name).trim()) {
    s.probe.style.color = '';
    s.probe.style.color = `var(${name})`;
    out = parseCss(getComputedStyle(s.probe).color, fallback);
    s.probe.style.color = '';
  }
  s.values.set(name, out);
  return out;
}

export function tokenCss(name: string, fallback: Rgba, scope?: Element): string {
  return css(tokenRgba(name, fallback, scope));
}

export function tokenHex(name: string, fallback: Rgba, scope?: Element): number {
  const c = tokenRgba(name, fallback, scope);
  return (Math.round(c[0]) << 16) | (Math.round(c[1]) << 8) | Math.round(c[2]);
}

export function tokenHexCss(name: string, fallback: Rgba, scope?: Element): string {
  return `#${tokenHex(name, fallback, scope).toString(16).padStart(6, '0')}`;
}

function signature(): string {
  const r = document.documentElement;
  return `${r.getAttribute('style') ?? ''}|${r.className}|${isOled()}|${document.body.className.includes('theme-light')}`;
}

function changed(): void {
  const sig = signature();
  if (sig === lastSig) return;
  lastSig = sig;
  gen += 1;
  for (const cb of [...subs]) cb();
}

function wire(): void {
  if (wired) return;
  wired = true;
  lastSig = signature();
  document.addEventListener('nm:ui-settings-changed', changed, true);
  document.addEventListener('formcad:prefs-changed', () => { gen += 1; for (const cb of [...subs]) cb(); }, true);
  const mo = new MutationObserver(changed);
  mo.observe(document.documentElement, { attributes: true, attributeFilter: ['style', 'class', 'data-oled', 'data-theme'] });
  mo.observe(document.body, { attributes: true, attributeFilter: ['class'] });
}

export function onThemeChange(cb: () => void): () => void {
  wire();
  subs.add(cb);
  return () => { subs.delete(cb); };
}
