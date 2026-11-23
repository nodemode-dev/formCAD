import { describe, expect, it } from 'vitest';
import { css, parseCss } from '../../src/canvas/color';
import { dashRun, patternLength } from '../../src/canvas/dash';
import { arcPoints, bulgePoints, polyPoints } from '../../src/canvas/tess';
import { aciHex } from '../../src/ui/panels/pref-rows';

const pairs = (a: number[]): Array<[number, number]> => {
  const out: Array<[number, number]> = [];
  for (let i = 0; i < a.length; i += 2) out.push([a[i], a[i + 1]]);
  return out;
};

const runLength = (pts: number[]): number => {
  let s = 0;
  for (let i = 2; i < pts.length; i += 2) s += Math.hypot(pts[i] - pts[i - 2], pts[i + 1] - pts[i - 1]);
  return s;
};

describe('tessellation', () => {
  it.each([
    [50, 0, Math.PI * 2, 0.01],
    [3, 0.4, 2.2, 0.001],
    [1000, -1, 0.5, 0.05],
    [0.2, 1, 5, 0.02],
  ])('an arc of radius %d tessellated to a chord tolerance stays within it of the true arc', (r, a0, sweep, tol) => {
    const out: number[] = [];
    arcPoints(7, -3, r, a0, sweep, tol, out);
    const pts = pairs(out);
    expect(pts.length).toBeGreaterThanOrEqual(2);
    for (const [x, y] of pts) expect(Math.hypot(x - 7, y + 3)).toBeCloseTo(r, 9);
    expect(Math.atan2(pts[0][1] + 3, pts[0][0] - 7)).toBeCloseTo(Math.atan2(Math.sin(a0), Math.cos(a0)), 9);
    const end = a0 + sweep;
    const last = pts[pts.length - 1];
    expect(last[0]).toBeCloseTo(7 + r * Math.cos(end), 9);
    expect(last[1]).toBeCloseTo(-3 + r * Math.sin(end), 9);
    for (let i = 1; i < pts.length; i++) {
      const mx = (pts[i][0] + pts[i - 1][0]) / 2, my = (pts[i][1] + pts[i - 1][1]) / 2;
      expect(r - Math.hypot(mx - 7, my + 3)).toBeLessThanOrEqual(tol + 1e-12);
    }
    const chordSag = r * (1 - Math.cos(sweep / (pts.length - 1) / 2));
    const fewer = r * (1 - Math.cos(sweep / (pts.length - 2) / 2));
    expect(chordSag).toBeLessThanOrEqual(tol + 1e-12);
    if (pts.length > 2) expect(fewer).toBeGreaterThan(tol * 0.5);
  });

  it.each([
    [1, Math.PI],
    [0.5, 4 * Math.atan(0.5)],
    [-0.25, 4 * Math.atan(0.25)],
    [2.5, 4 * Math.atan(2.5)],
  ])('a polyline segment with bulge %d becomes an arc with the closed form centre and radius', (bulge, theta) => {
    const [x0, y0, x1, y1] = [2, 1, 14, 6];
    const chord = Math.hypot(x1 - x0, y1 - y0);
    const r = chord / (2 * Math.sin(theta / 2));
    const sagitta = (Math.abs(bulge) * chord) / 2;
    const ux = (x1 - x0) / chord, uy = (y1 - y0) / chord;
    const nx = -uy, ny = ux;
    const off = (r - sagitta) * (bulge > 0 ? 1 : -1);
    const cx = (x0 + x1) / 2 + nx * off, cy = (y0 + y1) / 2 + ny * off;
    const out: number[] = [x0, y0];
    bulgePoints(x0, y0, x1, y1, bulge, 1e-4, out);
    const pts = pairs(out);
    for (const [x, y] of pts) expect(Math.hypot(x - cx, y - cy)).toBeCloseTo(r, 7);
    expect(pts[pts.length - 1]).toEqual([x1, y1]);
    let far = 0;
    for (const [x, y] of pts) {
      const side = (x - x0) * nx + (y - y0) * ny;
      expect(side * Math.sign(bulge)).toBeLessThanOrEqual(1e-9);
      far = Math.max(far, Math.abs(side));
    }
    expect(far).toBeCloseTo(sagitta, 3);
  });

  it('a closed polyline returns to its first vertex', () => {
    const out: number[] = [];
    polyPoints([[0, 0], [10, 0, 0.3], [10, 10], [0, 10]], true, 0.01, out);
    expect(out.slice(-2)).toEqual([0, 0]);
    expect(out.slice(0, 2)).toEqual([0, 0]);
  });
});

describe('dash patterns', () => {
  it('a dash and gap pattern on a straight line gives dashes of the stated length at the stated spacing', () => {
    const pieces: number[][] = [];
    dashRun([0, 0, 40, 0], false, [5, -3], 1, (p) => pieces.push([...p]), () => undefined);
    expect(pieces.map((p) => [p[0], p[p.length - 2]])).toEqual([[0, 5], [8, 13], [16, 21], [24, 29], [32, 37]]);
  });

  it('a dash runs on around a corner and the drawn length matches the pattern', () => {
    const pieces: number[][] = [];
    dashRun([0, 0, 6, 0, 6, 6], false, [5, -3], 1, (p) => pieces.push([...p]), () => undefined);
    expect(pieces.length).toBe(2);
    expect(pieces[0]).toEqual([0, 0, 5, 0]);
    expect(pieces[1][0]).toBeCloseTo(6, 12);
    expect(pieces[1][1]).toBeCloseTo(2, 12);
    expect(runLength(pieces[1])).toBeCloseTo(4, 12);
  });

  it('the linetype scale stretches every dash and gap', () => {
    const pieces: number[][] = [];
    dashRun([0, 0, 0, 30], false, [2, -1], 2.5, (p) => pieces.push([...p]), () => undefined);
    expect(patternLength([2, -1], 2.5)).toBeCloseTo(7.5, 12);
    expect(pieces.map((p) => [p[1], p[p.length - 1]])).toEqual([[0, 5], [7.5, 12.5], [15, 20], [22.5, 27.5]]);
  });

  it('a zero length element draws a dot at each repeat', () => {
    const dots: Array<[number, number]> = [];
    dashRun([0, 0, 10, 0], false, [0, -2], 1, () => undefined, (x, y) => dots.push([x, y]));
    expect(dots.map(([x]) => x)).toEqual([0, 2, 4, 6, 8, 10]);
  });

  it('the drawn length of a long dash pattern is the on fraction of the path', () => {
    let drawn = 0;
    dashRun([0, 0, 300, 400], false, [6, -2, 1, -1], 1, (p) => { drawn += runLength(p); }, () => undefined);
    expect(drawn).toBeCloseTo((500 / 10) * 7, 9);
  });
});

describe('colours', () => {
  it.each([
    ['#ff8000', [255, 128, 0, 1]],
    ['#F80', [255, 136, 0, 1]],
    ['#11223380', [17, 34, 51, 128 / 255]],
    ['rgb(10, 20, 30)', [10, 20, 30, 1]],
    ['rgba(10 20 30 / 0.5)', [10, 20, 30, 0.5]],
    ['color(srgb 1 0.5 0)', [255, 127.5, 0, 1]],
  ])('reads %s as the right red, green, blue and alpha', (text, want) => {
    const got = parseCss(text);
    want.forEach((w, i) => expect(got[i]).toBeCloseTo(w, 9));
  });

  it('writes a colour that reads back to the same values', () => {
    for (const c of [[0, 0, 0, 1], [255, 255, 255, 0.25], [12, 200, 99, 0.5]] as Array<[number, number, number, number]>) {
      expect(parseCss(css(c))).toEqual(c);
    }
  });

  it('falls back for text that is not a colour', () => {
    expect(parseCss('#12', [1, 2, 3, 1])).toEqual([1, 2, 3, 1]);
    expect(parseCss('banana', [9, 9, 9, 1])).toEqual([9, 9, 9, 1]);
  });

  it.each([
    [1, '#ff0000'], [2, '#ffff00'], [3, '#00ff00'], [4, '#00ffff'], [5, '#0000ff'], [6, '#ff00ff'], [7, '#ffffff'],
    [8, '#808080'], [9, '#c0c0c0'], [10, '#ff0000'], [250, '#333333'], [255, '#ffffff'],
  ])('colour index %d is %s', (n, hex) => {
    expect(aciHex(n)).toBe(hex);
  });
});
