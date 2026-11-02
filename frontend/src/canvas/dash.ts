export const MAX_REPEATS = 50000;

export function patternLength(pattern: number[], scale: number): number {
  let sum = 0;
  for (const v of pattern) sum += Math.abs(v);
  return sum * scale;
}

export function polylineLength(pts: number[], closed: boolean): number {
  let len = 0;
  for (let i = 2; i < pts.length; i += 2) len += Math.hypot(pts[i] - pts[i - 2], pts[i + 1] - pts[i - 1]);
  if (closed && pts.length >= 4) len += Math.hypot(pts[0] - pts[pts.length - 2], pts[1] - pts[pts.length - 1]);
  return len;
}

export function dashable(pattern: number[], scale: number, totalLen: number, minRepeat: number): boolean {
  const rep = patternLength(pattern, scale);
  if (!(rep > 0) || rep < minRepeat) return false;
  if (totalLen / rep > MAX_REPEATS) return false;
  let down = false;
  for (const v of pattern) if (v >= 0) down = true;
  return down;
}

export function dashRun(src: number[], closed: boolean, pattern: number[], scale: number, onPiece: (pts: number[]) => void, onDot: (x: number, y: number) => void): void {
  const pts = closed && src.length >= 4 ? src.concat([src[0], src[1]]) : src;
  const n = pts.length;
  if (n < 4 || pattern.length === 0) return;
  const pat = pattern.map((v) => v * scale);
  let idx = 0;
  let remaining = Math.abs(pat[0]);
  let piece: number[] = [];
  let guard = 0;

  const advance = (x: number, y: number): void => {
    idx = (idx + 1) % pat.length;
    remaining = Math.abs(pat[idx]);
    while (pat[idx] === 0 && guard++ < 1e6) {
      onDot(x, y);
      idx = (idx + 1) % pat.length;
      remaining = Math.abs(pat[idx]);
    }
  };

  if (pat[0] === 0) {
    onDot(pts[0], pts[1]);
    advance(pts[0], pts[1]);
  }

  for (let i = 0; i + 3 < n; i += 2) {
    const x0 = pts[i];
    const y0 = pts[i + 1];
    const dx = pts[i + 2] - x0;
    const dy = pts[i + 3] - y0;
    const len = Math.hypot(dx, dy);
    if (!(len > 0)) continue;
    let t = 0;
    while (t < len) {
      const down = pat[idx] > 0;
      const step = Math.min(remaining, len - t);
      if (down) {
        if (piece.length === 0) piece.push(x0 + (dx * t) / len, y0 + (dy * t) / len);
        piece.push(x0 + (dx * (t + step)) / len, y0 + (dy * (t + step)) / len);
      }
      t += step;
      remaining -= step;
      if (remaining <= 1e-12) {
        if (down && piece.length >= 4) onPiece(piece);
        piece = [];
        advance(x0 + (dx * t) / len, y0 + (dy * t) / len);
        if (++guard > 5e6) return;
      }
    }
  }
  if (piece.length >= 4) onPiece(piece);
}
