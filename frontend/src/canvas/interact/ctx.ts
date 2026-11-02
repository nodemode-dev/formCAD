import type { CommandLineState } from '../../io/api';
import type { CanvasApi, Pt } from '../types';
import type { Settings } from './settings';

export interface Pointer { px: number; py: number; x: number; y: number }

export interface Ctx {
  canvas: CanvasApi;
  host: HTMLElement;
  doc(): string | null;
  set(): Settings;
  state(): CommandLineState;
  ptr(): Pointer | null;
  shift(): boolean;
  ctrl(): boolean;
  schedule(): void;
  toast(text: string): void;
  publish(doc: string, state: CommandLineState): void;
  hint(text: string): void;
  effective(): Pt | null;
}

export const IDLE_STATE: CommandLineState = { active: false, prompt: 'Command:', options: [], defaultValue: null, history: [], rev: 0, expect: 'none', base: null, preview: false };

export function pointLike(s: CommandLineState): boolean {
  return s.active && (s.expect === 'point' || s.expect === 'distance' || s.expect === 'angle');
}
