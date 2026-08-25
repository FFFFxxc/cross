import { z } from "zod";

const Env = z.object({
  DATABASE_URL: z.string().url(),
});

export type DashboardEnv = z.infer<typeof Env>;

export function getEnv(): DashboardEnv {
  return Env.parse({
    DATABASE_URL: process.env.DATABASE_URL,
  });
}
