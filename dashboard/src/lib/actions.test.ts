import { beforeEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({ query: vi.fn() }));
vi.mock("./db", () => ({ query: mocks.query }));

import {
  createAction,
  scanInput,
  scheduleInput,
  settingsInput,
  sourceInput,
} from "./actions";

describe("dashboard mutations", () => {
  beforeEach(() => mocks.query.mockReset());

  it("returns the existing active publish action on a unique conflict", async () => {
    mocks.query
      .mockRejectedValueOnce(Object.assign(new Error("duplicate"), { code: "23505" }))
      .mockResolvedValueOnce([{ id: "existing", status: "pending" }]);
    const result = await createAction("publish_now", { item_id: "item-1" }, "item-1");
    expect(result.id).toBe("existing");
    expect(mocks.query.mock.calls[1][1]).toContain("item-1");
  });

  it("validates source links, scans and schedule slots", () => {
    expect(sourceInput.parse({ operation: "add", source: "https://t.me/anime_world" })).toBeTruthy();
    expect(() => sourceInput.parse({ operation: "add", source: "javascript:alert(1)" })).toThrow();
    expect(scanInput.parse({ count: 50, mediaKind: "video", start: "2026-08-01" })).toBeTruthy();
    expect(() => scanInput.parse({ count: 0 })).toThrow();
    expect(scheduleInput.parse({ time: "14:00", mediaKind: "video" })).toBeTruthy();
    expect(() => scheduleInput.parse({ time: "25:70", mediaKind: "audio" })).toThrow();
  });

  it("validates freshness, thresholds and signature URL", () => {
    expect(
      settingsInput.parse({
        freshDays: 7,
        minReactions: 0,
        minViews: 5000,
        signatureText: "НАШ ТГК",
        signatureUrl: "https://t.me/webm4ik",
      }),
    ).toBeTruthy();
    expect(() => settingsInput.parse({ freshDays: 91 })).toThrow();
    expect(() => settingsInput.parse({ minViews: -1 })).toThrow();
    expect(() => settingsInput.parse({ signatureUrl: "javascript:bad" })).toThrow();
  });
});
