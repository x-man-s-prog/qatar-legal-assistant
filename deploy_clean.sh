#!/usr/bin/env bash
# ═══════════════════════════════════════════════════════════
# المساعد القانوني — FULL CLEAN REBUILD & REDEPLOY
# ═══════════════════════════════════════════════════════════
# Run this on your production/dev machine where Docker is installed.
# Usage:  chmod +x deploy_clean.sh && ./deploy_clean.sh
# ═══════════════════════════════════════════════════════════
set -euo pipefail

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
NC='\033[0m'

log()  { echo -e "${CYAN}[$(date +%H:%M:%S)]${NC} $1"; }
ok()   { echo -e "${GREEN}  ✅ $1${NC}"; }
warn() { echo -e "${YELLOW}  ⚠️  $1${NC}"; }
err()  { echo -e "${RED}  ❌ $1${NC}"; }

echo ""
echo "═══════════════════════════════════════════════════════════"
echo "  المساعد القانوني — FULL CLEAN REBUILD"
echo "═══════════════════════════════════════════════════════════"
echo ""

# ─── STEP 1: Stop everything ───────────────────────────────
log "STEP 1: Stopping all containers..."

if docker compose ps -q 2>/dev/null | grep -q .; then
    docker compose down --remove-orphans 2>/dev/null || true
    ok "docker compose down completed"
elif docker-compose ps -q 2>/dev/null | grep -q .; then
    docker-compose down --remove-orphans 2>/dev/null || true
    ok "docker-compose down completed"
else
    warn "No compose project running"
fi

# Stop ANY remaining containers matching our names
for name in legal_app legal_db legal_redis legal_ollama legal_nginx; do
    if docker ps -q -f name="$name" 2>/dev/null | grep -q .; then
        docker stop "$name" 2>/dev/null || true
        docker rm -f "$name" 2>/dev/null || true
        ok "Stopped and removed: $name"
    fi
done

# ─── STEP 2: Kill any bare Python/uvicorn processes ────────
log "STEP 2: Checking for bare processes..."

PIDS=$(pgrep -f "uvicorn.*main:app" 2>/dev/null || true)
if [ -n "$PIDS" ]; then
    echo "$PIDS" | xargs kill -9 2>/dev/null || true
    ok "Killed uvicorn processes: $PIDS"
else
    ok "No bare uvicorn processes running"
fi

PIDS2=$(pgrep -f "python.*main.py" 2>/dev/null || true)
if [ -n "$PIDS2" ]; then
    echo "$PIDS2" | xargs kill -9 2>/dev/null || true
    ok "Killed python main.py processes: $PIDS2"
else
    ok "No bare python processes running"
fi

# ─── STEP 3: Remove old images ────────────────────────────
log "STEP 3: Removing old Docker images..."

# Remove the app image specifically
APP_IMAGES=$(docker images -q "*legal*" 2>/dev/null || true)
COMPOSE_IMAGES=$(docker images -q "*الكود*" 2>/dev/null || true)
if [ -n "$APP_IMAGES" ] || [ -n "$COMPOSE_IMAGES" ]; then
    docker rmi -f $APP_IMAGES $COMPOSE_IMAGES 2>/dev/null || true
    ok "Removed legal app images"
fi

# Remove dangling images
docker image prune -f 2>/dev/null || true
ok "Pruned dangling images"

# ─── STEP 4: Clear build cache ────────────────────────────
log "STEP 4: Clearing Docker build cache..."
docker builder prune -a -f 2>/dev/null || true
ok "Build cache cleared"

# ─── STEP 5: Clean volumes (preserve DB data) ─────────────
log "STEP 5: Cleaning unused volumes..."
# NOTE: We do NOT use docker volume prune because it would delete
# pgdata (your legal database). Only remove redis cache.
if docker volume ls -q 2>/dev/null | grep -q "redis_data"; then
    docker volume rm -f $(docker volume ls -q | grep redis_data) 2>/dev/null || true
    ok "Redis cache volume cleared"
fi
warn "PostgreSQL data volume PRESERVED (pgdata)"

# ─── STEP 6: Verify clean state ───────────────────────────
log "STEP 6: Verifying clean state..."

RUNNING=$(docker ps -q 2>/dev/null | wc -l)
if [ "$RUNNING" -eq 0 ]; then
    ok "No containers running — clean state confirmed"
else
    warn "$RUNNING containers still running (may be unrelated)"
    docker ps --format "table {{.Names}}\t{{.Image}}\t{{.Status}}"
fi

# ─── STEP 7: Rebuild from scratch ─────────────────────────
log "STEP 7: Rebuilding all images from scratch (--no-cache)..."
echo ""

if [ -f docker-compose.yml ]; then
    # Try docker compose (v2) first, fall back to docker-compose (v1)
    if docker compose version &>/dev/null; then
        docker compose build --no-cache
    else
        docker-compose build --no-cache
    fi
    ok "All images rebuilt from scratch"
else
    docker build --no-cache -t legal_app .
    ok "App image rebuilt from scratch"
fi

# ─── STEP 8: Start fresh ──────────────────────────────────
log "STEP 8: Starting fresh containers..."
echo ""

if [ -f docker-compose.yml ]; then
    if docker compose version &>/dev/null; then
        docker compose up -d
    else
        docker-compose up -d
    fi
    ok "All services started via compose"
else
    docker run -d --name legal_app -p 8000:8000 legal_app
    ok "App container started"
fi

# ─── STEP 9: Wait for services to be healthy ──────────────
log "STEP 9: Waiting for services to be healthy..."

MAX_WAIT=60
ELAPSED=0
while [ $ELAPSED -lt $MAX_WAIT ]; do
    # Check if app is responding
    if curl -s -o /dev/null -w "%{http_code}" http://localhost:8000/health 2>/dev/null | grep -q "200"; then
        ok "App is healthy (HTTP 200)"
        break
    fi
    # Try /docs as fallback
    if curl -s -o /dev/null -w "%{http_code}" http://localhost:8000/docs 2>/dev/null | grep -q "200"; then
        ok "App is healthy (/docs responding)"
        break
    fi
    sleep 2
    ELAPSED=$((ELAPSED + 2))
    echo -ne "  Waiting... ${ELAPSED}s / ${MAX_WAIT}s\r"
done

if [ $ELAPSED -ge $MAX_WAIT ]; then
    warn "App did not become healthy within ${MAX_WAIT}s — check logs:"
    echo "  docker compose logs app --tail 50"
fi

# ─── STEP 10: Verify latest code is running ───────────────
log "STEP 10: Verifying latest code version..."

# Check if the debug endpoint exists
VERIFY=$(curl -s http://localhost:8000/debug/code-version 2>/dev/null || echo "UNREACHABLE")
if echo "$VERIFY" | grep -q "REFUSAL_ENGINE_ACTIVE"; then
    ok "Latest code confirmed: REFUSAL_ENGINE_ACTIVE"
elif echo "$VERIFY" | grep -q "UNREACHABLE"; then
    warn "Could not reach /debug/code-version — app may still be starting"
    warn "Run: curl http://localhost:8000/debug/code-version"
else
    warn "Unexpected response: $VERIFY"
fi

# ─── STEP 11: Show running state ──────────────────────────
log "STEP 11: Final state..."
echo ""
docker ps --format "table {{.Names}}\t{{.Image}}\t{{.Status}}\t{{.Ports}}" 2>/dev/null || true
echo ""

NEW_ID=$(docker ps -q -f name=legal_app 2>/dev/null | head -1)
if [ -n "$NEW_ID" ]; then
    ok "New container ID: $NEW_ID"
else
    warn "legal_app container not found — check docker compose logs"
fi

echo ""
echo "═══════════════════════════════════════════════════════════"
echo "  REBUILD COMPLETE"
echo ""
echo "  Next steps:"
echo "    1. Test:  curl -X POST http://localhost:8000/ask -H 'Content-Type: application/json' -d '{\"query\": \"كم راتب الدرجة السابعة\"}'"
echo "    2. Logs:  docker compose logs -f app"
echo "    3. If issues: docker compose logs app --tail 100"
echo "═══════════════════════════════════════════════════════════"
