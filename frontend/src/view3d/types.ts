export type Vec3 = [number, number, number];

export type DisplayMode = 'wireframe' | 'shaded' | 'shadedEdges' | 'hiddenLine' | 'ghosted' | 'xray' | 'technical';
export type Projection = 'perspective' | 'parallel';
export type PickLevel = 'any' | 'body' | 'face' | 'edge';
export type SnapKind = 'vertex' | 'midpoint' | 'center' | 'other';
export type AngleConvention = 'third' | 'first';

export interface EdgeSet {
  positions: Float32Array;
  segEdge: Uint32Array;
}

export interface BodyData {
  id: number;
  name: string;
  color: number;
  positions: Float32Array;
  normals: Float32Array;
  indices: Uint32Array;
  triFace: Uint32Array;
  edges: EdgeSet;
  snaps: SnapPoint[];
  component?: string;
  instance?: string;
}

export interface SnapPoint {
  kind: SnapKind;
  p: Vec3;
  body: number;
  ref: number;
}

export interface SceneModel {
  rev: number;
  bodies: BodyData[];
  snaps: SnapPoint[];
}

export interface FaceRef { body: number; face: number }
export interface EdgeRef { body: number; edge: number }

export interface SelectionState {
  bodies: number[];
  faces: FaceRef[];
  edges: EdgeRef[];
}

export type PickHit =
  | { kind: 'edge'; body: number; edge: number; point: Vec3 }
  | { kind: 'face'; body: number; face: number; point: Vec3; normal: Vec3; distance: number }
  | { kind: 'body'; body: number; point: Vec3; normal: Vec3; distance: number };

export interface SnapHit {
  kind: SnapKind;
  label: string;
  p: Vec3;
  sx: number;
  sy: number;
  body: number;
  ref: number;
}

export interface ConstructionPlane {
  name: string;
  origin: Vec3;
  x: Vec3;
  y: Vec3;
  z: Vec3;
}

export interface CameraSpec {
  position: Vec3;
  target: Vec3;
  up: Vec3;
  projection: Projection;
  fov: number;
  height: number;
}

export type PlaneSpec = { world: string } | { points: Vec3[] } | { face: { point: Vec3; normal: Vec3 } };

export interface GridLines {
  step: number;
  extent: number;
  center: [number, number];
  major: number;
  snapped?: Vec3;
}

export interface GridAsk {
  plane: ConstructionPlane;
  target: Vec3;
  visible: number;
  radius: number;
  point?: Vec3;
  step?: number;
}

export interface ViewListener {
  askPlane?: (spec: PlaneSpec) => Promise<ConstructionPlane>;
  askGrid?: (ask: GridAsk) => Promise<GridLines>;
  onMode?: (mode: DisplayMode) => void;
  onProjection?: (p: Projection) => void;
  onSelection?: (s: SelectionState) => void;
  onHover?: (text: string) => void;
  onCursor?: (p: Vec3 | null) => void;
  onPlane?: (p: ConstructionPlane, gridOn: boolean) => void;
  onLevel?: (l: PickLevel) => void;
  onHint?: (text: string) => void;
  onPoint?: (p: Vec3, snap: SnapHit | null) => void;
}

export const MODE_LABELS: Record<DisplayMode, string> = {
  wireframe: 'Wireframe',
  shaded: 'Shaded',
  shadedEdges: 'Shaded with edges',
  hiddenLine: 'Hidden line',
  ghosted: 'Ghosted',
  xray: 'X-ray',
  technical: 'Technical',
};

export const MODE_ORDER: DisplayMode[] = ['wireframe', 'shaded', 'shadedEdges', 'hiddenLine', 'ghosted', 'xray', 'technical'];
