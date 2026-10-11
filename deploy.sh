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
PROXY_CONTAINER="filter-proxy"
OLLAMA_CONTAINER="local-ai"
IMAGE_NAME="localhost/filter-gateway:latest"
PROXY_IMAGE="localhost/filter-proxy:latest"
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

# Detect LAN IP for DNS publish (systemd-resolved owns 127.0.0.53, so bind
# loopback + LAN explicitly instead of 0.0.0.0:53)
LAN_IP=$(hostname -I 2>/dev/null | awk '{print $1}')
if [ -z "$LAN_IP" ]; then LAN_IP="$HOST_IP"; fi
echo "[+] Publishing DNS on 127.0.0.1:53 and $LAN_IP:53"

# 3. Build Filter Gateway Image
echo "[*] Building container image: $IMAGE_NAME..."
podman build -t filter-gateway:latest -f server/Containerfile server/

echo "[*] Building proxy image: $PROXY_IMAGE..."
podman build -t filter-proxy:latest -f proxy/Containerfile proxy/

# 4. Clean up existing Pod & Containers
echo "[*] Stopping previous pod and containers..."
podman rm -f "$GATEWAY_CONTAINER" "$PROXY_CONTAINER" "$OLLAMA_CONTAINER" 2>/dev/null || true
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
        -p 3128:3128 \
        -p 127.0.0.1:53:53/udp \
        -p "$LAN_IP":53:53/udp \
        -p 11434:11434

    echo "[*] Starting Ollama container ($OLLAMA_CONTAINER)..."
    podman run -d \
        --pod "$POD_NAME" \
        --name "$OLLAMA_CONTAINER" \
        -v /media/daddy/data/application/ollama_data:/root/.ollama:Z \
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
        -p 3128:3128 \
        -p 127.0.0.1:53:53/udp \
        -p "$LAN_IP":53:53/udp
fi

# 6. Start Filter Gateway inside Pod
echo "[*] Starting Gateway container ($GATEWAY_CONTAINER)..."
podman run -d \
    --pod "$POD_NAME" \
    --name "$GATEWAY_CONTAINER" \
    --env-file "$ENV_FILE" \
    --restart unless-stopped \
    "$IMAGE_NAME"

# 7. Start Squid Filter Proxy inside Pod
echo "[*] Starting Proxy container ($PROXY_CONTAINER)..."
podman run -d \
    --pod "$POD_NAME" \
    --name "$PROXY_CONTAINER" \
    --env "GATEWAY_URL=http://$LAN_IP:8080" \
    --restart unless-stopped \
    "$PROXY_IMAGE"

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
echo " - DNS Interception Port     : $HOST_IP:53 (UDP)"
echo " - Filter Proxy (HTTP/S)     : $HOST_IP:3128 (set as Wi-Fi proxy)"
echo " - Local AI Model Engine     : $AI_ENGINE_VAL (Embedded ONNX <2ms inference)"
echo " - Status & Logs             : podman logs -f $GATEWAY_CONTAINER"
echo " - Test Suite                : ./scripts/test_filter.sh"
echo "============================================================"
