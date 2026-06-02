#!/bin/bash
# GeminiRAG startup sequence for Hugging Face Spaces.
# Boots Redis and ChromaDB first, waits for them, then runs migrations
# and hands off to supervisord for the API and Celery worker.

set -e

echo "=== GeminiRAG starting ==="

# ── 1. Redis ─────────────────────────────────────────────────────────
echo "[1/5] Starting Redis..."
redis-server \
    --daemonize yes \
    --maxmemory 256mb \
    --maxmemory-policy allkeys-lru \
    --save "" \
    --logfile /var/log/redis.log

# Wait for Redis to accept connections
for i in $(seq 1 20); do
    redis-cli ping >/dev/null 2>&1 && break
    echo "      waiting for Redis... ($i)"
    sleep 1
done
echo "      Redis ready"

# ── 2. ChromaDB ──────────────────────────────────────────────────────
echo "[2/5] Starting ChromaDB..."
chroma run \
    --host 127.0.0.1 \
    --port 8001 \
    --path /data/chroma \
    > /var/log/chroma.log 2>&1 &

# Wait for ChromaDB heartbeat
for i in $(seq 1 30); do
    curl -sf http://127.0.0.1:8001/api/v2/heartbeat >/dev/null 2>&1 && break
    echo "      waiting for ChromaDB... ($i)"
    sleep 2
done
echo "      ChromaDB ready"

# ── 3. Database migrations ────────────────────────────────────────────
echo "[3/5] Running database migrations..."
cd /app
alembic upgrade head
echo "      Migrations done"

# ── 4. Seed admin (only on first boot) ───────────────────────────────
# Set ADMIN_EMAIL and ADMIN_PASSWORD as HF Space Secrets to auto-seed.
if [ -n "$ADMIN_EMAIL" ] && [ -n "$ADMIN_PASSWORD" ]; then
    echo "[4/5] Seeding admin user: $ADMIN_EMAIL"
    python scripts/seed_admin.py --email "$ADMIN_EMAIL" --password "$ADMIN_PASSWORD" || true
else
    echo "[4/5] Skipping admin seed (ADMIN_EMAIL/ADMIN_PASSWORD not set)"
fi

# ── 5. Start API + worker via supervisord ─────────────────────────────
echo "[5/5] Starting API and Celery worker..."
mkdir -p /var/log/supervisor
exec supervisord -c /etc/supervisor/conf.d/geminirag.conf
