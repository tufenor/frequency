# syntax=docker/dockerfile:1
FROM node:24-bookworm-slim AS frontend-build
WORKDIR /build/frontend
COPY frontend/package*.json ./
RUN npm ci --ignore-scripts
COPY frontend/public ./public
COPY frontend/src ./src
COPY frontend/tsconfig.json ./tsconfig.json
COPY frontend/scripts ./scripts
RUN npm run build

FROM python:3.14-slim
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    FREQUENCY_FRONTEND_DIR=/app/frontend/dist
RUN apt-get update \
    && apt-get install --no-install-recommends -y age ca-certificates curl gnupg \
    && install -d /usr/share/keyrings \
    && curl -fsSL https://www.postgresql.org/media/keys/ACCC4CF8.asc | gpg --dearmor -o /usr/share/keyrings/postgresql.gpg \
    && echo "deb [signed-by=/usr/share/keyrings/postgresql.gpg] https://apt.postgresql.org/pub/repos/apt trixie-pgdg main" > /etc/apt/sources.list.d/pgdg.list \
    && apt-get update \
    && apt-get install --no-install-recommends -y postgresql-client-18 \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd --system frequency \
    && useradd --system --gid frequency --home-dir /app --create-home frequency \
    && mkdir -p /backups
WORKDIR /app
COPY backend/requirements.txt /tmp/requirements.txt
RUN pip install --requirement /tmp/requirements.txt
COPY backend /app/backend
COPY --from=frontend-build /build/frontend/dist /app/frontend/dist
RUN chown -R frequency:frequency /app /backups
WORKDIR /app/backend
USER frequency
EXPOSE 8000
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]