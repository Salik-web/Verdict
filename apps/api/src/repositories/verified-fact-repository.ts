// SPDX-License-Identifier: AGPL-3.0-or-later
// Copyright (C) 2026 Salik Syed
import { and, eq } from "drizzle-orm";
import type { Database } from "../db/client.js";
import { verifiedFacts } from "../db/schema.js";

export type VerifiedFact = typeof verifiedFacts.$inferSelect;
export type NewVerifiedFact = typeof verifiedFacts.$inferInsert;

export class VerifiedFactRepository {
  constructor(private readonly db: Database) {}

  async listByAccount(accountId: string): Promise<VerifiedFact[]> {
    return this.db
      .select()
      .from(verifiedFacts)
      .where(eq(verifiedFacts.accountId, accountId));
  }

  async findById(accountId: string, id: string): Promise<VerifiedFact | null> {
    const rows = await this.db
      .select()
      .from(verifiedFacts)
      .where(
        and(eq(verifiedFacts.accountId, accountId), eq(verifiedFacts.id, id)),
      )
      .limit(1);
    return rows[0] ?? null;
  }

  async create(data: NewVerifiedFact): Promise<VerifiedFact> {
    const rows = await this.db.insert(verifiedFacts).values(data).returning();
    return rows[0]!;
  }

  async update(
    accountId: string,
    id: string,
    patch: Partial<
      Pick<
        NewVerifiedFact,
        | "value"
        | "source"
        | "confidence"
        | "isActive"
        | "effectiveFrom"
        | "effectiveTo"
      >
    >,
  ): Promise<VerifiedFact | null> {
    const rows = await this.db
      .update(verifiedFacts)
      .set(patch)
      .where(
        and(eq(verifiedFacts.accountId, accountId), eq(verifiedFacts.id, id)),
      )
      .returning();
    return rows[0] ?? null;
  }

  async delete(accountId: string, id: string): Promise<boolean> {
    const rows = await this.db
      .delete(verifiedFacts)
      .where(
        and(eq(verifiedFacts.accountId, accountId), eq(verifiedFacts.id, id)),
      )
      .returning({ id: verifiedFacts.id });
    return rows.length > 0;
  }
}
