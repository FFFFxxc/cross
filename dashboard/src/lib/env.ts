import { z } from "zod";

const Env = z.object({
  DATABASE_URL: z.string().url(),
  DB_BRIDGE_URL: z.string().url().optional(),
  DB_BRIDGE_TOKEN: z.string().min(32).optional(),
}).superRefine((value, ctx) => {
  if (Boolean(value.DB_BRIDGE_URL) !== Boolean(value.DB_BRIDGE_TOKEN)) {
    ctx.addIssue({
      code: "custom",
      message: "DB_BRIDGE_URL и DB_BRIDGE_TOKEN должны быть заданы вместе.",
    });
  }
});

export type DashboardEnv = z.infer<typeof Env>;

export function getEnv(): DashboardEnv {
  return Env.parse({
    DATABASE_URL: process.env.DATABASE_URL,
    DB_BRIDGE_URL: process.env.DB_BRIDGE_URL || undefined,
    DB_BRIDGE_TOKEN: process.env.DB_BRIDGE_TOKEN || undefined,
  });
}
