// SPDX-License-Identifier: AGPL-3.0-or-later
// Copyright (C) 2026 Salik Syed
import { and, eq } from "drizzle-orm";
import type { Database } from "../db/client.js";
import { competitors } from "../db/schema.js";

export type Competitor = typeof competitors.$inferSelect;
export type NewCompetitor = typeof competitors.$inferInsert;

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

  async create(data: NewCompetitor): Promise<Competitor> {
    const rows = await this.db.insert(competitors).values(data).returning();
    return rows[0]!;
  }

  async update(
    accountId: string,
    id: string,
    patch: Partial<
      Pick<NewCompetitor, "name" | "domain" | "aliases" | "isSelf">
    >,
  ): Promise<Competitor | null> {
    const rows = await this.db
      .update(competitors)
      .set(patch)
      .where(and(eq(competitors.accountId, accountId), eq(competitors.id, id)))
      .returning();
    return rows[0] ?? null;
  }

  async delete(accountId: string, id: string): Promise<boolean> {
    const rows = await this.db
      .delete(competitors)
      .where(and(eq(competitors.accountId, accountId), eq(competitors.id, id)))
      .returning({ id: competitors.id });
    return rows.length > 0;
  }
}
