FROM node:20-alpine

WORKDIR /workspace

# Copy dependencies manifest
COPY frontend/package*.json ./

# Install the locked dependency tree first. npm can omit Rollup's platform
# package from cross-platform lockfiles (npm/cli#4828), so install the native
# Alpine x64 binary explicitly at the exact Rollup version selected above.
RUN npm ci \
    && ROLLUP_VERSION="$(node -p "require('rollup/package.json').version")" \
    && npm install --no-save --package-lock=false \
        "@rollup/rollup-linux-x64-musl@${ROLLUP_VERSION}"

# Copy application files
COPY frontend/ ./

# Expose Vite dev server port
EXPOSE 5173

# Start development server with host flag for external access
CMD ["npm", "run", "dev", "--", "--host"]
