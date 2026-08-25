import { OverviewClient } from "@/components/overview-client";
import { requireSession } from "@/lib/auth";

export default async function OverviewPage() {
  await requireSession();
  return <OverviewClient />;
}
