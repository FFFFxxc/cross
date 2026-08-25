import { describe, expect, it } from "vitest";

import { buildQueueQuery, parseQueueFilters } from "./queue-query";

describe("queue query", () => {
  it.each([
    ["newest", "published_at DESC, id DESC"],
    ["reactions", "reactions_count DESC, published_at DESC"],
    ["views", "views_count DESC, published_at DESC"],
    ["score", "score DESC, published_at DESC"],
  ])("maps %s to a fixed order", (sort, order) => {
    const filters = parseQueueFilters(new URLSearchParams({ sort }));
    expect(buildQueueQuery(filters).sql).toContain(`ORDER BY ${order}`);
  });

  it("parameterizes all user filters and clamps page size", () => {
    const attack = "source' DESC; DROP TABLE automation_queue; --";
    const filters = parseQueueFilters(
      new URLSearchParams({
        source: attack,
        media: "video",
        status: "pending",
        minReactions: "12",
        minViews: "3000",
        limit: "999",
        cursor: "40",
      }),
    );
    const built = buildQueueQuery(filters);
    expect(filters.limit).toBe(60);
    expect(built.sql).not.toContain(attack);
    expect(built.values).toContain(attack);
    expect(built.sql).toContain("LIMIT");
    expect(built.sql).toContain("OFFSET");
  });

  it("rejects unknown sort, media, status and malformed numbers", () => {
    expect(() => parseQueueFilters(new URLSearchParams({ sort: "score;drop" }))).toThrow();
    expect(() => parseQueueFilters(new URLSearchParams({ media: "audio" }))).toThrow();
    expect(() => parseQueueFilters(new URLSearchParams({ status: "anything" }))).toThrow();
    expect(() => parseQueueFilters(new URLSearchParams({ minViews: "NaN" }))).toThrow();
  });
});
