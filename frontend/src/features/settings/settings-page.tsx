import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Check, Pencil, Plus, Save, X } from "lucide-react";
import { NotificationAlert } from "@/components/shared/notification-alert";
import { PageContainer } from "@/components/shared/page-container";
import { PageHeader } from "@/components/shared/page-header";
import { ErrorState, LoadingState } from "@/components/shared/states";
import { Button } from "@/components/ui/button";
import { Select, type SelectOption } from "@/components/ui/select";
import { ApiError } from "@/services/api";
import type { PdfCompressionMode } from "@/services/pdfs";
import {
  getExclusionKeywords,
  getPdfSettings,
  updateExclusionKeywords,
  updatePdfSettings,
} from "@/services/settings";

function normalizeKeyword(raw: string): string {
  return raw.normalize("NFC").trim().replace(/\s+/g, " ");
}

function getErrorMessage(error: unknown): string {
  if (error instanceof ApiError || error instanceof Error) return error.message;
  return "An unexpected error occurred.";
}

export function SettingsPage() {
  const queryClient = useQueryClient();
  const [draftKeywords, setDraftKeywords] = useState<string[] | null>(null);
  const [newKeyword, setNewKeyword] = useState("");
  const [validationError, setValidationError] = useState<string | null>(null);
  const [editingIndex, setEditingIndex] = useState<number | null>(null);
  const [editingValue, setEditingValue] = useState("");
  const [feedback, setFeedback] = useState<{
    type: "success" | "error";
    message: string;
  } | null>(null);
  const [draftCompression, setDraftCompression] =
    useState<PdfCompressionMode | null>(null);
  const [pdfFeedback, setPdfFeedback] = useState<{
    type: "success" | "error";
    message: string;
  } | null>(null);

  const query = useQuery({
    queryKey: ["settings", "exclusion-keywords"],
    queryFn: ({ signal }) => getExclusionKeywords(signal),
  });

  const pdfQuery = useQuery({
    queryKey: ["settings", "pdf"],
    queryFn: ({ signal }) => getPdfSettings(signal),
  });

  const dirty = draftKeywords !== null;
  const keywords = draftKeywords ?? query.data?.keywords ?? [];
  const activeCompression: PdfCompressionMode =
    draftCompression ?? pdfQuery.data?.compression ?? "lossless";
  const pdfDirty =
    draftCompression !== null &&
    draftCompression !== pdfQuery.data?.compression;

  const savePdfMutation = useMutation({
    mutationFn: (compression: PdfCompressionMode) =>
      updatePdfSettings(compression),
    onSuccess: async (res) => {
      setDraftCompression(null);
      const selectedLabel =
        res.options.find((opt) => opt.mode === res.compression)?.label ??
        res.compression;
      setPdfFeedback({
        type: "success",
        message: `Saved PDF compression mode: ${selectedLabel}. Applies to future generations only.`,
      });
      await queryClient.invalidateQueries({ queryKey: ["settings", "pdf"] });
      await queryClient.invalidateQueries({ queryKey: ["pdf-config"] });
    },
    onError: (err) => {
      setPdfFeedback({ type: "error", message: getErrorMessage(err) });
    },
  });

  const saveMutation = useMutation({
    mutationFn: (nextKeywords: string[]) =>
      updateExclusionKeywords(nextKeywords),
    onSuccess: async (res) => {
      setDraftKeywords(null);
      setValidationError(null);
      setFeedback({
        type: "success",
        message: `Saved ${res.keywords.length} exclusion keyword${res.keywords.length === 1 ? "" : "s"}. ${res.excluded_video_count} excluded, ${res.eligible_video_count} eligible.`,
      });
      await queryClient.invalidateQueries({
        queryKey: ["settings", "exclusion-keywords"],
      });
      await queryClient.invalidateQueries({ queryKey: ["videos"] });
      await queryClient.invalidateQueries({ queryKey: ["video-summary"] });
    },
    onError: (err) => {
      setFeedback({ type: "error", message: getErrorMessage(err) });
    },
  });

  const handleAdd = (rawValue: string) => {
    const cleaned = normalizeKeyword(rawValue);
    if (!cleaned) {
      setValidationError("Keyword cannot be empty.");
      return;
    }
    const lower = cleaned.toLocaleLowerCase();
    if (keywords.some((k) => k.toLocaleLowerCase() === lower)) {
      setValidationError(`"${cleaned}" is already in the exclusion list.`);
      return;
    }
    setValidationError(null);
    setFeedback(null);
    setDraftKeywords([...keywords, cleaned]);
    setNewKeyword("");
  };

  const handleRemove = (index: number) => {
    setValidationError(null);
    setFeedback(null);
    setDraftKeywords(keywords.filter((_, idx) => idx !== index));
    if (editingIndex === index) {
      setEditingIndex(null);
      setEditingValue("");
    }
  };

  const handleSaveEdit = (index: number) => {
    const cleaned = normalizeKeyword(editingValue);
    if (!cleaned) {
      setValidationError("Keyword cannot be empty.");
      return;
    }
    const lower = cleaned.toLocaleLowerCase();
    if (
      keywords.some(
        (k, idx) => idx !== index && k.toLocaleLowerCase() === lower,
      )
    ) {
      setValidationError(`"${cleaned}" is already in the exclusion list.`);
      return;
    }
    setValidationError(null);
    setFeedback(null);
    setDraftKeywords(
      keywords.map((item, idx) => (idx === index ? cleaned : item)),
    );
    setEditingIndex(null);
    setEditingValue("");
  };

  const suggested = (query.data?.suggested_keywords ?? []).filter(
    (s) =>
      !keywords.some((k) => k.toLocaleLowerCase() === s.toLocaleLowerCase()),
  );

  return (
    <PageContainer>
      <PageHeader
        eyebrow="CONFIGURATION"
        title="Settings"
        description="Configure global application rules and video filtering."
      />

      {query.isPending && <LoadingState message="Loading settings…" />}
      {query.isError && (
        <ErrorState
          message={query.error.message}
          onRetry={() => void query.refetch()}
        />
      )}

      {query.data && (
        <section
          aria-labelledby="exclude-keywords-heading"
          className="rounded-xl border border-border bg-white p-5 shadow-xs"
        >
          <div className="flex flex-wrap items-start justify-between gap-3 border-b border-border pb-3">
            <div>
              <h2
                id="exclude-keywords-heading"
                className="text-base font-semibold"
              >
                Exclude Keywords
              </h2>
              <p className="mt-0.5 text-xs text-muted-foreground">
                Videos whose titles contain any configured keyword or phrase
                (English or Bengali) are automatically marked as excluded and
                blocked from download and processing.
              </p>
            </div>
            <Button
              type="button"
              size="sm"
              disabled={!dirty || saveMutation.isPending}
              onClick={() => saveMutation.mutate(keywords)}
            >
              <Save size={14} aria-hidden="true" />
              {saveMutation.isPending ? "Saving…" : "Save changes"}
            </Button>
          </div>

          {feedback && (
            <div className="mt-3">
              <NotificationAlert
                tone={feedback.type}
                summary={feedback.message}
                onDismiss={() => setFeedback(null)}
              />
            </div>
          )}

          <form
            className="mt-4 flex flex-wrap items-center gap-2"
            onSubmit={(event) => {
              event.preventDefault();
              handleAdd(newKeyword);
            }}
          >
            <label htmlFor="new-exclusion-keyword" className="sr-only">
              Add exclusion keyword
            </label>
            <input
              id="new-exclusion-keyword"
              type="text"
              value={newKeyword}
              onChange={(event) => {
                setNewKeyword(event.target.value);
                if (validationError) setValidationError(null);
              }}
              placeholder="Add keyword or phrase (e.g., Math, গণিত)…"
              className="h-9 min-w-[260px] flex-1 rounded-md border border-border bg-white px-3 text-sm focus:border-primary focus:outline-none"
            />
            <Button type="submit" variant="outline" size="sm">
              <Plus size={14} aria-hidden="true" />
              Add keyword
            </Button>
          </form>

          {validationError && (
            <p role="alert" className="mt-2 text-xs text-red-700">
              {validationError}
            </p>
          )}

          <div className="mt-4">
            <p className="text-xs font-medium text-muted-foreground">
              Active exclusion keywords ({keywords.length})
            </p>
            {keywords.length === 0 ? (
              <p className="mt-2 text-xs text-muted-foreground">
                No exclusion keywords configured. All discovered videos remain
                eligible.
              </p>
            ) : (
              <ul className="mt-2 flex flex-wrap gap-2">
                {keywords.map((kw, index) => (
                  <li
                    key={`${kw}-${index}`}
                    className="inline-flex items-center gap-1 rounded-full border border-border bg-muted/60 px-2.5 py-1 text-xs"
                  >
                    {editingIndex === index ? (
                      <>
                        <input
                          type="text"
                          aria-label={`Edit keyword ${kw}`}
                          value={editingValue}
                          onChange={(e) => setEditingValue(e.target.value)}
                          onKeyDown={(e) => {
                            if (e.key === "Enter") {
                              e.preventDefault();
                              handleSaveEdit(index);
                            } else if (e.key === "Escape") {
                              setEditingIndex(null);
                              setEditingValue("");
                            }
                          }}
                          className="h-5 w-32 rounded border border-border bg-white px-1.5 text-xs focus:border-primary focus:outline-none"
                        />
                        <button
                          type="button"
                          aria-label={`Save keyword ${kw}`}
                          onClick={() => handleSaveEdit(index)}
                          className="rounded p-0.5 text-emerald-700 hover:bg-emerald-100"
                        >
                          <Check size={12} aria-hidden="true" />
                        </button>
                        <button
                          type="button"
                          aria-label="Cancel editing"
                          onClick={() => {
                            setEditingIndex(null);
                            setEditingValue("");
                          }}
                          className="rounded p-0.5 text-muted-foreground hover:bg-muted"
                        >
                          <X size={12} aria-hidden="true" />
                        </button>
                      </>
                    ) : (
                      <>
                        <span className="font-medium text-foreground">
                          {kw}
                        </span>
                        <button
                          type="button"
                          aria-label={`Edit ${kw}`}
                          title={`Edit ${kw}`}
                          onClick={() => {
                            setEditingIndex(index);
                            setEditingValue(kw);
                          }}
                          className="rounded p-0.5 text-muted-foreground hover:text-foreground"
                        >
                          <Pencil size={11} aria-hidden="true" />
                        </button>
                        <button
                          type="button"
                          aria-label={`Remove ${kw}`}
                          title={`Remove ${kw}`}
                          onClick={() => handleRemove(index)}
                          className="rounded p-0.5 text-muted-foreground hover:text-red-700"
                        >
                          <X size={12} aria-hidden="true" />
                        </button>
                      </>
                    )}
                  </li>
                ))}
              </ul>
            )}
          </div>

          {suggested.length > 0 && (
            <div className="mt-4 border-t border-border pt-3">
              <p className="text-xs text-muted-foreground">
                Example keywords (click to add):
              </p>
              <div className="mt-1.5 flex flex-wrap gap-1.5">
                {suggested.map((example) => (
                  <button
                    key={example}
                    type="button"
                    onClick={() => handleAdd(example)}
                    className="inline-flex items-center gap-1 rounded-full border border-dashed border-border px-2.5 py-0.5 text-xs text-muted-foreground transition-colors hover:border-primary hover:text-foreground"
                  >
                    <Plus size={11} aria-hidden="true" />
                    {example}
                  </button>
                ))}
              </div>
            </div>
          )}
        </section>
      )}

      {pdfQuery.data && (
        <section
          aria-labelledby="pdf-generation-heading"
          className="mt-5 rounded-xl border border-border bg-white p-5 shadow-xs"
        >
          <div className="flex flex-wrap items-start justify-between gap-3 border-b border-border pb-3">
            <div>
              <h2
                id="pdf-generation-heading"
                className="text-base font-semibold"
              >
                PDF Generation
              </h2>
              <p className="mt-0.5 text-xs text-muted-foreground">
                Default image compression for newly generated PDFs. Existing
                PDFs are never modified automatically.
              </p>
            </div>
            <Button
              type="button"
              size="sm"
              disabled={!pdfDirty || savePdfMutation.isPending}
              onClick={() => savePdfMutation.mutate(activeCompression)}
            >
              <Save size={14} aria-hidden="true" />
              {savePdfMutation.isPending ? "Saving…" : "Save PDF settings"}
            </Button>
          </div>

          {pdfFeedback && (
            <div className="mt-3">
              <NotificationAlert
                tone={pdfFeedback.type}
                summary={pdfFeedback.message}
                onDismiss={() => setPdfFeedback(null)}
              />
            </div>
          )}

          <div className="mt-4 flex flex-wrap items-center gap-3">
            <label
              htmlFor="pdf-compression-select"
              className="text-xs font-medium text-foreground"
            >
              Compression mode
            </label>
            <Select
              id="pdf-compression-select"
              ariaLabel="PDF compression mode"
              value={activeCompression}
              options={
                pdfQuery.data.options.map((opt) => ({
                  value: opt.mode,
                  label: opt.label,
                })) as readonly SelectOption<PdfCompressionMode>[]
              }
              onValueChange={(next) => {
                setPdfFeedback(null);
                setDraftCompression(next);
              }}
              className="min-w-[230px]"
            />
            <span className="text-xs text-muted-foreground">
              Default:{" "}
              {pdfQuery.data.options.find(
                (opt) => opt.mode === pdfQuery.data?.default_compression,
              )?.label ?? pdfQuery.data.default_compression}
            </span>
          </div>

          <ul className="mt-3 space-y-1 text-xs text-muted-foreground">
            {pdfQuery.data.options.map((opt) => (
              <li
                key={opt.mode}
                className={
                  opt.mode === activeCompression
                    ? "font-medium text-foreground"
                    : undefined
                }
              >
                <span className="font-medium">{opt.label}:</span>{" "}
                {opt.description}
              </li>
            ))}
          </ul>
        </section>
      )}
    </PageContainer>
  );
}
