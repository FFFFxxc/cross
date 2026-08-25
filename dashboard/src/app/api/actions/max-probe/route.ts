import { privateJson } from "@/lib/api";
import { createAction } from "@/lib/actions";
import { requireSameOrigin } from "@/lib/auth";

export async function POST(request: Request) {
  try {
    requireSameOrigin(request);
    return privateJson({ action: await createAction("max_probe", {}) }, { status: 202 });
  } catch {
    return privateJson({ error: "Запрос отклонён." }, { status: 403 });
  }
}
