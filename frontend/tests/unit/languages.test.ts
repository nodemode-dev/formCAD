import { beforeEach, describe, expect, it, vi } from 'vitest';
import { KEYS } from '../../src/ui/i18n/keys';
import { LANG_CODES, LANG_PARENT } from '../../src/ui/i18n/langs';

type I18n = typeof import('../../src/ui/i18n');

async function fresh(): Promise<I18n> {
  vi.resetModules();
  return import('../../src/ui/i18n');
}

const placeholders = (s: string): string[] => (s.match(/\{[A-Za-z0-9_]+\}/g) ?? []).sort();
const shipped = LANG_CODES.filter((l) => l !== 'en');

beforeEach(() => {
  localStorage.clear();
  document.body.innerHTML = '';
});

describe('languages', () => {
  it.each(shipped)('every interface key has a non-empty text in %s, its own or its parent language', async (lang) => {
    const i18n = await fresh();
    await i18n.setLanguage(lang);
    expect(i18n.language()).toBe(lang);
    const tables = import.meta.glob<{ default: Record<number, string> }>('../../src/ui/i18n/tables/*.ts');
    const own: Record<number, string> = {};
    const parent: Record<number, string> = {};
    for (const part of ['a', 'b', 'c', 'd']) {
      Object.assign(own, (await tables[`../../src/ui/i18n/tables/${lang}.${part}.ts`]()).default);
      const p = LANG_PARENT[lang];
      if (p) Object.assign(parent, (await tables[`../../src/ui/i18n/tables/${p}.${part}.ts`]()).default);
    }
    const missing = KEYS.filter((_k, i) => !(own[i] ?? parent[i]));
    expect(missing).toEqual([]);
    const empty = KEYS.filter((k) => i18n.t(k).trim() === '');
    expect(empty).toEqual([]);
    const translated = KEYS.filter((k) => i18n.t(k) !== k).length;
    expect(translated / KEYS.length).toBeGreaterThan(0.6);
  });

  it.each(shipped)('placeholders such as {n} and {name} match the English text for every key in %s', async (lang) => {
    const i18n = await fresh();
    await i18n.setLanguage(lang);
    const wrong = KEYS.filter((k) => placeholders(i18n.t(k)).join() !== placeholders(k).join()).map((k) => `${k} => ${i18n.t(k)}`);
    expect(wrong).toEqual([]);
  });

  it('a text that has no entry is shown in English', async () => {
    const i18n = await fresh();
    await i18n.setLanguage('de');
    expect(i18n.t('A sentence no table has, 42')).toBe('A sentence no table has, 42');
    expect(i18n.t('About FormCAD')).not.toBe('About FormCAD');
  });

  it('a regional language without its own entry uses its parent language', async () => {
    const i18n = await fresh();
    await i18n.setLanguage('es');
    const parentText = KEYS.map((k) => i18n.t(k));
    const again = await fresh();
    await again.setLanguage('es-MX');
    const regional = KEYS.map((k) => again.t(k));
    const tables = import.meta.glob<{ default: Record<number, string> }>('../../src/ui/i18n/tables/es-MX.*.ts');
    const own: Record<number, string> = {};
    for (const load of Object.values(tables)) Object.assign(own, (await load()).default);
    const fromParent = KEYS.map((_k, i) => i).filter((i) => !own[i]);
    expect(fromParent.length).toBeGreaterThan(0);
    for (const i of fromParent) expect(regional[i]).toBe(parentText[i]);
    for (const i of Object.keys(own).map(Number)) expect(regional[i]).toBe(own[i]);
  });

  it('keeps a trailing ellipsis or colon on a translated text', async () => {
    const i18n = await fresh();
    await i18n.setLanguage('de');
    const base = i18n.t('About FormCAD');
    expect(i18n.t('About FormCAD...')).toBe(`${base}...`);
    expect(i18n.t('About FormCAD:')).toBe(`${base}:`);
  });

  it('a count is put into the plural form of the language', async () => {
    const i18n = await fresh();
    expect(i18n.tn(1, '{n} item', '{n} items')).toBe('1 item');
    expect(i18n.tn(1234, '{n} item', '{n} items')).toBe('1,234 items');
    await i18n.setLanguage('de');
    expect(i18n.tn(1234, '{n} item', '{n} items')).toContain('1.234');
  });

  it('switching language repaints the text on the page in place and switching back restores the English', async () => {
    const i18n = await fresh();
    const p = document.createElement('p');
    p.textContent = 'About FormCAD';
    const b = document.createElement('button');
    b.setAttribute('title', 'Accessibility');
    const typed = document.createElement('input');
    typed.value = 'About FormCAD';
    document.body.append(p, b, typed);
    const node = p.firstChild;
    i18n.startPageTranslator();
    await i18n.setLanguage('fr');
    const fr = i18n.t('About FormCAD');
    expect(fr).not.toBe('About FormCAD');
    expect(p.textContent).toBe(fr);
    expect(p.firstChild).toBe(node);
    expect(b.getAttribute('title')).toBe(i18n.t('Accessibility'));
    expect(typed.value).toBe('About FormCAD');
    expect(document.documentElement.lang).toBe('fr');
    await i18n.setLanguage('ar');
    expect(p.textContent).toBe(i18n.t('About FormCAD'));
    expect(document.documentElement.dir).toBe('rtl');
    await i18n.setLanguage('en');
    expect(p.textContent).toBe('About FormCAD');
    expect(b.getAttribute('title')).toBe('Accessibility');
    expect(document.documentElement.dir).toBe('ltr');
  });
});
