import { NextResponse } from "next/server";

import { clearSessionCookie, requireSameOrigin } from "@/lib/auth";

export async function POST(request: Request) {
  try {
    requireSameOrigin(request);
  } catch {
    return NextResponse.json({ error: "Запрос отклонён." }, { status: 403 });
  }
  const session = clearSessionCookie();
  const response = NextResponse.json({ ok: true });
  response.cookies.set(session.name, session.value, session.options);
  return response;
}
