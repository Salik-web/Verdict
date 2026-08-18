// SPDX-License-Identifier: AGPL-3.0-or-later
// Copyright (C) 2026 Salik Syed
/**
 * Zod boundary validation. Every route parses its body/params/query through
 * here; invalid input never reaches a handler.
 */
import type { FastifyReply } from "fastify";
import { z } from "zod";

export class ValidationFailed extends Error {
  constructor(readonly issues: z.ZodIssue[]) {
    super("validation failed");
  }
}

export function parse<T extends z.ZodTypeAny>(
  schema: T,
  data: unknown,
): z.infer<T> {
  const result = schema.safeParse(data);
  if (!result.success) throw new ValidationFailed(result.error.issues);
  return result.data;
}

export async function sendValidationError(
  reply: FastifyReply,
  err: ValidationFailed,
): Promise<void> {
  await reply.code(400).send({
    error: "invalid_request",
    issues: err.issues.map((i) => ({
      path: i.path.join("."),
      message: i.message,
    })),
  });
}

export const uuidParam = z.object({ id: z.string().uuid() });

/**
 * A registrable hostname, normalized.
 *
 * `z.string().max(255)` used to be the only guard, which accepted `""`, a
 * single space, and `http://example.com/pricing`. None of those are caught
 * until Diagnosis builds `https://{domain}` and tries to fetch it — an empty
 * string makes the stage silently skip (falsy), and whitespace makes it fetch
 * `https:// `. Validating at the boundary is what stops a bad value being
 * stored at all.
 *
 * Deliberately forgiving about INPUT and strict about what gets STORED: people
 * paste URLs out of a browser bar, so a scheme, a path, a port, and surrounding
 * whitespace are stripped rather than rejected. What survives must be a real
 * hostname.
 *
 * Note this rejects bare IP addresses as a side effect of requiring an
 * alphabetic TLD, which is intended — an account's brand domain is a domain.
 * SSRF safety is enforced separately, at fetch time, by the pipeline's
 * `assert_public_url`; this is a data-quality check, not a security boundary.
 */
const HOSTNAME_RE =
  /^(?=.{1,253}$)(?!-)[a-z0-9-]{1,63}(?<!-)(\.(?!-)[a-z0-9-]{1,63}(?<!-))*\.[a-z]{2,63}$/;

export const domainSchema = z
  .string()
  .trim()
  .transform((raw) =>
    raw
      .replace(/^[a-z][a-z0-9+.-]*:\/\//i, "") // scheme
      .replace(/^[^/@]*@/, "") // userinfo
      .replace(/[/?#].*$/, "") // path, query, fragment
      .replace(/:\d+$/, "") // port
      .replace(/\.$/, "") // fully-qualified trailing dot
      .toLowerCase(),
  )
  .refine((host) => host.length > 0, {
    message:
      "domain is required — send null to clear it, not an empty string",
  })
  .refine((host) => HOSTNAME_RE.test(host), {
    message:
      "must be a hostname like example.com (no scheme, path, or IP address)",
  });
