import bcrypt from "bcryptjs";
import { afterEach, describe, expect, it } from "vitest";

import {
  createSessionToken,
  requireSameOrigin,
  verifyPassword,
  verifySessionToken,
} from "./auth";
import { getEnv } from "./env";

const original = { ...process.env };

afterEach(() => {
  process.env = { ...original };
});

describe("dashboard authentication", () => {
  it("accepts only the password matching the bcrypt hash", async () => {
    const hash = await bcrypt.hash("правильный пароль", 4);
    await expect(verifyPassword("правильный пароль", hash)).resolves.toBe(true);
    await expect(verifyPassword("ошибка", hash)).resolves.toBe(false);
  });

  it("rejects missing or weak server environment", () => {
    delete process.env.DATABASE_URL;
    delete process.env.ADMIN_PASSWORD_HASH;
    delete process.env.AUTH_SECRET;
    expect(() => getEnv()).toThrow();
  });

  it("signs, verifies and expires session tokens", async () => {
    const secret = "s".repeat(40);
    const token = await createSessionToken(secret, "2h");
    await expect(verifySessionToken(token, secret)).resolves.toBe(true);
    const expired = await createSessionToken(secret, "0s");
    await expect(verifySessionToken(expired, secret)).resolves.toBe(false);
  });

  it("rejects state changes from a foreign origin", () => {
    const request = new Request("https://panel.example/api/settings", {
      method: "POST",
      headers: { Origin: "https://evil.example" },
    });
    expect(() => requireSameOrigin(request)).toThrow(/origin/i);
  });
});
