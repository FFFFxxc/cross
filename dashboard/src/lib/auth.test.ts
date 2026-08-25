import { afterEach, describe, expect, it } from "vitest";

import { requireSameOrigin } from "./auth";
import { getEnv } from "./env";

const original = { ...process.env };

afterEach(() => {
  process.env = { ...original };
});

describe("public dashboard security", () => {
  it("requires only the database URL", () => {
    process.env.DATABASE_URL = "postgresql://user:pass@localhost/db";
    delete process.env.ADMIN_PASSWORD_HASH;
    delete process.env.AUTH_SECRET;
    expect(getEnv()).toEqual({
      DATABASE_URL: "postgresql://user:pass@localhost/db",
    });
  });

  it("rejects state changes from a foreign origin", () => {
    const request = new Request("https://panel.example/api/settings", {
      method: "POST",
      headers: { Origin: "https://evil.example" },
    });
    expect(() => requireSameOrigin(request)).toThrow(/origin/i);
  });

  it("accepts the public host when Next receives an internal proxy URL", () => {
    const request = new Request("http://localhost:3100/api/settings", {
      method: "POST",
      headers: {
        Origin: "http://127.0.0.1:3100",
        Host: "127.0.0.1:3100",
      },
    });
    expect(() => requireSameOrigin(request)).not.toThrow();
  });
});
