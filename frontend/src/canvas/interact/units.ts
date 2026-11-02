const MAX_DEN = 256;

function roundHalfAway(v: number, prec: number): number {
  const f = Math.pow(10, prec);
  const s = Math.abs(v);
  const r = Math.round(Number((s * f).toPrecision(15))) / f;
  return v < 0 ? -r : r;
}

function fixed(v: number, prec: number): string {
  if (!Number.isFinite(v)) return (0).toFixed(prec);
  const r = roundHalfAway(v, prec);
  const s = Math.abs(r).toFixed(prec);
  return r < 0 && Number(s) !== 0 ? `-${s}` : s;
}

function gcd(a: number, b: number): number {
  return b === 0 ? a : gcd(b, a % b);
}

function fractionText(units: number, den: number): { whole: number; frac: string } {
  const whole = Math.floor(units / den);
  let n = units - whole * den;
  let d = den;
  if (n > 0) {
    const g = gcd(n, d);
    n /= g;
    d /= g;
    return { whole, frac: `${n}/${d}` };
  }
  return { whole, frac: '' };
}

export function fmtLinear(value: number, lunits: number, luprec: number): string {
  if (!Number.isFinite(value)) value = 0;
  const prec = Math.max(0, Math.min(8, Math.round(luprec)));
  const neg = value < 0 && roundHalfAway(value, prec) !== 0;
  const a = Math.abs(value);
  const sign = neg ? '-' : '';
  if (a > 9e18) return fixed(value, prec);
  const den = Math.min(MAX_DEN, Math.pow(2, prec));
  switch (lunits) {
    case 1: {
      const e = a === 0 ? 0 : Math.floor(Math.log10(a));
      let m = a === 0 ? 0 : a / Math.pow(10, e);
      let ee = e;
      if (Number(m.toFixed(prec)) >= 10) { m /= 10; ee += 1; }
      return `${sign}${m.toFixed(prec)}E${ee < 0 ? '-' : '+'}${String(Math.abs(ee)).padStart(2, '0')}`;
    }
    case 3: {
      let feet = Math.floor(a / 12);
      let inch = a - feet * 12;
      if (Number(inch.toFixed(prec)) >= 12) { feet += 1; inch = 0; }
      return `${sign}${feet}'-${inch.toFixed(prec)}"`;
    }
    case 4: {
      let total = Math.round(a * den);
      const per = 12 * den;
      const feet = Math.floor(total / per);
      total -= feet * per;
      const f = fractionText(total, den);
      const inch = f.frac ? (f.whole > 0 ? `${f.whole} ${f.frac}` : f.frac) : String(f.whole);
      return `${sign}${feet}'-${inch}"`;
    }
    case 5: {
      const f = fractionText(Math.round(a * den), den);
      if (!f.frac) return `${sign}${f.whole}`;
      return f.whole > 0 ? `${sign}${f.whole} ${f.frac}` : `${sign}${f.frac}`;
    }
    default:
      return fixed(value, prec);
  }
}

export function fmtAngleDeg(deg: number, aunits: number, auprec: number): string {
  if (!Number.isFinite(deg)) deg = 0;
  const prec = Math.max(0, Math.min(8, Math.round(auprec)));
  let d = ((deg % 360) + 360) % 360;
  const wrapCheck = (v: number, full: number): number => (Number(v.toFixed(prec)) >= full ? 0 : v);
  switch (aunits) {
    case 1: {
      d = wrapCheck(d, 360);
      let degs = Math.floor(d);
      let rem = (d - degs) * 60;
      let mins = Math.floor(rem);
      let secs = (rem - mins) * 60;
      if (prec <= 0) {
        degs = Math.round(d) % 360;
        return `${degs}d`;
      }
      if (prec <= 2) {
        mins = Math.round(rem);
        if (mins >= 60) { mins = 0; degs += 1; }
        return `${degs % 360}d${mins}'`;
      }
      const sp = prec - 4 > 0 ? prec - 4 : 0;
      secs = Number(secs.toFixed(sp));
      if (secs >= 60) { secs = 0; mins += 1; }
      if (mins >= 60) { mins = 0; degs += 1; }
      rem = 0;
      return `${degs % 360}d${mins}'${secs.toFixed(sp)}"`;
    }
    case 2:
      return `${wrapCheck((d / 360) * 400, 400).toFixed(prec)}g`;
    case 3:
      return `${wrapCheck((d * Math.PI) / 180, Math.PI * 2).toFixed(prec)}r`;
    case 4: {
      const ns = d <= 90 || d >= 270 ? 'N' : 'S';
      const ew = d < 180 ? 'E' : 'W';
      let a = d <= 90 ? 90 - d : d <= 180 ? d - 90 : d <= 270 ? 270 - d : d - 270;
      a = a % 360;
      if (a === 0 && prec > 0) return d === 90 ? 'E' : d === 270 ? 'W' : d === 0 ? 'N' : 'S';
      return `${ns} ${a.toFixed(prec)}d ${ew}`;
    }
    default:
      return wrapCheck(d, 360).toFixed(prec);
  }
}

export function round1(v: number): string {
  const r = roundHalfAway(v, 1);
  return (Object.is(r, -0) ? 0 : r).toFixed(1);
}
