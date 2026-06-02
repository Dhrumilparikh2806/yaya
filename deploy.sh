#!/bin/bash
# =============================================================================
# GeminiRAG — Oracle Cloud ARM server bootstrap script
#
# Run this ONCE on a fresh Ubuntu 22.04 ARM VM:
#   chmod +x deploy.sh && sudo ./deploy.sh
#
# What it does:
#   1. Installs Docker + Docker Compose plugin
#   2. Clones the repo
#   3. Guides you through creating .env
#   4. Runs database migrations
#   5. Builds and starts all services
#   6. Prints the public URL
# =============================================================================

set -e
REPO_URL="https://github.com/Dhrumilparikh2806/yaya.git"
APP_DIR="/opt/geminirag"
COMPOSE_FILE="docker-compose.prod.yml"

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; NC='\033[0m'
info()    { echo -e "${GREEN}[INFO]${NC}  $1"; }
warn()    { echo -e "${YELLOW}[WARN]${NC}  $1"; }
section() { echo -e "\n${GREEN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"; echo -e "${GREEN} $1${NC}"; echo -e "${GREEN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"; }

# ── 1. System update ──────────────────────────────────────────────────────────
section "1/6  System update"
apt-get update -qq && apt-get upgrade -y -qq
info "System updated"

# ── 2. Docker ─────────────────────────────────────────────────────────────────
section "2/6  Installing Docker"
if command -v docker &>/dev/null; then
    info "Docker already installed — $(docker --version)"
else
    apt-get install -y -qq ca-certificates curl gnupg lsb-release
    install -m 0755 -d /etc/apt/keyrings
    curl -fsSL https://download.docker.com/linux/ubuntu/gpg \
        | gpg --dearmor -o /etc/apt/keyrings/docker.gpg
    chmod a+r /etc/apt/keyrings/docker.gpg
    echo \
        "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] \
        https://download.docker.com/linux/ubuntu \
        $(lsb_release -cs) stable" \
        | tee /etc/apt/sources.list.d/docker.list > /dev/null
    apt-get update -qq
    apt-get install -y -qq docker-ce docker-ce-cli containerd.io \
        docker-buildx-plugin docker-compose-plugin
    systemctl enable --now docker
    info "Docker installed — $(docker --version)"
fi

# Add ubuntu user to docker group so sudo isn't needed later
usermod -aG docker ubuntu 2>/dev/null || true

# ── 3. Clone repo ─────────────────────────────────────────────────────────────
section "3/6  Cloning repository"
if [ -d "$APP_DIR/.git" ]; then
    info "Repo already cloned — pulling latest"
    git -C "$APP_DIR" pull
else
    git clone "$REPO_URL" "$APP_DIR"
    info "Cloned to $APP_DIR"
fi
cd "$APP_DIR"

# ── 4. Create .env ────────────────────────────────────────────────────────────
section "4/6  Environment configuration"
if [ -f .env ]; then
    warn ".env already exists — skipping creation. Edit $APP_DIR/.env to change values."
else
    PUBLIC_IP=$(curl -s ifconfig.me || curl -s api.ipify.org)
    info "Detected public IP: $PUBLIC_IP"

    echo ""
    echo "  You need 3 things:"
    echo "  • A Groq API key   → https://console.groq.com"
    echo "  • A random 48-char SECRET_KEY (generate: openssl rand -hex 24)"
    echo "  • Your Vercel frontend URL (fill in AFTER deploying frontend)"
    echo ""

    read -rp "  GROQ_API_KEY: " GROQ_KEY
    SECRET=$(openssl rand -hex 24)
    info "Generated SECRET_KEY automatically"

    read -rp "  GEMINI_API_KEY (optional, press Enter to skip): " GEMINI_KEY
    GEMINI_KEY=${GEMINI_KEY:-""}

    read -rp "  ALLOWED_ORIGINS (your Vercel URL, e.g. https://myapp.vercel.app): " ORIGINS
    ORIGINS=${ORIGINS:-"http://$PUBLIC_IP:8000"}

    cat > .env << EOF
# ── Required ──────────────────────────────────────────────────────────────────
GROQ_API_KEY=${GROQ_KEY}
SECRET_KEY=${SECRET}
DATABASE_URL=postgresql://geminirag:geminirag@postgres:5432/geminirag
REDIS_URL=redis://redis:6379/0

# ── Optional ──────────────────────────────────────────────────────────────────
GEMINI_API_KEY=${GEMINI_KEY}

# ── Infrastructure ────────────────────────────────────────────────────────────
CHROMA_HOST=chromadb
CHROMA_PORT=8001
CHROMA_COLLECTION=geminirag_chunks
UPLOAD_DIR=/tmp/geminirag_uploads
ALLOWED_ORIGINS=${ORIGINS}

# ── Models ────────────────────────────────────────────────────────────────────
GROQ_MODEL=llama-3.3-70b-versatile
GROQ_PROCESSING_MODEL=llama-3.1-8b-instant
GROQ_VISION_MODEL=meta-llama/llama-4-scout-17b-16e-instruct
WHISPER_MODEL=whisper-large-v3
EMBEDDING_MODEL=BAAI/bge-small-en-v1.5
GEMINI_MODEL=gemini-2.0-flash

# ── RAG ───────────────────────────────────────────────────────────────────────
CHUNK_SIZE=600
CHILD_CHUNK_SIZE=150
CHUNK_OVERLAP=50
RAG_TOP_K=6
CONFIDENCE_THRESHOLD=0.35

# ── Celery ────────────────────────────────────────────────────────────────────
CELERY_MAX_RETRIES=3
CELERY_RETRY_BACKOFF=60

# ── Postgres (used by docker-compose) ─────────────────────────────────────────
POSTGRES_USER=geminirag
POSTGRES_PASSWORD=geminirag
POSTGRES_DB=geminirag
EOF
    info ".env created"
fi

# ── 5. Build + start ──────────────────────────────────────────────────────────
section "5/6  Building and starting services"
docker compose -f $COMPOSE_FILE pull postgres redis chromadb
docker compose -f $COMPOSE_FILE build --no-cache api worker
docker compose -f $COMPOSE_FILE up -d postgres redis chromadb
info "Waiting 15s for Postgres to be ready..."
sleep 15

# Run migrations
info "Running database migrations..."
docker compose -f $COMPOSE_FILE run --rm api alembic upgrade head

# Start everything
docker compose -f $COMPOSE_FILE up -d
info "All services started"

# ── 6. Seed admin ─────────────────────────────────────────────────────────────
section "6/6  Seeding admin user"
echo ""
read -rp "  Admin email: " ADMIN_EMAIL
read -rsp "  Admin password: " ADMIN_PASS
echo ""
docker compose -f $COMPOSE_FILE run --rm api \
    python scripts/seed_admin.py --email "$ADMIN_EMAIL" --password "$ADMIN_PASS"

# ── Done ──────────────────────────────────────────────────────────────────────
PUBLIC_IP=$(curl -s ifconfig.me || curl -s api.ipify.org)
section "Deployment complete"
echo ""
echo -e "  ${GREEN}API:${NC}    http://$PUBLIC_IP:8000"
echo -e "  ${GREEN}Health:${NC} http://$PUBLIC_IP:8000/health"
echo -e "  ${GREEN}Docs:${NC}   http://$PUBLIC_IP:8000/docs"
echo ""
echo "  Next step: deploy the frontend to Vercel"
echo "  Set VITE_API_URL=http://$PUBLIC_IP:8000 in Vercel env vars"
echo ""
echo "  Useful commands:"
echo "    docker compose -f $COMPOSE_FILE logs -f api"
echo "    docker compose -f $COMPOSE_FILE ps"
echo "    docker compose -f $COMPOSE_FILE restart api worker"
echo ""
