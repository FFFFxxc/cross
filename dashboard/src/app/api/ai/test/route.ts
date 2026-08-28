import { privateJson } from "@/lib/api";
import { createAction } from "@/lib/actions";
import { requireSameOrigin } from "@/lib/auth";

export async function POST(request: Request) {
  try {
    requireSameOrigin(request);
    const body = await request.json();
    if (body.provider !== 1 && body.provider !== 2) throw new Error();
    return privateJson(
      { action: await createAction("ai_test", { provider: body.provider }) },
      { status: 202 },
    );
  } catch {
    return privateJson({ error: "Запрос отклонён." }, { status: 403 });
  }
}
