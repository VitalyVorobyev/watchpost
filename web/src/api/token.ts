/** Pairing token handling.
 *
 * The token arrives once, in the URL of the QR code the Mac displays. It is persisted and
 * then stripped from the address bar so it does not linger in browser history or get
 * shared when someone copies the URL. See ADR-0006.
 */

const KEY = "watchpost.token";

let cached: string | null = null;

export function bootstrapToken(): string | null {
  if (cached) return cached;

  const params = new URLSearchParams(window.location.search);
  const fromUrl = params.get("t");
  if (fromUrl) {
    localStorage.setItem(KEY, fromUrl);
    cached = fromUrl;
    params.delete("t");
    const query = params.toString();
    window.history.replaceState(
      {},
      "",
      window.location.pathname + (query ? `?${query}` : "") + window.location.hash,
    );
    return cached;
  }

  cached = localStorage.getItem(KEY);
  return cached;
}

export function getToken(): string | null {
  return cached ?? localStorage.getItem(KEY);
}

export function setToken(token: string): void {
  cached = token;
  localStorage.setItem(KEY, token);
}

export function clearToken(): void {
  cached = null;
  localStorage.removeItem(KEY);
}

/** Append the token to a media URL.
 *
 * `<img>` and `<video>` cannot set an Authorization header, so media has to carry the
 * token in the query string. Only use this for element `src` attributes — fetch() calls
 * use the header instead.
 */
export function withToken(path: string): string {
  const token = getToken();
  if (!token) return path;
  const separator = path.includes("?") ? "&" : "?";
  return `${path}${separator}t=${encodeURIComponent(token)}`;
}
