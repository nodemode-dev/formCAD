export type Interceptor = () => boolean | Promise<boolean>;

const table = new Map<string, Interceptor>();

export function registerInterceptor(names: string[], fn: Interceptor): void {
  for (const n of names) table.set(n.toLowerCase(), fn);
}

export function interceptCommand(name: string): boolean {
  const fn = table.get(name.toLowerCase());
  if (!fn) return false;
  const out = fn();
  if (out instanceof Promise) { void out; return true; }
  return out;
}
