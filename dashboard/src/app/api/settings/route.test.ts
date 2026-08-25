import { beforeEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({
  query: vi.fn(),
}));
vi.mock("@/lib/db", () => ({ query: mocks.query }));

import { PUT } from "./route";

function request(body: unknown, origin = "https://panel.example") {
  return new Request("https://panel.example/api/settings", {
    method: "PUT",
    headers: { "content-type": "application/json", origin },
    body: JSON.stringify(body),
  });
}

describe("settings mutation", () => {
  beforeEach(() => {
    mocks.query.mockReset().mockResolvedValue([]);
  });

  it("rejects foreign origin and invalid values", async () => {
    expect((await PUT(request({ freshDays: 7 }, "https://evil.example"))).status).toBe(403);
    expect((await PUT(request({ minReactions: -1 }))).status).toBe(400);
    expect((await PUT(request({ signatureUrl: "file:///secret" }))).status).toBe(400);
    expect(mocks.query).not.toHaveBeenCalled();
  });

  it("upserts only validated whitelisted settings", async () => {
    const response = await PUT(
      request({ freshDays: 14, minReactions: 0, ignoredSecret: "no" }),
    );
    expect(response.status).toBe(200);
    const values = mocks.query.mock.calls.flatMap((call) => call[1]);
    expect(values).toContain("fresh_days");
    expect(values).toContain("min_reactions");
    expect(values).not.toContain("ignoredSecret");
  });

  it("allows a same-origin mutation without a session", async () => {
    const response = await PUT(request({ freshDays: 7 }));
    expect(response.status).toBe(200);
    expect(mocks.query).toHaveBeenCalled();
  });
});
