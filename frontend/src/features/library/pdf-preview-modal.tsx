import { Download } from "lucide-react";
import { Modal } from "@/components/ui/modal";
import { pdfDownloadUrl, pdfPreviewUrl } from "@/services/pdfs";

export function PdfPreviewModal({
  open,
  videoId,
  title,
  filename,
  onClose,
}: {
  open: boolean;
  videoId: number | null;
  title: string;
  filename?: string | null;
  onClose: () => void;
}) {
  return (
    <Modal
      open={open && videoId !== null}
      title={title}
      description={filename ?? undefined}
      size="fullscreen"
      onClose={onClose}
    >
      {open && videoId !== null && (
        <div className="flex h-full flex-col gap-3">
          <div className="flex items-center justify-between gap-2">
            <span className="text-xs text-muted-foreground">
              Original-resolution lossless PDF preview
            </span>
            <a
              href={pdfDownloadUrl(videoId)}
              download={filename ?? undefined}
              className="inline-flex h-8 items-center gap-1.5 rounded-md border border-border bg-white px-3 text-xs font-medium text-foreground hover:bg-muted"
            >
              <Download size={13} aria-hidden="true" />
              Download PDF
            </a>
          </div>
          <iframe
            title={`PDF preview for ${title}`}
            src={pdfPreviewUrl(videoId)}
            className="min-h-[70vh] w-full flex-1 rounded-lg border border-border bg-muted/20"
          />
        </div>
      )}
    </Modal>
  );
}
