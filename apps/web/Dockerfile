# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Salik Syed
#
# Next.js UI. Built from the REPO ROOT as context (workspace install).
#
#   docker build -f apps/web/Dockerfile .

FROM node:20-slim AS base
ENV PNPM_HOME=/pnpm PATH=/pnpm:$PATH
RUN corepack enable
WORKDIR /repo

FROM base AS deps
COPY package.json pnpm-lock.yaml pnpm-workspace.yaml .npmrc ./
COPY apps/api/package.json apps/api/
COPY apps/web/package.json apps/web/
COPY packages/shared/package.json packages/shared/
RUN --mount=type=cache,id=pnpm,target=/pnpm/store \
    pnpm install --frozen-lockfile

FROM deps AS build
COPY apps/web apps/web
COPY packages/shared packages/shared
COPY tsconfig.base.json ./
# The browser talks to the API directly, so this is baked in at build time.
ARG NEXT_PUBLIC_API_BASE_URL=http://localhost:3000
ENV NEXT_PUBLIC_API_BASE_URL=$NEXT_PUBLIC_API_BASE_URL
RUN pnpm --filter @geo/web build

FROM base AS runtime
ENV NODE_ENV=production
COPY --from=build /repo/node_modules ./node_modules
COPY --from=build /repo/apps/web ./apps/web
WORKDIR /repo/apps/web
USER node
EXPOSE 5173
# Invoke next DIRECTLY rather than through `pnpm start`. At runtime the repo-root
# package.json is not present, so corepack cannot see `packageManager` and
# fetches the newest pnpm — which requires node:sqlite and dies on Node 20. A
# server has no reason to run a package manager anyway.
CMD ["node_modules/.bin/next", "start", "-p", "5173"]
