FROM oven/bun:1.1-slim
WORKDIR /app
COPY package.json bun.lock* ./
RUN bun install --frozen-lockfile || bun install
COPY src ./src
ENV PORT=8080
EXPOSE 8080
CMD ["bun", "src/index.ts"]
