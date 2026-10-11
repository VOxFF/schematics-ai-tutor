# Production image for Fly.io (fly.toml): one process serves the API, the WebSocket and the built frontend.

# Frontend build. vite.config.js reads the root config.yaml; SCHEMATICS_PUBLIC=true hides debug features.
FROM node:22-slim AS frontend
WORKDIR /app/frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --silent
COPY config.yaml /app/config.yaml
COPY frontend/ ./
RUN SCHEMATICS_PUBLIC=true npm run build

# Backend. Installed in place, so REPO_ROOT (backend/app/config.py) is /app and finds config.yaml and frontend/dist.
FROM python:3.12-slim
ENV PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 PIP_DISABLE_PIP_VERSION_CHECK=1
WORKDIR /app
COPY backend/pyproject.toml backend/
COPY backend/app backend/app
COPY backend/data backend/data
RUN pip install -e backend
COPY config.yaml ./
COPY --from=frontend /app/frontend/dist frontend/dist
WORKDIR /app/backend
EXPOSE 8080
# One worker: rate limits, the task cache and reference solutions are in memory (docs/design.md §4).
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8080", "--proxy-headers", "--forwarded-allow-ips", "*"]
