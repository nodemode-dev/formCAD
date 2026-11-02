import { isLang, type Lang } from './i18n/langs';

export type DrawUnit = 'mm' | 'cm' | 'm' | 'in' | 'ft';
export type AngleUnit = 'deg' | 'rad' | 'grad';
export type ThemeMode = 'fixed' | 'system';
export type AnimationMode = 'system' | 'on' | 'off';
export type FileSaveKind ='dxf' | 'dwg';

export const SAVE_VERSIONS: ReadonlyArray<readonly [string, string]> = [['2000', '2000'], ['2004', '2004'], ['2007', '2007'], ['2010', '2010'], ['2013', '2013'], ['2018', '2018']];
export const ANIMATION_MODES: ReadonlyArray<readonly [AnimationMode, string]> = [['system', 'Use System Setting'], ['on', 'On'], ['off', 'Off']];

export const DRAW_UNITS: ReadonlyArray<readonly [DrawUnit, string]> = [['mm', 'Millimetres'], ['cm', 'Centimetres'], ['m', 'Metres'], ['in', 'Inches'], ['ft', 'Feet']];
export const ANGLE_UNITS: ReadonlyArray<readonly [AngleUnit, string]> = [['deg', 'Degrees'], ['rad', 'Radians'], ['grad', 'Gradians']];

export interface Prefs {
  language: Lang;
  autoShowHome: boolean;
  homeOnLastClose: boolean;
  restoreSession: boolean;
  uiScale: number;
  fontSize: number;
  animations: boolean;
  reduceMotion: boolean;
  themeMode: ThemeMode;
  themeLight: string;
  themeDark: string;
  noticeSeconds: number;
  recentFileCount: number;
  showCommandLine: boolean;
  showDock: boolean;
  dockWidth: number;
  units: DrawUnit;
  precision: number;
  angleUnit: AngleUnit;
  animationMode: AnimationMode;
  languageAuto: boolean;
  historyLines: number;
  systemCursor: boolean;
  modelBackground: string;
  layoutPaper: string;
  selectionColor: string;
  saveFormat: FileSaveKind;
  saveVersion: string;
  snapMarkerSize: number;
  timeRightClick: boolean;
  shortcuts: Record<string, string[]>;
}

export const DEFAULT_PREFS: Prefs = {
  language: 'en',
  autoShowHome: true,
  homeOnLastClose: true,
  restoreSession: true,
  uiScale: 100,
  fontSize: 12,
  animations: true,
  reduceMotion: false,
  themeMode: 'fixed',
  themeLight: 'light',
  themeDark: 'studio',
  noticeSeconds: 0,
  recentFileCount: 20,
  showCommandLine: true,
  showDock: true,
  dockWidth: 300,
  units: 'mm',
  precision: 3,
  angleUnit: 'deg',
  animationMode: 'system',
  languageAuto: true,
  historyLines: 3,
  systemCursor: false,
  modelBackground: '',
  layoutPaper: '',
  selectionColor: '',
  saveFormat: 'dxf',
  saveVersion: '2018',
  snapMarkerSize: 11,
  timeRightClick: true,
  shortcuts: {},
};

export const PREFS_KEY = 'formCAD.prefs';

const flag = (v: unknown, def: boolean): boolean => (typeof v === 'boolean' ? v : def);
const num = (v: unknown, lo: number, hi: number, def: number): number => (typeof v === 'number' && Number.isFinite(v) ? Math.min(hi, Math.max(lo, v)) : def);
const whole = (v: unknown, lo: number, hi: number, def: number): number => Math.round(num(v, lo, hi, def));
const pick = <T extends string>(v: unknown, allowed: ReadonlyArray<readonly [T, string]>, def: T): T => (allowed.some(([k]) => k === v) ? (v as T) : def);
const text = (v: unknown, def: string): string => (typeof v === 'string' && v.length > 0 && v.length <= 64 ? v : def);
const hex = (v: unknown): string => (typeof v === 'string' && /^#[0-9a-fA-F]{6}$/.test(v) ? v.toLowerCase() : '');

function cleanShortcuts(v: unknown): Record<string, string[]> {
  if (!v || typeof v !== 'object') return {};
  const out: Record<string, string[]> = {};
  for (const [k, list] of Object.entries(v as Record<string, unknown>)) {
    if (Array.isArray(list)) out[k] = list.filter((x): x is string => typeof x === 'string');
  }
  return out;
}

export function loadPrefs(): Prefs {
  let r: Partial<Record<keyof Prefs, unknown>> = {};
  try {
    const parsed: unknown = JSON.parse(localStorage.getItem(PREFS_KEY) ?? '{}');
    if (parsed && typeof parsed === 'object') r = parsed as Partial<Record<keyof Prefs, unknown>>;
  } catch {
    r = {};
  }
  const d = DEFAULT_PREFS;
  return {
    language: isLang(r.language) ? r.language : d.language,
    autoShowHome: flag(r.autoShowHome, d.autoShowHome),
    homeOnLastClose: flag(r.homeOnLastClose, d.homeOnLastClose),
    restoreSession: flag(r.restoreSession, d.restoreSession),
    uiScale: whole(r.uiScale, 50, 300, d.uiScale),
    fontSize: whole(r.fontSize, 10, 16, d.fontSize),
    animations: flag(r.animations, d.animations),
    reduceMotion: flag(r.reduceMotion, d.reduceMotion),
    themeMode: r.themeMode === 'system' ? 'system' : 'fixed',
    themeLight: text(r.themeLight, d.themeLight),
    themeDark: text(r.themeDark, d.themeDark),
    noticeSeconds: whole(r.noticeSeconds, 0, 60, d.noticeSeconds),
    recentFileCount: whole(r.recentFileCount, 0, 100, d.recentFileCount),
    showCommandLine: flag(r.showCommandLine, d.showCommandLine),
    showDock: flag(r.showDock, d.showDock),
    dockWidth: whole(r.dockWidth, 240, 560, d.dockWidth),
    units: pick(r.units, DRAW_UNITS, d.units),
    precision: whole(r.precision, 0, 8, d.precision),
    angleUnit: pick(r.angleUnit, ANGLE_UNITS, d.angleUnit),
    animationMode: r.animationMode === 'on' || r.animationMode === 'off' ? r.animationMode : 'system',
    languageAuto: flag(r.languageAuto, d.languageAuto),
    historyLines: whole(r.historyLines, 0, 12, d.historyLines),
    systemCursor: flag(r.systemCursor, d.systemCursor),
    modelBackground: hex(r.modelBackground),
    layoutPaper: hex(r.layoutPaper),
    selectionColor: hex(r.selectionColor),
    saveFormat: r.saveFormat === 'dwg' ? 'dwg' : 'dxf',
    saveVersion: pick(r.saveVersion, SAVE_VERSIONS, d.saveVersion),
    snapMarkerSize: whole(r.snapMarkerSize, 5, 31, d.snapMarkerSize),
    timeRightClick: flag(r.timeRightClick, d.timeRightClick),
    shortcuts: cleanShortcuts(r.shortcuts),
  };
}

export function savePrefs(p: Prefs): void {
  try { localStorage.setItem(PREFS_KEY, JSON.stringify(p)); } catch { return; }
}

export function updatePrefs(patch: Partial<Prefs>): Prefs {
  const p = { ...loadPrefs(), ...patch };
  savePrefs(p);
  document.dispatchEvent(new CustomEvent('formcad:prefs-changed', { detail: { keys: Object.keys(patch) } }));
  return p;
}

export function applyLookPrefs(p: Prefs = loadPrefs()): void {
  const root = document.documentElement;
  document.body.style.zoom = p.uiScale === 100 ? '' : String(p.uiScale / 100);
  root.style.setProperty('--fs-12', `${p.fontSize}px`);
  const calm = p.animationMode === 'off' || (p.animationMode === 'system' && typeof matchMedia === 'function' && matchMedia('(prefers-reduced-motion: reduce)').matches);
  document.body.classList.toggle('animations-disabled', calm || !p.animations || p.reduceMotion);
  document.body.classList.toggle('show-system-cursor', p.systemCursor);
  applyCanvasPrefs(p);
}

const channel = (h: string, i: number): number => parseInt(h.slice(1 + i * 2, 3 + i * 2), 16);
const mixHex = (a: string, b: string, t: number): string => '#' + [0, 1, 2].map((i) => Math.round(channel(a, i) * (1 - t) + channel(b, i) * t).toString(16).padStart(2, '0')).join('');
const luminance = (h: string): number => (0.2126 * channel(h, 0) + 0.7152 * channel(h, 1) + 0.0722 * channel(h, 2)) / 255;

export function applyCanvasPrefs(p: Prefs = loadPrefs()): void {
  const root = document.documentElement.style;
  const bg = p.modelBackground;
  if (bg) {
    const light = luminance(bg) > 0.5, toward = light ? '#000000' : '#ffffff';
    root.setProperty('--canvas-bg-model', bg);
    root.setProperty('--canvas-grid', mixHex(bg, toward, 0.05));
    root.setProperty('--canvas-grid-major', mixHex(bg, toward, 0.11));
    root.setProperty('--canvas-crosshair', light ? '#202020' : '#e8e8e8');
  } else {
    for (const k of ['--canvas-bg-model', '--canvas-grid', '--canvas-grid-major', '--canvas-crosshair']) root.removeProperty(k);
  }
  if (p.layoutPaper) root.setProperty('--canvas-paper', p.layoutPaper); else root.removeProperty('--canvas-paper');
  if (p.selectionColor) root.setProperty('--canvas-selection', p.selectionColor); else root.removeProperty('--canvas-selection');
}
