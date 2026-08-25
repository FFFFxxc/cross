import { Pool, type QueryResultRow } from "pg";

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

export async function query<T extends QueryResultRow>(
  sql: string,
  values: readonly unknown[] = [],
): Promise<T[]> {
  const result = await pool().query<T>(sql, [...values]);
  return result.rows;
}
