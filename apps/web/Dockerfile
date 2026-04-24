FROM node:22-bookworm-slim AS base
WORKDIR /app

# Install dependencies
FROM base AS deps
COPY package.json package-lock.json* ./
RUN npm ci

# Build
FROM base AS build
COPY --from=deps /app/node_modules ./node_modules
COPY . .
ARG NEXT_PUBLIC_EGP_API_BASE_URL=http://127.0.0.1:8010
ARG NEXT_PUBLIC_SITE_URL=http://127.0.0.1:3002
ENV NEXT_TELEMETRY_DISABLED=1
ENV NEXT_PUBLIC_EGP_API_BASE_URL=${NEXT_PUBLIC_EGP_API_BASE_URL}
ENV NEXT_PUBLIC_SITE_URL=${NEXT_PUBLIC_SITE_URL}
RUN npm run build

# Runtime
FROM base AS runtime
ENV NODE_ENV=production
ENV NEXT_TELEMETRY_DISABLED=1
ENV NEXT_PUBLIC_EGP_API_BASE_URL=http://127.0.0.1:8010
ENV NEXT_PUBLIC_SITE_URL=http://127.0.0.1:3002

RUN addgroup --system --gid 1001 nodejs && \
    adduser --system --uid 1001 nextjs

COPY --from=build /app/public ./public
COPY --from=build --chown=nextjs:nodejs /app/.next/standalone ./
COPY --from=build --chown=nextjs:nodejs /app/.next/static ./.next/static

USER nextjs
EXPOSE 3000
ENV PORT=3000
ENV HOSTNAME="0.0.0.0"

CMD ["node", "server.js"]
