import { NextResponse } from "next/server";

export const PRIVATE_HEADERS = {
  "Cache-Control": "private, no-store, max-age=0",
};

export function privateJson(body: unknown, init: ResponseInit = {}) {
  return NextResponse.json(body, {
    ...init,
    headers: { ...PRIVATE_HEADERS, ...init.headers },
  });
}

export function unauthorized() {
  return privateJson({ error: "Требуется вход." }, { status: 401 });
}
