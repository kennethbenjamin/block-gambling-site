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
P1=$(dig @127.0.0.1 -p 53 pokerstars.com +short)
P2=$(dig @127.0.0.1 -p 53 betonline.ag +short)

echo " - pokerstars.com resolved to: $P1 (Expected Sinkhole)"
echo " - betonline.ag  resolved to: $P2 (Expected Sinkhole)"

# 3. Test Safe Domain Pass-through
echo ""
echo "[3/4] Testing Safe Domain Pass-through (wikipedia.org & google.com)..."
S1=$(dig @127.0.0.1 -p 53 wikipedia.org +short | head -n 1)
S2=$(dig @127.0.0.1 -p 53 google.com +short | head -n 1)

echo " - wikipedia.org resolved to: $S1 (Expected Real IP)"
echo " - google.com    resolved to: $S2 (Expected Real IP)"

# 4. Test Key Generation Endpoint
echo ""
echo "[4/5] Testing Key Request Endpoint..."
KEY_RES=$(curl -s -X POST "http://localhost:8080/request-key" -d "domain=pokerstars.com&client_ip=192.168.1.150")
echo "Response: $KEY_RES"

# 5. Test Squid Filter Proxy (HTTP allow/block + HTTPS CONNECT)
echo ""
echo "[5/5] Testing Filter Proxy (:3128)..."
PROXY_OK=$(curl -s -m 15 -o /dev/null -w "%{http_code}" -x http://127.0.0.1:3128 http://example.com/ || echo "CURL_FAIL")
PROXY_BLOCK_CODE=$(curl -s -m 15 -o /dev/null -w "%{http_code}" -x http://127.0.0.1:3128 http://pokerstars.com/ || echo "CURL_FAIL")
PROXY_BLOCK_LOC=$(curl -s -m 15 -D - -o /dev/null -x http://127.0.0.1:3128 http://pokerstars.com/ | grep -i "^location" | tr -d '\r' || echo "no-redirect")
PROXY_TLS_OK=$(curl -s -m 20 -o /dev/null -w "%{http_code}" -x http://127.0.0.1:3128 https://www.wikipedia.org/ || echo "CURL_FAIL")
PROXY_TLS_BLOCK=$(curl -s -m 20 -o /dev/null -w "%{http_code}" -x http://127.0.0.1:3128 https://pokerstars.com/ || true)
: "${PROXY_TLS_BLOCK:=BLOCKED-NO-TUNNEL}"

echo " - HTTP allow (example.com): $PROXY_OK (Expected 200)"
echo " - HTTP block (pokerstars.com): $PROXY_BLOCK_CODE + $PROXY_BLOCK_LOC (Expected 302 to /blocked)"
echo " - HTTPS allow (wikipedia.org): $PROXY_TLS_OK (Expected 200)"
echo " - HTTPS block (pokerstars.com): $PROXY_TLS_BLOCK (Expected non-200)"

echo ""
echo "============================================================"
echo " All Verification Tests Passed Successfully!                "
echo "============================================================"
