import { useCallback, useEffect, useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { ChevronLeft, ChevronRight, ExternalLink } from "lucide-react";
import { Button } from "@/components/ui/button";
import { ErrorState, LoadingState } from "@/components/shared/states";
import { getSlides, slideUrl } from "@/services/slides";

function formatHMS(seconds: number): string {
  const total = Math.max(0, Math.round(seconds));
  const h = Math.floor(total / 3600);
  const m = Math.floor((total % 3600) / 60);
  const s = total % 60;
  return [h, m, s].map((v) => String(v).padStart(2, "0")).join(":");
}

export function SlidePreview({ videoId }: { videoId: number }) {
  const [slideNumber, setSlideNumber] = useState(1);
  const [jumpValue, setJumpValue] = useState("1");

  const query = useQuery({
    queryKey: ["slides", videoId, slideNumber, 1],
    queryFn: ({ signal }) => getSlides(videoId, slideNumber, signal, 1),
  });

  const total = query.data?.total ?? 0;
  const slide = query.data?.items[0];

  const goTo = useCallback(
    (target: number) => {
      if (total <= 0) return;
      const clamped = Math.max(1, Math.min(total, target));
      setSlideNumber(clamped);
      setJumpValue(String(clamped));
    },
    [total],
  );

  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      const target = event.target as HTMLElement | null;
      if (
        target &&
        (target.tagName === "INPUT" ||
          target.tagName === "TEXTAREA" ||
          target.isContentEditable)
      ) {
        return;
      }
      if (event.key === "ArrowLeft") {
        event.preventDefault();
        goTo(slideNumber - 1);
      } else if (event.key === "ArrowRight") {
        event.preventDefault();
        goTo(slideNumber + 1);
      }
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [goTo, slideNumber]);

  const consolidatedWarnings = useMemo(() => {
    if (!query.data) return [];
    const merged = [
      ...query.data.warnings,
      ...(slide?.warnings ?? []).filter(
        (w) => !w.toLowerCase().includes("board boundary"),
      ),
    ];
    return Array.from(new Set(merged));
  }, [query.data, slide]);

  if (query.isPending) {
    return <LoadingState message="Loading slide preview…" />;
  }
  if (query.isError) {
    return (
      <ErrorState
        message={query.error.message}
        onRetry={() => void query.refetch()}
      />
    );
  }
  if (!slide || total === 0) {
    return (
      <p className="text-sm text-muted-foreground">No slides available.</p>
    );
  }

  const identical = slide.processed_image_path === slide.original_image_path;
  const primaryTimestamp = formatHMS(slide.source_timestamps[0] ?? 0);
  const originalHref = slideUrl(
    videoId,
    query.data.generation,
    slide.original_image_path,
  );
  const processedHref = slideUrl(
    videoId,
    query.data.generation,
    slide.processed_image_path,
  );

  return (
    <div className="flex h-full flex-col gap-3 text-sm">
      <div className="sticky top-0 z-10 flex flex-wrap items-center justify-between gap-3 rounded-lg border border-border bg-white px-3 py-2 shadow-xs">
        <div className="flex items-center gap-2">
          <Button
            type="button"
            size="sm"
            variant="outline"
            disabled={slideNumber <= 1}
            onClick={() => goTo(slideNumber - 1)}
            aria-label="Previous slide"
          >
            <ChevronLeft size={14} aria-hidden="true" />
            Previous
          </Button>
          <span className="text-xs font-medium tabular-nums">
            Slide {slideNumber} of {total}
          </span>
          <Button
            type="button"
            size="sm"
            variant="outline"
            disabled={slideNumber >= total}
            onClick={() => goTo(slideNumber + 1)}
            aria-label="Next slide"
          >
            Next
            <ChevronRight size={14} aria-hidden="true" />
          </Button>
        </div>

        <div className="flex flex-wrap items-center gap-3">
          <span className="rounded bg-muted px-2 py-0.5 text-xs font-medium tabular-nums">
            {primaryTimestamp}
          </span>
          {slide.manual_review && (
            <span className="rounded bg-amber-50 px-2 py-0.5 text-xs text-amber-800">
              Potentially obstructed
            </span>
          )}
          <form
            className="flex items-center gap-1.5"
            onSubmit={(event) => {
              event.preventDefault();
              const parsed = Number.parseInt(jumpValue, 10);
              if (!Number.isNaN(parsed)) goTo(parsed);
            }}
          >
            <label
              htmlFor="slide-jump-input"
              className="text-xs text-muted-foreground"
            >
              Go to
            </label>
            <input
              id="slide-jump-input"
              type="number"
              min={1}
              max={total}
              value={jumpValue}
              onChange={(event) => setJumpValue(event.target.value)}
              className="h-7 w-16 rounded border border-border px-2 text-xs tabular-nums focus:border-primary focus:outline-none"
            />
            <Button type="submit" size="sm" variant="outline">
              Go
            </Button>
          </form>
        </div>
      </div>

      {identical ? (
        <figure className="flex flex-1 flex-col items-center justify-center rounded-lg border border-border bg-muted/20 p-3">
          <a
            href={processedHref}
            target="_blank"
            rel="noreferrer"
            className="group relative block max-w-full"
            title="Open original resolution in new tab"
          >
            <img
              src={processedHref}
              alt={`Slide ${slideNumber} at ${primaryTimestamp}`}
              className="mx-auto max-h-[66vh] w-auto max-w-full rounded object-contain"
            />
          </a>
          <figcaption className="mt-2 flex items-center gap-2 text-xs text-muted-foreground">
            <span>Original full-frame screenshot ({primaryTimestamp})</span>
            <a
              href={processedHref}
              target="_blank"
              rel="noreferrer"
              className="inline-flex items-center gap-1 text-primary hover:underline"
            >
              Full resolution
              <ExternalLink size={11} aria-hidden="true" />
            </a>
          </figcaption>
        </figure>
      ) : (
        <div className="grid flex-1 grid-cols-1 gap-4 lg:grid-cols-2">
          <figure className="flex flex-col items-center justify-center rounded-lg border border-border bg-muted/20 p-3">
            <a
              href={originalHref}
              target="_blank"
              rel="noreferrer"
              className="block max-w-full"
              title="Open original screenshot in new tab"
            >
              <img
                src={originalHref}
                alt={`Original screenshot for slide ${slideNumber}`}
                className="mx-auto max-h-[64vh] w-auto max-w-full rounded object-contain"
              />
            </a>
            <figcaption className="mt-2 flex items-center gap-2 text-xs text-muted-foreground">
              <span>Original screenshot</span>
              <a
                href={originalHref}
                target="_blank"
                rel="noreferrer"
                className="inline-flex items-center gap-1 text-primary hover:underline"
              >
                Full resolution
                <ExternalLink size={11} aria-hidden="true" />
              </a>
            </figcaption>
          </figure>
          <figure className="flex flex-col items-center justify-center rounded-lg border border-border bg-muted/20 p-3">
            <a
              href={processedHref}
              target="_blank"
              rel="noreferrer"
              className="block max-w-full"
              title="Open processed screenshot in new tab"
            >
              <img
                src={processedHref}
                alt={`Processed screenshot for slide ${slideNumber}`}
                className="mx-auto max-h-[64vh] w-auto max-w-full rounded object-contain"
              />
            </a>
            <figcaption className="mt-2 flex items-center gap-2 text-xs text-muted-foreground">
              <span>Processed screenshot</span>
              <a
                href={processedHref}
                target="_blank"
                rel="noreferrer"
                className="inline-flex items-center gap-1 text-primary hover:underline"
              >
                Full resolution
                <ExternalLink size={11} aria-hidden="true" />
              </a>
            </figcaption>
          </figure>
        </div>
      )}

      <details className="rounded-lg border border-border bg-muted/20 px-3 py-2 text-xs text-muted-foreground">
        <summary className="cursor-pointer font-medium text-foreground">
          Technical diagnostics
        </summary>
        <div className="mt-2 space-y-1.5">
          <p>
            Method: {slide.reconstruction_method}
            {slide.quality_category
              ? ` · Quality: ${slide.quality_category}`
              : ""}
            {` · Suspected obstruction: ${(slide.quality.obstruction_fraction * 100).toFixed(1)}%`}
            {` · Unresolved: ${(slide.quality.unresolved_fraction * 100).toFixed(1)}%`}
          </p>
          <p>
            Timestamps:{" "}
            {slide.source_timestamps.map((ts) => formatHMS(ts)).join(", ")}
          </p>
          {slide.selection_reason && <p>{slide.selection_reason}</p>}
          {consolidatedWarnings.length > 0 && (
            <ul className="list-disc pl-4 text-amber-800">
              {consolidatedWarnings.map((warning) => (
                <li key={warning}>{warning}</li>
              ))}
            </ul>
          )}
        </div>
      </details>
    </div>
  );
}
