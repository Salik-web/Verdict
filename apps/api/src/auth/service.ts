/**
 * AuthService — the auth abstraction.
 *
 * LocalAuthService implements email+password entirely offline (argon2 +
 * Redis sessions), satisfying mock-first. A ClerkAuthService (or Supabase)
 * can implement the same interface later and be selected via config — the
 * same swappability pattern as the model gateway.
 *
 * Email verification and MFA: both need an external provider (email/SMS),
 * i.e. keys. The interface carries the hooks now; LocalAuthService records
 * users as unverified-capable but active, so the flows slot in without
 * schema or route changes.
 */
import type { Database } from "../db/client.js";
import { AccountRepository } from "../repositories/account-repository.js";
import { UserRepository, type User } from "../repositories/user-repository.js";
import { hashPassword, verifyPassword } from "./password.js";
import type { SessionPair, SessionStore } from "./session-store.js";

export interface SignupInput {
  email: string;
  password: string;
  name?: string;
  accountName: string;
}

export interface AuthResult {
  userId: string;
  accountId: string;
  pair: SessionPair;
}

export interface AuthService {
  signup(input: SignupInput): Promise<AuthResult>;
  login(email: string, password: string): Promise<AuthResult | null>;
  refresh(refreshId: string): Promise<SessionPair | null>;
  logout(sessionId?: string, refreshId?: string): Promise<void>;
}

function slugify(name: string): string {
  const base = name
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "")
    .slice(0, 40);
  // Random suffix avoids collisions without a read-check race.
  return `${base || "account"}-${Math.random().toString(36).slice(2, 8)}`;
}

export class LocalAuthService implements AuthService {
  constructor(
    private readonly db: Database,
    private readonly sessions: SessionStore,
  ) {}

  async signup(input: SignupInput): Promise<AuthResult> {
    const usersRepo = new UserRepository(this.db);
    const existing = await usersRepo.findByEmail(input.email);
    if (existing) {
      throw new AuthError("email_taken", "an account with this email exists");
    }

    // Account + owner user atomically — no orphan accounts on failure.
    const { user } = await this.db.transaction(async (tx) => {
      const account = await new AccountRepository(
        tx as unknown as Database,
      ).create({
        name: input.accountName,
        slug: slugify(input.accountName),
      });
      const user = await new UserRepository(tx as unknown as Database).create({
        accountId: account.id,
        email: input.email.toLowerCase(),
        name: input.name,
        role: "owner",
        passwordHash: await hashPassword(input.password),
      });
      return { user };
    });

    const pair = await this.sessions.create(user.id, user.accountId);
    return { userId: user.id, accountId: user.accountId, pair };
  }

  async login(email: string, password: string): Promise<AuthResult | null> {
    const usersRepo = new UserRepository(this.db);
    const user = await usersRepo.findByEmail(email);
    // Always run a verify to keep timing uniform for unknown emails.
    const ok = await verifyPassword(user?.passwordHash ?? DUMMY_HASH, password);
    if (!user?.passwordHash || !ok || user.status !== "active") return null;

    await usersRepo.touchLastLogin(user.id);
    const pair = await this.sessions.create(user.id, user.accountId);
    return { userId: user.id, accountId: user.accountId, pair };
  }

  async refresh(refreshId: string): Promise<SessionPair | null> {
    return this.sessions.rotate(refreshId);
  }

  async logout(sessionId?: string, refreshId?: string): Promise<void> {
    await this.sessions.destroy({ sessionId, refreshId });
  }
}

export class AuthError extends Error {
  constructor(
    readonly code: "email_taken",
    message: string,
  ) {
    super(message);
    this.name = "AuthError";
  }
}

/** Pre-computed argon2id hash of a random string; used to equalize timing. */
const DUMMY_HASH =
  "$argon2id$v=19$m=19456,t=2,p=1$AAAAAAAAAAAAAAAAAAAAAA$K5cIJvHkoZmb0Nh1knPQnkH9uk1HpcIkgs209hjuA1A";

export type { User };
