import { useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Archive, ArchiveRestore, ChevronDown, ChevronRight, FileUp, MailCheck,
  Pencil, ShieldAlert, Trash2,
} from "lucide-react";
import { apiFetch } from "@/lib/api";
import type { RosterEntry, Section } from "@/types/api";
import { PageHeader } from "@/components/PageHeader";
import { Card, CardTitle } from "@/components/Card";
import { Badge } from "@/components/Badge";
import { Button } from "@/components/Button";
import { Input, Label } from "@/components/Input";
import { Spinner } from "@/components/Spinner";

const STATUS_LABEL: Record<RosterEntry["status"], string> = {
  unclaimed: "not registered",
  pending: "awaiting email confirmation",
  active: "active",
};

const STATUS_TONE: Record<RosterEntry["status"], "neutral" | "warning" | "success"> = {
  unclaimed: "neutral",
  pending: "warning",
  active: "success",
};

/** The class list for one section: who is allowed to register, and where each
 * student has got to. Uploading a CSV is the only way to admit a student. */
function RosterPanel({ sectionId }: { sectionId: number }) {
  const qc = useQueryClient();
  const fileRef = useRef<HTMLInputElement>(null);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<string | null>(null);

  const key = ["instructor", "roster", sectionId];
  const { data: entries, isPending } = useQuery({
    queryKey: key,
    queryFn: () => apiFetch<RosterEntry[]>(`/api/instructor/sections/${sectionId}/roster`),
  });
  const invalidate = () => {
    qc.invalidateQueries({ queryKey: key });
    qc.invalidateQueries({ queryKey: ["instructor", "sections"] });
  };

  const confirmEntry = useMutation({
    mutationFn: (id: number) =>
      apiFetch(`/api/instructor/roster/${id}/verify`, { json: {} }),
    onSuccess: invalidate,
  });
  const removeEntry = useMutation({
    mutationFn: (id: number) =>
      apiFetch(`/api/instructor/roster/${id}`, {
        method: "DELETE",
        headers: { "X-Requested-With": "fetch" },
      }),
    onSuccess: invalidate,
  });

  async function upload(file: File) {
    setError(null);
    setResult(null);
    const form = new FormData();
    form.append("file", file);
    const res = await fetch(`/api/instructor/sections/${sectionId}/roster`, {
      method: "POST",
      body: form,
      credentials: "same-origin",
      cache: "no-store",
      headers: { "X-Requested-With": "fetch" },
    });
    const body = await res.json().catch(() => null);
    if (!res.ok) {
      const findings = body?.detail?.findings as
        | { where: string; message: string; severity: string }[]
        | undefined;
      setError(
        findings
          ? findings
              .filter((f) => f.severity === "error")
              .map((f) => `${f.where}: ${f.message}`)
              .join("\n")
          : `Upload failed (${res.status}).`,
      );
      return;
    }
    setResult(`${body.added} added, ${body.updated} updated.`);
    invalidate();
  }

  return (
    <div className="mt-3 border-t border-hairline pt-3">
      <div className="flex items-center justify-between gap-3">
        <p className="text-[13px] text-ink-faint">
          Only listed addresses can register. Upload the Albert class list as CSV.
        </p>
        <Button
          variant="secondary"
          onClick={() => fileRef.current?.click()}
          className="shrink-0"
        >
          <FileUp className="size-4" /> Upload class list
        </Button>
        <input
          ref={fileRef}
          type="file"
          accept=".csv,text/csv"
          className="hidden"
          onChange={(e) => {
            const f = e.target.files?.[0];
            if (f) upload(f);
            e.target.value = "";
          }}
        />
      </div>

      {error && (
        <pre className="mt-2 whitespace-pre-wrap rounded-(--radius-control) border border-error/30 bg-error/5 px-3 py-2 text-[13px] text-error">
          {error}
        </pre>
      )}
      {result && <p className="mt-2 text-[13px] text-ink-soft">{result}</p>}

      {isPending ? (
        <div className="flex justify-center py-4">
          <Spinner />
        </div>
      ) : entries && entries.length > 0 ? (
        <ul className="mt-3 space-y-1">
          {entries.map((e) => (
            <li
              key={e.id}
              className="flex items-center justify-between gap-3 rounded-(--radius-control) px-2 py-1.5 hover:bg-paper"
            >
              <div className="min-w-0">
                <div className="truncate text-[15px] text-ink">{e.full_name || e.email}</div>
                <div className="truncate text-[13px] text-ink-faint">{e.email}</div>
              </div>
              <div className="flex shrink-0 items-center gap-2">
                <Badge tone={STATUS_TONE[e.status]}>{STATUS_LABEL[e.status]}</Badge>
                {e.status === "active" && e.vouched && (
                  <span title="Confirmed by an instructor, not by the student opening the emailed link">
                    <ShieldAlert className="size-4 text-warning" />
                  </span>
                )}
                {e.status === "pending" && (
                  <button
                    title="Confirm without email, only if you know this student registered"
                    onClick={() => {
                      // Confirming replaces proof that the registrant can read
                      // that mailbox. Done carelessly it lets one student take
                      // over another's account, so make the instructor say so.
                      const ok = window.confirm(
                        [
                          `Confirm ${e.full_name || e.email} without email?`,
                          "",
                          "Normally the student proves the address is theirs by opening the link we email them. Confirming here replaces that step.",
                          "",
                          "Only do this if you know THIS student registered the account. Otherwise someone else could take over their account.",
                        ].join("\n"),
                      );
                      if (ok) confirmEntry.mutate(e.id);
                    }}
                    className="inline-flex size-8 items-center justify-center rounded-(--radius-control) text-ink-faint transition-colors hover:bg-surface hover:text-ink"
                  >
                    <MailCheck className="size-4" />
                  </button>
                )}
                {e.status === "unclaimed" && (
                  <button
                    title="Remove from the class list"
                    onClick={() => removeEntry.mutate(e.id)}
                    className="inline-flex size-8 items-center justify-center rounded-(--radius-control) text-ink-faint transition-colors hover:bg-surface hover:text-error"
                  >
                    <Trash2 className="size-4" />
                  </button>
                )}
              </div>
            </li>
          ))}
        </ul>
      ) : (
        <p className="py-3 text-[15px] text-ink-faint">No one listed yet.</p>
      )}
    </div>
  );
}

function SectionRow({ section }: { section: Section }) {
  const qc = useQueryClient();
  const [open, setOpen] = useState(false);
  const [renaming, setRenaming] = useState(false);
  const [name, setName] = useState(section.name);
  const [error, setError] = useState<string | null>(null);
  const invalidate = () => qc.invalidateQueries({ queryKey: ["instructor", "sections"] });

  const update = useMutation({
    mutationFn: (body: { name?: string; is_active?: boolean }) =>
      apiFetch<Section>(`/api/instructor/sections/${section.id}`, { json: body }),
    onSuccess: () => {
      setRenaming(false);
      invalidate();
    },
  });

  const remove = useMutation({
    mutationFn: () =>
      apiFetch(`/api/instructor/sections/${section.id}`, {
        method: "DELETE",
        headers: { "X-Requested-With": "fetch" },
      }),
    onSuccess: invalidate,
    onError: () => setError("Sections with students can't be deleted. Archive it instead."),
  });

  return (
    <div className="border-b border-hairline py-3 last:border-b-0">
      <div className="flex items-center justify-between gap-3">
        {renaming ? (
          <form
            className="flex flex-1 items-center gap-2"
            onSubmit={(e) => {
              e.preventDefault();
              if (name.trim()) update.mutate({ name: name.trim() });
            }}
          >
            <Input value={name} onChange={(e) => setName(e.target.value)} autoFocus maxLength={80} />
            <Button type="submit" className="h-8 px-3 text-[13px]" loading={update.isPending}>
              Save
            </Button>
            <Button
              type="button"
              variant="ghost"
              className="h-8 px-2 text-[13px]"
              onClick={() => {
                setName(section.name);
                setRenaming(false);
              }}
            >
              Cancel
            </Button>
          </form>
        ) : (
          <>
            <div className="min-w-0">
              <div className="flex items-center gap-2">
                <span className="truncate font-medium text-ink">{section.name}</span>
                {!section.is_active && <Badge>archived</Badge>}
              </div>
              <div className="text-sm text-ink-soft">
                {section.student_count} student{section.student_count === 1 ? "" : "s"}
              </div>
            </div>
            <div className="flex shrink-0 items-center gap-1">
              <button
                onClick={() => setRenaming(true)}
                title="Rename"
                className="inline-flex size-8 items-center justify-center rounded-(--radius-control) text-ink-faint hover:bg-paper hover:text-ink"
              >
                <Pencil className="size-4" />
              </button>
              <button
                onClick={() => update.mutate({ is_active: !section.is_active })}
                title={section.is_active ? "Archive: stops new registrations" : "Reactivate"}
                className="inline-flex size-8 items-center justify-center rounded-(--radius-control) text-ink-faint hover:bg-paper hover:text-ink"
              >
                {section.is_active ? <Archive className="size-4" /> : <ArchiveRestore className="size-4" />}
              </button>
              {section.student_count === 0 && (
                <button
                  onClick={() => {
                    if (window.confirm(`Delete "${section.name}" and its class list?`)) remove.mutate();
                  }}
                  title="Delete"
                  className="inline-flex size-8 items-center justify-center rounded-(--radius-control) text-ink-faint hover:bg-paper hover:text-error"
                >
                  <Trash2 className="size-4" />
                </button>
              )}
              <Button variant="secondary" className="ml-1" onClick={() => setOpen((v) => !v)}>
                {open ? <ChevronDown className="size-4" /> : <ChevronRight className="size-4" />}
                Class list
              </Button>
            </div>
          </>
        )}
      </div>
      {error && <p className="mt-1.5 text-[13px] text-error">{error}</p>}
      {open && <RosterPanel sectionId={section.id} />}
    </div>
  );
}

function SectionsCard() {
  const { data: sections, isPending } = useQuery({
    queryKey: ["instructor", "sections"],
    queryFn: () => apiFetch<Section[]>("/api/instructor/sections"),
  });
  const qc = useQueryClient();
  const [name, setName] = useState("");
  const create = useMutation({
    mutationFn: () => apiFetch<Section>("/api/instructor/sections", { json: { name } }),
    onSuccess: () => {
      setName("");
      qc.invalidateQueries({ queryKey: ["instructor", "sections"] });
    },
  });

  return (
    <Card>
      <div className="flex items-center justify-between">
        <CardTitle>Sections</CardTitle>
        <Badge tone="violet">class lists</Badge>
      </div>
      <div className="mt-1">
        {isPending ? (
          <div className="flex justify-center py-6">
            <Spinner />
          </div>
        ) : sections && sections.length > 0 ? (
          sections.map((s) => <SectionRow key={s.id} section={s} />)
        ) : (
          <p className="py-4 text-[15px] text-ink-faint">
            No sections yet. Create the first one below.
          </p>
        )}
      </div>
      <form
        className="mt-3 flex items-end gap-2 border-t border-hairline pt-3"
        onSubmit={(e) => {
          e.preventDefault();
          if (name.trim()) create.mutate();
        }}
      >
        <div className="flex-1">
          <Label htmlFor="section-name">New section</Label>
          <Input
            id="section-name"
            value={name}
            onChange={(e) => setName(e.target.value)}
            placeholder="Section A, Fall 2026"
          />
        </div>
        <Button type="submit" loading={create.isPending}>
          Create
        </Button>
      </form>
    </Card>
  );
}


/* ── the page ───────────────────────────────────────────────────────── */

export function EnrollmentPage() {
  return (
    <>
      <PageHeader
        title="Enrolment"
        subtitle="Who is in the course: sections, class lists, and accounts waiting to be confirmed."
      />
      <div className="max-w-3xl">
        <SectionsCard />
      </div>
    </>
  );
}
