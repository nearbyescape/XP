# syntax=docker/dockerfile:1
# Build context: repository root (docker compose sets it)

FROM node:22-alpine AS build
WORKDIR /web
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY frontend/ ./
RUN npm run build

FROM nginx:1.28-alpine
ENV SEARCH_INDEXING=false \
    API_UPSTREAM=api:8000
RUN rm -f /etc/nginx/conf.d/default.conf
COPY frontend/nginx/default.conf.template /etc/nginx/templates/default.conf.template
COPY --from=build /web/dist /usr/share/nginx/html
EXPOSE 8080
HEALTHCHECK --interval=30s --timeout=5s --retries=3 CMD wget -qO- http://127.0.0.1:8080/robots.txt >/dev/null || exit 1
