import { events } from '../io/events';
import { docStore } from '../ui/doc-store';
import { asm, isAssembly } from '../u8/asm';
import { docUrl, req, type Json } from './kit';

export type JointType = 'rigid' | 'revolute' | 'slider' | 'cylindrical' | 'pinslot' | 'planar' | 'ball';
export type LimitState = 'free' | 'at_min' | 'at_max' | 'outside';

export interface Frame { origin?: number[]; o?: number[]; z: number[]; x?: number[] }
export interface Side { comp: string | null; frame: Frame }
export interface Coord { key: string; kind: 'angle' | 'length'; value: number; min: number | null; max: number | null; rest: number | null; state: LimitState; driven: boolean }
export interface Joint {
  id: number | string; name: string; label: string; type: JointType; a: Side; b: Side;
  as_built: boolean; suppressed: boolean; coords: Coord[]; cone: { value: number; max: number | null } | null; dof: number; links: Array<number | string>;
}
export interface Link { id: number | string; name: string; label: string; first: { joint: number | string; coord: string }; second: { joint: number | string; coord: string }; ratio: number; reverse: boolean; suppressed: boolean }
export interface JointStatus { state: string; dof: number; rank?: number; redundant_rows?: number; residual?: number; components?: Record<string, { dof: number; state: string }> }
export interface Track { joint: number | string; coord: string; keys: Array<{ t: number; v: number; ease: 'linear' | 'smooth' | 'hold' }> }
export interface Study { id: string; name: string; duration: number; fps: number; tracks: Track[]; contact: { sets: string[]; mode: 'stop' | 'report' | 'off'; stride?: number }; plots: Array<{ joint: number | string; coord: string }> }
export interface ContactSet { id: string; name: string; all: boolean; pairs: Array<[string, string]>; touch: number }
export interface Dynamics { gravity: number[]; density: number; servo_hz: number; damping_ratio: number; solref_loop: number; timestep: number; friction: number; contact_time?: number }
export interface MotionLimits { window?: Record<string, number>; restricted?: Record<string, number> }
export interface MotionState { studies: Study[]; contacts: ContactSet[]; dynamics: Dynamics | null; limits: MotionLimits }
export interface Plot { joint: number | string; coord: string; kind: string; unit: string; t: number[]; v: number[] }
export interface JobResult {
  frames: number; duration: number;
  stopped: null | { time: number; reason: string; message?: string; pair: [string, string] | null; gap: number | null; joints?: Json };
  message?: string; planned?: number;
  plots: Plot[]; contacts: Array<{ t: number; pair: [string, string]; gap?: number; force?: number }>; solve_ms?: number; checks?: unknown;
}
export interface Job {
  id: string; doc: string; kind: 'study' | 'dynamics'; study?: string; state: 'queued' | 'running' | 'done' | 'cancelled' | 'failed'; message: string;
  progress: { fraction: number; t?: number; frames?: number; steps?: number; elapsed?: number }; created?: number; finished?: number; result?: JobResult;
}
export interface Frame3 { t: number; q: Record<string, Record<string, number>>; poses: Record<string, number[]> }

export const TYPE_LABEL: Record<JointType, string> = {
  rigid: 'Rigid', revolute: 'Revolute', slider: 'Slider', cylindrical: 'Cylindrical', pinslot: 'Pin-slot', planar: 'Planar', ball: 'Ball',
};
export const TYPE_COORDS: Record<JointType, string[]> = {
  rigid: [], revolute: ['rz'], slider: ['tz'], cylindrical: ['rz', 'tz'], pinslot: ['rz', 'tx'], planar: ['tx', 'ty', 'rz'], ball: ['rx', 'ry', 'rz'],
};
export const COORD_LABEL: Record<string, string> = {
  rz: 'Rotation about Z', tz: 'Slide along Z', tx: 'Slide along X', ty: 'Slide along Y', rx: 'Rotation about X', ry: 'Rotation about Y',
};

class JointStore {
  joints: Joint[] = [];
  links: Link[] = [];
  status: JointStatus | null = null;
  motion: MotionState = { studies: [], contacts: [], dynamics: null, limits: {} };
  selected: string = '';
  error = '';
  private readonly subs = new Set<() => void>();
  private timer = 0;
  private busy = false;
  private again = false;

  onChange(fn: () => void): void { this.subs.add(fn); }
  private emit(): void { for (const f of this.subs) f(); }
  id(): string | null { return docStore.activeId; }
  key(j: { id: number | string }): string { return String(j.id); }
  joint(id: number | string | null | undefined): Joint | undefined { return this.joints.find((j) => String(j.id) === String(id)) ?? this.joints.find((j) => j.name === String(id)); }
  current(): Joint | undefined { return this.joint(this.selected); }
  select(id: string): void { if (this.selected === id) return; this.selected = id; this.emit(); }

  schedule(delay = 150): void {
    if (this.timer) return;
    this.timer = window.setTimeout(() => { this.timer = 0; void this.refresh(); }, delay);
  }

  async refresh(): Promise<void> {
    if (this.busy) { this.again = true; return; }
    const id = this.id();
    if (!id || !isAssembly()) {
      if (this.joints.length || this.links.length || this.motion.studies.length || this.motion.contacts.length) {
        this.joints = []; this.links = []; this.status = null; this.motion = { studies: [], contacts: [], dynamics: null, limits: {} }; this.emit();
      }
      return;
    }
    this.busy = true;
    try {
      do {
        this.again = false;
        const [j, m] = await Promise.all([
          req<{ joints: Joint[]; links: Link[]; status: JointStatus }>('GET', docUrl(id, 'joints')).catch((e: unknown) => { this.error = e instanceof Error ? e.message : ''; return null; }),
          req<MotionState>('GET', docUrl(id, 'motion')).catch(() => null),
        ]);
        if (id !== this.id()) break;
        if (j) { this.joints = j.joints; this.links = j.links; this.status = j.status; this.error = ''; }
        if (m) this.motion = { studies: m.studies ?? [], contacts: m.contacts ?? [], dynamics: m.dynamics ?? null, limits: m.limits ?? {} };
        if (this.selected && !this.joint(this.selected)) this.selected = '';
        this.emit();
      } while (this.again);
    } finally {
      this.busy = false;
    }
  }

  study(id: string): Study | undefined { return this.motion.studies.find((s) => s.id === id); }
}

export const joints = new JointStore();

events.on('doc', (e) => { if (e.id === docStore.activeId) joints.schedule(); });
docStore.onChange(() => joints.schedule(50));
let primed = false;
asm.onChange(() => { if (!primed && isAssembly()) { primed = true; joints.schedule(0); } });

export const jurl = (tail: string): string => docUrl(joints.id() ?? '', tail);

export const jointView: { layer: import('./joint-layer').JointLayer | null } = { layer: null };

export function showPoses(poses: Record<string, number[]> | null): void {
  asm.showPoses(poses);
  jointView.layer?.follow(poses);
}
