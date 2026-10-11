# Deployment & Operations Guide

This guide documents the deployment procedures, automation scripts, and exact Podman commands used to build and manage the AI Gambling Filter container stack.

---

## 1. Automated One-Command Installation

To deploy or update the complete container stack, run the deployment script from the project root:

```bash
cd /Users/ibmbendev/workspace/block-gambling-site
./deploy.sh
```

### What `deploy.sh` Does Automatically:
1. **Checks Podman**: Ensures the Podman container engine is running.
2. **Loads Configuration**: Reads `.env` settings (including `$MOTHER` recipient and SMTP credentials).
3. **Detects Gateway IP**: Automatically resolves the host's Wi-Fi IP address (e.g. `192.168.1.7`).
4. **Creates Network**: Scaffolds the isolated Podman bridge network (`filter-net`).
5. **Builds Container**: Compiles `filter-gateway:latest` using `server/Containerfile`.
6. **Starts Service**: Runs the container with DNS and Web ports forwarded.
7. **Performs Health Check**: Validates that the FastAPI and DNS services are healthy.

---

## 2. Exact Manual Podman Commands Used

If you prefer to run or debug commands manually:

### Build Container Image
```bash
podman build -t filter-gateway:latest -f server/Containerfile server/
```

### Create Network
```bash
podman network create filter-net
```

### Run Container
```bash
podman run -d \
  --name filter-gateway \
  --network filter-net \
  -p 8080:8080 \
  -p 53:53/udp \
  --env-file .env \
  --restart unless-stopped \
  localhost/filter-gateway:latest
```

### View Live Logs & Intercepted Traffic
```bash
podman logs -f filter-gateway
```

### Stop & Remove Container
```bash
podman stop filter-gateway && podman rm filter-gateway
```

---

## 3. Automated Test & Verification Script

Run the verification suite to test DNS sinkholing, AI classification, and `$MOTHER` key delivery:

```bash
./scripts/test_filter.sh
```

### Test Output Verification:
- **Gambling Sites** (`pokerstars.com`, `betonline.ag`): Resolved to Sinkhole IP (`172.28.0.10`).
- **Safe Sites** (`google.com`, `wikipedia.org`): Forwarded to `1.1.1.1` and resolved to real IPs.
- **Key Generation**: Generates 6-character OTP and logs/emails directly to `$MOTHER`.

---

## 4. Connecting Cellphones & Router

### Option A: Test on Single Cellphone
1. Go to **Settings > Wi-Fi** on your phone.
2. Tap the `(i)` icon next to your network.
3. Set **Configure DNS** to **Manual**.
4. Set Server IP to `192.168.1.7`.

### Option B: Network-Wide (All Wi-Fi Users)
1. Open your home Wi-Fi router admin page (`192.168.1.1`).
2. Navigate to **DHCP Settings > Primary DNS**.
3. Set **Primary DNS** to `192.168.1.7`.
4. All connected phones, laptops, and tablets are now protected.

---

## 5. Squid Filter Proxy (No DNS Changes Needed)

`deploy.sh` also builds and runs a Squid forward proxy (`filter-proxy`
container, port `3128`). It asks `filter-gateway` for a live verdict on every
domain, for both plain HTTP and HTTPS (HTTPS is filtered by CONNECT hostname —
no certificate install needed).

### Phone setup (per device, 1 minute)
1. Connect to home Wi-Fi.
2. Open Wi-Fi details for the network > **Proxy** > **Manual**.
3. Hostname `192.168.1.8`, port `3128`. Save.
4. Browse: safe sites load, gambling sites land on the block page (HTTP) or a
   proxy error (HTTPS). Unlock keys work via the block page as usual.

### Verify from a terminal
```bash
curl -x http://192.168.1.8:3128 http://example.com/ -o /dev/null -w "%{http_code}\n"   # 200
curl -x http://192.168.1.8:3128 http://pokerstars.com/ -D - -o /dev/null | grep -i location  # 302 to /blocked
```

### Notes
- The proxy helper (`proxy/gambling_helper.py`) queries `check-dns` per new
  domain (300s cache) and fails closed: classifier down = blocked.
- Rebuild after config edits: `./deploy.sh` (rebuilds both images).
