export function polylineArea(verts: number[][]): number {
  const n = verts.length;
  if (n < 3) return 0;
  let twice = 0;
  let caps = 0;
  for (let i = 0; i < n; i++) {
    const a = verts[i], b = verts[(i + 1) % n];
    twice += a[0] * b[1] - b[0] * a[1];
    const bulge = a[2] ?? 0;
    if (bulge) {
      const chord = Math.hypot(b[0] - a[0], b[1] - a[1]);
      const theta = 4 * Math.atan(Math.abs(bulge));
      const r = chord / (2 * Math.sin(theta / 2));
      caps += Math.sign(bulge) * 0.5 * r * r * (theta - Math.sin(theta));
    }
  }
  return Math.abs(twice / 2 + caps);
}
