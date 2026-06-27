import { eq } from "drizzle-orm";
import type { Database } from "../db/client.js";
import { accounts } from "../db/schema.js";

export type Account = typeof accounts.$inferSelect;

/**
 * Data access for the tenant root. accounts has no account_id (it IS the
 * tenant), so lookups are by id/slug. All other entities are reached through
 * tenant-scoped repositories.
 */
export class AccountRepository {
  constructor(private readonly db: Database) {}

  async findById(id: string): Promise<Account | null> {
    const rows = await this.db
      .select()
      .from(accounts)
      .where(eq(accounts.id, id))
      .limit(1);
    return rows[0] ?? null;
  }

  async findBySlug(slug: string): Promise<Account | null> {
    const rows = await this.db
      .select()
      .from(accounts)
      .where(eq(accounts.slug, slug))
      .limit(1);
    return rows[0] ?? null;
  }
}
