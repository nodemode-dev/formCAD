import * as THREE from 'three';
import { describe, expect, it } from 'vitest';
import { Camera } from '../../src/canvas/camera';
import { rayHit } from '../../src/view3d/planes';
import { Rig } from '../../src/view3d/rig';

function rig(w: number, h: number): Rig {
  const host = document.createElement('div');
  document.body.append(host);
  const r = new Rig(host);
  r.size(w, h);
  return r;
}

const v = (a: number[]): THREE.Vector3 => new THREE.Vector3(a[0], a[1], a[2]);

describe('2D view', () => {
  it('panning by pixels moves the world under the pointer by the same pixels', () => {
    const cam = new Camera();
    cam.setSize(1000, 500);
    cam.set(12, -7, 250);
    const world = cam.toWorld(310, 140);
    cam.panBy(55, -20);
    const [sx, sy] = cam.toScreen(world[0], world[1]);
    expect(sx).toBeCloseTo(310 + 55, 9);
    expect(sy).toBeCloseTo(140 - 20, 9);
    expect(cam.cx).toBeCloseTo(12 - 55 / 2, 9);
    expect(cam.cy).toBeCloseTo(-7 - 20 / 2, 9);
    expect(cam.height).toBe(250);
  });

  it('zooming in and then out by the same factor about one pixel returns the same view', () => {
    const cam = new Camera();
    cam.setSize(800, 600);
    cam.set(3, 4, 120);
    cam.zoomAt(1.7, 123, 456);
    cam.zoomAt(1 / 1.7, 123, 456);
    expect(cam.cx).toBeCloseTo(3, 9);
    expect(cam.cy).toBeCloseTo(4, 9);
    expect(cam.height).toBeCloseTo(120, 9);
  });

  it('fitting a tall rectangle in a wide window keeps the full height in view', () => {
    const cam = new Camera();
    cam.setSize(900, 300);
    cam.fit([0, 0, 10, 200]);
    const [x0, y0, x1, y1] = cam.visible();
    expect(y0).toBeLessThanOrEqual(0);
    expect(y1).toBeGreaterThanOrEqual(200);
    expect(x0).toBeLessThanOrEqual(0);
    expect(x1).toBeGreaterThanOrEqual(10);
    expect(cam.height).toBeLessThan(200 * 1.2);
  });
});

describe('3D view', () => {
  it('orbiting to a new direction keeps the target fixed and the distance constant', () => {
    const r = rig(800, 600);
    r.setBounds([0, 0, 0], 50);
    r.moveTo(v([1, -1, 1]), v([10, 20, 5]), 120, false);
    const before = r.camera.position.distanceTo(r.target);
    for (const dir of [[0, -1, 0], [1, 2, 3], [-1, 0.2, -0.5], [0, 0.0001, 1]]) {
      r.lookFrom(dir as [number, number, number], false);
      expect(r.target.x).toBeCloseTo(10, 9);
      expect(r.target.y).toBeCloseTo(20, 9);
      expect(r.target.z).toBeCloseTo(5, 9);
      expect(r.camera.position.distanceTo(r.target)).toBeCloseTo(before, 6);
      const want = v(dir).normalize();
      expect(r.direction().angleTo(want)).toBeLessThan(1e-6);
    }
  });

  it('a pick ray through the screen centre points along the view direction and passes through the target', () => {
    for (const projection of ['perspective', 'parallel'] as const) {
      const r = rig(640, 480);
      r.setBounds([0, 0, 0], 40);
      r.setProjection(projection);
      r.moveTo(v([2, -3, 1]), v([5, -2, 7]), 90, false);
      const ray = r.ndcToRay(0, 0);
      const look = r.target.clone().sub(r.camera.position).normalize();
      expect(ray.direction.angleTo(look)).toBeLessThan(1e-6);
      expect(ray.distanceToPoint(r.target)).toBeLessThan(1e-6);
    }
  });

  it('a pick ray off centre goes through the world point that projects to that screen position', () => {
    const r = rig(800, 450);
    r.setBounds([0, 0, 0], 40);
    r.moveTo(v([1, -2, 1.5]), v([0, 0, 0]), 80, false);
    const p = v([12, -5, 9]);
    const ndc = p.clone().project(r.camera);
    const ray = r.ndcToRay(ndc.x, ndc.y);
    expect(ray.distanceToPoint(p)).toBeLessThan(1e-6);
  });

  it.each([
    ['perspective', [1, -1, 1], 800, 600],
    ['perspective', [0, -1, 0], 400, 900],
    ['parallel', [-2, 1, 3], 1200, 500],
    ['parallel', [0, 0, 1], 600, 600],
  ] as const)('fitting a box in %s view from %j puts all eight corners inside the view', (projection, dir, w, h) => {
    const r = rig(w, h);
    const min: [number, number, number] = [-40, 10, -5];
    const max: [number, number, number] = [60, 35, 80];
    const centre: [number, number, number] = [10, 22.5, 37.5];
    r.setBounds(centre, Math.hypot(50, 12.5, 42.5));
    r.setProjection(projection);
    r.fitBox(min, max, false, v([...dir]));
    r.camera.updateMatrixWorld();
    let widest = 0;
    for (let i = 0; i < 8; i++) {
      const corner = v([i & 1 ? max[0] : min[0], i & 2 ? max[1] : min[1], i & 4 ? max[2] : min[2]]);
      const n = corner.project(r.camera);
      expect(Math.abs(n.x)).toBeLessThanOrEqual(1);
      expect(Math.abs(n.y)).toBeLessThanOrEqual(1);
      expect(Math.abs(n.z)).toBeLessThanOrEqual(1);
      widest = Math.max(widest, Math.abs(n.x), Math.abs(n.y));
    }
    expect(widest).toBeGreaterThan(0.6);
  });

  it('a ray meets a construction plane at the closed form point and misses one it runs parallel to or away from', () => {
    const plane = { name: 'P', origin: [0, 0, 5] as [number, number, number], x: [1, 0, 0] as [number, number, number], y: [0, 1, 0] as [number, number, number], z: [0, 0, 1] as [number, number, number] };
    const hit = rayHit(plane, [1, 2, 25], [0.3, -0.4, -1]);
    expect(hit?.[0]).toBeCloseTo(1 + 0.3 * 20, 9);
    expect(hit?.[1]).toBeCloseTo(2 - 0.4 * 20, 9);
    expect(hit?.[2]).toBeCloseTo(5, 9);
    expect(rayHit(plane, [0, 0, 25], [1, 0, 0])).toBeNull();
    expect(rayHit(plane, [0, 0, 25], [0, 0, 1])).toBeNull();
  });
});
