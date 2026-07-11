/**
 * Envelope encryption for secrets at rest (CMS credentials).
 *
 * Scheme: a fresh 32-byte data key (DEK) encrypts the plaintext with
 * AES-256-GCM; the DEK itself is encrypted ("wrapped") by the master key (KEK)
 * from MASTER_ENCRYPTION_KEY. Only {wrapped DEK, ciphertext} are stored —
 * compromising the DB alone reveals nothing, and rotating the KEK never
 * requires re-encrypting data (only re-wrapping DEKs; key_version tracks it).
 *
 * Blob layout (both fields): 12-byte IV || 16-byte GCM auth tag || data.
 */
import {
  createCipheriv,
  createDecipheriv,
  randomBytes,
  timingSafeEqual,
} from "node:crypto";

const ALG = "aes-256-gcm";
const IV_LEN = 12;
const TAG_LEN = 16;

export interface EncryptedEnvelope {
  encryptedDek: Buffer;
  ciphertext: Buffer;
  keyVersion: number;
}

function seal(key: Buffer, plaintext: Buffer): Buffer {
  const iv = randomBytes(IV_LEN);
  const cipher = createCipheriv(ALG, key, iv);
  const data = Buffer.concat([cipher.update(plaintext), cipher.final()]);
  return Buffer.concat([iv, cipher.getAuthTag(), data]);
}

function open(key: Buffer, blob: Buffer): Buffer {
  const iv = blob.subarray(0, IV_LEN);
  const tag = blob.subarray(IV_LEN, IV_LEN + TAG_LEN);
  const data = blob.subarray(IV_LEN + TAG_LEN);
  const decipher = createDecipheriv(ALG, key, iv);
  decipher.setAuthTag(tag);
  return Buffer.concat([decipher.update(data), decipher.final()]);
}

export class Envelope {
  private readonly kek: Buffer;

  constructor(
    masterKeyHex: string,
    readonly keyVersion = 1,
  ) {
    this.kek = Buffer.from(masterKeyHex, "hex");
    if (this.kek.length !== 32) {
      throw new Error("MASTER_ENCRYPTION_KEY must be 32 bytes of hex");
    }
  }

  encrypt(plaintext: string): EncryptedEnvelope {
    const dek = randomBytes(32);
    try {
      return {
        encryptedDek: seal(this.kek, dek),
        ciphertext: seal(dek, Buffer.from(plaintext, "utf8")),
        keyVersion: this.keyVersion,
      };
    } finally {
      dek.fill(0);
    }
  }

  decrypt(env: Pick<EncryptedEnvelope, "encryptedDek" | "ciphertext">): string {
    const dek = open(this.kek, env.encryptedDek);
    try {
      return open(dek, env.ciphertext).toString("utf8");
    } finally {
      dek.fill(0);
    }
  }
}

/** Constant-time string comparison for secrets. */
export function safeEqual(a: string, b: string): boolean {
  const ba = Buffer.from(a);
  const bb = Buffer.from(b);
  return ba.length === bb.length && timingSafeEqual(ba, bb);
}
