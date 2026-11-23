import { beforeEach, describe, expect, it } from 'vitest';
import { RTree } from '../../src/canvas/spatial';
import type { Rect } from '../../src/canvas/types';
import { circle, drawingCanvas, item, line, segDist, seeded, show, type TestCanvas } from './support';

const SCALE = 2;
const AP = 5;
let cv: TestCanvas;

const px = (x: number, y: number): [number, number] => [400 + x * SCALE, 300 - y * SCALE];
const handlesAt = (x: number, y: number, ap = AP): Array<string | number> => cv.pickAt(...px(x, y), ap).map((h) => h.handle);

beforeEach(async () => {
  cv = await drawingCanvas(800, 600);
  cv.setView(0, 0, 600 / SCALE);
});

describe('clicking on the 2D canvas', () => {
  it('selects a line when the click is within the pick tolerance in pixels and not when it is outside', () => {
    show(cv, [line('L', -50, 10, 50, 10)]);
    expect(handlesAt(0, 10 + 4 / SCALE)).toEqual(['L']);
    expect(handlesAt(0, 10 - 4.9 / SCALE)).toEqual(['L']);
    expect(handlesAt(0, 10 + 5.2 / SCALE)).toEqual([]);
    expect(handlesAt(50 + 6 / SCALE, 10)).toEqual([]);
  });

  it('reports the distance from the click to the line in world units', () => {
    show(cv, [line('L', 0, 0, 30, 40)]);
    const [hit] = cv.pickAt(...px(15 + 0.8, 20 - 0.6), AP);
    expect(hit.handle).toBe('L');
    expect(hit.dist).toBeCloseTo(1, 6);
  });

  it('selects a circle near its outline but not at its centre', () => {
    show(cv, [circle('C', 10, 5, 20)]);
    const a = Math.PI / 5;
    expect(handlesAt(10 + (20 + 2 / SCALE) * Math.cos(a), 5 + (20 + 2 / SCALE) * Math.sin(a))).toEqual(['C']);
    expect(handlesAt(10 + (20 - 3 / SCALE) * Math.cos(-a), 5 + (20 - 3 / SCALE) * Math.sin(-a))).toEqual(['C']);
    expect(handlesAt(10, 5)).toEqual([]);
    expect(handlesAt(10 + 20 + 8 / SCALE, 5)).toEqual([]);
  });

  it('selects an arc on its sweep and not on the part of the circle the arc does not cover', () => {
    show(cv, [item('A', { type: 'arc', c: [0, 0], r: 30, a0: 0, a1: Math.PI / 2 }, [0, 0, 30, 30])]);
    const on = Math.PI / 4;
    expect(handlesAt(30 * Math.cos(on), 30 * Math.sin(on))).toEqual(['A']);
    expect(handlesAt(-30, 0)).toEqual([]);
    expect(handlesAt(0, -30)).toEqual([]);
  });

  it('selects a polyline on its bulged segment at the arc apex and not at the chord between its ends', () => {
    show(cv, [item('P', { type: 'poly', verts: [[0, 0, 1], [20, 0, 0], [20, 20, 0]], closed: false }, [0, -10, 20, 20])]);
    expect(handlesAt(10, -10)).toEqual(['P']);
    expect(handlesAt(10, 0)).toEqual([]);
    expect(handlesAt(20, 10)).toEqual(['P']);
  });

  it('lists the nearer of two overlapping candidates first', () => {
    show(cv, [line('far', -20, 0, 20, 0), line('near', -20, 2 / SCALE, 20, 2 / SCALE)]);
    const hits = cv.pickAt(...px(0, 1.6 / SCALE), AP);
    expect(hits.map((h) => h.handle)).toEqual(['near', 'far']);
  });

  it('does not select an entity on a layer that is turned off', () => {
    show(cv, [line('shown', -20, 0, 20, 0), line('hidden', -20, 0, 20, 0, 'Off')], { Off: { on: false } });
    expect(handlesAt(0, 0)).toEqual(['shown']);
  });

  it('agrees with a brute force segment distance check over many random lines', () => {
    const rnd = seeded(12);
    const items = [];
    const segs: Array<[string, number, number, number, number]> = [];
    for (let i = 0; i < 300; i++) {
      const x0 = rnd() * 360 - 180, y0 = rnd() * 260 - 130;
      const x1 = x0 + rnd() * 60 - 30, y1 = y0 + rnd() * 60 - 30;
      segs.push([`s${i}`, x0, y0, x1, y1]);
      items.push(line(`s${i}`, x0, y0, x1, y1));
    }
    show(cv, items);
    const apWorld = AP / SCALE;
    for (let k = 0; k < 60; k++) {
      const x = rnd() * 360 - 180, y = rnd() * 260 - 130;
      const want = segs.filter(([, a, b, c, d]) => segDist(x, y, a, b, c, d) <= apWorld - 1e-9).map(([h]) => h).sort();
      const edge = segs.filter(([, a, b, c, d]) => Math.abs(segDist(x, y, a, b, c, d) - apWorld) < 1e-6);
      if (edge.length) continue;
      expect(handlesAt(x, y).map(String).sort()).toEqual(want);
    }
  });
});

describe('window and crossing selection', () => {
  const scene = (): void => show(cv, [
    line('inside', 10, 10, 30, 20),
    line('through', 20, 15, 80, 15),
    line('outside', 100, 100, 120, 120),
    line('diagonal', 0, 50, 50, 0),
    circle('ring', 30, 24, 5),
  ]);

  it('a window takes only entities that lie wholly inside it', () => {
    scene();
    expect(cv.boxQuery([5, 5, 40, 40], false).sort()).toEqual(['inside', 'ring']);
  });

  it('a crossing box also takes entities that it touches', () => {
    scene();
    expect(cv.boxQuery([5, 5, 40, 40], true).sort()).toEqual(['diagonal', 'inside', 'ring', 'through']);
  });

  it('a crossing box does not take an entity whose bounds overlap the box but whose path misses it', () => {
    scene();
    expect(cv.boxQuery([1, 1, 4, 4], true)).toEqual([]);
    expect(cv.boxQuery([30, 30, 50, 50], true)).toEqual([]);
  });

  it('a box gives the same answer whichever corner it was dragged from', () => {
    scene();
    expect(cv.boxQuery([40, 40, 5, 5], false).sort()).toEqual(['inside', 'ring']);
  });
});

describe('the spatial index', () => {
  it('returns exactly the boxes a brute force overlap test finds, for random boxes', () => {
    const rnd = seeded(7);
    const boxes: Rect[] = [];
    for (let i = 0; i < 2500; i++) {
      const x = rnd() * 1000, y = rnd() * 1000, w = rnd() ** 3 * 200, h = rnd() ** 3 * 200;
      boxes.push([x, y, x + w, y + h]);
    }
    const tree = RTree.build(boxes);
    for (let k = 0; k < 200; k++) {
      const x = rnd() * 1100 - 50, y = rnd() * 1100 - 50, w = rnd() * 150, h = rnd() * 150;
      const got: number[] = [];
      tree.query(x, y, x + w, y + h, (id) => got.push(id));
      const want = boxes.map((b, i) => (b[0] <= x + w && b[2] >= x && b[1] <= y + h && b[3] >= y ? i : -1)).filter((i) => i >= 0);
      expect(got.sort((a, b) => a - b)).toEqual(want);
    }
  });

  it('finds nothing in an empty index and each box once in a full query', () => {
    const none: number[] = [];
    RTree.build([]).query(-1e9, -1e9, 1e9, 1e9, (id) => none.push(id));
    expect(none).toEqual([]);
    const boxes: Rect[] = Array.from({ length: 300 }, (_, i) => [i, i, i + 1, i + 1]);
    const all: number[] = [];
    RTree.build(boxes).query(-1, -1, 1000, 1000, (id) => all.push(id));
    expect(all.sort((a, b) => a - b)).toEqual(boxes.map((_, i) => i));
  });
});
