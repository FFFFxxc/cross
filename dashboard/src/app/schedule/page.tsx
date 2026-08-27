import { AppShell } from "@/components/app-shell";
import { ScheduleEditor } from "@/components/schedule-editor";
import { query } from "@/lib/db";

type Slot = { run_time: string; media_kind: string; source: string | null };
type Source = { peer: string; title: string; category: "content" | "news" };

export default async function SchedulePage() {
  const [slots, sources] = await Promise.all([
    query<Slot>("SELECT run_time, media_kind, source FROM automation_slots ORDER BY run_time"),
    query<Source>("SELECT peer, title, category FROM automation_sources ORDER BY title"),
  ]);
  return (
    <AppShell>
      <div className="page-heading"><div><p className="eyebrow">Europe/Moscow</p><h1>Расписание</h1></div></div>
      <ScheduleEditor
        initialSlots={slots.map((slot) => ({ time: slot.run_time, mediaKind: slot.media_kind, source: slot.source }))}
        sources={sources}
      />
    </AppShell>
  );
}
