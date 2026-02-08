FROM node:22-alpine

WORKDIR /app

# Enable pnpm via corepack
RUN corepack enable

# Copy package files
COPY package.json pnpm-lock.yaml ./

# Install dependencies
RUN pnpm install --frozen-lockfile

# Copy source files
COPY . .

# Build the application
RUN pnpm build

# Expose port
EXPOSE 3000

# Run the server
CMD ["node", ".output/server/index.mjs"]
