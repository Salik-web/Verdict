import { and, eq } from "drizzle-orm";
import type { Database } from "../db/client.js";
import { prompts } from "../db/schema.js";

export type Prompt = typeof prompts.$inferSelect;
export type NewPrompt = typeof prompts.$inferInsert;

/** Tenant-scoped data access for prompts. */
export class PromptRepository {
  constructor(private readonly db: Database) {}

  async listByAccount(
    accountId: string,
    opts: { activeOnly?: boolean } = {},
  ): Promise<Prompt[]> {
    const where = opts.activeOnly
      ? and(eq(prompts.accountId, accountId), eq(prompts.active, true))
      : eq(prompts.accountId, accountId);
    return this.db.select().from(prompts).where(where);
  }

  async findById(accountId: string, id: string): Promise<Prompt | null> {
    const rows = await this.db
      .select()
      .from(prompts)
      .where(and(eq(prompts.accountId, accountId), eq(prompts.id, id)))
      .limit(1);
    return rows[0] ?? null;
  }

  async create(data: NewPrompt): Promise<Prompt> {
    const rows = await this.db.insert(prompts).values(data).returning();
    return rows[0]!;
  }

  async update(
    accountId: string,
    id: string,
    patch: Partial<
      Pick<NewPrompt, "text" | "category" | "promptGroup" | "active">
    >,
  ): Promise<Prompt | null> {
    const rows = await this.db
      .update(prompts)
      .set(patch)
      .where(and(eq(prompts.accountId, accountId), eq(prompts.id, id)))
      .returning();
    return rows[0] ?? null;
  }

  async delete(accountId: string, id: string): Promise<boolean> {
    const rows = await this.db
      .delete(prompts)
      .where(and(eq(prompts.accountId, accountId), eq(prompts.id, id)))
      .returning({ id: prompts.id });
    return rows.length > 0;
  }
}
