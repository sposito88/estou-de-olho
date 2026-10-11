# syntax=docker/dockerfile:1

# ---------------------------------------------------------------- front (React)
FROM node:22-alpine AS web-build
WORKDIR /web
COPY web/package.json web/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY web/ ./
# Sem VITE_API_URL o site chama a API na mesma origem (o Caddy faz o proxy).
ARG VITE_API_URL=
ENV VITE_API_URL=${VITE_API_URL}
RUN npm run build

FROM caddy:2-alpine AS web
COPY deploy/Caddyfile /etc/caddy/Caddyfile
COPY --from=web-build /web/dist /srv

# ---------------------------------------------------------------- API + coletor (Python)
FROM python:3.12-slim AS api
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1
WORKDIR /app
COPY requirements.txt .
RUN pip install -r requirements.txt
COPY civic/ civic/
RUN mkdir -p data && chmod 777 data
EXPOSE 8000
CMD ["uvicorn", "civic.api:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers", "--forwarded-allow-ips", "*"]
