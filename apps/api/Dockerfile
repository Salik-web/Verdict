# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Salik Syed
#
# TypeScript API. Built from the REPO ROOT as context, because it depends on the
# @geo/shared workspace package — a build context of apps/api alone cannot see it.
#
#   docker build -f apps/api/Dockerfile .

FROM node:20-slim AS base
ENV PNPM_HOME=/pnpm PATH=/pnpm:$PATH
RUN corepack enable
WORKDIR /repo

# ── deps: cached on the manifests alone, so editing source doesn't re-resolve ──
FROM base AS deps
COPY package.json pnpm-lock.yaml pnpm-workspace.yaml .npmrc ./
COPY apps/api/package.json apps/api/
COPY apps/web/package.json apps/web/
COPY packages/shared/package.json packages/shared/
RUN --mount=type=cache,id=pnpm,target=/pnpm/store \
    pnpm install --frozen-lockfile

# ── build ─────────────────────────────────────────────────────────────────────
FROM deps AS build
COPY packages/shared packages/shared
COPY apps/api apps/api
COPY tsconfig.base.json ./
# @geo/shared must be built first: the API imports its compiled .d.ts.
RUN pnpm --filter @geo/shared build && pnpm --filter @geo/api build

# ── runtime ───────────────────────────────────────────────────────────────────
FROM base AS runtime
ENV NODE_ENV=production
COPY --from=build /repo/node_modules ./node_modules
COPY --from=build /repo/packages/shared ./packages/shared
COPY --from=build /repo/apps/api ./apps/api
# db/ carries the migrations and seed SQL the entrypoint applies.
COPY db ./db

WORKDIR /repo/apps/api
# node:20-slim ships a `node` user; drop root before serving traffic.
USER node
EXPOSE 3000
CMD ["node", "dist/index.js"]
