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
