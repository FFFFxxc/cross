import { privateJson } from "@/lib/api";
import { createAction, scanInput } from "@/lib/actions";
import { requireSameOrigin } from "@/lib/auth";

export async function POST(request: Request) {
  try {
    requireSameOrigin(request);
    const input = scanInput.parse(await request.json());
    const action = await createAction("scan", {
      count: input.count,
      source: input.source,
      kind: input.mediaKind,
      start: input.start,
      end: input.end,
    });
    return privateJson({ action }, { status: 202 });
  } catch (error) {
    return privateJson(
      { error: error instanceof Error ? error.message : "Некорректный сбор." },
      { status: 400 },
    );
  }
}
