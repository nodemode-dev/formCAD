export const LANG_CODES: readonly string[] = ['en'];
export type Lang = string;

export const LANG_NAMES: ReadonlyArray<readonly [Lang, string]> = [
  ['en', 'English'],
];

export const RTL_LANGS: ReadonlySet<Lang> = new Set<Lang>([]);

export const LANG_PARENT: Readonly<Record<Lang, Lang | undefined>> = {};

export const isLang = (v: unknown): v is Lang => typeof v === 'string' && LANG_CODES.includes(v);
