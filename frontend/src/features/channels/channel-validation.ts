const YOUTUBE_HOSTS = new Set([
  "youtube.com",
  "www.youtube.com",
  "m.youtube.com",
  "music.youtube.com",
]);
const CHANNEL_TABS = new Set([
  "videos",
  "featured",
  "streams",
  "shorts",
  "playlists",
  "community",
  "posts",
  "about",
  "live",
  "releases",
  "podcasts",
]);
const CHANNEL_ID_RE = /^UC[A-Za-z0-9_-]{6,62}$/;
const VIDEO_ID_RE = /^[A-Za-z0-9_-]{6,32}$/;

export function validateChannelUrl(rawUrl: string): string | null {
  const trimmed = rawUrl.trim();
  if (!trimmed) return "Channel URL is required.";

  let parsed: URL;
  try {
    parsed = new URL(trimmed);
  } catch {
    return "Enter a valid YouTube channel URL (e.g. https://www.youtube.com/@handle).";
  }

  if (parsed.protocol !== "http:" && parsed.protocol !== "https:") {
    return "Channel URL must start with http:// or https://.";
  }
  if (!YOUTUBE_HOSTS.has(parsed.hostname.toLowerCase())) {
    return "Channel URL must use a youtube.com domain.";
  }

  let segments = parsed.pathname.split("/").filter(Boolean);
  if (segments.length === 0) {
    return "Channel URL must point to /@handle, /channel/UC..., /c/name, or /user/name.";
  }
  if (
    segments.length >= 2 &&
    CHANNEL_TABS.has(segments[segments.length - 1].toLowerCase())
  ) {
    segments = segments.slice(0, -1);
  }

  if (segments[0].startsWith("@")) {
    if (segments.length !== 1 || segments[0].length < 3) {
      return "YouTube handle URL is invalid.";
    }
    return null;
  }

  const prefix = segments[0].toLowerCase();
  if (prefix === "channel") {
    if (segments.length !== 2 || !CHANNEL_ID_RE.test(segments[1])) {
      return "YouTube /channel/ URL must include a valid UC... channel ID.";
    }
    return null;
  }

  if ((prefix === "c" || prefix === "user") && segments.length === 2) {
    return null;
  }

  return "Channel URL must point to /@handle, /channel/UC..., /c/name, or /user/name.";
}

export function validateSampleVideoUrl(rawUrl: string): string | null {
  const trimmed = rawUrl.trim();
  if (!trimmed) return null;

  let parsed: URL;
  try {
    parsed = new URL(trimmed);
  } catch {
    return "Enter a valid YouTube video URL (e.g. https://www.youtube.com/watch?v=...).";
  }

  if (parsed.protocol !== "http:" && parsed.protocol !== "https:") {
    return "Sample video URL must start with http:// or https://.";
  }

  const host = parsed.hostname.toLowerCase();
  const segments = parsed.pathname.split("/").filter(Boolean);
  let videoId: string | null = null;

  if (host === "youtu.be") {
    if (segments.length === 1) videoId = segments[0];
  } else if (YOUTUBE_HOSTS.has(host)) {
    if (segments.length === 1 && segments[0] === "watch") {
      videoId = parsed.searchParams.get("v");
    } else if (
      segments.length === 2 &&
      ["shorts", "live", "embed"].includes(segments[0].toLowerCase())
    ) {
      videoId = segments[1];
    }
  } else {
    return "Sample video URL must use youtube.com or youtu.be.";
  }

  if (!videoId || !VIDEO_ID_RE.test(videoId)) {
    return "Sample video URL must include a valid YouTube video ID.";
  }
  return null;
}

export function validateYoutubeChannelId(rawId: string): string | null {
  const trimmed = rawId.trim();
  if (!trimmed) return null;
  if (!CHANNEL_ID_RE.test(trimmed)) {
    return "YouTube channel ID must start with 'UC' and use letters, numbers, '_' or '-'.";
  }
  return null;
}
