// SPDX-License-Identifier: AGPL-3.0-or-later
// Copyright (C) 2026 Salik Syed
import type { FastifyInstance } from "fastify";
import { z } from "zod";
import { authOf, buildRequireAuth } from "../auth/plugin.js";
import type { AppContext } from "../context.js";
import { AuditRepository } from "../repositories/audit-repository.js";
import { CmsCredentialRepository } from "../repositories/cms-credential-repository.js";
import { parse, uuidParam } from "../validate.js";

const createSchema = z.object({
  cmsType: z.string().min(1).max(40),
  name: z.string().min(1).max(120),
  // Free-form credential material (tokens, app passwords, URLs). Encrypted as
  // a JSON blob; shape depends on cms_type and is validated at use time.
  credentials: z
    .record(z.string().max(4000))
    .refine((o) => Object.keys(o).length > 0, "credentials must not be empty"),
});

/**
 * CMS credentials: WRITE-ONLY from the API consumer's perspective. Stored via
 * envelope encryption; list/read endpoints return metadata only — never the
 * secret material, in any form.
 */
export function registerCmsCredentialRoutes(
  app: FastifyInstance,
  ctx: AppContext,
): void {
  const requireAuth = buildRequireAuth(ctx.sessions);
  const repo = new CmsCredentialRepository(ctx.db);
  const audit = new AuditRepository(ctx.db);

  app.post(
    "/cms-credentials",
    { preHandler: requireAuth },
    async (req, reply) => {
      const { accountId, userId } = authOf(req);
      const body = parse(createSchema, req.body);

      const sealed = ctx.envelope.encrypt(JSON.stringify(body.credentials));
      const row = await repo.create({
        accountId,
        cmsType: body.cmsType,
        name: body.name,
        keyVersion: sealed.keyVersion,
        encryptedDek: sealed.encryptedDek,
        ciphertext: sealed.ciphertext,
      });

      void audit.record({
        accountId,
        actorType: "user",
        actorId: userId,
        action: "cms_credential.create",
        resourceType: "cms_credential",
        resourceId: row.id,
        metadata: { cmsType: body.cmsType },
        ip: req.ip,
      });
      return reply.code(201).send(row); // public shape only — no key material
    },
  );

  app.get("/cms-credentials", { preHandler: requireAuth }, async (req) => {
    const { accountId } = authOf(req);
    return repo.listByAccount(accountId); // metadata only
  });

  app.delete(
    "/cms-credentials/:id",
    { preHandler: requireAuth },
    async (req, reply) => {
      const { accountId, userId } = authOf(req);
      const { id } = parse(uuidParam, req.params);
      const deleted = await repo.delete(accountId, id);
      if (!deleted) return reply.code(404).send({ error: "not_found" });
      void audit.record({
        accountId,
        actorType: "user",
        actorId: userId,
        action: "cms_credential.delete",
        resourceType: "cms_credential",
        resourceId: id,
        ip: req.ip,
      });
      return reply.code(204).send();
    },
  );
}
