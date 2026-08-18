// SPDX-License-Identifier: AGPL-3.0-or-later
// Copyright (C) 2026 Salik Syed
/**
 * Domain validation at the API boundary (B1).
 *
 * The bug: `z.string().max(255)` accepted "", " ", and full URLs. None of those
 * fail until Diagnosis builds `https://{domain}` — an empty string is falsy, so
 * the stage SILENTLY SKIPS and the user sees a scan that diagnosed nothing with
 * no explanation. Whitespace is truthy, so it fetches `https:// ` instead.
 *
 * The script guard (scripts/create-real-account.mjs) checked this already; a
 * client that talks to the API directly bypassed it entirely.
 */
import assert from "node:assert/strict";
import { test } from "node:test";
import { domainSchema } from "../validate.js";

const accepts = (input: string, expected: string) => {
  const result = domainSchema.safeParse(input);
  assert.equal(
    result.success,
    true,
    `expected ${JSON.stringify(input)} to be accepted`,
  );
  if (result.success) assert.equal(result.data, expected);
};

const rejects = (input: string) => {
  assert.equal(
    domainSchema.safeParse(input).success,
    false,
    `expected ${JSON.stringify(input)} to be rejected`,
  );
};

test("accepts a plain hostname", () => {
  accepts("example.com", "example.com");
  accepts("imagine.art", "imagine.art");
  accepts("sub.domain.example.co.uk", "sub.domain.example.co.uk");
});

test("normalizes what people actually paste out of a browser", () => {
  accepts("https://www.imagine.art/pricing", "www.imagine.art");
  accepts("http://example.com", "example.com");
  accepts("  Example.COM  ", "example.com");
  accepts("example.com:8443", "example.com");
  accepts("example.com.", "example.com");
  accepts("https://user:pw@example.com/x?y=1#z", "example.com");
});

test("rejects the empty and whitespace values that caused the silent skip", () => {
  rejects("");
  rejects("   ");
  rejects("https://");
});

test("rejects things that are not hostnames", () => {
  rejects("not a domain");
  rejects("example");           // no TLD
  rejects("-example.com");      // leading hyphen
  rejects("example-.com");      // trailing hyphen
  rejects("exa mple.com");
  rejects(`${"a".repeat(64)}.com`); // label over 63 chars
  rejects(`${"a".repeat(250)}.com`); // over 253 total
});

test("rejects bare IP addresses", () => {
  // An account's brand domain is a domain. SSRF safety is enforced separately
  // at fetch time; this is a data-quality rule.
  rejects("8.8.8.8");
  rejects("127.0.0.1");
  rejects("http://192.168.1.1");
});
