# Production image. deploy/docker/frontend.Dockerfile (dev) runs Vite's own
# dev server against a live-mounted source tree; this file builds the static
# bundle once and serves it from nginx.

# ---------------------------------------------------------------------------
# Stage 1: build -- identical to frontend.Dockerfile's dependency install,
# including its own arch-detected Rollup native-binary fix (npm/cli#4828),
# which stays exactly as-is: that bug and its fix are unrelated to dev vs.
# prod and already correct.
# ---------------------------------------------------------------------------
FROM node:20-alpine AS build

WORKDIR /workspace

COPY frontend/package*.json ./

RUN npm ci \
    && ROLLUP_VERSION="$(node -p "require('rollup/package.json').version")" \
    && ROLLUP_ARCH="$(node -p "process.arch")" \
    && npm install --no-save --package-lock=false \
        "@rollup/rollup-linux-${ROLLUP_ARCH}-musl@${ROLLUP_VERSION}"

COPY frontend/ ./

# No VITE_API_BASE_URL build ARG here, unlike a typical SPA -- there is
# nothing to bake in. frontend/src/services/apiClient.ts calls fetch() with
# relative "/api/v1/..." paths exclusively (verified: no VITE_API_* env var
# is read anywhere under frontend/src), so the SPA always talks to whatever
# origin served it, and deploy/docker/nginx.conf's `location /api` proxy is
# what makes that resolve to the backend. The only VITE_* the app reads at
# runtime, VITE_DEV_AUTH_BYPASS (frontend/src/providers/AuthProvider.tsx),
# is additionally gated on import.meta.env.DEV, so `vite build`'s production
# mode compiles that branch out regardless of what's set at build time.
RUN npm run build

# ---------------------------------------------------------------------------
# Stage 2: serve -- nginx-unprivileged rather than plain nginx:1.27-alpine:
# it already listens on 8080 (a port a non-root process can bind) and runs
# as a non-root uid by default, so no imperative chown/adduser dance is
# needed here to get the same non-root guarantee backend.prod.Dockerfile
# gives the backend.
# ---------------------------------------------------------------------------
FROM nginxinc/nginx-unprivileged:1.27-alpine AS serve

COPY --from=build /workspace/dist /usr/share/nginx/html
COPY deploy/docker/nginx.conf /etc/nginx/conf.d/default.conf

EXPOSE 8080

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD wget -q -O- http://127.0.0.1:8080/healthz || exit 1
