import type { Pt } from '../types';

export interface SysApi {
  num(name: string, fallback: number): number;
  text(name: string, fallback?: string): string;
  vec(name: string, fallback: Pt): Pt;
}

export interface Settings {
  osmode: number;
  autosnap: number;
  polarang: number;
  polaradd: number[];
  polarmode: number;
  polardist: number;
  ortho: boolean;
  snapmode: boolean;
  snaptype: number;
  snapunit: Pt;
  snapbase: Pt;
  snapang: number;
  iso: boolean;
  isoplane: number;
  angbase: number;
  angdir: number;
  aperture: number;
  pickbox: number;
  pickfirst: boolean;
  pickadd: boolean;
  pickdrag: number;
  selpreview: number;
  cycling: number;
  grips: boolean;
  gripsize: number;
  gripobjlimit: number;
  dynmode: boolean;
  dynprompt: boolean;
  dynpiformat: boolean;
  dynpicoords: boolean;
  dyndigrip: number;
  dyndivis: number;
  osnaphatch: boolean;
  lunits: number;
  luprec: number;
  aunits: number;
  auprec: number;
  selarea: boolean;
  winColor: number;
  crossColor: number;
  areaOpacity: number;
}

export function readSettings(s: SysApi): Settings {
  const raw = s.text('POLARADDANG', '').trim();
  const addClean = raw === '' ? [] : raw.split(';').map((x) => Number(x.trim())).filter((x) => Number.isFinite(x)).slice(0, 10);
  return {
    osmode: s.num('OSMODE', 4133),
    autosnap: s.num('AUTOSNAP', 61),
    polarang: Math.max(0.0001, s.num('POLARANG', 90)),
    polaradd: addClean,
    polarmode: s.num('POLARMODE', 0),
    polardist: s.num('POLARDIST', 0),
    ortho: s.num('ORTHOMODE', 0) !== 0,
    snapmode: s.num('SNAPMODE', 0) !== 0,
    snaptype: s.num('SNAPTYPE', 0),
    snapunit: s.vec('SNAPUNIT', [0.5, 0.5]),
    snapbase: s.vec('SNAPBASE', [0, 0]),
    snapang: s.num('SNAPANG', 0),
    iso: s.num('SNAPSTYL', 0) === 1,
    isoplane: s.num('SNAPISOPAIR', 0),
    angbase: s.num('ANGBASE', 0),
    angdir: s.num('ANGDIR', 0),
    aperture: Math.max(1, s.num('APERTURE', 10)),
    pickbox: s.num('PICKBOX', 3),
    pickfirst: s.num('PICKFIRST', 1) !== 0,
    pickadd: s.num('PICKADD', 1) !== 0,
    pickdrag: s.num('PICKDRAG', 2),
    selpreview: s.num('SELECTIONPREVIEW', 3),
    cycling: s.num('SELECTIONCYCLING', -2),
    grips: s.num('GRIPS', 1) !== 0,
    gripsize: s.num('GRIPSIZE', 5),
    gripobjlimit: s.num('GRIPOBJLIMIT', 100),
    dynmode: s.num('DYNMODE', 1) !== 0,
    dynprompt: s.num('DYNPROMPT', 1) !== 0,
    dynpiformat: s.num('DYNPIFORMAT', 0) !== 0,
    dynpicoords: s.num('DYNPICOORDS', 0) !== 0,
    dyndigrip: s.num('DYNDIGRIP', 31),
    dyndivis: s.num('DYNDIVIS', 1),
    osnaphatch: s.num('OSNAPHATCH', 0) !== 0,
    lunits: s.num('LUNITS', 2),
    luprec: s.num('LUPREC', 4),
    aunits: s.num('AUNITS', 0),
    auprec: s.num('AUPREC', 0),
    selarea: s.num('SELECTIONAREA', 1) !== 0,
    winColor: s.num('WINDOWAREACOLOR', 150),
    crossColor: s.num('CROSSINGAREACOLOR', 100),
    areaOpacity: s.num('SELECTIONAREAOPACITY', 25),
  };
}
