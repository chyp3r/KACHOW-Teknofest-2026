FROM node:20-alpine

WORKDIR /workspace

# Copy dependencies manifest
COPY frontend/package*.json ./

# Install dependencies
RUN npm install

# Copy application files
COPY frontend/ ./

# Expose Vite dev server port
EXPOSE 5173

# Start development server with host flag for external access
CMD ["npm", "run", "dev", "--", "--host"]
