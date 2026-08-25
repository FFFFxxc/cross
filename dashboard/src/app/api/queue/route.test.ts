import { beforeEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({
  hasSession: vi.fn(),
  query: vi.fn(),
}));

vi.mock("@/lib/auth", () => ({ hasSession: mocks.hasSession }));
vi.mock("@/lib/db", () => ({ query: mocks.query }));

import { GET } from "./route";

describe("queue route", () => {
  beforeEach(() => {
    mocks.hasSession.mockReset();
    mocks.query.mockReset();
  });

  it("returns 401 without a valid session", async () => {
    mocks.hasSession.mockResolvedValue(false);
    const response = await GET(new Request("https://panel.example/api/queue"));
    expect(response.status).toBe(401);
    expect(mocks.query).not.toHaveBeenCalled();
  });

  it("returns sanitized legacy-compatible rows and a cursor", async () => {
    mocks.hasSession.mockResolvedValue(true);
    mocks.query.mockResolvedValue([
      {
        id: "item-1",
        source: "anime",
        post_key: "message:1",
        message_ids: "[1]",
        media_kind: "image",
        score: 9,
        published_at: "2026-08-25T12:00:00+00:00",
        status: "pending",
        caption_excerpt: "caption",
        views_count: null,
        reactions_count: null,
        forwards_count: null,
        preview_mime: "image/webp",
        error: null,
        total_count: 11,
        preview_data: Buffer.from("must-not-leak"),
      },
    ]);
    const response = await GET(
      new Request("https://panel.example/api/queue?limit=10&sort=reactions"),
    );
    const payload = await response.json();

    expect(response.status).toBe(200);
    expect(response.headers.get("cache-control")).toContain("private");
    expect(payload.items[0]).toMatchObject({
      viewsCount: 0,
      reactionsCount: 0,
      forwardsCount: 0,
      hasPreview: true,
    });
    expect(payload.items[0]).not.toHaveProperty("preview_data");
    expect(payload.nextCursor).toBe("10");
  });

  it("returns 400 for invalid query values", async () => {
    mocks.hasSession.mockResolvedValue(true);
    const response = await GET(
      new Request("https://panel.example/api/queue?sort=DROP%20TABLE"),
    );
    expect(response.status).toBe(400);
  });
});
