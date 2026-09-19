export type ApiErrorCode =
  | "unauthorized"
  | "expired"
  | "stale_revision"
  | "rule_mismatch"
  | "unavailable"
  | "invalid_input"
  | "unknown";

export class ApiError extends Error {
  readonly status: number;
  readonly code: ApiErrorCode;
  readonly retryable: boolean;
  readonly details?: unknown;

  constructor(
    status: number,
    code: ApiErrorCode,
    message: string,
    retryable: boolean,
    details?: unknown,
  ) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.code = code;
    this.retryable = retryable;
    this.details = details;
  }
}

export interface RequestOptions {
  body?: unknown;
  headers?: HeadersInit;
  signal?: AbortSignal;
}

export interface RestClientOptions {
  baseUrl: string;
  getToken?: () => Promise<string | null>;
  timeoutMs?: number;
  fetchImpl?: typeof fetch;
}

const KNOWN_CODES = new Set<ApiErrorCode>([
  "unauthorized",
  "expired",
  "stale_revision",
  "rule_mismatch",
  "unavailable",
  "invalid_input",
]);

export class RestClient {
  readonly #baseUrl: string;
  readonly #getToken?: () => Promise<string | null>;
  readonly #timeoutMs: number;
  readonly #fetch: typeof fetch;

  constructor(options: RestClientOptions) {
    this.#baseUrl = options.baseUrl.replace(/\/$/, "");
    this.#getToken = options.getToken;
    this.#timeoutMs = options.timeoutMs ?? 10_000;
    this.#fetch = options.fetchImpl ?? globalThis.fetch.bind(globalThis);
  }

  async request<T>(
    method: string,
    path: string,
    options: RequestOptions = {},
  ): Promise<T> {
    const controller = new AbortController();
    const abort = () => controller.abort(options.signal?.reason);
    if (options.signal?.aborted) abort();
    else options.signal?.addEventListener("abort", abort, { once: true });

    const timeout = setTimeout(
      () => controller.abort(new DOMException("Request timed out", "TimeoutError")),
      this.#timeoutMs,
    );

    try {
      const token = await this.#getToken?.();
      const headers = new Headers(options.headers);
      headers.set("Accept", "application/json");
      if (token) headers.set("Authorization", `Bearer ${token}`);
      if (options.body !== undefined) headers.set("Content-Type", "application/json");

      const response = await this.#fetch(
        `${this.#baseUrl}/${path.replace(/^\//, "")}`,
        {
          method,
          headers,
          body: options.body === undefined ? undefined : JSON.stringify(options.body),
          signal: controller.signal,
        },
      );
      const payload = await readPayload(response);

      if (!response.ok) throw toApiError(response.status, payload);
      return payload as T;
    } catch (error) {
      if (error instanceof ApiError) throw error;
      const message =
        error instanceof Error ? error.message : "Network request failed";
      throw new ApiError(0, "unavailable", message, true);
    } finally {
      clearTimeout(timeout);
      options.signal?.removeEventListener("abort", abort);
    }
  }
}

async function readPayload(response: Response): Promise<unknown> {
  if (response.status === 204) return undefined;
  const text = await response.text();
  if (!text) return undefined;
  try {
    return JSON.parse(text);
  } catch {
    return text;
  }
}

function toApiError(status: number, payload: unknown): ApiError {
  const body = asRecord(payload);
  const error = asRecord(body?.error) ?? body;
  const rawCode = typeof error?.code === "string" ? error.code : "unknown";
  const code = KNOWN_CODES.has(rawCode as ApiErrorCode)
    ? (rawCode as ApiErrorCode)
    : "unknown";
  const message =
    typeof error?.message === "string" ? error.message : `HTTP ${status}`;
  const retryable = status === 408 || status === 429 || status >= 500;
  return new ApiError(status, code, message, retryable, error?.details);
}

function asRecord(value: unknown): Record<string, unknown> | undefined {
  return value !== null && typeof value === "object"
    ? (value as Record<string, unknown>)
    : undefined;
}
