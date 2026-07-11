/**
 * Password hashing via argon2id (OWASP first choice). Parameters follow the
 * OWASP minimums (19 MiB memory, t=2, p=1).
 */
import argon2 from "argon2";

const OPTS: argon2.Options = {
  type: argon2.argon2id,
  memoryCost: 19456, // KiB = 19 MiB
  timeCost: 2,
  parallelism: 1,
};

export async function hashPassword(plain: string): Promise<string> {
  return argon2.hash(plain, OPTS);
}

export async function verifyPassword(
  hash: string,
  plain: string,
): Promise<boolean> {
  try {
    return await argon2.verify(hash, plain);
  } catch {
    return false;
  }
}
