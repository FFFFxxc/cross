import { describe, expect, it } from "vitest";

import { decryptAiSecret, encryptAiSecret } from "./ai-secrets";

describe("AI provider secrets", () => {
  it("encrypts API keys with a stable shared secret", () => {
    const encrypted = encryptAiSecret("sk-private", "postgresql://shared-secret");
    expect(encrypted).toMatch(/^enc:v1:/);
    expect(encrypted).not.toContain("sk-private");
    expect(decryptAiSecret(encrypted, "postgresql://shared-secret")).toBe("sk-private");
  });
});
