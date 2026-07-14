import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { RefreshCw } from "lucide-react";
import { apiFetch } from "@/lib/api";
import type { Section } from "@/types/api";
import { PageHeader } from "@/components/PageHeader";
import { Card, CardTitle } from "@/components/Card";
import { Badge } from "@/components/Badge";
import { Button } from "@/components/Button";
import { Input, Label } from "@/components/Input";
import { Spinner } from "@/components/Spinner";

function useSections() {
  return useQuery({
    queryKey: ["instructor", "sections"],
    queryFn: () => apiFetch<Section[]>("/api/instructor/sections"),
  });
}

function SectionRow({ section }: { section: Section }) {
  const qc = useQueryClient();
  const regen = useMutation({
    mutationFn: () =>
      apiFetch<Section>(`/api/instructor/sections/${section.id}/regenerate-code`, { json: {} }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["instructor", "sections"] }),
  });

  return (
    <div className="flex items-center justify-between gap-4 border-b border-hairline py-3 last:border-b-0">
      <div>
        <div className="font-medium text-ink">{section.name}</div>
        <div className="text-sm text-ink-soft">
          {section.student_count} student{section.student_count === 1 ? "" : "s"} registered
        </div>
      </div>
      <div className="flex items-center gap-2">
        <code className="rounded-(--radius-control) border border-hairline bg-paper px-3 py-1 font-mono text-[15px] tracking-wider text-ink">
          {section.class_code}
        </code>
        <button
          onClick={() => regen.mutate()}
          title="Regenerate class code"
          className="inline-flex size-8 items-center justify-center rounded-(--radius-control) text-ink-faint transition-colors hover:bg-paper hover:text-ink"
        >
          {regen.isPending ? <Spinner className="size-4" /> : <RefreshCw className="size-4" />}
        </button>
      </div>
    </div>
  );
}

export function ClassDashboardPage() {
  const { data: sections, isPending } = useSections();
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
    <>
      <PageHeader
        title="Class"
        subtitle="Sections, class codes, and (soon) the cohort progress matrix."
      />
      <div className="grid gap-4 lg:grid-cols-2">
        <Card>
          <div className="flex items-center justify-between">
            <CardTitle>Sections</CardTitle>
            <Badge tone="violet">class codes</Badge>
          </div>
          <p className="mt-1 text-sm text-ink-soft">
            Students register with a section's class code.
          </p>
          <div className="mt-3">
            {isPending ? (
              <div className="flex justify-center py-6">
                <Spinner />
              </div>
            ) : sections && sections.length > 0 ? (
              sections.map((s) => <SectionRow key={s.id} section={s} />)
            ) : (
              <p className="py-4 text-[15px] text-ink-faint">
                No sections yet — create the first one below.
              </p>
            )}
          </div>
          <form
            className="mt-4 flex items-end gap-2 border-t border-hairline pt-4"
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
                placeholder="Section A — Fall 2026"
              />
            </div>
            <Button type="submit" loading={create.isPending}>
              Create
            </Button>
          </form>
        </Card>
        <Card>
          <CardTitle>Cohort progress</CardTitle>
          <p className="mt-2 text-[15px] text-ink-soft">
            The completion matrix, quiz score distribution, and activity feed land in
            milestone 5.
          </p>
        </Card>
      </div>
    </>
  );
}
