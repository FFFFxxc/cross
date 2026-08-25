import bcrypt from "bcryptjs";
import { beforeAll, describe, expect, it } from "vitest";

import { POST } from "./route";

beforeAll(async () => {
  process.env.DATABASE_URL = "postgresql://user:pass@localhost/db";
  process.env.ADMIN_PASSWORD_HASH = await bcrypt.hash("secret", 4);
  process.env.AUTH_SECRET = "a".repeat(40);
});

function login(password: string, ip = crypto.randomUUID()) {
  return POST(
    new Request("https://panel.example/api/session/login", {
      method: "POST",
      headers: {
        "content-type": "application/json",
        origin: "https://panel.example",
        "x-forwarded-for": ip,
      },
      body: JSON.stringify({ password }),
    }),
  );
}

describe("login route", () => {
  it("sets a hardened cookie only for a valid password", async () => {
    const bad = await login("wrong");
    expect(bad.status).toBe(401);
    expect(bad.headers.get("set-cookie")).toBeNull();

    const good = await login("secret");
    expect(good.status).toBe(200);
    expect(good.headers.get("set-cookie")).toContain("desiree_session=");
    expect(good.headers.get("set-cookie")).toContain("HttpOnly");
    expect(good.headers.get("set-cookie")).toContain("Secure");
    expect(good.headers.get("set-cookie")).toContain("SameSite=lax");
  });

  it("rate limits repeated failures without leaking configuration", async () => {
    const ip = crypto.randomUUID();
    for (let attempt = 0; attempt < 5; attempt += 1) {
      expect((await login("wrong", ip)).status).toBe(401);
    }
    expect((await login("wrong", ip)).status).toBe(429);
  });
});
