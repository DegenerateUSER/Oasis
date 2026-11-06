import { beforeEach, describe, expect, it, vi } from 'vitest';
import { api, download } from './api';

beforeEach(() => { document.head.innerHTML = '<meta name="oasis-token" content="session-test">'; });
describe('local API transport', () => {
  it('authenticates same-origin JSON requests without putting a token in URLs or credentials', async () => {
    const transport = vi.spyOn(globalThis, 'fetch').mockResolvedValue(new Response(JSON.stringify({ id: 'new' }), { status: 201 }));
    expect(await api('/api/import', { method: 'POST', body: JSON.stringify({ source_id: 'historical-master' }) })).toEqual({ id: 'new' });
    expect(transport).toHaveBeenCalledWith('/api/import', expect.objectContaining({ method: 'POST', credentials: 'omit', headers: expect.any(Headers) }));
    const headers = new Headers(transport.mock.calls[0][1]?.headers);
    expect(headers.get('X-Oasis-Token')).toBe('session-test');
    expect(headers.get('Content-Type')).toBe('application/json');
  });
  it('surfaces actionable API failures instead of displaying successful-looking data', async () => {
    vi.spyOn(globalThis, 'fetch').mockResolvedValueOnce(new Response(JSON.stringify({ error: 'Dirty tracked state; use a worktree.' }), { status: 409 })).mockResolvedValueOnce(new Response('Gateway failure', { status: 500 }));
    await expect(api('/api/jobs')).rejects.toThrow('Dirty tracked state; use a worktree.');
    await expect(api('/api/jobs')).rejects.toThrow('Local request failed (500).');
  });
  it('downloads protected CSV via authenticated fetch and revokes the temporary URL', async () => {
    const transport = vi.spyOn(globalThis, 'fetch').mockResolvedValue(new Response('repo_name,mutant_id\na,m1', { headers: { 'Content-Type': 'text/csv' } }));
    const create = vi.fn(() => 'blob:test'); const revoke = vi.fn();
    Object.defineProperty(URL, 'createObjectURL', { configurable: true, value: create });
    Object.defineProperty(URL, 'revokeObjectURL', { configurable: true, value: revoke });
    const click = vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => {});
    await download('/api/datasets/data/csv?status=survived', 'oasis.csv');
    expect(transport.mock.calls[0][0]).toBe('/api/datasets/data/csv?status=survived');
    expect(new Headers(transport.mock.calls[0][1]?.headers).get('X-Oasis-Token')).toBe('session-test');
    expect(click).toHaveBeenCalledOnce(); expect(create).toHaveBeenCalledOnce(); expect(revoke).toHaveBeenCalledWith('blob:test');
  });
});
