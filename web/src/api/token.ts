/** Pairing token handling.
 *
 * The token arrives once, in the URL of the QR code the Mac displays. See ADR-0006.
 */

const KEY = "watchpost.token";

let cached: string | null = null;

/** Whether the page is running as an installed home-screen app rather than in a tab. */
export function isStandalone(): boolean {
  return (
    window.matchMedia?.("(display-mode: standalone)").matches === true ||
    // iOS predates display-mode and reports installation on navigator instead.
    (window.navigator as Navigator & { standalone?: boolean }).standalone === true
  );
}

export function bootstrapToken(): string | null {
  if (cached) return cached;

  const params = new URLSearchParams(window.location.search);
  const fromUrl = params.get("t");
  if (fromUrl) {
    localStorage.setItem(KEY, fromUrl);
    cached = fromUrl;

    // Only clean the address bar once installed. In a tab the token has to stay in the
    // URL: "Add to Home Screen" captures whatever is in the address bar, and an installed
    // iOS web app gets its *own* storage container — the token Safari just saved is
    // invisible to it. Strip it here and the installed app launches unauthenticated
    // every time, with no way to recover short of re-adding it. Standalone has no address
    // bar to clean, but stripping keeps the token out of any link shared from the app.
    if (isStandalone()) {
      params.delete("t");
      const query = params.toString();
      window.history.replaceState(
        {},
        "",
        window.location.pathname + (query ? `?${query}` : "") + window.location.hash,
      );
    }
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
