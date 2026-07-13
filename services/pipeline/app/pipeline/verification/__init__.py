"""Verification stage: prove what a shipped asset actually moved.

Re-runs the asset's exact target prompts through the Monitor stage, compares
self-visibility before vs after those same queries, and writes an honest verdict
(`improved` / `no_change` / `regressed` / `inconclusive`) with a confidence that
reflects sample size and effect magnitude. Results feed back into the planner's
confidence weighting so the loop learns.
"""
