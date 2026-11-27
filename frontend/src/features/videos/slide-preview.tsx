import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Button } from "@/components/ui/button";
import { LoadingState, ErrorState } from "@/components/shared/states";
import { getSlides, slideUrl } from "@/services/slides";

export function SlidePreview({ videoId }: { videoId: number }) {
  const [page, setPage] = useState(1);
  const query = useQuery({
    queryKey: ["slides", videoId, page],
    queryFn: ({ signal }) => getSlides(videoId, page, signal),
  });
  if (query.isPending)
    return <LoadingState message="Loading slide comparisons…" />;
  if (query.isError)
    return (
      <ErrorState
        message={query.error.message}
        onRetry={() => void query.refetch()}
      />
    );
  return (
    <div className="space-y-4">
      <p>
        Open any image for full resolution. Measurements are visibility
        heuristics, not reconstruction accuracy.
      </p>
      {query.data.warnings.map((warning) => (
        <p key={warning}>{warning}</p>
      ))}
      {query.data.items.length === 0 && <p>No slides on this page.</p>}
      {query.data.items.map((slide) => (
        <article key={slide.slide_id} className="space-y-2 rounded border p-3">
          <h3>
            {slide.slide_id} · {slide.source_timestamps.join(", ")}s ·{" "}
            {slide.reconstruction_method}
          </h3>
          <p>
            {slide.fallback && "Fallback · "}
            {slide.incomplete && "Incomplete · "}
            {slide.manual_review && "Manual review required"}
          </p>
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
            {(
              [
                ["Original screenshot", slide.original_image_path],
                ["Cropped smartboard", slide.cropped_image_path],
                ["Reconstructed slide", slide.processed_image_path],
                ["Obstruction mask (heuristic)", slide.obstruction_mask_path],
              ] as const
            ).map(([label, name]) => (
              <figure key={label}>
                <a
                  href={slideUrl(videoId, query.data.generation, name)}
                  target="_blank"
                  rel="noreferrer"
                >
                  <img
                    src={slideUrl(videoId, query.data.generation, name)}
                    alt={`${label} for ${slide.slide_id}`}
                    loading="lazy"
                    className="w-full"
                  />
                </a>
                <figcaption>{label}</figcaption>
              </figure>
            ))}
          </div>
          <p>
            Suspected obstruction:{" "}
            {(slide.quality.obstruction_fraction * 100).toFixed(1)}% ·
            Unresolved: {(slide.quality.unresolved_fraction * 100).toFixed(1)}%
          </p>
          {slide.warnings.map((warning) => (
            <p key={warning} className="text-sm">
              {warning}
            </p>
          ))}
        </article>
      ))}
      <div className="flex gap-3">
        <Button disabled={page === 1} onClick={() => setPage(page - 1)}>
          Previous slides
        </Button>
        <span>
          Page {page} · {query.data.total} slides
        </span>
        <Button
          disabled={page * query.data.page_size >= query.data.total}
          onClick={() => setPage(page + 1)}
        >
          Next slides
        </Button>
      </div>
    </div>
  );
}
