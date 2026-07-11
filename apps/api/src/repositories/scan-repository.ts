import { and, desc, eq, gte, sql } from "drizzle-orm";
import type { Database } from "../db/client.js";
import { scans } from "../db/schema.js";

export type Scan = typeof scans.$inferSelect;
export type NewScan = typeof scans.$inferInsert;

export class ScanRepository {
  constructor(private readonly db: Database) {}

  async create(data: NewScan): Promise<Scan> {
    const rows = await this.db.insert(scans).values(data).returning();
    return rows[0]!;
  }

  async findById(accountId: string, id: string): Promise<Scan | null> {
    const rows = await this.db
      .select()
      .from(scans)
      .where(and(eq(scans.accountId, accountId), eq(scans.id, id)))
      .limit(1);
    return rows[0] ?? null;
  }

  async listByAccount(accountId: string, limit = 50): Promise<Scan[]> {
    return this.db
      .select()
      .from(scans)
      .where(eq(scans.accountId, accountId))
      .orderBy(desc(scans.createdAt))
      .limit(limit);
  }

  /** Scans created since `since` — drives the plan usage quota. */
  async countSince(accountId: string, since: Date): Promise<number> {
    const rows = await this.db
      .select({ n: sql<number>`count(*)::int` })
      .from(scans)
      .where(and(eq(scans.accountId, accountId), gte(scans.createdAt, since)));
    return rows[0]?.n ?? 0;
  }
}
