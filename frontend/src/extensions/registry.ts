export type ToolId = string;
export interface Pt { x: number; y: number }

export interface ToolPointer { world: Pt; screen: Pt; button: number; shift: boolean; alt: boolean; mod: boolean; clicks: number }
export interface ViewInfo { zoom: number; dpr: number; width: number; height: number; toScreen(p: Pt): Pt; toWorld(p: Pt): Pt }
export interface Paint { accent: string; crosshair: string; snap: string; handle: string }
export interface ToolContext { docId: string | null; view(): ViewInfo; paint(): Paint }

export type OptionSpec = (
  | { kind: 'title'; text: string }
  | { kind: 'segment'; label?: string; choices: ReadonlyArray<{ id: string; label: string }>; get: () => string; set: (id: string) => void }
  | { kind: 'toggle'; label: string; get: () => boolean; set: (v: boolean) => void }
  | { kind: 'select'; label: string; choices: ReadonlyArray<{ id: string; label: string }>; get: () => string; set: (id: string) => void }
  | { kind: 'number'; label: string; min?: number; max?: number; step?: number; unit?: string; get: () => number | null; set: (v: number) => void }
  | { kind: 'readout'; label: string; get: () => string }
  | { kind: 'button'; label: string; icon?: string; run: () => void }
) & {
  when?: () => boolean;
  priority?: number;
};

export interface Tool {
  id: ToolId;
  label: string;
  key: string;
  order: number;
  group?: string;
  hidden?: boolean;
  plugin?: string;
  icon(): string;
  hint(): string;
  cursor?(ctx: ToolContext, p: ToolPointer | null): string;
  down?(ctx: ToolContext, p: ToolPointer): void;
  move?(ctx: ToolContext, p: ToolPointer): void;
  up?(ctx: ToolContext, p: ToolPointer): void;
  hover?(ctx: ToolContext, p: ToolPointer | null): void;
  keydown?(ctx: ToolContext, e: KeyboardEvent): boolean;
  wheel?(ctx: ToolContext, e: WheelEvent): boolean;
  cancel?(ctx: ToolContext): void;
  overlay?(ctx: ToolContext, g: CanvasRenderingContext2D): void;
  options?(): OptionSpec[];
}

const registry = new Map<ToolId, Tool>();

export function registerTool(tool: Tool): void {
  if (registry.has(tool.id)) throw new Error(`Tool "${tool.id}" is already registered`);
  registry.set(tool.id, tool);
}

export function unregisterTool(id: ToolId): void {
  if (registry.get(id)?.plugin) registry.delete(id);
}

export const toolList = (): Tool[] => [...registry.values()].sort((a, b) => a.order - b.order);
export const getTool = (id: ToolId): Tool | undefined => registry.get(id);
export const toolForKey = (key: string): Tool | undefined => toolList().find((t) => t.key === key.toUpperCase());
export const toolsForKey = (key: string): Tool[] => toolList().filter((t) => t.key === key.toUpperCase());

export const toolHost = { run: (id: string): void => { void id; } };
