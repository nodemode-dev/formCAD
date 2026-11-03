export type Scalar = number | boolean | string;

export const scalar = (type: string, value: Scalar): unknown => ({ type, tree: { '{0}': [value] } });
export const lines = (type: string, values: Scalar[]): unknown => ({ type, tree: { '{0}': values } });

export function itemsOf(persistent: unknown): unknown[] {
  if (!persistent || typeof persistent !== 'object') return [];
  const tree = (persistent as { tree?: unknown }).tree;
  if (!tree || typeof tree !== 'object') return [];
  const branch = Object.values(tree as Record<string, unknown>)[0];
  return Array.isArray(branch) ? branch : [];
}

export const firstOf = (persistent: unknown): unknown => itemsOf(persistent)[0];

export function stopAll(root: HTMLElement): void {
  for (const type of ['pointerdown', 'dblclick', 'keydown', 'keyup']) root.addEventListener(type, (e) => { e.stopPropagation(); });
  root.addEventListener('wheel', (e) => { if ((e.target as HTMLElement).closest('.is-scroll')) e.stopPropagation(); }, { passive: true });
}
