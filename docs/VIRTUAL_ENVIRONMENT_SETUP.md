# Virtual Testing Environment Setup (Podman Edition)

This guide documents the rootless container deployment that runs entirely inside **Podman** without altering your host system.

---

## 1. Container Topology & Port Mapping

| Service | Container Internal Port | Host Mapped Port | Purpose |
| :--- | :--- | :--- | :--- |
| **DNS Filter Daemon** | `53/udp` | `1053/udp` | Intercepts DNS queries, sinkholes gambling domains, passes safe queries to `1.1.1.1` |
| **Block & Unlock Portal** | `8080/tcp` | `8080/tcp` | Web UI, OTP emailer to `$MOTHER`, client whitelisting |

---

## 2. Podman Build & Launch Commands

```bash
cd /Users/ibmbendev/workspace/block-gambling-site

# 1. Build Container Image
podman build -t filter-gateway:latest -f server/Containerfile server/

# 2. Run Container in Dedicated Podman Network
podman run -d --name filter-gateway \
  --network filter-net \
  -p 8080:8080 \
  -p 1053:53/udp \
  --env-file .env \
  localhost/filter-gateway:latest
```

---

## 3. Verification & DNS Resolution Tests

### Test Gambling Domain Resolution (Sinkholed):
```bash
dig @127.0.0.1 -p 1053 betonline.ag +short
# Output: 172.28.0.10 (Sinkhole Gateway)

dig @127.0.0.1 -p 1053 pokerstars.com +short
# Output: 172.28.0.10 (Sinkhole Gateway)
```

### Test Safe Domain Resolution (Pass-Through):
```bash
dig @127.0.0.1 -p 1053 google.com +short
# Output: 142.250.x.x (Real Google IP)

dig @127.0.0.1 -p 1053 wikipedia.org +short
# Output: 103.102.x.x (Real Wikipedia IP)
```

---

## 4. Testing with Mobile / Simulated Client

1. **Web Portal Interception Screen**:
   Open in your phone's browser:
   ```text
   http://192.168.1.7:8080/blocked?domain=pokerstars.com
   ```
2. **Request Unlock**:
   - Tap "Request Unlock Key".
   - Key is dispatched to `$MOTHER` (`ibmbendev@gmail.com`).
3. **Authorize**:
   - Enter OTP to unlock the domain for 1 hour.
