import { describe, expect, it } from 'vitest';
import { Camera } from '../../src/canvas/camera';

describe('the 2D camera', () => {
  it('maps a screen point to the world and back to the same pixel', () => {
    const cam = new Camera();
    cam.setSize(800, 600);
    cam.set(100, 50, 300);
    const [wx, wy] = cam.toWorld(200, 150);
    expect(wx).toBeCloseTo(100 + (200 - 400) / 2, 9);
    expect(wy).toBeCloseTo(50 - (150 - 300) / 2, 9);
    const [px, py] = cam.toScreen(wx, wy);
    expect(px).toBeCloseTo(200, 9);
    expect(py).toBeCloseTo(150, 9);
  });

  it('keeps the world point under the pointer fixed while zooming', () => {
    const cam = new Camera();
    cam.setSize(800, 600);
    cam.set(0, 0, 300);
    const before = cam.toWorld(650, 120);
    cam.zoomAt(2, 650, 120);
    const after = cam.toWorld(650, 120);
    expect(cam.height).toBeCloseTo(150, 9);
    expect(after[0]).toBeCloseTo(before[0], 9);
    expect(after[1]).toBeCloseTo(before[1], 9);
  });

  it('fits a rectangle so that all of it is visible and centred', () => {
    const cam = new Camera();
    cam.setSize(800, 400);
    cam.fit([10, 20, 410, 70]);
    const [x0, y0, x1, y1] = cam.visible();
    expect(x0).toBeLessThanOrEqual(10);
    expect(y0).toBeLessThanOrEqual(20);
    expect(x1).toBeGreaterThanOrEqual(410);
    expect(y1).toBeGreaterThanOrEqual(70);
    expect(cam.cx).toBeCloseTo(210, 9);
    expect(cam.cy).toBeCloseTo(45, 9);
  });

  it('refuses a view that is not a finite positive height', () => {
    const cam = new Camera();
    cam.set(5, 6, 100);
    expect(cam.set(Number.NaN, 0, 100)).toBe(false);
    expect(cam.set(0, 0, 0)).toBe(false);
    expect([cam.cx, cam.cy, cam.height]).toEqual([5, 6, 100]);
  });
});
