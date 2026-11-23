import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { engine, jsonResponse } from './support';

async function fresh<T>(path: string): Promise<{ mod: T; docStore: { activeId: string | null }; notices: () => ReadonlyArray<{ text: string; kind: string }> }> {
  vi.resetModules();
  const { docStore } = await import('../../src/ui/doc-store');
  const toast = await import('../../src/ui/toast');
  const mod = (await import(path)) as T;
  docStore.activeId = 'D1';
  return { mod, docStore, notices: toast.noticeHistory };
}

beforeEach(() => { vi.useFakeTimers(); });
afterEach(() => { vi.unstubAllGlobals(); vi.useRealTimers(); });

describe('the simulation store', () => {
  it('installing the mesher posts to the install route and polls status once a second until it is done', async () => {
    const { mod } = await fresh<typeof import('../../src/p13/sim-store')>('../../src/p13/sim-store');
    const statuses = [{ installing: true, progress: 0.4 }, { installing: true, progress: 0.8 }, { installing: false, available: true, version: '4.13' }];
    const sent = engine((method, url) => {
      if (method === 'POST' && url === '/api/docs/D1/sim/mesher/install') return jsonResponse(200, { installing: true, progress: 0 });
      if (method === 'GET' && url === '/api/docs/D1/sim/status') return jsonResponse(200, statuses.shift());
      return jsonResponse(404, { detail: 'unexpected' });
    });
    const done = mod.sim.installMesher();
    await vi.advanceTimersByTimeAsync(0);
    expect(sent.map((s) => `${s.method} ${s.url}`)).toEqual(['POST /api/docs/D1/sim/mesher/install']);
    expect(mod.sim.mesher.installing).toBe(true);
    await mod.sim.installMesher();
    expect(sent).toHaveLength(1);
    await vi.advanceTimersByTimeAsync(999);
    expect(sent).toHaveLength(1);
    await vi.advanceTimersByTimeAsync(1);
    expect(sent).toHaveLength(2);
    expect(mod.sim.mesher.progress).toBe(0.4);
    await vi.advanceTimersByTimeAsync(1000);
    expect(sent).toHaveLength(3);
    await vi.advanceTimersByTimeAsync(1000);
    expect(sent).toHaveLength(4);
    await done;
    await vi.advanceTimersByTimeAsync(10000);
    expect(sent).toHaveLength(4);
    expect(sent.slice(1).every((s) => s.method === 'GET' && s.url === '/api/docs/D1/sim/status')).toBe(true);
    expect(mod.sim.mesher).toMatchObject({ installing: false, available: true, version: '4.13' });
  });

  it('a failed install is reported to the person and polling never starts', async () => {
    const { mod, notices } = await fresh<typeof import('../../src/p13/sim-store')>('../../src/p13/sim-store');
    const sent = engine(() => jsonResponse(403, { detail: 'Installing the mesher is not allowed here' }));
    await mod.sim.installMesher();
    await vi.advanceTimersByTimeAsync(5000);
    expect(sent).toHaveLength(1);
    expect(notices().at(-1)).toMatchObject({ text: 'Installing the mesher is not allowed here', kind: 'error' });
  });

  it('a refresh applies the studies the engine lists and a failed refresh keeps them and shows the error', async () => {
    const { mod } = await fresh<typeof import('../../src/p13/sim-store')>('../../src/p13/sim-store');
    let fail = false;
    engine(() => (fail
      ? jsonResponse(503, { detail: 'The engine is restarting' })
      : jsonResponse(200, { records: [{ id: 'S1', kind: 'study', name: 'Static 1' }, { id: 'X1', kind: 'fixture', study: 'S1' }, { id: 'S2', kind: 'study', name: 'Modal' }] })));
    await mod.sim.refresh();
    expect(mod.sim.of('study').map((r) => r.id)).toEqual(['S1', 'S2']);
    expect(mod.sim.studyId).toBe('S1');
    expect(mod.sim.error).toBe('');
    fail = true;
    await mod.sim.refresh();
    expect(mod.sim.error).toBe('The engine is restarting');
    expect([...mod.sim.records.keys()].sort()).toEqual(['S1', 'S2', 'X1']);
    expect(mod.sim.studyId).toBe('S1');
  });

  it('a started run is polled until the engine reports it finished', async () => {
    const { mod } = await fresh<typeof import('../../src/p13/sim-store')>('../../src/p13/sim-store');
    const states = ['running', 'running', 'done'];
    const sent = engine((method, url) => {
      if (method === 'POST' && url === '/api/docs/D1/sim/studies/S1/run') return jsonResponse(200, { job: 'J7' });
      if (url === '/api/docs/D1/sim/jobs/J7') return jsonResponse(200, { job: 'J7', state: states.shift(), progress: 0.5 });
      return jsonResponse(200, { records: [] });
    });
    expect(await mod.sim.run('S1')).toBe(true);
    expect(mod.sim.running).toBe(true);
    await vi.advanceTimersByTimeAsync(400 * 3);
    expect(mod.sim.running).toBe(false);
    expect(mod.sim.job?.state).toBe('done');
    const polls = (): number => sent.filter((s) => s.url.endsWith('/jobs/J7')).length;
    const before = polls();
    await vi.advanceTimersByTimeAsync(4000);
    expect(polls()).toBe(before);
  });
});

describe('the sheet metal store', () => {
  const offState = { on: false, flip: false, fixed_face: null, align: 'x', rule: null };

  it('a successful change applies the state the engine answers with', async () => {
    const { mod } = await fresh<typeof import('../../src/sheet/store')>('../../src/sheet/store');
    const sent = engine(() => jsonResponse(200, { state: { ...offState, on: true }, flat: undefined }));
    mod.sheetStore.state = { ...offState };
    expect(await mod.sheetStore.set({ on: true })).toBe(true);
    expect(sent[0]).toMatchObject({ method: 'PUT', url: '/api/docs/D1/sheetmetal/flat', body: { on: true } });
    expect(mod.sheetStore.state).toEqual({ ...offState, on: true });
  });

  it('a refused change keeps the previous state and tells the person why', async () => {
    const { mod, notices } = await fresh<typeof import('../../src/sheet/store')>('../../src/sheet/store');
    engine(() => jsonResponse(409, { detail: 'The part has no base flange' }));
    mod.sheetStore.state = { ...offState };
    expect(await mod.sheetStore.set({ flip: true })).toBe(false);
    expect(mod.sheetStore.state).toEqual(offState);
    expect(notices().at(-1)).toMatchObject({ text: 'The part has no base flange', kind: 'error' });
    expect(mod.sheetStore.busy).toBe(false);
  });
});
