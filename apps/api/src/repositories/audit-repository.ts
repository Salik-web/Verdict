// SPDX-License-Identifier: AGPL-3.0-or-later
// Copyright (C) 2026 Salik Syed
import type { Database } from "../db/client.js";
import { auditLogs } from "../db/schema.js";

export class AuditRepository {
  constructor(private readonly db: Database) {}

  /** Append-only; failures must never break the request path (fire-and-log). */
  async record(entry: {
    accountId?: string | null;
    actorType: "user" | "system" | "internal";
    actorId?: string | null;
    action: string;
    resourceType?: string | null;
    resourceId?: string | null;
    metadata?: Record<string, unknown>;
    ip?: string | null;
  }): Promise<void> {
    await this.db.insert(auditLogs).values({
      accountId: entry.accountId ?? null,
      actorType: entry.actorType,
      actorId: entry.actorId ?? null,
      action: entry.action,
      resourceType: entry.resourceType ?? null,
      resourceId: entry.resourceId ?? null,
      metadata: entry.metadata ?? {},
      ip: entry.ip ?? null,
    });
  }
}
