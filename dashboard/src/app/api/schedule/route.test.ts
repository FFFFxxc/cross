import { beforeEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({ query: vi.fn() }));
vi.mock("@/lib/db", () => ({ query: mocks.query }));

import { PUT } from "./route";

function request(body: unknown) {
  return new Request("https://panel.example/api/schedule", {
    method: "PUT",
    headers: {
      "content-type": "application/json",
      origin: "https://panel.example",
    },
    body: JSON.stringify(body),
  });
}

describe("schedule mutation", () => {
  beforeEach(() => mocks.query.mockReset());

  it("rejects a content source assigned to a news slot", async () => {
    mocks.query.mockResolvedValueOnce([{ category: "content" }]);

    const response = await PUT(request({
      time: "16:00",
      mediaKind: "news",
      source: "memes",
    }));

    expect(response.status).toBe(400);
    expect(mocks.query).toHaveBeenCalledTimes(1);
  });
});
