#!/usr/bin/env bash
CONTAINER_NAME="filter-gateway"

echo "[*] Stopping AI Gambling Filter Gateway ($CONTAINER_NAME)..."
podman stop "$CONTAINER_NAME" 2>/dev/null || true
podman rm "$CONTAINER_NAME" 2>/dev/null || true
echo "[+] Container stopped and removed."
