export class ApiError extends Error {
  status: number;
  code: string;

  constructor(status: number, code: string, message?: string) {
    super(message ?? code);
    this.status = status;
    this.code = code;
  }
}

/** Same-origin fetch wrapper. Cookies flow automatically; non-2xx becomes a
 * typed ApiError; a 401 anywhere except /api/auth/me announces session
 * expiry so the app can route to /login. */
export async function apiFetch<T>(
  path: string,
  opts: RequestInit & { json?: unknown } = {},
): Promise<T> {
  const { json, ...init } = opts;
  if (json !== undefined) {
    init.body = JSON.stringify(json);
    init.headers = { "Content-Type": "application/json", ...init.headers };
    init.method = init.method ?? "POST";
  }
  const res = await fetch(path, { credentials: "same-origin", ...init });
  if (res.status === 401 && path !== "/api/auth/me") {
    window.dispatchEvent(new CustomEvent("session-expired"));
  }
  if (!res.ok) {
    let code = `http_${res.status}`;
    try {
      const body = await res.json();
      if (typeof body.detail === "string") code = body.detail;
    } catch {
      /* non-JSON error body */
    }
    throw new ApiError(res.status, code);
  }
  if (res.status === 204) return undefined as T;
  return (await res.json()) as T;
}
