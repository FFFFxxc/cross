import { PRIVATE_HEADERS } from "@/lib/api";
import { query } from "@/lib/db";

type PreviewRow = { preview_mime: string | null; preview_data: Buffer | null };

export async function GET(
  _request: Request,
  context: { params: Promise<{ id: string }> },
) {
  const { id } = await context.params;
  const rows = await query<PreviewRow>(
    "SELECT preview_mime, preview_data FROM automation_queue WHERE id = $1",
    [id],
  );
  const preview = rows[0];
  if (!preview?.preview_data || !preview.preview_mime) {
    return new Response(null, { status: 404, headers: PRIVATE_HEADERS });
  }
  return new Response(new Uint8Array(preview.preview_data), {
    headers: {
      ...PRIVATE_HEADERS,
      "Content-Type": preview.preview_mime,
      "Content-Length": String(preview.preview_data.length),
    },
  });
}
