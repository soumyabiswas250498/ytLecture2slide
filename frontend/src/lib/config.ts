import { z } from "zod";

const apiUrl = z.string().refine((value) => {
  if (value.startsWith("/") && !value.startsWith("//") && !value.includes("\\"))
    return true;
  try {
    return ["http:", "https:"].includes(new URL(value).protocol);
  } catch {
    return false;
  }
}, "VITE_API_URL must be an HTTP(S) URL or an absolute path");

export const config = z
  .object({ apiUrl })
  .parse({ apiUrl: import.meta.env.VITE_API_URL ?? "/api/v1" });
