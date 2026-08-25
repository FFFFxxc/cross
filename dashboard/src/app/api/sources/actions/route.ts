import { privateJson, unauthorized } from "@/lib/api";
import { createAction, sourceInput } from "@/lib/actions";
import { hasSession, requireSameOrigin } from "@/lib/auth";

export async function POST(request: Request) {
  if (!(await hasSession())) return unauthorized();
  try {
    requireSameOrigin(request);
    const input = sourceInput.parse(await request.json());
    const kind = input.operation === "add" ? "add_source" : "remove_source";
    const action = await createAction(kind, { source: input.source });
    return privateJson({ action }, { status: 202 });
  } catch (error) {
    return privateJson(
      { error: error instanceof Error ? error.message : "Некорректный источник." },
      { status: 400 },
    );
  }
}
