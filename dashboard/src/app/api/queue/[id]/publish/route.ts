import { privateJson } from "@/lib/api";
import { createAction } from "@/lib/actions";
import { requireSameOrigin } from "@/lib/auth";

export async function POST(
  request: Request,
  context: { params: Promise<{ id: string }> },
) {
  try {
    requireSameOrigin(request);
    const { id } = await context.params;
    const action = await createAction("publish_now", { item_id: id }, id);
    return privateJson({ action }, { status: 202 });
  } catch (error) {
    return privateJson(
      { error: error instanceof Error ? error.message : "Не удалось создать действие." },
      { status: 400 },
    );
  }
}
