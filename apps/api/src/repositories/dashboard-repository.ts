import { and, desc, eq } from "drizzle-orm";
import type { Database } from "../db/client.js";
import {
  assets,
  gaps,
  mentions,
  shareOfVoice,
  verifications,
} from "../db/schema.js";

export type Mention = typeof mentions.$inferSelect;
export type Gap = typeof gaps.$inferSelect;
export type Asset = typeof assets.$inferSelect;
export type ShareOfVoice = typeof shareOfVoice.$inferSelect;
export type Verification = typeof verifications.$inferSelect;

/**
 * Read-only dashboard queries. All tenant-scoped; pipeline stages write these
 * tables, the API only reads them.
 */
export class DashboardRepository {
  constructor(private readonly db: Database) {}

  async listMentions(
    accountId: string,
    opts: { scanId?: string; limit?: number } = {},
  ): Promise<Mention[]> {
    const where = opts.scanId
      ? and(eq(mentions.accountId, accountId), eq(mentions.scanId, opts.scanId))
      : eq(mentions.accountId, accountId);
    return this.db
      .select()
      .from(mentions)
      .where(where)
      .orderBy(desc(mentions.createdAt))
      .limit(opts.limit ?? 100);
  }

  async listGaps(
    accountId: string,
    opts: { status?: Gap["status"]; limit?: number } = {},
  ): Promise<Gap[]> {
    const where = opts.status
      ? and(eq(gaps.accountId, accountId), eq(gaps.status, opts.status))
      : eq(gaps.accountId, accountId);
    return this.db
      .select()
      .from(gaps)
      .where(where)
      .orderBy(desc(gaps.createdAt))
      .limit(opts.limit ?? 100);
  }

  async listAssets(
    accountId: string,
    opts: { status?: Asset["status"]; limit?: number } = {},
  ): Promise<Asset[]> {
    const where = opts.status
      ? and(eq(assets.accountId, accountId), eq(assets.status, opts.status))
      : eq(assets.accountId, accountId);
    return this.db
      .select()
      .from(assets)
      .where(where)
      .orderBy(desc(assets.createdAt))
      .limit(opts.limit ?? 100);
  }

  async getAsset(accountId: string, id: string): Promise<Asset | undefined> {
    const rows = await this.db
      .select()
      .from(assets)
      .where(and(eq(assets.accountId, accountId), eq(assets.id, id)))
      .limit(1);
    return rows[0];
  }

  async listVerifications(
    accountId: string,
    opts: { assetId?: string; limit?: number } = {},
  ): Promise<Verification[]> {
    const where = opts.assetId
      ? and(
          eq(verifications.accountId, accountId),
          eq(verifications.assetId, opts.assetId),
        )
      : eq(verifications.accountId, accountId);
    return this.db
      .select()
      .from(verifications)
      .where(where)
      .orderBy(desc(verifications.createdAt))
      .limit(opts.limit ?? 100);
  }

  async getVerification(
    accountId: string,
    id: string,
  ): Promise<Verification | undefined> {
    const rows = await this.db
      .select()
      .from(verifications)
      .where(
        and(eq(verifications.accountId, accountId), eq(verifications.id, id)),
      )
      .limit(1);
    return rows[0];
  }

  async listShareOfVoice(
    accountId: string,
    opts: { scanId?: string; limit?: number } = {},
  ): Promise<ShareOfVoice[]> {
    const where = opts.scanId
      ? and(
          eq(shareOfVoice.accountId, accountId),
          eq(shareOfVoice.scanId, opts.scanId),
        )
      : eq(shareOfVoice.accountId, accountId);
    return this.db
      .select()
      .from(shareOfVoice)
      .where(where)
      .orderBy(desc(shareOfVoice.createdAt))
      .limit(opts.limit ?? 100);
  }
}
