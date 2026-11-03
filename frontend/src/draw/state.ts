export interface PaletteState {
  sourceDoc: string;
  component: string;
  scale: string;
  mode: 'exact' | 'draft' | 'auto';
}

export const palette: PaletteState = { sourceDoc: '', component: '', scale: '1:1', mode: 'auto' };

export const STANDARD_VIEWS: ReadonlyArray<{ id: string; label: string; vnormal?: number[]; vup?: number[] }> = [
  { id: 'front', label: 'Front' },
  { id: 'back', label: 'Back' },
  { id: 'left', label: 'Left' },
  { id: 'right', label: 'Right' },
  { id: 'top', label: 'Top' },
  { id: 'bottom', label: 'Bottom' },
  { id: 'iso', label: 'Isometric' },
  { id: 'iso2', label: 'Iso, left front', vnormal: [-1, -1, 1], vup: [0, 0, 1] },
  { id: 'iso3', label: 'Iso, right back', vnormal: [1, 1, 1], vup: [0, 0, 1] },
  { id: 'iso4', label: 'Iso, left back', vnormal: [-1, 1, 1], vup: [0, 0, 1] },
];

export const SCALES = ['10:1', '5:1', '2:1', '1:1', '1:2', '1:5', '1:10', '1:20', '1:50', '1:100'];
