import { privateJson } from "@/lib/api";
import { createAction, sourceInput } from "@/lib/actions";
import { requireSameOrigin } from "@/lib/auth";

export async function POST(request: Request) {
  try {
    requireSameOrigin(request);
    const input = sourceInput.parse(await request.json());
    const kind = input.operation === "add"
      ? "add_source"
      : input.operation === "set_category"
        ? "set_source_category"
        : "remove_source";
    const payload = input.operation === "remove"
      ? { source: input.source }
      : { source: input.source, category: input.category };
    const action = await createAction(kind, payload);
    return privateJson({ action }, { status: 202 });
  } catch (error) {
    return privateJson(
      { error: error instanceof Error ? error.message : "Некорректный источник." },
      { status: 400 },
    );
  }
}
