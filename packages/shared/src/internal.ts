// SPDX-License-Identifier: AGPL-3.0-or-later
// Copyright (C) 2026 Salik Syed
/**
 * Internal service-to-service HTTP contract.
 *
 * The TS API authenticates to the Python pipeline's internal endpoints by
 * sending a shared secret in this header. The Python service rejects any
 * internal request missing or mismatching it.
 */

/** Header carrying the INTERNAL_SHARED_SECRET on internal calls. */
export const INTERNAL_SECRET_HEADER = "x-internal-secret" as const;
