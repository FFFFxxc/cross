import { expect, test } from "@playwright/test";

const queueItem = {
  id: "item-e2e",
  source: "animeworldmem",
  postKey: "message:77",
  messageIds: [77],
  mediaKind: "video",
  score: 9500,
  publishedAt: "2026-08-25T12:00:00.000Z",
  status: "pending",
  captionExcerpt: "Проверочный аниме-пост",
  viewsCount: 25_000,
  reactionsCount: 870,
  forwardsCount: 92,
  metricsKnown: true,
  hasPreview: true,
  error: null,
};

test("public queue controls and safe settings work on desktop and mobile", async ({ page }) => {
  const consoleErrors: string[] = [];
  const queueRequests: string[] = [];
  page.on("console", (message) => {
    if (message.type() === "error") consoleErrors.push(message.text());
  });

  await page.route("**/api/overview", (route) => route.fulfill({
    json: {
      worker: { state: "active", heartbeatAt: new Date().toISOString() },
      scheduler: { state: "active", heartbeatAt: new Date().toISOString(), lastError: null },
      queue: { pending: 1, published: 10 },
      settings: { freshDays: 7, minReactions: 0, minViews: 0 },
      latestActivity: null,
    },
  }));
  await page.route("**/api/queue/item-e2e/preview", (route) => route.fulfill({
    status: 200,
    contentType: "image/png",
    body: Buffer.from(
      "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAusB9Y9Z4xkAAAAASUVORK5CYII=",
      "base64",
    ),
  }));
  await page.route(/\/api\/queue(?:\?.*)?$/, (route) => {
    queueRequests.push(route.request().url());
    return route.fulfill({ json: { items: [queueItem], total: 1, nextCursor: null } });
  });
  await page.route("**/api/settings", async (route) => {
    if (route.request().method() === "GET") {
      return route.fulfill({
        json: {
          settings: {
            fresh_days: "7",
            min_reactions: "0",
            min_views: "0",
            signature_text: "НАШ ТГК",
            signature_url: "https://t.me/webm4ik",
          },
        },
      });
    }
    return route.fulfill({ json: { settings: { min_reactions: "150" } } });
  });
  await page.route("**/api/scans", (route) => route.fulfill({
    status: 202,
    json: { action: { id: "scan-e2e", status: "pending" } },
  }));

  await page.goto("/");
  await expect(page).toHaveURL(/\/$/);
  await expect(page.getByLabel("Пароль")).toHaveCount(0);
  await expect(
    page.getByRole("article").filter({ hasText: "Render-воркер" }).getByText("Работает"),
  ).toBeVisible();

  await page.getByRole("link", { name: "Очередь", exact: true }).click();
  await expect(page.getByText("Проверочный аниме-пост")).toBeVisible();
  await expect(page.getByRole("img", { name: "Проверочный аниме-пост" })).toBeVisible();
  await page.getByLabel("Сортировка").selectOption("reactions");
  await expect.poll(() => queueRequests.some((url) => url.includes("sort=reactions"))).toBe(true);
  await page.getByLabel("Сортировка").selectOption("views");
  await page.getByLabel("Тип").selectOption("video");
  await expect.poll(() => queueRequests.some((url) => url.includes("sort=views") && url.includes("media=video"))).toBe(true);

  await page.getByRole("link", { name: "Настройки" }).click();
  await page.getByLabel("Минимум реакций").fill("150");
  await page.getByRole("button", { name: "Сохранить настройки" }).click();
  await expect(page.getByText("Настройки сохранены.")).toBeVisible();
  const scanStatus = await page.evaluate(async () => {
    const response = await fetch("/api/scans", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ count: 5, mediaKind: "video" }),
    });
    return response.status;
  });
  expect(scanStatus).toBe(202);

  await page.setViewportSize({ width: 375, height: 812 });
  await page.goto("/queue?sort=views&media=video");
  await expect(page.getByText("Проверочный аниме-пост")).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
  expect(consoleErrors).toEqual([]);
});
