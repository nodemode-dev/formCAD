import { toast } from '../toast';
import type { Notes } from './output-api';

export function tellNotes(prefix: string, n?: Notes | null): void {
  const lines = [...(n?.notes ?? []), ...(n?.warnings ?? [])];
  if (!lines.length) { toast(prefix, 'info'); return; }
  const more = lines.length > 2 ? ` and ${lines.length - 2} more` : '';
  toast(`${prefix} ${lines.slice(0, 2).join(' ')}${more}`, 'info');
}
