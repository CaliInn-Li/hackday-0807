import {
  normalizeAnimation,
  normalizeCharacter,
  normalizeJob,
  normalizeList,
  normalizeMotion,
  asRecord,
} from "./normalize";
import type {
  AnimationAsset,
  AssetFileDownload,
  AssetKind,
  CharacterAsset,
  CreateAnimationInput,
  FileKind,
  Job,
  MotionAsset,
  RequestOptions,
  UploadMotionOptions,
} from "./types";

const API_KEY_STORAGE = "naqi.frontend.apiKey";
const API_BASE_STORAGE = "naqi.frontend.apiBase";

export interface TokenStore {
  get(): string | null;
  set(value: string): void;
  clear(): void;
}

class MemoryTokenStore implements TokenStore {
  private value: string | null = null;

  get(): string | null {
    return this.value;
  }

  set(value: string): void {
    this.value = value;
  }

  clear(): void {
    this.value = null;
  }
}

export function createSessionTokenStore(storage?: Storage): TokenStore {
  if (storage) {
    return {
      get: () => storage.getItem(API_KEY_STORAGE),
      set: (value) => storage.setItem(API_KEY_STORAGE, value),
      clear: () => storage.removeItem(API_KEY_STORAGE),
    };
  }
  if (typeof window !== "undefined" && window.sessionStorage) {
    return createSessionTokenStore(window.sessionStorage);
  }
  return new MemoryTokenStore();
}

export function getStoredApiBase(storage?: Storage): string | null {
  if (storage) return storage.getItem(API_BASE_STORAGE);
  if (typeof window !== "undefined" && window.sessionStorage) {
    return getStoredApiBase(window.sessionStorage);
  }
  return null;
}

export function setStoredApiBase(value: string, storage?: Storage): void {
  if (storage) {
    storage.setItem(API_BASE_STORAGE, value);
    return;
  }
  if (typeof window !== "undefined" && window.sessionStorage) {
    setStoredApiBase(value, window.sessionStorage);
  }
}

export function hasStoredApiKey(storage?: Storage): boolean {
  const token = createSessionTokenStore(storage).get();
  return Boolean(token?.trim());
}

export class ApiError extends Error {
  readonly status: number;

  constructor(status: number, message: string) {
    super(message);
    this.name = "ApiError";
    this.status = status;
  }
}

export function sanitizeErrorMessage(value: string): string {
  return value
    .replace(/Bearer\s+[^\s]+/gi, "Bearer [已隐藏]")
    .replace(/(api[-_ ]?key|authorization|token)[=: ]+[^,;\s]+/gi, "$1=[已隐藏]")
    .slice(0, 500);
}

function normalizeBaseUrl(value: string): string {
  return value.trim().replace(/\/+$/, "");
}

function contentDispositionFilename(value: string | null): string | undefined {
  if (!value) return undefined;
  const utf8Match = value.match(/filename\*=UTF-8''([^;]+)/i);
  if (utf8Match?.[1]) {
    try {
      return decodeURIComponent(utf8Match[1].replace(/^"|"$/g, ""));
    } catch {
      return utf8Match[1];
    }
  }
  const match = value.match(/filename="?([^";]+)"?/i);
  return match?.[1];
}

async function responseErrorMessage(response: Response): Promise<string> {
  try {
    const text = await response.text();
    if (!text) return response.statusText || `请求失败（${response.status}）`;
    try {
      const body = asRecord(JSON.parse(text));
      const detail = body.detail ?? body.message ?? body.error;
      if (typeof detail === "string") return sanitizeErrorMessage(detail);
    } catch {
      // The server may return a plain-text proxy error.
    }
    return sanitizeErrorMessage(text);
  } catch {
    return response.statusText || `请求失败（${response.status}）`;
  }
}

export interface ApiClientOptions {
  baseUrl?: string;
  tokenStore?: TokenStore;
  fetchImpl?: typeof fetch;
}

export class ApiClient {
  readonly baseUrl: string;
  private readonly tokenStore: TokenStore;
  private readonly fetchImpl: typeof fetch;

  constructor(options: ApiClientOptions = {}) {
    this.baseUrl = normalizeBaseUrl(
      options.baseUrl ?? import.meta.env.VITE_NAQI_API_BASE ?? "http://localhost:18080",
    );
    this.tokenStore = options.tokenStore ?? createSessionTokenStore();
    // Browser fetch relies on its global receiver in some runtimes. Keeping an
    // unbound reference and invoking it as an ApiClient property can otherwise
    // fail with "Illegal invocation" before the request reaches the backend.
    this.fetchImpl = options.fetchImpl ?? globalThis.fetch.bind(globalThis);
  }

  get token(): string | null {
    return this.tokenStore.get();
  }

  setToken(value: string): void {
    this.tokenStore.set(value.trim());
  }

  clearToken(): void {
    this.tokenStore.clear();
  }

  private async request(path: string, init: RequestInit = {}): Promise<Response> {
    const headers = new Headers(init.headers);
    const token = this.tokenStore.get();
    if (token) headers.set("Authorization", `Bearer ${token}`);
    if (!headers.has("Accept")) headers.set("Accept", "application/json");

    let response: Response;
    try {
      response = await this.fetchImpl(`${this.baseUrl}${path}`, {
        ...init,
        headers,
      });
    } catch (error) {
      const message = error instanceof Error ? error.message : "无法连接后端";
      throw new ApiError(0, sanitizeErrorMessage(message));
    }
    if (!response.ok) throw new ApiError(response.status, await responseErrorMessage(response));
    return response;
  }

  private async json<T>(path: string, init: RequestInit = {}): Promise<T> {
    const response = await this.request(path, init);
    if (response.status === 204) return undefined as T;
    return (await response.json()) as T;
  }

  async healthLive(options: RequestOptions = {}): Promise<unknown> {
    return this.json<unknown>("/health/live", { signal: options.signal });
  }

  async listCharacters(options: RequestOptions = {}): Promise<CharacterAsset[]> {
    const payload = await this.json<unknown>("/v1/assets/characters", { signal: options.signal });
    return normalizeList(payload, normalizeCharacter);
  }

  async uploadCharacter(file: File, options: RequestOptions = {}): Promise<unknown> {
    const form = new FormData();
    form.append("file", file, file.name);
    return this.json<unknown>("/v1/assets/characters", { method: "POST", body: form, signal: options.signal });
  }

  async listMotions(options: RequestOptions = {}): Promise<MotionAsset[]> {
    const payload = await this.json<unknown>("/v1/assets/motions", { signal: options.signal });
    return normalizeList(payload, normalizeMotion);
  }

  async uploadMotion(file: File, options: UploadMotionOptions = {}): Promise<unknown> {
    const form = new FormData();
    form.append("file", file, file.name);
    if (options.cameraMode) form.append("camera_mode", options.cameraMode);
    return this.json<unknown>("/v1/assets/motions", {
      method: "POST",
      body: form,
      signal: options.signal,
    });
  }

  async listAnimations(options: RequestOptions = {}): Promise<AnimationAsset[]> {
    const payload = await this.json<unknown>("/v1/assets/animations", { signal: options.signal });
    return normalizeList(payload, normalizeAnimation);
  }

  async createAnimation(input: CreateAnimationInput, options: RequestOptions = {}): Promise<unknown> {
    return this.json<unknown>("/v1/animations", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ character_id: input.characterId, motion_id: input.motionId }),
      signal: options.signal,
    });
  }

  async listJobs(options: RequestOptions = {}): Promise<Job[]> {
    const payload = await this.json<unknown>("/v1/jobs", { signal: options.signal });
    return normalizeList(payload, normalizeJob);
  }

  async getJob(id: string, options: RequestOptions = {}): Promise<Job> {
    const payload = await this.json<unknown>(`/v1/jobs/${encodeURIComponent(id)}`, { signal: options.signal });
    return normalizeJob(payload);
  }

  async getAssetFile(
    kind: AssetKind,
    id: string,
    fileKind: FileKind,
    download = false,
    options: RequestOptions = {},
  ): Promise<AssetFileDownload> {
    const path = `/v1/assets/${kind}/${encodeURIComponent(id)}/files/${encodeURIComponent(fileKind)}?download=${String(download)}`;
    const response = await this.request(path, { signal: options.signal, headers: { Accept: "*/*" } });
    return {
      blob: await response.blob(),
      filename: contentDispositionFilename(response.headers.get("content-disposition")),
      contentType: response.headers.get("content-type") ?? undefined,
    };
  }
}
