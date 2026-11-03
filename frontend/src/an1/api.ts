import type { CameraSpec } from '../view3d/types';
import { docUrl, req } from '../u8/net';

export type StyleId = 'shaded' | 'outline' | 'white_fill' | 'flat_colour' | 'hidden_dashed';
export type EaseId = 'linear' | 'ease' | 'ease_in' | 'ease_out' | 'hold';

export interface CameraKey { at: number; camera: CameraSpec }
export interface Shot {
  id: number;
  name: string;
  duration: number;
  ease: EaseId;
  explode?: { view: string; from?: number; to?: number };
  drive?: { mate: string; from?: number; to: number };
  camera?: { keys: CameraKey[]; orbit?: number };
  loop?: boolean;
  style?: StyleId;
}
export interface Span { id: number; name: string; first: number; frames: number }
export interface Plan { frames: number; seconds: number; fps: number; spans: Span[] }
export interface Board {
  name: string;
  fps: number;
  width: number;
  height: number;
  style: StyleId;
  source: SourceId;
  samples: number;
  shots: Shot[];
  plan: Plan;
}
export type SourceId = 'viewport' | 'raster' | 'path';
export interface Limits { shots: number; keys: number; boards: number; seconds: number; frames: number; fps: number; width: number; height: number; samples: number; sample_frames: number }
export interface BoardList { boards: Record<string, Board>; limits: Limits; styles: StyleId[]; easings: EaseId[] }

export interface FrameRow {
  i: number;
  shot: number;
  u: number;
  camera: CameraSpec | null;
  style: StyleId | null;
  matrices: Record<string, number[]>;
  explode?: { view: string; t: number };
  drive?: { mate: string; value: number };
}
export interface FrameChunk { name: string; first: number; count: number; total: number; fps: number; frames: FrameRow[]; drive_ms: number }

export const STYLE_LABELS: ReadonlyArray<readonly [StyleId, string]> = [
  ['shaded', 'Shaded'],
  ['outline', 'Shaded with outline'],
  ['white_fill', 'White fill with lines'],
  ['flat_colour', 'Flat colour with lines'],
  ['hidden_dashed', 'Lines with dashed hidden edges'],
];

export const SOURCE_LABELS: ReadonlyArray<readonly [SourceId, string]> = [
  ['viewport', 'Viewport styles'],
  ['raster', 'Render materials, one pass'],
  ['path', 'Path traced'],
];

export const EASE_LABELS: ReadonlyArray<readonly [EaseId, string]> = [
  ['ease', 'Ease in and out'],
  ['linear', 'Linear'],
  ['ease_in', 'Ease in'],
  ['ease_out', 'Ease out'],
  ['hold', 'Hold, then jump'],
];

export const boardApi = {
  list: (id: string) => req<BoardList>('GET', docUrl(id, 'storyboards')),
  create: (id: string, body: Partial<Board>) => req<Board>('POST', docUrl(id, 'storyboards'), body),
  seed: (id: string, body: Record<string, unknown>) => req<Board>('POST', docUrl(id, 'storyboards/from-explode'), body),
  put: (id: string, name: string, body: Partial<Board>) => req<Board>('PUT', docUrl(id, `storyboards/${encodeURIComponent(name)}`), body),
  del: (id: string, name: string) => req<{ deleted: string }>('DELETE', docUrl(id, `storyboards/${encodeURIComponent(name)}`)),
  frames: (id: string, name: string, first: number, count: number, signal?: AbortSignal) =>
    req<FrameChunk>('GET', docUrl(id, `storyboards/${encodeURIComponent(name)}/frames?first=${first}&count=${count}`), undefined, signal),
};
