import * as THREE from 'three';
import type { Appearance } from './net';

export function physicalFrom(a: Appearance, mmPerUnit: number): THREE.MeshPhysicalMaterial {
  const m = new THREE.MeshPhysicalMaterial();
  applyAppearance(m, a, mmPerUnit);
  return m;
}

export function applyAppearance(m: THREE.MeshPhysicalMaterial, a: Appearance, mmPerUnit: number): void {
  m.color.set(a.base_color);
  m.metalness = a.metallic;
  m.roughness = a.roughness;
  m.ior = a.ior;
  m.transmission = a.transmission;
  m.thickness = a.thickness > 0 ? a.thickness / Math.max(mmPerUnit, 1e-9) : 0;
  m.attenuationColor.set(a.attenuation_color);
  m.attenuationDistance = a.attenuation_distance > 0 ? a.attenuation_distance / Math.max(mmPerUnit, 1e-9) : Infinity;
  m.clearcoat = a.clearcoat;
  m.clearcoatRoughness = a.clearcoat_roughness;
  m.sheen = a.sheen;
  m.sheenRoughness = a.sheen_roughness;
  m.sheenColor.set(a.sheen_color);
  m.emissive.set(a.emissive);
  m.emissiveIntensity = a.emissive_intensity;
  m.opacity = a.opacity;
  m.transparent = a.opacity < 1;
  m.side = THREE.FrontSide;
  m.needsUpdate = true;
}

export function appearanceKey(a: Appearance): string {
  return [a.base_color, a.metallic, a.roughness, a.ior, a.transmission, a.thickness, a.clearcoat, a.clearcoat_roughness, a.sheen, a.sheen_roughness, a.sheen_color, a.emissive, a.emissive_intensity, a.opacity, a.attenuation_color, a.attenuation_distance].join('|');
}

export function swatch(a: Appearance): string {
  if (a.emissive_intensity > 0 && a.emissive !== '#000000') return a.emissive;
  return a.base_color;
}
