import bcrypt from "bcryptjs";
import { SignJWT, jwtVerify } from "jose";
import { cookies } from "next/headers";
import { redirect } from "next/navigation";

import { getEnv } from "./env";

export const SESSION_COOKIE = "desiree_session";
export const SESSION_OPTIONS = {
  httpOnly: true,
  secure: true,
  sameSite: "lax" as const,
  path: "/",
  maxAge: 60 * 60 * 24 * 7,
};

function key(secret: string): Uint8Array {
  return new TextEncoder().encode(secret);
}

export async function verifyPassword(password: string, hash: string): Promise<boolean> {
  return bcrypt.compare(password, hash);
}

export async function createSessionToken(
  secret: string,
  expiresIn: string | number = "7d",
): Promise<string> {
  return new SignJWT({ role: "admin" })
    .setProtectedHeader({ alg: "HS256" })
    .setIssuedAt()
    .setExpirationTime(expiresIn)
    .sign(key(secret));
}

export async function verifySessionToken(
  token: string,
  secret: string,
): Promise<boolean> {
  try {
    const result = await jwtVerify(token, key(secret), { algorithms: ["HS256"] });
    return result.payload.role === "admin";
  } catch {
    return false;
  }
}

export async function createSessionCookie(): Promise<{
  name: string;
  value: string;
  options: typeof SESSION_OPTIONS;
}> {
  const token = await createSessionToken(getEnv().AUTH_SECRET);
  return { name: SESSION_COOKIE, value: token, options: SESSION_OPTIONS };
}

export function clearSessionCookie() {
  return {
    name: SESSION_COOKIE,
    value: "",
    options: { ...SESSION_OPTIONS, maxAge: 0 },
  };
}

export async function hasSession(token?: string): Promise<boolean> {
  const value = token ?? (await cookies()).get(SESSION_COOKIE)?.value;
  return Boolean(value && (await verifySessionToken(value, getEnv().AUTH_SECRET)));
}

export async function requireSession(token?: string): Promise<void> {
  if (!(await hasSession(token))) {
    redirect("/login");
  }
}

export function requireSameOrigin(request: Request): void {
  const origin = request.headers.get("origin");
  if (!origin || origin !== new URL(request.url).origin) {
    throw new Error("Invalid request origin");
  }
}
