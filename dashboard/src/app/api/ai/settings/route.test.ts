import { beforeEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({ query: vi.fn() }));
vi.mock("@/lib/db", () => ({ query: mocks.query }));

import { GET, PUT } from "./route";

function request(body: unknown, origin = "https://panel.example") {
  return new Request("https://panel.example/api/ai/settings", {
    method: "PUT",
    headers: { "content-type": "application/json", origin },
    body: JSON.stringify(body),
  });
}

describe("AI settings route", () => {
  beforeEach(() => {
    vi.stubEnv("DATABASE_URL", "postgresql://user:pass@example.com/db");
    mocks.query.mockReset().mockResolvedValue([]);
  });

  it("never returns saved API keys", async () => {
    mocks.query.mockResolvedValue([
      { key: "ai_enabled", value: "true" },
      { key: "ai_provider_1_base_url", value: "https://router.example/v1" },
      { key: "ai_provider_1_model", value: "vision-model" },
      { key: "ai_provider_1_api_key", value: "enc:v1:secret-ciphertext" },
    ]);

    const payload = await (await GET()).json();

    expect(payload.settings.providers[0]).toMatchObject({
      baseUrl: "https://router.example/v1",
      model: "vision-model",
      hasKey: true,
    });
    expect(JSON.stringify(payload)).not.toContain("secret-ciphertext");
  });

  it("encrypts a new key and preserves it when the password field is blank", async () => {
    const response = await PUT(request({
      enabled: true,
      prompt: "Короткая подпись",
      maxChars: 140,
      autoDelaySeconds: 90,
      intervalSeconds: 20,
      providers: [
        { index: 1, baseUrl: "https://router.example/v1", model: "vision", apiKey: "sk-new" },
        { index: 2, baseUrl: "", model: "", apiKey: "" },
      ],
    }));

    expect(response.status).toBe(200);
    const values = mocks.query.mock.calls.flatMap((call) => call[1] || []);
    expect(values).toContain("ai_provider_1_api_key");
    expect(values.some((value) => typeof value === "string" && value.startsWith("enc:v1:"))).toBe(true);
    expect(values).not.toContain("sk-new");
  });

  it("rejects non-HTTPS provider URLs and foreign origins", async () => {
    expect((await PUT(request({ enabled: true, prompt: "x", maxChars: 140, autoDelaySeconds: 90, intervalSeconds: 20, providers: [
      { index: 1, baseUrl: "http://localhost:8080/v1", model: "x", apiKey: "x" },
      { index: 2, baseUrl: "", model: "", apiKey: "" },
    ] }))).status).toBe(400);
    expect((await PUT(request({ enabled: false }, "https://evil.example"))).status).toBe(403);
  });
});
