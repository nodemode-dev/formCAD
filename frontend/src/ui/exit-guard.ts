import { askSaveChangesAll } from './dialogs';
import { docStore } from './doc-store';

let asking = false;
let watching = false;

async function review(): Promise<boolean> {
  const dirty = docStore.docs.filter((d) => d.dirty);
  let all: 'save' | 'discard' | null = null;
  for (const doc of dirty) {
    let choice: 'save' | 'discard' | 'cancel';
    if (all) {
      choice = all;
    } else {
      const answer = await askSaveChangesAll(doc.name, dirty.length > 1);
      choice = answer.choice;
      if (answer.all && choice !== 'cancel') all = choice;
    }
    if (choice === 'cancel') return false;
    if (choice === 'save' && !(await docStore.save(doc.id))) return false;
  }
  return true;
}

export async function watchExitRequests(): Promise<void> {
  if (!('__TAURI_INTERNALS__' in window) || watching) return;
  watching = true;
  try {
    const { listen } = await import('@tauri-apps/api/event');
    const { invoke } = await import('@tauri-apps/api/core');
    await listen('formcad://exit-requested', () => {
      if (asking) return;
      asking = true;
      void (async () => {
        let cancel = false;
        try {
          cancel = !(await review());
        } catch {
          cancel = true;
        } finally {
          asking = false;
        }
        await invoke('confirm_exit', { cancel }).catch(() => undefined);
      })();
    });
  } catch {
    return;
  }
}
