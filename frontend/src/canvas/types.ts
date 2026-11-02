export type Pt = [number, number];
export type Rect = [number, number, number, number];
export type Handle = string | number;
export type Rgb = [number, number, number];

export interface LineType { name: string; pattern: number[]; scale: number }

export type Geom =
  | { type: 'line'; p1: Pt; p2: Pt }
  | { type: 'xline' | 'ray'; p: Pt; dir: Pt }
  | { type: 'circle'; c: Pt; r: number }
  | { type: 'arc'; c: Pt; r: number; a0: number; a1: number }
  | { type: 'ellipse'; c: Pt; major: Pt; ratio: number; a0: number; a1: number }
  | { type: 'poly'; verts: number[][]; closed: boolean; elev?: number }
  | { type: 'spline'; degree: number; knots: number[]; ctrl: number[][]; weights?: number[] | null; fit?: number[][] | null; closed?: boolean }
  | { type: 'point'; p: Pt; mode: number; size: number }
  | { type: 'text'; insert: Pt; height: number; rot: number; box: number[][] }
  | { type: 'compound'; parts: Geom[] };

export type Prim =
  | { t: 'pl'; pts: number[]; closed?: boolean }
  | { t: 'tri'; pts: number[] }
  | { t: 'fill'; rings: number[][] };

export interface Grip { id: string | number; p: Pt; kind?: string }

export interface DisplayItem {
  h: Handle | null;
  kind: string;
  layer: string;
  color: Rgb;
  color7?: boolean;
  lw: number;
  lt: LineType | null;
  tr: number;
  plot?: boolean;
  order: number;
  geom: Geom | null;
  prims?: Prim[];
  grips?: Grip[];
  bounds: Rect;
}

export interface LayerState { color?: Rgb | string; on?: boolean; frozen?: boolean; locked?: boolean; lw?: number; lt?: string }

export interface DisplayPayload {
  rev: number;
  full: boolean;
  space?: string;
  removed: Handle[];
  items: DisplayItem[];
  layers?: Record<string, LayerState>;
  extents?: Rect | null;
  sheet?: Rect | null;
  printable?: Rect | null;
}

export interface ViewState {
  cx: number;
  cy: number;
  height: number;
  scale: number;
  width: number;
  heightPx: number;
}

export interface Hit { handle: Handle; dist: number; order: number }

export interface GripMark { p: Pt; state?: 'cold' | 'warm' | 'hot'; kind?: string; dyn?: boolean }
export interface SnapMark { p: Pt; mode: string; label?: string }
export interface TrackMark { type: 'path' | 'cross' | 'acquired' | 'tip'; p?: Pt; q?: Pt; text?: string; parallel?: boolean }
export interface BoxMark { x0: number; y0: number; x1: number; y1: number; crossing?: boolean }
export interface HighlightMark { handles: Handle[]; kind: 'selected' | 'hover' }

export type OverlayName = 'jig' | 'grips' | 'snap-marker' | 'tracking' | 'selection-box' | 'highlight';
export type OverlayItems = DisplayItem[] | GripMark[] | SnapMark[] | TrackMark[] | BoxMark[] | HighlightMark[];

export interface PointerInfo {
  x: number;
  y: number;
  px: number;
  py: number;
  button: number;
  shift: boolean;
  ctrl: boolean;
  alt: boolean;
}

export interface DragInfo extends PointerInfo {
  phase: 'start' | 'move' | 'end';
  x0: number;
  y0: number;
  px0: number;
  py0: number;
}

export interface CanvasEvents {
  cursor: { x: number; y: number } | null;
  view: ViewState;
  click: PointerInfo;
  drag: DragInfo;
  dblclick: PointerInfo;
  display: number;
}

export interface DocEventInfo {
  id: string;
  rev: number;
  reason?: string;
  view?: { mode?: string; center?: number[]; height?: number; [key: string]: unknown };
}

export type CursorMode = 'point' | 'pick' | 'none';

export interface CanvasDeps {
  fetchDisplay(docId: string, since: number | undefined, space: string | undefined): Promise<DisplayPayload>;
  sysvar(name: string, fallback: number): number;
  sysvarVec(name: string): number[] | null;
  onSysvar(fn: (name: string) => void): () => void;
  markerSize(): number;
  systemCursor(): boolean;
  notify(text: string): void;
  store(key: string, value: string): void;
  stored(key: string): string | null;
}

export interface CanvasApi {
  readonly view: ViewState;
  readonly renderer: 'webgl2' | 'canvas2d';
  setDocument(docId: string | null): void;
  applyDocEvent(e: DocEventInfo): void;
  setSpace(space: string): void;
  refresh(): void;
  pickAt(px: number, py: number, aperturePx?: number): Hit[];
  boxQuery(rect: Rect, crossing: boolean): Handle[];
  itemsIn(rect: Rect): DisplayItem[];
  item(h: Handle): DisplayItem | undefined;
  setEffectivePoint(p: Pt | null): void;
  worldFromScreen(px: number, py: number): Pt;
  screenFromWorld(x: number, y: number): Pt;
  setOverlay(name: OverlayName, items: OverlayItems | null): void;
  setCursorMode(mode: CursorMode | null): void;
  setView(cx: number, cy: number, height: number): void;
  zoomExtents(): void;
  zoomWindow(rect: Rect): void;
  panBy(dx: number, dy: number): void;
  setViewCubeVisible(on: boolean): void;
  setUcsIconVisible(on: boolean): void;
  stats(): { items: number; chunks: number; builds: number; frames: number };
  on<K extends keyof CanvasEvents>(event: K, fn: (e: CanvasEvents[K]) => void): () => void;
}
