import { PageHeader } from "@/components/PageHeader";
import { Card } from "@/components/Card";

export function Placeholder({ title, milestone }: { title: string; milestone: string }) {
  return (
    <>
      <PageHeader title={title} />
      <Card>
        <p className="text-[15px] text-ink-soft">Coming in {milestone}.</p>
      </Card>
    </>
  );
}
