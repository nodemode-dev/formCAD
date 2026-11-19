import { parseCss, type Rgba } from './color';
import { isOled } from './ink';
import { MEDIA } from './media';

export interface Theme {
  bg: Rgba;
  grid: Rgba;
  gridMajor: Rgba;
  axisX: Rgba;
  axisY: Rgba;
  crosshair: Rgba;
  selWindow: Rgba;
  selCross: Rgba;
  snap: Rgba;
  handle: Rgba;
  paper: Rgba;
  paperEdge: Rgba;
  selection: Rgba;
  text: Rgba;
  panel: Rgba;
  line: Rgba;
  accent: Rgba;
  surround: Rgba;
}

const NAMES: Array<[keyof Theme, string, Rgba]> = [
  ['bg', '--canvas-bg-model', [33, 40, 48, 1]],
  ['grid', '--canvas-grid', [255, 255, 255, 0.07]],
  ['gridMajor', '--canvas-grid-major', [255, 255, 255, 0.16]],
  ['axisX', '--canvas-axis-x', [229, 72, 77, 1]],
  ['axisY', '--canvas-axis-y', [63, 185, 80, 1]],
  ['crosshair', '--canvas-crosshair', [255, 255, 255, 1]],
  ['selWindow', '--canvas-select-window', [59, 130, 246, 0.18]],
  ['selCross', '--canvas-select-cross', [63, 185, 80, 0.18]],
  ['snap', '--canvas-snap', [251, 191, 36, 1]],
  ['handle', '--canvas-handle', [59, 130, 246, 1]],
  ['paper', '--canvas-paper', [255, 255, 255, 1]],
  ['paperEdge', '--canvas-paper-edge', [0, 0, 0, 0.55]],
  ['selection', '--canvas-selection', [74, 143, 255, 1]],
  ['text', '--text-primary', [230, 230, 230, 1]],
  ['panel', '--surface-1', [30, 30, 34, 0.96]],
  ['line', '--line-1', [255, 255, 255, 0.18]],
  ['accent', '--accent-color', [249, 115, 22, 1]],
];

export function readTheme(host: HTMLElement, probe: HTMLElement): Theme {
  const cs = getComputedStyle(host);
  const out = {} as Theme;
  for (const [key, prop, fallback] of NAMES) {
    if (!cs.getPropertyValue(prop).trim()) {
      out[key] = fallback;
      continue;
    }
    probe.style.color = '';
    probe.style.color = `var(${prop})`;
    out[key] = parseCss(getComputedStyle(probe).color, fallback);
  }
  probe.style.color = '';
  const ink = out.text;
  out.grid = [ink[0], ink[1], ink[2], out.grid[3]];
  out.gridMajor = [ink[0], ink[1], ink[2], out.gridMajor[3]];
  out.surround = isOled() ? out.bg : MEDIA.sheetSurround;
  return out;
}
