import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Button } from "@/components/ui/button";
import { ErrorState, LoadingState } from "@/components/shared/states";
import { frameUrl, getFrames } from "@/services/extractions";

export function FramePreview({ videoId }: { videoId: number }) {
  const [page, setPage] = useState(1);
  const query = useQuery({
    queryKey: ["frames", videoId, page],
    queryFn: ({ signal }) => getFrames(videoId, page, signal),
  });
  if (query.isPending) return <LoadingState message="Loading frames…" />;
  if (query.isError)
    return (
      <ErrorState
        message={query.error.message}
        onRetry={() => void query.refetch()}
      />
    );
  return (
    <div className="space-y-4">
      <p>Open a screenshot to view its original resolution.</p>
      <div className="grid grid-cols-2 gap-3">
        {query.data.items.map((frame) => (
          <figure key={frame.filename}>
            <a
              href={frameUrl(videoId, frame.filename)}
              target="_blank"
              rel="noreferrer"
            >
              <img
                src={frameUrl(videoId, frame.filename)}
                alt={`Frame at ${frame.actual_timestamp.toFixed(3)} seconds`}
                loading="lazy"
                className="w-full"
              />
            </a>
            <figcaption className="text-sm">
              {frame.actual_timestamp.toFixed(3)}s · {frame.width}×
              {frame.height}
              <br />
              Requested: {frame.requested_timestamp.toFixed(3)}s
            </figcaption>
          </figure>
        ))}
      </div>
      {query.data.items.length === 0 && <p>No frames on this page.</p>}
      <div className="flex items-center gap-3">
        <Button disabled={page === 1} onClick={() => setPage(page - 1)}>
          Previous frames
        </Button>
        <span>
          Page {page} · {query.data.total} frames
        </span>
        <Button
          disabled={page * query.data.page_size >= query.data.total}
          onClick={() => setPage(page + 1)}
        >
          Next frames
        </Button>
      </div>
    </div>
  );
}
