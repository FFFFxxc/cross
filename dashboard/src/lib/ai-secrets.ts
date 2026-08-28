import { createCipheriv, createDecipheriv, createHash, randomBytes } from "node:crypto";

const AAD = Buffer.from("desiree-ai-provider-v1", "utf8");

function key(secret: string) {
  if (!secret) throw new Error("Секрет шифрования AI-ключей не задан.");
  let material = secret;
  try {
    const parsed = new URL(secret);
    if (parsed.password) material = decodeURIComponent(parsed.password);
  } catch {
    // A non-URL secret is valid for local tests and development.
  }
  return createHash("sha256").update(material, "utf8").digest();
}

export function encryptAiSecret(value: string, secret: string): string {
  if (!value) throw new Error("API-ключ не может быть пустым.");
  const nonce = randomBytes(12);
  const cipher = createCipheriv("aes-256-gcm", key(secret), nonce);
  cipher.setAAD(AAD);
  const encrypted = Buffer.concat([cipher.update(value, "utf8"), cipher.final()]);
  const payload = Buffer.concat([nonce, encrypted, cipher.getAuthTag()]).toString("base64url");
  return `enc:v1:${payload}`;
}

export function decryptAiSecret(value: string, secret: string): string {
  if (!value.startsWith("enc:v1:")) return value;
  const payload = Buffer.from(value.slice("enc:v1:".length), "base64url");
  const nonce = payload.subarray(0, 12);
  const ciphertext = payload.subarray(12, -16);
  const tag = payload.subarray(-16);
  const decipher = createDecipheriv("aes-256-gcm", key(secret), nonce);
  decipher.setAAD(AAD);
  decipher.setAuthTag(tag);
  return Buffer.concat([decipher.update(ciphertext), decipher.final()]).toString("utf8");
}
