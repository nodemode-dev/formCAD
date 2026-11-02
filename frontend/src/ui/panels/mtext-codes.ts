export interface MFmt {
  b: boolean;
  i: boolean;
  u: boolean;
  o: boolean;
  k: boolean;
  c: string;
  f: string;
  h: string;
  w: string;
  q: string;
  t: string;
  a: string;
}

export interface MTab { p: number; k: string }

export interface MPara {
  i: number;
  l: number;
  r: number;
  b: number;
  a: number;
  q: string;
  t: MTab[];
}

export const DEFAULT_FMT: MFmt = { b: false, i: false, u: false, o: false, k: false, c: '', f: '', h: '', w: '', q: '', t: '', a: '' };
export const DEFAULT_PARA: MPara = { i: 0, l: 0, r: 0, b: 0, a: 0, q: '', t: [] };

export const copyPara = (p: MPara): MPara => ({ ...p, t: p.t.map((x) => ({ ...x })) });

const FLAGS = ['b', 'i', 'u', 'o', 'k'] as const;
const RAWS = ['c', 'f', 'h', 'w', 'q', 't', 'a'] as const;
const NUM = /^[+-]?(\d+\.?\d*|\.\d+)([eE][+-]?\d+)?$/;

export function fmtKey(f: MFmt): string {
  return `${+f.b}${+f.i}${+f.u}${+f.o}${+f.k}|${f.c}|${f.f}|${f.h}|${f.w}|${f.q}|${f.t}|${f.a}`;
}

export const isPlain = (f: MFmt): boolean => fmtKey(f) === fmtKey(DEFAULT_FMT);

export function paraKey(p: MPara): string {
  return `${p.i},${p.l},${p.r},${p.b},${p.a},${p.q},${p.t.map((x) => `${x.k}${x.p}`).join(' ')}`;
}

export type MNode =
  | { t: 'text'; s: string; f: MFmt }
  | { t: 'stack'; top: string; sep: string; bot: string; f: MFmt }
  | { t: 'br'; f: MFmt };

export interface MParagraph { p: MPara; nodes: MNode[] }

function parsePara(spec: string, cur: MPara): MPara {
  const p = copyPara(cur);
  let inTab = false;
  for (const raw of spec.split(',')) {
    let tok = raw.trim();
    if (!tok) continue;
    if (tok[0] === 'x' && tok.length > 1 && /[a-zA-Z]/.test(tok[1])) tok = tok.slice(1);
    const c = tok[0], rest = tok.slice(1);
    if (inTab) {
      if ('crd'.includes(c) && NUM.test(rest.trim())) { p.t.push({ p: Number(rest), k: c }); continue; }
      if (NUM.test(tok)) { p.t.push({ p: Number(tok), k: 'l' }); continue; }
    }
    inTab = false;
    const v = NUM.test(rest.trim()) ? Number(rest) : null;
    if (c === 'i' && v !== null) p.i = v;
    else if (c === 'l' && v !== null) p.l = v;
    else if (c === 'r' && v !== null) p.r = v;
    else if (c === 'b' && v !== null) p.b = v;
    else if (c === 'a' && v !== null) p.a = v;
    else if (c === 'q') p.q = 'lcrjd'.includes(rest[0] ?? '*') && rest ? rest[0] : '';
    else if (c === 't') {
      p.t = [];
      inTab = true;
      if (v !== null) p.t.push({ p: v, k: 'l' });
      else if ('crd'.includes(rest[0] ?? '') && rest && NUM.test(rest.slice(1))) p.t.push({ p: Number(rest.slice(1)), k: rest[0] });
    }
  }
  p.t.sort((a, b) => a.p - b.p);
  return p;
}

function stackParts(arg: string): { top: string; sep: string; bot: string } {
  let k = 0;
  while (k < arg.length) {
    const ch = arg[k];
    if (ch === '\\' && k + 1 < arg.length) { k += 2; continue; }
    if ('/#^'.includes(ch)) return { top: arg.slice(0, k).replace(/\\/g, ''), sep: ch, bot: arg.slice(k + 1).replace(/\\/g, '') };
    k++;
  }
  return { top: arg.replace(/\\/g, ''), sep: '^', bot: '' };
}

export function parseContents(contents: string): MParagraph[] {
  const text = contents.replace(/\r\n?/g, '\n');
  let props: MPara = copyPara(DEFAULT_PARA);
  let st: MFmt = { ...DEFAULT_FMT };
  const stack: MFmt[] = [];
  let buf = '';
  let para: MParagraph = { p: copyPara(props), nodes: [] };
  const out: MParagraph[] = [para];
  const flush = (): void => {
    if (!buf) return;
    para.nodes.push({ t: 'text', s: buf, f: { ...st } });
    buf = '';
  };
  const next = (): void => {
    flush();
    para = { p: copyPara(props), nodes: [] };
    out.push(para);
  };
  let i = 0;
  const n = text.length;
  while (i < n) {
    const c = text[i];
    if (c === '{') { flush(); stack.push({ ...st }); i++; continue; }
    if (c === '}') { flush(); const top = stack.pop(); if (top) st = top; i++; continue; }
    if (c === '\n') { next(); i++; continue; }
    if (c === '^' && i + 1 < n) {
      const d = text[i + 1];
      if (d === 'I') buf += '\t';
      else if (d === 'J') next();
      else if (d === ' ') buf += '^';
      else buf += c + d;
      i += 2;
      continue;
    }
    if (c === '\\' && i + 1 < n) {
      const d = text[i + 1];
      i += 2;
      if (d === '\\' || d === '{' || d === '}') { buf += d; continue; }
      if (d === 'P') { next(); continue; }
      if (d === 'N') { flush(); para.nodes.push({ t: 'br', f: { ...st } }); continue; }
      if (d === '~') { buf += ' '; continue; }
      if ('LlOoKk'.includes(d)) {
        flush();
        const on = d === d.toUpperCase();
        st = { ...st, ...(d === 'L' || d === 'l' ? { u: on } : d === 'O' || d === 'o' ? { o: on } : { k: on }) };
        continue;
      }
      if ('SfFHWQTCcApP'.includes(d)) {
        let end = text.indexOf(';', i);
        if (end < 0) end = n;
        const arg = text.slice(i, end);
        i = end + 1;
        flush();
        if (d === 'S') {
          const s = stackParts(arg);
          para.nodes.push({ t: 'stack', top: s.top, sep: s.sep, bot: s.bot, f: { ...st } });
        } else if (d === 'p' || d === 'P') {
          props = parsePara(arg, props);
          if (!para.nodes.length) para.p = copyPara(props);
        } else if (d === 'f' || d === 'F') {
          const parts = arg.split('|');
          st = { ...st, f: parts[0] ?? '', b: false, i: false };
          for (const flag of parts.slice(1)) {
            if (flag[0] === 'b') st.b = flag.slice(1) === '1';
            else if (flag[0] === 'i') st.i = flag.slice(1) === '1';
          }
        } else if (d === 'C') st = { ...st, c: `i:${arg.trim()}` };
        else if (d === 'c') st = { ...st, c: `r:${arg.trim()}` };
        else st = { ...st, [d.toLowerCase()]: arg.trim() };
        continue;
      }
      continue;
    }
    buf += c;
    i++;
  }
  flush();
  return out;
}

function escapeText(s: string, afterCaretSafe: boolean): string {
  let r = '';
  for (let k = 0; k < s.length; k++) {
    const ch = s[k];
    if (ch === '\\') r += '\\\\';
    else if (ch === '{') r += '\\{';
    else if (ch === '}') r += '\\}';
    else if (ch === ' ') r += '\\~';
    else if (ch === '\n') r += '\\N';
    else if (ch === '^' && (k + 1 >= s.length ? afterCaretSafe : 'IJ '.includes(s[k + 1]))) r += '^ ';
    else r += ch;
  }
  return r;
}

export function fmtCodes(f: MFmt, defaultFace: string): string {
  let r = '';
  if (f.b || f.i || f.f) r += `\\f${f.f || defaultFace}|b${f.b ? 1 : 0}|i${f.i ? 1 : 0};`;
  if (f.h) r += `\\H${f.h};`;
  if (f.w) r += `\\W${f.w};`;
  if (f.q) r += `\\Q${f.q};`;
  if (f.t) r += `\\T${f.t};`;
  if (f.a) r += `\\A${f.a};`;
  if (f.c.startsWith('i:')) r += `\\C${f.c.slice(2)};`;
  else if (f.c.startsWith('r:')) r += `\\c${f.c.slice(2)};`;
  if (f.u) r += '\\L';
  if (f.o) r += '\\O';
  if (f.k) r += '\\K';
  return r;
}

const num = (v: number): number => Number(v.toFixed(6));

function paraSpec(p: MPara): string {
  const tabs = p.t.map((x) => `${x.k === 'l' ? '' : x.k}${num(x.p)}`).join(',');
  return `i${num(p.i)},l${num(p.l)},r${num(p.r)},b${num(p.b)},a${num(p.a)},q${p.q || '*'},t${tabs}`;
}

const sameFmt = (a: MFmt, b: MFmt): boolean => fmtKey(a) === fmtKey(b);

export function serializeContents(paras: MParagraph[], defaultFace: string): string {
  let prev = paraKey(DEFAULT_PARA);
  const chunks: string[] = [];
  paras.forEach((para, idx) => {
    let out = '';
    const k = paraKey(para.p);
    if (k !== prev) { out += `\\p${paraSpec(para.p)};`; prev = k; }
    let run: { f: MFmt; body: string } | null = null;
    const close = (): void => {
      if (!run) return;
      out += isPlain(run.f) ? run.body : `{${fmtCodes(run.f, defaultFace)}${run.body}}`;
      run = null;
    };
    for (const node of para.nodes) {
      let body: string;
      if (node.t === 'text') body = escapeText(node.s, true);
      else if (node.t === 'br') body = '\\N';
      else body = `\\S${node.top.replace(/[\\;]/g, '')}${node.sep}${node.bot.replace(/[\\;]/g, '')};`;
      if (run && sameFmt(run.f, node.f)) run.body += body;
      else { close(); run = { f: node.f, body }; }
    }
    close();
    chunks.push(out);
    void idx;
  });
  return chunks.join('\\P');
}

export function plainOf(paras: MParagraph[]): string {
  return paras.map((p) => p.nodes.map((n) => (n.t === 'text' ? n.s : n.t === 'br' ? '\n' : `${n.top}${n.sep === '^' ? '^' : n.sep}${n.bot}`)).join('')).join('\n');
}

export const FLAG_KEYS = FLAGS;
export const RAW_KEYS = RAWS;
