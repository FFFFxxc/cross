import { z } from "zod";

const Env = z.object({
  DATABASE_URL: z.string().url(),
  ADMIN_PASSWORD_HASH: z.string().min(40),
  AUTH_SECRET: z.string().min(32),
});

export type DashboardEnv = z.infer<typeof Env>;

export function getEnv(): DashboardEnv {
  return Env.parse({
    DATABASE_URL: process.env.DATABASE_URL,
    ADMIN_PASSWORD_HASH: process.env.ADMIN_PASSWORD_HASH,
    AUTH_SECRET: process.env.AUTH_SECRET,
  });
}
