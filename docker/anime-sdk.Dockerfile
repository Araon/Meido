FROM node:22-bookworm-slim

ENV NODE_ENV=production \
    PORT=8080

RUN apt-get update \
    && apt-get install --no-install-recommends -y ca-certificates ffmpeg \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY sidecars/anime-sdk/package.json sidecars/anime-sdk/package-lock.json ./
RUN npm ci --omit=dev \
    && npm cache clean --force \
    && npm audit --omit=dev

COPY sidecars/anime-sdk/server.js ./

USER node
CMD ["node", "server.js"]
