FROM node:20-slim AS base
ENV PNPM_HOME="/pnpm"
ENV PATH="$PNPM_HOME:$PATH"
RUN corepack enable

WORKDIR /app

# Copy workspace config
COPY package.json pnpm-workspace.yaml pnpm-lock.yaml ./
COPY packages ./packages
COPY apps/web/package.json ./apps/web/package.json

# Install dependencies
RUN pnpm install --frozen-lockfile

# Copy source and build
COPY apps/web ./apps/web
RUN pnpm --filter ./apps/web build

EXPOSE 3000

CMD ["pnpm", "--filter", "./apps/web", "start"]
