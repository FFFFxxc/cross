import { Pool, type QueryResultRow } from "pg";
import { connection } from "next/server";

import { getEnv } from "./env";

const globalDatabase = globalThis as typeof globalThis & {
  desireePool?: Pool;
};

function pool(): Pool {
  if (!globalDatabase.desireePool) {
    globalDatabase.desireePool = new Pool({
      connectionString: getEnv().DATABASE_URL,
      max: 2,
      ssl: { rejectUnauthorized: false },
      idleTimeoutMillis: 20_000,
    });
  }
  return globalDatabase.desireePool;
}

function revive(value: unknown): unknown {
  if (Array.isArray(value)) {
    return value.map(revive);
  }

  if (value && typeof value === "object") {
    const record = value as Record<string, unknown>;

    if (
      record.__type === "Buffer" &&
      typeof record.data === "string"
    ) {
      return Buffer.from(record.data, "base64");
    }

    return Object.fromEntries(
      Object.entries(record).map(([key, item]) => [key, revive(item)]),
    );
  }

  return value;
}

async function bridgeQuery<T extends QueryResultRow>(
  sql: string,
  values: readonly unknown[],
): Promise<T[]> {
  const env = getEnv();

  if (!env.DB_BRIDGE_URL || !env.DB_BRIDGE_TOKEN) {
    throw new Error("DB bridge настроен не полностью.");
  }

  const response = await fetch(
    `${env.DB_BRIDGE_URL.replace(/\/$/, "")}/v1/query`,
    {
      method: "POST",
      headers: {
        "content-type": "application/json",
        authorization: `Bearer ${env.DB_BRIDGE_TOKEN}`,
      },
      body: JSON.stringify({
        sql,
        values,
      }),
      cache: "no-store",
      signal: AbortSignal.timeout(20_000),
    },
  );

  const payload = (await response.json().catch(() => ({}))) as {
    rows?: unknown[];
    error?: string;
  };

  if (!response.ok) {
    throw new Error(payload.error || `DB bridge HTTP ${response.status}`);
  }

  return revive(payload.rows || []) as T[];
}

export async function query<T extends QueryResultRow>(
  sql: string,
  values: readonly unknown[] = [],
): Promise<T[]> {
  await connection();

  const env = getEnv();

  if (env.DB_BRIDGE_URL && env.DB_BRIDGE_TOKEN) {
    return bridgeQuery<T>(sql, values);
  }

  const result = await pool().query<T>(sql, [...values]);
  return result.rows;
}
