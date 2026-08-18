// SPDX-License-Identifier: AGPL-3.0-or-later
// Copyright (C) 2026 Salik Syed
import { eq } from "drizzle-orm";
import type { Database } from "../db/client.js";
import { accounts } from "../db/schema.js";

export type Account = typeof accounts.$inferSelect;
export type NewAccount = typeof accounts.$inferInsert;

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

  async create(data: NewAccount): Promise<Account> {
    const rows = await this.db.insert(accounts).values(data).returning();
    return rows[0]!;
  }

  async update(
    id: string,
    patch: Partial<
      Pick<
        NewAccount,
        "name" | "domain" | "brandName" | "brandAliases" | "settings"
      >
    >,
  ): Promise<Account | null> {
    const rows = await this.db
      .update(accounts)
      .set(patch)
      .where(eq(accounts.id, id))
      .returning();
    return rows[0] ?? null;
  }
}
