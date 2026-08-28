import { beforeEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({ query: vi.fn() }));
vi.mock("@/lib/db", () => ({ query: mocks.query }));

import { DELETE, POST } from "./route";

function request(method: "POST" | "DELETE", origin = "https://panel.example") {
  return new Request("https://panel.example/api/queue/item-1/ai-caption", {
    method,
    headers: { origin },
  });
}

const context = { params: Promise.resolve({ id: "item-1" }) };

describe("queue AI caption route", () => {
  beforeEach(() => {
    mocks.query.mockReset().mockResolvedValue([{ id: "item-1", ai_caption_status: "unchecked" }]);
  });

  it("resets a caption for regeneration", async () => {
    expect((await POST(request("POST"), context)).status).toBe(200);
    expect(mocks.query.mock.calls[0][0]).toContain("ai_caption_status = 'manual'");
  });

  it("removes a caption permanently until manual regeneration", async () => {
    expect((await DELETE(request("DELETE"), context)).status).toBe(200);
    expect(mocks.query.mock.calls[0][0]).toContain("ai_caption_status = 'dismissed'");
  });

  it("rejects a foreign origin", async () => {
    expect((await DELETE(request("DELETE", "https://evil.example"), context)).status).toBe(403);
  });
});
