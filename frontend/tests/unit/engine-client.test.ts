import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { engine, jsonResponse } from './support';

type ApiModule = typeof import('../../src/io/api');
type Holder = { __FORMCAD_TOKEN?: unknown };

async function freshApi(): Promise<ApiModule> {
  vi.resetModules();
  return import('../../src/io/api');
}

beforeEach(() => {
  sessionStorage.clear();
  document.head.querySelectorAll('meta[name="formcad-token"]').forEach((m) => m.remove());
  delete (window as unknown as Holder).__FORMCAD_TOKEN;
});

afterEach(() => {
  vi.unstubAllGlobals();
  vi.useRealTimers();
});

describe('the engine client', () => {
  it('sends the session key the page was given on every request and removes it from the page global', async () => {
    (window as unknown as Holder).__FORMCAD_TOKEN = 'k-123';
    const { api } = await freshApi();
    const sent = engine(() => jsonResponse(200, { docs: [] }));
    await api.docs();
    expect('__FORMCAD_TOKEN' in window).toBe(false);
    await api.createDoc({ name: 'A' });
    await api.sendInput('D 1', 'LINE');
    expect(sent.map((s) => s.headers['X-FormCAD-Token'])).toEqual(['k-123', 'k-123', 'k-123']);
    expect(sent.map((s) => `${s.method} ${s.url}`)).toEqual(['GET /api/docs', 'POST /api/docs', 'POST /api/docs/D%201/input']);
    expect(sent[2].body).toEqual({ text: 'LINE' });
    expect(sent[2].headers['Content-Type']).toBe('application/json');
    expect(sent[0].headers['Content-Type']).toBeUndefined();
  });

  it('a script that sets the global later cannot replace the key already taken', async () => {
    (window as unknown as Holder).__FORMCAD_TOKEN = 'first';
    const { api, token } = await freshApi();
    expect(token()).toBe('first');
    (window as unknown as Holder).__FORMCAD_TOKEN = 'second';
    const sent = engine(() => jsonResponse(200, {}));
    await api.health();
    expect(sent[0].headers['X-FormCAD-Token']).toBe('first');
  });

  it('takes the key from the served page tag and keeps it across a reload of the page', async () => {
    const meta = document.createElement('meta');
    meta.name = 'formcad-token';
    meta.content = 'served-9';
    document.head.append(meta);
    let mod = await freshApi();
    let sent = engine(() => jsonResponse(200, {}));
    await mod.api.health();
    expect(sent[0].headers['X-FormCAD-Token']).toBe('served-9');
    meta.remove();
    mod = await freshApi();
    sent = engine(() => jsonResponse(200, {}));
    await mod.api.health();
    expect(sent[0].headers['X-FormCAD-Token']).toBe('served-9');
  });

  it('sends no key header at all when the page has none', async () => {
    const { api } = await freshApi();
    const sent = engine(() => jsonResponse(200, {}));
    await api.health();
    expect(Object.keys(sent[0].headers)).not.toContain('X-FormCAD-Token');
  });

  it.each([
    [404, { detail: 'No document D9' }, 'No document D9'],
    [422, { message: 'Radius must be positive' }, 'Radius must be positive'],
    [500, { detail: 'Kernel crashed' }, 'Kernel crashed'],
  ])('a %d answer rejects with the server message and status', async (status, body, message) => {
    const { api, ApiError } = await freshApi();
    engine(() => jsonResponse(status, body, 'Status Text'));
    const err = await api.docs().catch((e: unknown) => e);
    expect(err).toBeInstanceOf(ApiError);
    expect((err as InstanceType<typeof ApiError>).status).toBe(status);
    expect((err as Error).message).toBe(message);
  });

  it('a failed answer without a readable body rejects with the status text', async () => {
    const { api } = await freshApi();
    engine(() => new Response('<html>bad gateway</html>', { status: 502, statusText: 'Bad Gateway' }));
    await expect(api.docs()).rejects.toMatchObject({ status: 502, message: 'Bad Gateway' });
  });

  it('a request the network refuses rejects as unreachable with status 0', async () => {
    const { api } = await freshApi();
    vi.stubGlobal('fetch', vi.fn(async () => { throw new TypeError('Failed to fetch'); }));
    await expect(api.docs()).rejects.toMatchObject({ status: 0, message: 'The engine is not reachable' });
  });

  it('a request with no answer for thirty seconds is abandoned with a message', async () => {
    vi.useFakeTimers();
    const { api } = await freshApi();
    vi.stubGlobal('fetch', vi.fn((_url: string, init: RequestInit) => new Promise((_ok, fail) => {
      init.signal?.addEventListener('abort', () => fail(new DOMException('aborted', 'AbortError')));
    })));
    const pending = api.docs().catch((e: unknown) => e);
    await vi.advanceTimersByTimeAsync(29999);
    let settled = false;
    void pending.then(() => { settled = true; });
    await Promise.resolve();
    expect(settled).toBe(false);
    await vi.advanceTimersByTimeAsync(2);
    expect(await pending).toMatchObject({ status: 0, message: 'The engine did not answer in time' });
  });

  it('an empty success answer resolves without a body', async () => {
    const { call } = await freshApi();
    engine(() => new Response(null, { status: 204 }));
    await expect(call('DELETE', '/api/x')).resolves.toBeUndefined();
  });

  it('asks for the display since a revision and for a named space in one query', async () => {
    const { api } = await freshApi();
    const sent = engine(() => jsonResponse(200, { rev: 1, full: false, removed: [], items: [] }));
    await api.display('D1', 7, 'Layout 1');
    await api.display('D1');
    expect(sent.map((s) => s.url)).toEqual(['/api/docs/D1/display?since=7&space=Layout%201', '/api/docs/D1/display']);
  });

  it('the workspace request helper carries the same key and the server message', async () => {
    (window as unknown as Holder).__FORMCAD_TOKEN = 'k-net';
    vi.resetModules();
    const net = await import('../../src/u8/net');
    const sent = engine((method) => (method === 'GET' ? jsonResponse(200, { ok: 1 }) : jsonResponse(409, { detail: { message: 'Study is running' } })));
    await expect(net.req('GET', net.docUrl('D/1', 'sim'))).resolves.toEqual({ ok: 1 });
    await expect(net.req('POST', net.docUrl('D/1', 'sim/run'), {})).rejects.toMatchObject({ status: 409, message: 'Study is running' });
    expect(sent.map((s) => [s.url, s.headers['X-FormCAD-Token']])).toEqual([['/api/docs/D%2F1/sim', 'k-net'], ['/api/docs/D%2F1/sim/run', 'k-net']]);
  });
});
