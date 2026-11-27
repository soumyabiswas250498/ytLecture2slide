import { useState, type FormEvent } from "react";
import { Download, Upload } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Modal } from "@/components/ui/modal";
import type { CsvImportResponse } from "@/services/channels";

export function ChannelImportModal({
  open,
  isImporting,
  error,
  result,
  onClose,
  onImport,
  onDownloadTemplate,
}: {
  open: boolean;
  isImporting: boolean;
  error: string | null;
  result: CsvImportResponse | null;
  onClose: () => void;
  onImport: (file: File) => Promise<void>;
  onDownloadTemplate: () => Promise<void>;
}) {
  const [selectedFile, setSelectedFile] = useState<File | null>(null);
  const [localError, setLocalError] = useState<string | null>(null);

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!selectedFile) {
      setLocalError("Choose a UTF-8 CSV file before importing.");
      return;
    }
    setLocalError(null);
    await onImport(selectedFile);
  }

  function handleClose() {
    setSelectedFile(null);
    setLocalError(null);
    onClose();
  }

  const displayedError = localError ?? error;

  return (
    <Modal
      open={open}
      title="Import channels from CSV"
      description="Supports UTF-8 CSV with channel_name, channel_url, sample_video_url, and optional search_keyword and is_active columns."
      onClose={handleClose}
    >
      <div className="space-y-4">
        <div className="flex flex-wrap items-center justify-between gap-2 rounded-lg border border-border bg-muted/40 p-3 text-xs text-muted-foreground">
          <span>
            Duplicates are skipped without overwriting existing records.
          </span>
          <Button
            type="button"
            variant="outline"
            size="sm"
            onClick={() => {
              void onDownloadTemplate();
            }}
          >
            <Download size={14} aria-hidden="true" />
            Download CSV template
          </Button>
        </div>

        <form
          onSubmit={(event) => {
            void handleSubmit(event);
          }}
          className="space-y-4"
        >
          {displayedError && (
            <div
              role="alert"
              className="rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-800"
            >
              {displayedError}
            </div>
          )}

          <div>
            <label
              htmlFor="csv-file-input"
              className="mb-1 block text-sm font-medium"
            >
              CSV file
            </label>
            <input
              id="csv-file-input"
              type="file"
              accept=".csv,text/csv"
              onChange={(event) => {
                setSelectedFile(event.target.files?.[0] ?? null);
                setLocalError(null);
              }}
              className="block w-full rounded-md border border-border px-3 py-2 text-sm file:mr-3 file:rounded file:border-0 file:bg-muted file:px-3 file:py-1 file:text-xs file:font-medium"
            />
          </div>

          <div className="flex justify-end gap-2">
            <Button
              type="button"
              variant="outline"
              disabled={isImporting}
              onClick={handleClose}
            >
              Close
            </Button>
            <Button type="submit" disabled={isImporting}>
              <Upload size={16} aria-hidden="true" />
              {isImporting ? "Importing…" : "Import CSV"}
            </Button>
          </div>
        </form>

        {result && (
          <div
            role="status"
            className="space-y-4 border-t border-border pt-4 text-sm"
          >
            <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
              <div className="rounded-lg border border-border p-3">
                <p className="text-xs text-muted-foreground">Total rows</p>
                <p className="mt-1 text-lg font-semibold">
                  {result.total_rows}
                </p>
              </div>
              <div className="rounded-lg border border-emerald-200 bg-emerald-50 p-3">
                <p className="text-xs text-emerald-800">Imported</p>
                <p className="mt-1 text-lg font-semibold text-emerald-900">
                  {result.imported_count}
                </p>
              </div>
              <div className="rounded-lg border border-amber-200 bg-amber-50 p-3">
                <p className="text-xs text-amber-800">Skipped</p>
                <p className="mt-1 text-lg font-semibold text-amber-900">
                  {result.skipped_count}
                </p>
              </div>
              <div className="rounded-lg border border-red-200 bg-red-50 p-3">
                <p className="text-xs text-red-800">Invalid</p>
                <p className="mt-1 text-lg font-semibold text-red-900">
                  {result.invalid_count}
                </p>
              </div>
            </div>

            {result.errors.length > 0 && (
              <div className="space-y-2">
                <h3 className="text-xs font-semibold tracking-wide text-red-800 uppercase">
                  Row validation errors
                </h3>
                <ul className="max-h-44 space-y-1.5 overflow-y-auto rounded-lg border border-red-200 bg-red-50/50 p-3 text-xs">
                  {result.errors.map((issue, idx) => (
                    <li
                      key={`${issue.row_number}-${idx}`}
                      className="text-red-900"
                    >
                      <span className="font-semibold">
                        Row {issue.row_number}
                      </span>
                      {issue.channel_name ? ` (${issue.channel_name})` : ""}:{" "}
                      {issue.reason}
                    </li>
                  ))}
                </ul>
              </div>
            )}

            {result.skipped.length > 0 && (
              <div className="space-y-2">
                <h3 className="text-xs font-semibold tracking-wide text-amber-800 uppercase">
                  Skipped duplicates
                </h3>
                <ul className="max-h-40 space-y-1.5 overflow-y-auto rounded-lg border border-amber-200 bg-amber-50/50 p-3 text-xs">
                  {result.skipped.map((issue, idx) => (
                    <li
                      key={`${issue.row_number}-${idx}`}
                      className="text-amber-900"
                    >
                      <span className="font-semibold">
                        Row {issue.row_number}
                      </span>
                      {issue.channel_name ? ` (${issue.channel_name})` : ""}:{" "}
                      {issue.reason}
                    </li>
                  ))}
                </ul>
              </div>
            )}
          </div>
        )}
      </div>
    </Modal>
  );
}
