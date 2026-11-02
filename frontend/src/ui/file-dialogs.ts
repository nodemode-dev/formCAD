import { promptName } from './dialogs';

const FILTERS = [
  { name: 'FormCAD project', extensions: ['fcad'] },
  { name: 'DXF drawing', extensions: ['dxf'] },
];

const native = (): boolean => '__TAURI_INTERNALS__' in window;

export async function pickOpenPath(): Promise<string | null> {
  if (native()) {
    try {
      const { open } = await import('@tauri-apps/plugin-dialog');
      const picked = await open({ multiple: false, directory: false, filters: FILTERS });
      return typeof picked === 'string' ? picked : null;
    } catch {
      return null;
    }
  }
  return promptName('Open a file by path', '', 'Open');
}

export async function pickSavePath(suggested: string): Promise<string | null> {
  if (native()) {
    try {
      const { save } = await import('@tauri-apps/plugin-dialog');
      return (await save({ defaultPath: suggested, filters: FILTERS.slice(0, 1) })) ?? null;
    } catch {
      return null;
    }
  }
  return promptName('Save as (file path)', suggested, 'Save');
}

export async function onOpenPaths(handler: (paths: string[]) => void): Promise<void> {
  if (!native()) return;
  try {
    const { listen } = await import('@tauri-apps/api/event');
    const { invoke } = await import('@tauri-apps/api/core');
    await listen<string[]>('formcad://open-paths', (e) => { if (Array.isArray(e.payload)) handler(e.payload); });
    const pending = await invoke<string[]>('take_pending_opens');
    if (pending.length) handler(pending);
  } catch {
    return;
  }
}
