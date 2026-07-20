import { useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  AlertTriangle, BookOpen, CheckCircle2, FileUp, ListChecks, XCircle,
} from "lucide-react";
import { apiFetch, ApiError } from "@/lib/api";
import type { LibraryTutorial, ValidationFinding } from "@/types/api";
import { PageHeader } from "@/components/PageHeader";
import { Card, CardTitle } from "@/components/Card";
import { Badge } from "@/components/Badge";
import { Button } from "@/components/Button";
import { Spinner } from "@/components/Spinner";
import { cn } from "@/components/cn";
import { timeAgo } from "./ClassDashboardPage";

/* ── validation findings list ───────────────────────────────────────── */

function FindingsList({ findings }: { findings: ValidationFinding[] }) {
  return (
    <ul className="mt-2 space-y-1.5">
      {findings.map((f, i) => (
        <li key={i} className="flex items-start gap-2 text-[13px]">
          {f.severity === "error" ? (
            <XCircle className="mt-0.5 size-4 shrink-0 text-error" />
          ) : (
            <AlertTriangle className="mt-0.5 size-4 shrink-0 text-warning" />
          )}
          <span>
            <code className="font-mono text-ink-soft">{f.where}</code>{" "}
            <span className="text-ink">{f.message}</span>
          </span>
        </li>
      ))}
    </ul>
  );
}

/* ── upload card ────────────────────────────────────────────────────── */

function UploadCard() {
  const qc = useQueryClient();
  const fileRef = useRef<HTMLInputElement>(null);
  const [fileName, setFileName] = useState<string | null>(null);
  const [product, setProduct] = useState("mechanical");
  const [mandatory, setMandatory] = useState(false);
  const [findings, setFindings] = useState<ValidationFinding[] | null>(null);
  const [uploaded, setUploaded] = useState<{ tutorial_id: string; version: number } | null>(null);

  const upload = useMutation({
    mutationFn: async () => {
      const file = fileRef.current?.files?.[0];
      if (!file) throw new Error("no file");
      const form = new FormData();
      form.append("file", file);
      form.append("product", product);
      form.append("is_mandatory", String(mandatory));
      const res = await fetch("/api/instructor/tutorials", {
        method: "POST",
        credentials: "same-origin",
        headers: { "X-Requested-With": "fetch" },
        body: form,
      });
      if (res.status === 422) {
        const body = await res.json();
        setFindings(body.detail.findings as ValidationFinding[]);
        setUploaded(null);
        throw new ApiError(422, "validation_failed");
      }
      if (!res.ok) throw new ApiError(res.status, `http_${res.status}`);
      return (await res.json()) as { tutorial_id: string; version: number; warnings: ValidationFinding[] };
    },
    onSuccess: (r) => {
      setFindings(r.warnings.length > 0 ? r.warnings : null);
      setUploaded({ tutorial_id: r.tutorial_id, version: r.version });
      setFileName(null);
      if (fileRef.current) fileRef.current.value = "";
      qc.invalidateQueries({ queryKey: ["instructor", "library"] });
    },
  });

  return (
    <Card>
      <div className="flex items-center gap-2">
        <FileUp className="size-5 text-violet" />
        <CardTitle>Upload a tutorial</CardTitle>
      </div>
      <p className="mt-2 text-sm text-ink-soft">
        A tutorial is one JSON file (start from{" "}
        <code className="font-mono text-[13px]">mock_server/data/_template.json</code>).
        Uploads are validated, stored as a new immutable version, and stay
        drafts until you publish them.
      </p>
      <label
        className="mt-3 flex cursor-pointer items-center justify-center gap-2 rounded-(--radius-control) border border-dashed border-ink-faint bg-paper px-4 py-6 text-sm text-ink-soft hover:border-violet hover:text-ink"
      >
        <FileUp className="size-4" />
        {fileName ?? "Choose a .json file…"}
        <input
          ref={fileRef}
          type="file"
          accept=".json,application/json"
          className="hidden"
          onChange={(e) => {
            setFileName(e.target.files?.[0]?.name ?? null);
            setFindings(null);
            setUploaded(null);
          }}
        />
      </label>
      <div className="mt-3 flex flex-wrap items-center gap-4">
        <label className="flex items-center gap-2 text-sm text-ink">
          Product
          <select
            value={product}
            onChange={(e) => setProduct(e.target.value)}
            className="h-9 rounded-(--radius-control) border border-hairline bg-surface px-2 text-sm"
          >
            <option value="mechanical">Mechanical</option>
            <option value="fluent">Fluent</option>
            <option value="discovery">Discovery</option>
          </select>
        </label>
        <label className="flex items-center gap-2 text-sm text-ink">
          <input
            type="checkbox"
            checked={mandatory}
            onChange={(e) => setMandatory(e.target.checked)}
            className="size-4 accent-(--color-violet)"
          />
          Mandatory
        </label>
        <Button
          className="ml-auto"
          disabled={!fileName}
          loading={upload.isPending}
          onClick={() => upload.mutate()}
        >
          Validate &amp; upload
        </Button>
      </div>

      {findings && (
        <div
          className={cn(
            "mt-4 rounded-(--radius-control) border px-4 py-3",
            uploaded ? "border-warning/40 bg-warning-tint" : "border-error/40 bg-error-tint",
          )}
        >
          <div className={cn("text-sm font-semibold", uploaded ? "text-warning" : "text-error")}>
            {uploaded ? "Uploaded with warnings" : "Validation failed — nothing was stored"}
          </div>
          <FindingsList findings={findings} />
        </div>
      )}
      {uploaded && (
        <div className="mt-3 flex items-center gap-2 rounded-(--radius-control) border border-success/40 bg-success-tint px-4 py-3 text-sm text-ink">
          <CheckCircle2 className="size-4 text-success" />
          Stored <code className="font-mono">{uploaded.tutorial_id}</code> as draft v{uploaded.version} — publish it below when ready.
        </div>
      )}
    </Card>
  );
}

/* ── library table ──────────────────────────────────────────────────── */

function TutorialRow({ t }: { t: LibraryTutorial }) {
  const qc = useQueryClient();
  const invalidate = () => {
    qc.invalidateQueries({ queryKey: ["instructor", "library"] });
    qc.invalidateQueries({ queryKey: ["instructor", "progress"] });
  };
  const publish = useMutation({
    mutationFn: (version: number) =>
      apiFetch(`/api/instructor/tutorials/${t.tutorial_id}/publish`, { json: { version } }),
    onSuccess: invalidate,
  });
  const toggleMandatory = useMutation({
    mutationFn: () =>
      apiFetch(`/api/instructor/tutorials/${t.tutorial_id}/settings`, {
        json: { is_mandatory: !t.is_mandatory },
      }),
    onSuccess: invalidate,
  });
  const [open, setOpen] = useState(false);
  const hasDraft = t.versions.some((v) => v.version !== t.published_version);

  return (
    <div className="border-b border-hairline py-3 last:border-b-0">
      <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-2">
            <span className="font-medium text-ink">{t.title}</span>
            {t.published_version != null ? (
              <Badge tone="violet" className="font-mono">v{t.published_version} live</Badge>
            ) : (
              <Badge>draft</Badge>
            )}
            {t.is_mandatory && <Badge tone="violet">Mandatory</Badge>}
            {t.quiz_id && (
              <span title="Has a quiz">
                <ListChecks className="size-4 text-ink-faint" />
              </span>
            )}
          </div>
          <div className="mt-0.5 font-mono text-[12px] text-ink-faint">
            {t.tutorial_id} · {t.product} · {t.versions.length} version{t.versions.length === 1 ? "" : "s"}
          </div>
        </div>
        <div className="flex items-center gap-2">
          <Button variant="ghost" className="h-8 px-2 text-[13px]" onClick={() => toggleMandatory.mutate()}>
            {t.is_mandatory ? "Make optional" : "Make mandatory"}
          </Button>
          <Button
            variant="secondary"
            className="h-8 px-3 text-[13px]"
            onClick={() => setOpen(!open)}
          >
            Versions
          </Button>
        </div>
      </div>
      {open && (
        <ul className="mt-2 space-y-1.5 rounded-(--radius-control) border border-hairline bg-paper px-3 py-2">
          {t.versions.map((v) => (
            <li key={v.version} className="flex flex-wrap items-center gap-2 text-sm">
              <code className="font-mono text-ink">v{v.version}</code>
              <span className="text-[12px] text-ink-faint">{timeAgo(v.uploaded_at)}</span>
              {v.warnings.length > 0 && (
                <span className="flex items-center gap-1 text-[12px] text-warning">
                  <AlertTriangle className="size-3.5" /> {v.warnings.length} warning{v.warnings.length === 1 ? "" : "s"}
                </span>
              )}
              {v.version === t.published_version ? (
                <Badge tone="violet" className="ml-auto">published</Badge>
              ) : (
                <Button
                  variant="secondary"
                  className="ml-auto h-7 px-2.5 text-[12px]"
                  loading={publish.isPending}
                  onClick={() => publish.mutate(v.version)}
                >
                  Publish v{v.version}
                </Button>
              )}
            </li>
          ))}
        </ul>
      )}
      {!open && hasDraft && t.published_version == null && (
        <div className="mt-1.5 text-[13px] text-warning">
          Not visible to students until a version is published.
        </div>
      )}
    </div>
  );
}

export function TutorialLibraryPage() {
  const { data: library, isPending } = useQuery({
    queryKey: ["instructor", "library"],
    queryFn: () => apiFetch<LibraryTutorial[]>("/api/instructor/tutorials"),
  });

  return (
    <>
      <PageHeader
        title="Tutorial library"
        subtitle="Versioned tutorial content — upload, validate, publish."
      />
      <div className="grid items-start gap-4 xl:grid-cols-[1fr_420px]">
        <Card>
          <div className="flex items-center gap-2">
            <BookOpen className="size-5 text-violet" />
            <CardTitle>Tutorials</CardTitle>
          </div>
          <div className="mt-1">
            {isPending ? (
              <div className="flex justify-center py-8">
                <Spinner />
              </div>
            ) : library && library.length > 0 ? (
              library.map((t) => <TutorialRow key={t.tutorial_id} t={t} />)
            ) : (
              <p className="py-4 text-[15px] text-ink-faint">No tutorials yet.</p>
            )}
          </div>
        </Card>
        <UploadCard />
      </div>
    </>
  );
}
