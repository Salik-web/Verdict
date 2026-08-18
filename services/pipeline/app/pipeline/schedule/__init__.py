# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Salik Syed
"""Scheduling: decide WHEN each account's next scan runs, with per-account jitter
so a cohort never fires at once, and a config-driven plan-quota check that gates
any expensive job. The Python beat (or the TS side over internal HTTP) drives it.
"""
