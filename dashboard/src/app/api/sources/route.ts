import { privateJson, unauthorized } from "@/lib/api";
import { hasSession } from "@/lib/auth";
import { query } from "@/lib/db";

type SourceRow = {
  peer: string;
  title: string;
  availability: string;
  checked_at: string | null;
  error: string | null;
};

export async function GET() {
  if (!(await hasSession())) return unauthorized();
  const sources = await query<SourceRow>(
    `SELECT peer, title, availability, checked_at, error
     FROM automation_sources ORDER BY added_at, peer`,
  );
  return privateJson({
    sources: sources.map((source) => ({
      peer: source.peer,
      title: source.title,
      availability: source.availability,
      checkedAt: source.checked_at,
      error: source.error,
    })),
  });
}
