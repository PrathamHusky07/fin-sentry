#!/usr/bin/env bash
# Local development setup for fin-sentry.
# Idempotent: safe to run multiple times.

# Resolve project root from the script's own location, so the script works
# regardless of the operator's current working directory.
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$PROJECT_ROOT"

set -euo pipefail

echo "[1/6] Checking docker-compose stack is up..."
if ! docker compose -f docker-compose.dev.yml ps --format json | grep -q '"State":"running"'; then
    echo "  Starting compose stack..."
    docker compose -f docker-compose.dev.yml up -d
    sleep 30
fi

echo "[2/6] Waiting for services to be healthy..."
for i in {1..12}; do
    status=$(docker compose -f docker-compose.dev.yml ps --format json)
    if echo "$status" | grep -qE '"Health":"unhealthy"|"Health":"starting"'; then
        sleep 5
    else
        break
    fi
done

echo "[3/6] Verifying Redpanda dual-listener configuration..."
brokers=$(docker exec finsentry-redpanda rpk cluster info --brokers localhost:9092 2>&1)
if echo "$brokers" | grep -q "127.0.0.1"; then
    echo "  ERROR: Redpanda is advertising 127.0.0.1 -- dual-listener config missing."
    echo "  Check docker-compose.dev.yml redpanda command args."
    exit 1
fi
echo "  OK: Redpanda advertising internal listener correctly."

echo "[4/6] Initializing RisingWave sources and materialized views..."
PYTHONPATH="$PROJECT_ROOT" python scripts/init_risingwave.py

echo "[5/6] Verifying Ollama is running..."
if ! curl -sf http://localhost:11434/api/tags > /dev/null 2>&1; then
    echo "  WARN: Ollama not reachable at http://localhost:11434."
    echo "  Install: brew install ollama"
    echo "  Start:   brew services start ollama"
    echo "  Pull:    ollama pull llama3.1:8b"
    echo "  The gateway will start but RAG calls will fail until Ollama is running."
else
    echo "  OK: Ollama is running."
    if ! curl -sf http://localhost:11434/api/tags | grep -q "llama3.1:8b"; then
        echo "  WARN: llama3.1:8b not pulled. Run: ollama pull llama3.1:8b"
    fi
fi

echo "[6/6] Setup complete."
echo ""
echo "Next steps in three terminals:"
echo "  Terminal 1:  uvicorn finsentry.gateway.main:app --port 8000"
echo "  Terminal 2:  python -m finsentry.consumer.main"
echo "  Terminal 3:  uvicorn finsentry.dashboard.app:app --port 8081"
echo ""
echo "Then run the smoke test:"
echo "  python scripts/smoke_test_e2e.py"
