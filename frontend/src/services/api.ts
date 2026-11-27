import { z } from "zod";
import { config } from "@/lib/config";

export class ApiError extends Error {
  constructor(
    message: string,
    public readonly status?: number,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

const errorSchema = z.object({ error: z.object({ message: z.string() }) });

function buildApiUrl(path: string): string {
  return `${config.apiUrl.replace(/\/$/, "")}/${path.replace(/^\//, "")}`;
}

async function rawFetch(path: string, init?: RequestInit): Promise<Response> {
  try {
    return await fetch(buildApiUrl(path), init);
  } catch (error) {
    if (
      (error instanceof Error || error instanceof DOMException) &&
      error.name === "AbortError"
    )
      throw error;
    throw new ApiError("Cannot reach the backend. Check that it is running.");
  }
}

async function parseErrorResponse(response: Response): Promise<never> {
  const body: unknown = await response.json().catch(() => null);
  const parsed = errorSchema.safeParse(body);
  throw new ApiError(
    parsed.success
      ? parsed.data.error.message
      : `Request failed (${response.status}).`,
    response.status,
  );
}

export async function apiRequest<T>(
  path: string,
  schema: z.ZodType<T>,
  init?: RequestInit,
): Promise<T> {
  const headers = new Headers(init?.headers);
  if (!headers.has("Accept")) {
    headers.set("Accept", "application/json");
  }
  const response = await rawFetch(path, { ...init, headers });
  if (!response.ok) {
    await parseErrorResponse(response);
  }
  const body: unknown = await response.json().catch(() => null);
  const parsed = schema.safeParse(body);
  if (!parsed.success)
    throw new ApiError(
      "The backend returned an invalid response.",
      response.status,
    );
  return parsed.data;
}

export async function apiGet<T>(
  path: string,
  schema: z.ZodType<T>,
  signal?: AbortSignal,
): Promise<T> {
  return apiRequest(path, schema, { signal });
}

export async function apiPost<T>(
  path: string,
  body: unknown,
  schema: z.ZodType<T>,
): Promise<T> {
  return apiRequest(path, schema, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
}

export async function apiPatch<T>(
  path: string,
  body: unknown,
  schema: z.ZodType<T>,
): Promise<T> {
  return apiRequest(path, schema, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
}

export async function apiPut<T>(
  path: string,
  body: unknown,
  schema: z.ZodType<T>,
): Promise<T> {
  return apiRequest(path, schema, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
}

export async function apiDelete(path: string): Promise<void> {
  const response = await rawFetch(path, {
    method: "DELETE",
    headers: { Accept: "application/json" },
  });
  if (!response.ok) {
    await parseErrorResponse(response);
  }
}

export async function apiUpload<T>(
  path: string,
  formData: FormData,
  schema: z.ZodType<T>,
): Promise<T> {
  return apiRequest(path, schema, {
    method: "POST",
    body: formData,
  });
}

export async function apiDownloadText(path: string): Promise<string> {
  const response = await rawFetch(path, {
    headers: { Accept: "text/csv, text/plain" },
  });
  if (!response.ok) {
    await parseErrorResponse(response);
  }
  return response.text();
}

export const healthSchema = z.object({ status: z.literal("ok") });

export function getHealth(signal?: AbortSignal) {
  return apiGet("health", healthSchema, signal);
}
