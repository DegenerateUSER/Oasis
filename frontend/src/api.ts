async function request(path: string, options: RequestInit = {}): Promise<Response> {
  if (!path.startsWith('/api/')) throw new Error('Only the local Oasis API is supported.');
  const headers = new Headers(options.headers);
  headers.set('X-Oasis-Token', document.querySelector<HTMLMetaElement>('meta[name="oasis-token"]')?.content || '');
  if (options.body) headers.set('Content-Type', 'application/json');
  const response = await fetch(path, { ...options, credentials: 'omit', headers });
  if (!response.ok) {
    const body = await response.json().catch(() => null);
    throw new Error(body?.error || `Local request failed (${response.status}).`);
  }
  return response;
}
export async function api<T>(path: string, options: RequestInit = {}): Promise<T> {
  return (await request(path, options)).json() as Promise<T>;
}
export function saveBlob(blob: Blob, filename: string): void {
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement('a');
  anchor.href = url; anchor.download = filename;
  document.body.append(anchor); anchor.click(); anchor.remove();
  URL.revokeObjectURL(url);
}
export async function download(path: string, filename: string): Promise<void> {
  saveBlob(await (await request(path)).blob(), filename);
}
