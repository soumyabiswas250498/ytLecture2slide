import { afterEach, expect, it, vi } from "vitest";
import { ApiError, getHealth } from "./api";
afterEach(() => vi.unstubAllGlobals());
function respond(body: unknown, status = 200) {
  vi.stubGlobal(
    "fetch",
    vi.fn().mockResolvedValue(new Response(JSON.stringify(body), { status })),
  );
}
it("validates successful responses", async () => {
  respond({ status: "ok" });
  await expect(getHealth()).resolves.toEqual({ status: "ok" });
});
it("rejects invalid success payloads", async () => {
  respond({ status: "invented" });
  await expect(getHealth()).rejects.toThrow("invalid response");
});
it("uses structured backend errors", async () => {
  respond({ error: { message: "Database unavailable" } }, 503);
  await expect(getHealth()).rejects.toMatchObject({
    message: "Database unavailable",
    status: 503,
  });
});
it("handles non-JSON error responses", async () => {
  vi.stubGlobal(
    "fetch",
    vi
      .fn()
      .mockResolvedValue(new Response("upstream failure", { status: 502 })),
  );
  await expect(getHealth()).rejects.toThrow("Request failed (502)");
});
it("reports network failures", async () => {
  vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new TypeError("offline")));
  await expect(getHealth()).rejects.toBeInstanceOf(ApiError);
});
it("preserves request cancellation", async () => {
  const error = new DOMException("Cancelled", "AbortError");
  vi.stubGlobal("fetch", vi.fn().mockRejectedValue(error));
  await expect(getHealth()).rejects.toBe(error);
});
