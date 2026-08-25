import { QueueClient } from "@/components/queue-client";

export { QueueClient } from "@/components/queue-client";

export default async function QueuePage({
  searchParams,
}: {
  searchParams: Promise<Record<string, string | string[] | undefined>>;
}) {
  const raw = await searchParams;
  const query = new URLSearchParams();
  for (const [key, value] of Object.entries(raw)) {
    if (typeof value === "string") query.set(key, value);
  }
  return <QueueClient initialSearch={query.toString()} />;
}
