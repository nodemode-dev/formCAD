import * as THREE from 'three';
import { HDRLoader } from 'three/examples/jsm/loaders/HDRLoader.js';
import { downloadEnv, envBytes } from './net';

const cache = new Map<string, Promise<THREE.DataTexture>>();

export function loadEnvironment(id: string, res: string): Promise<THREE.DataTexture> {
  const key = `${id}:${res}`;
  let hit = cache.get(key);
  if (!hit) {
    hit = (async () => {
      let buf = await envBytes(id, res).catch(() => null);
      if (!buf) {
        await downloadEnv(id, res);
        buf = await envBytes(id, res);
      }
      if (!buf) throw new Error(`The environment ${id} (${res}) is not available.`);
      const tex = new HDRLoader().createDataTexture(buf);
      tex.mapping = THREE.EquirectangularReflectionMapping;
      tex.colorSpace = THREE.LinearSRGBColorSpace;
      tex.needsUpdate = true;
      return tex;
    })();
    hit.catch(() => { cache.delete(key); });
    cache.set(key, hit);
  }
  return hit;
}

export function forgetEnvironments(): void {
  for (const p of cache.values()) void p.then((t) => t.dispose(), () => undefined);
  cache.clear();
}
