FROM node:20-alpine

WORKDIR /workspace

# Copy dependencies manifest
COPY frontend/package*.json ./

# Install the locked dependency tree first. npm can omit Rollup's platform
# package from cross-platform lockfiles (npm/cli#4828), so install the native
# Alpine binary explicitly at the exact Rollup version selected above. The
# image is always Linux/musl (Alpine) regardless of the host OS -- Mac or
# Windows, Docker Desktop builds a Linux container either way -- but the
# host's CPU architecture carries through to the container (Apple Silicon
# Macs and ARM Windows build arm64 images; Intel/AMD builds x64), so the
# arch has to be detected at build time rather than hardcoded.
RUN npm ci \
    && ROLLUP_VERSION="$(node -p "require('rollup/package.json').version")" \
    && ROLLUP_ARCH="$(node -p "process.arch")" \
    && npm install --no-save --package-lock=false \
        "@rollup/rollup-linux-${ROLLUP_ARCH}-musl@${ROLLUP_VERSION}"

# Copy application files
COPY frontend/ ./

# Expose Vite dev server port
EXPOSE 5173

# Start development server with host flag for external access
CMD ["npm", "run", "dev", "--", "--host"]
