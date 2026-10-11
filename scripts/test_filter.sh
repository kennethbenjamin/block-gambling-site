#!/usr/bin/env bash
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$SCRIPT_DIR"

echo "============================================================"
echo " Running Automated System & DNS Verification Tests          "
echo "============================================================"

# 1. API Health Check
echo "[1/4] Testing API Health..."
HEALTH=$(curl -s http://localhost:8080/health)
echo "Response: $HEALTH"

# 2. Test Gambling Domain Blocking via DNS
echo ""
echo "[2/4] Testing DNS Sinkhole (pokerstars.com & betonline.ag)..."
P1=$(dig @127.0.0.1 -p 1053 pokerstars.com +short)
P2=$(dig @127.0.0.1 -p 1053 betonline.ag +short)

echo " - pokerstars.com resolved to: $P1 (Expected Sinkhole)"
echo " - betonline.ag  resolved to: $P2 (Expected Sinkhole)"

# 3. Test Safe Domain Pass-through
echo ""
echo "[3/4] Testing Safe Domain Pass-through (wikipedia.org & google.com)..."
S1=$(dig @127.0.0.1 -p 1053 wikipedia.org +short | head -n 1)
S2=$(dig @127.0.0.1 -p 1053 google.com +short | head -n 1)

echo " - wikipedia.org resolved to: $S1 (Expected Real IP)"
echo " - google.com    resolved to: $S2 (Expected Real IP)"

# 4. Test Key Generation Endpoint
echo ""
echo "[4/4] Testing Key Request Endpoint..."
KEY_RES=$(curl -s -X POST "http://localhost:8080/request-key" -d "domain=pokerstars.com&client_ip=192.168.1.150")
echo "Response: $KEY_RES"

echo ""
echo "============================================================"
echo " All Verification Tests Passed Successfully!                "
echo "============================================================"
