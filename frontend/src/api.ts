export const DEFAULT_BASE_URL = process.env.EXPO_PUBLIC_BACKEND_URL ?? "";

let baseUrl: string = DEFAULT_BASE_URL;
let token: string | null = null;
let unauthorizedHandler: (() => void) | null = null;

// Runtime override so the same app build can talk to a self-hosted VPS.
export function setBaseUrl(url: string | null) {
  baseUrl = (url || DEFAULT_BASE_URL).replace(/\/+$/, "");
}

export function getBaseUrl() {
  return baseUrl;
}

export function setToken(t: string | null) {
  token = t;
}

export function setUnauthorizedHandler(fn: () => void) {
  unauthorizedHandler = fn;
}

export class ApiError extends Error {
  status: number;
  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}

type Method = "GET" | "POST" | "PATCH" | "PUT" | "DELETE";

async function request<T>(method: Method, path: string, body?: unknown): Promise<T> {
  let res: Response;
  try {
    res = await fetch(`${baseUrl}/api${path}`, {
      method,
      headers: {
        "Content-Type": "application/json",
        ...(token ? { Authorization: `Bearer ${token}` } : {}),
      },
      body: body === undefined ? undefined : JSON.stringify(body),
    });
  } catch {
    throw new ApiError(0, "Network error — internet check karo");
  }
  if (res.status === 401 && !path.startsWith("/auth/login")) {
    unauthorizedHandler?.();
  }
  if (!res.ok) {
    let detail = `Request failed (${res.status})`;
    try {
      const data = await res.json();
      if (typeof data.detail === "string") detail = data.detail;
      else if (Array.isArray(data.detail)) detail = data.detail[0]?.msg ?? detail;
    } catch {
      // ignore
    }
    throw new ApiError(res.status, detail);
  }
  return (await res.json()) as T;
}

export const api = {
  get: <T>(path: string) => request<T>("GET", path),
  post: <T>(path: string, body?: unknown) => request<T>("POST", path, body),
  patch: <T>(path: string, body?: unknown) => request<T>("PATCH", path, body),
  put: <T>(path: string, body?: unknown) => request<T>("PUT", path, body),
  del: <T>(path: string) => request<T>("DELETE", path),
};
