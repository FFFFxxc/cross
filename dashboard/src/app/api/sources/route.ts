import { privateJson } from "@/lib/api";
import { query } from "@/lib/db";

type SourceRow = {
  peer: string;
  title: string;
  category: "content" | "news";
  availability: string;
  checked_at: string | null;
  error: string | null;
};

export async function GET() {
  const sources = await query<SourceRow>(
    `SELECT peer, title, category, availability, checked_at, error
     FROM automation_sources ORDER BY added_at, peer`,
  );
  return privateJson({
    sources: sources.map((source) => ({
      peer: source.peer,
      title: source.title,
      category: source.category,
      availability: source.availability,
      checkedAt: source.checked_at,
      error: source.error,
    })),
  });
}
