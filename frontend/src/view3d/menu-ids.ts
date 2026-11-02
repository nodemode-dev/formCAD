import type { MenuItem } from '../ui/menu';

const SEP = '-' as const;

export const STD_VIEW_IDS: Array<[string, string]> = [
  ['front', 'Front'], ['back', 'Back'], ['left', 'Left'], ['right', 'Right'], ['top', 'Top'], ['bottom', 'Bottom'],
  ['iso', 'Isometric'], ['iso2', 'Isometric Back Right'], ['iso3', 'Isometric Back Left'], ['iso4', 'Isometric Front Left'],
];

export const PLANE_IDS: Array<[string, string]> = [
  ['top', 'Top'], ['bottom', 'Bottom'], ['front', 'Front'], ['back', 'Back'], ['right', 'Right'], ['left', 'Left'],
];

export const LEVEL_IDS: Array<[string, string]> = [
  ['any', 'Any'], ['body', 'Body'], ['face', 'Face'], ['edge', 'Edge'],
];

export const V3_MENU: MenuItem[] = [
  'v3-toggle', SEP,
  { label: 'Standard Views', items: STD_VIEW_IDS.map(([id]) => `v3-view-${id}`) },
  { label: 'Display Mode', items: ['wireframe', 'shaded', 'shadedEdges', 'hiddenLine', 'ghosted', 'xray', 'technical'].map((id) => `v3-mode-${id}`) },
  { label: 'Projection', items: ['v3-proj-persp', 'v3-proj-ortho'] },
  { label: 'Construction Plane', items: [...PLANE_IDS.map(([id]) => `v3-plane-${id}`), SEP, 'v3-plane-3pt', 'v3-plane-face', 'v3-plane-view', SEP, 'v3-grid', 'v3-section', 'v3-section-flip'] },
  { label: 'Pick Filter', items: LEVEL_IDS.map(([id]) => `v3-level-${id}`) },
  SEP, 'v3-extents', 'v3-zoom-sel', 'v3-home', 'v3-cube', 'v3-views',
  { label: 'Sheet Convention', items: ['v3-angle-third', 'v3-angle-first'] },
];
