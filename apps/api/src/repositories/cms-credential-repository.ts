import { and, eq } from "drizzle-orm";
import type { Database } from "../db/client.js";
import { cmsCredentials } from "../db/schema.js";

type Row = typeof cmsCredentials.$inferSelect;

/** What the API is allowed to return — never key material or ciphertext. */
export interface CmsCredentialPublic {
  id: string;
  cmsType: string;
  name: string;
  status: string;
  lastUsedAt: Date | null;
  createdAt: Date;
}

function toPublic(row: Row): CmsCredentialPublic {
  return {
    id: row.id,
    cmsType: row.cmsType,
    name: row.name,
    status: row.status,
    lastUsedAt: row.lastUsedAt,
    createdAt: row.createdAt,
  };
}

export class CmsCredentialRepository {
  constructor(private readonly db: Database) {}

  async create(data: {
    accountId: string;
    cmsType: string;
    name: string;
    keyVersion: number;
    encryptedDek: Buffer;
    ciphertext: Buffer;
  }): Promise<CmsCredentialPublic> {
    const rows = await this.db.insert(cmsCredentials).values(data).returning();
    return toPublic(rows[0]!);
  }

  async listByAccount(accountId: string): Promise<CmsCredentialPublic[]> {
    const rows = await this.db
      .select()
      .from(cmsCredentials)
      .where(eq(cmsCredentials.accountId, accountId));
    return rows.map(toPublic);
  }

  /**
   * Full row incl. ciphertext — ONLY for the Execute stage's internal
   * decryption path, never for API responses.
   */
  async findEncrypted(accountId: string, id: string): Promise<Row | null> {
    const rows = await this.db
      .select()
      .from(cmsCredentials)
      .where(
        and(eq(cmsCredentials.accountId, accountId), eq(cmsCredentials.id, id)),
      )
      .limit(1);
    return rows[0] ?? null;
  }

  async delete(accountId: string, id: string): Promise<boolean> {
    const rows = await this.db
      .delete(cmsCredentials)
      .where(
        and(eq(cmsCredentials.accountId, accountId), eq(cmsCredentials.id, id)),
      )
      .returning({ id: cmsCredentials.id });
    return rows.length > 0;
  }
}
