import { and, eq } from "drizzle-orm";
import type { Database } from "../db/client.js";
import { competitors } from "../db/schema.js";

export type Competitor = typeof competitors.$inferSelect;

/**
 * Tenant-scoped: every method requires accountId and filters on it. There is no
 * way to read a competitor without naming the tenant — multi-tenancy by design.
 */
export class CompetitorRepository {
  constructor(private readonly db: Database) {}

  async listByAccount(accountId: string): Promise<Competitor[]> {
    return this.db
      .select()
      .from(competitors)
      .where(eq(competitors.accountId, accountId));
  }

  async findById(accountId: string, id: string): Promise<Competitor | null> {
    const rows = await this.db
      .select()
      .from(competitors)
      .where(and(eq(competitors.accountId, accountId), eq(competitors.id, id)))
      .limit(1);
    return rows[0] ?? null;
  }
}
