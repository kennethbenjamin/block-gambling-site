#!/usr/bin/env bash
set -e

# ==============================================================================
# AI Gambling Filter & Parental Unlock Gateway - Automated Deployment Script
# Engine: Podman Pod (Rootless Virtual Containers + ONNX Runtime / Ollama)
# ==============================================================================

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

POD_NAME="filter-pod"
GATEWAY_CONTAINER="filter-gateway"
OLLAMA_CONTAINER="local-ai"
IMAGE_NAME="localhost/filter-gateway:latest"
ENV_FILE="$SCRIPT_DIR/.env"

echo "============================================================"
echo " Starting AI Gambling Filter Gateway Deployment (Podman)    "
echo "============================================================"

# 1. Check Podman
if ! command -v podman &> /dev/null; then
    echo "[-] Error: Podman is not installed. Please install Podman first."
    exit 1
fi
echo "[+] Podman is available: $(podman --version)"

# 2. Check / Setup .env file
if [ ! -f "$ENV_FILE" ]; then
    if [ -f "$SCRIPT_DIR/.env.example" ]; then
        echo "[*] Creating .env from .env.example template..."
        cp "$SCRIPT_DIR/.env.example" "$ENV_FILE"
    else
        echo "[-] Error: .env file missing."
        exit 1
    fi
fi
echo "[+] Configuration loaded from $ENV_FILE"

# Detect Host IP
HOST_IP=$(ipconfig getifaddr en0 2>/dev/null || ipconfig getifaddr en1 2>/dev/null || echo "127.0.0.1")
echo "[+] Host Local Gateway IP: $HOST_IP"

# 3. Build Filter Gateway Image
echo "[*] Building container image: $IMAGE_NAME..."
podman build -t filter-gateway:latest -f server/Containerfile server/

# 4. Clean up existing Pod & Containers
echo "[*] Stopping previous pod and containers..."
podman rm -f "$GATEWAY_CONTAINER" "$OLLAMA_CONTAINER" 2>/dev/null || true
podman pod rm -f "$POD_NAME" 2>/dev/null || true

# Read AI Engine choice
AI_ENGINE_VAL=$(grep -E "^AI_ENGINE=" "$ENV_FILE" | cut -d '=' -f2 | tr -d ' "' || echo "onnx")
if [ -z "$AI_ENGINE_VAL" ]; then AI_ENGINE_VAL="onnx"; fi

# 5. Create Podman Pod with mapped ports
echo "[*] Creating Podman Pod: $POD_NAME (Engine: $AI_ENGINE_VAL)..."
if [[ "$AI_ENGINE_VAL" == "ollama"* || "$AI_ENGINE_VAL" == "hybrid"* ]]; then
    podman pod create \
        --name "$POD_NAME" \
        -p 8080:8080 \
        -p 1053:53/udp \
        -p 11434:11434

    echo "[*] Starting Ollama container ($OLLAMA_CONTAINER)..."
    podman run -d \
        --pod "$POD_NAME" \
        --name "$OLLAMA_CONTAINER" \
        -v ollama_models:/root/.ollama:Z \
        --restart unless-stopped \
        docker.io/ollama/ollama:latest

    echo "[*] Verifying Ollama model (llama3.2:1b)..."
    sleep 2
    if ! podman exec "$OLLAMA_CONTAINER" ollama list | grep -q "llama3.2:1b"; then
        echo "[*] Pulling llama3.2:1b into Ollama container..."
        podman exec "$OLLAMA_CONTAINER" ollama pull llama3.2:1b
    fi
else
    podman pod create \
        --name "$POD_NAME" \
        -p 8080:8080 \
        -p 1053:53/udp
fi

# 6. Start Filter Gateway inside Pod
echo "[*] Starting Gateway container ($GATEWAY_CONTAINER)..."
podman run -d \
    --pod "$POD_NAME" \
    --name "$GATEWAY_CONTAINER" \
    --env-file "$ENV_FILE" \
    --restart unless-stopped \
    "$IMAGE_NAME"

# 9. Health Check
echo "[*] Waiting for container initialization..."
sleep 2

HEALTH_CHECK=$(curl -s http://localhost:8080/health || echo "failed")
if [[ "$HEALTH_CHECK" == *"online"* ]]; then
    echo "[+] System and AI filter are healthy and online!"
else
    echo "[-] Warning: Health check returned: $HEALTH_CHECK"
fi

echo "============================================================"
echo " Deployment Complete!                                       "
echo "============================================================"
echo " - Web Block & Unlock Portal : http://$HOST_IP:8080/blocked"
echo " - DNS Interception Port     : $HOST_IP:1053 (UDP)"
echo " - Local AI Model Engine     : $AI_ENGINE_VAL (Embedded ONNX <2ms inference)"
echo " - Status & Logs             : podman logs -f $GATEWAY_CONTAINER"
echo " - Test Suite                : ./scripts/test_filter.sh"
echo "============================================================"
