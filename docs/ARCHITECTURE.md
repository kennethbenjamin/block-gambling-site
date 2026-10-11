# System Architecture & Technical Specifications (Podman Edition)

## 1. High-Level Flow

```
[ Client Device on Wi-Fi ]
           │
           ▼
[ Network Gateway / Router (OpenWrt / pfSense / Podman Pod) ]
   ├── Port 53 / 853 Firewall Rules (Anti-Bypass Enforcement)
   └── Local DNS Resolver (CoreDNS / AdGuard Home)
           │
           ├── Check Static Gambling Blocklists & Redis Cache
           │       │
           │       ├── [MATCH / CACHED GAMBLING] ──► Redirect to Block Portal (Port 8080)
           │       └── [UNKNOWN DOMAIN] ──────────► AI Classifier Worker (Ollama Container)
           │                                            │
           │                                            ├── Scrapes Target Content
           │                                            ├── LLM Verdict (Gambling: YES/NO)
           │                                            └── Updates Cache
           │
[ Block Portal & Unlock Gateway ]
   ├── User Requests Unlock Key
   ├── OTP Generated (HMAC / Cryptographic Token, 10-min TTL)
   ├── Email Sent to: $MOTHER
   └── User Submits Received Key ──► Grants Temporary Whitelist Lease (1 Hour)
```

---

## 2. Podman Isolation & Network Layer

Running the filter stack on **Podman** provides rootless, daemonless security isolation:

- **Isolated Pod Network**: The filter gateway, local AI (Ollama), and test client run in a dedicated Podman bridge network (`podman-network-filter`).
- **Restricted Access**: Client containers cannot tamper with the container runtime socket or host configuration.
- **Rootless Operation**: No root privileges required on the host system.

---

## 3. Gateway Anti-Bypass Rules

To prevent clients from circumventing local DNS policies (via manual DNS settings, DoH, or DoT), the gateway enforces the following firewall rules:

### A. Force Standard DNS Redirection (Port 53)
```bash
# Redirect all outbound UDP/TCP port 53 traffic to the local resolver (e.g. 192.168.1.1)
iptables -t nat -A PREROUTING -i br-lan -p udp --dport 53 -j DNAT --to-destination 192.168.1.1:53
iptables -t nat -A PREROUTING -i br-lan -p tcp --dport 53 -j DNAT --to-destination 192.168.1.1:53
```

### B. Block DNS-over-TLS (DoT)
```bash
# Drop all outbound TCP traffic on port 853
iptables -A FORWARD -i br-lan -p tcp --dport 853 -j REJECT
```

### C. Restrict Router Management Access
```bash
# Prevent Wi-Fi clients from accessing router management interface
iptables -A INPUT -i wlan0 -p tcp --dport 80 -j DROP
iptables -A INPUT -i wlan0 -p tcp --dport 443 -j DROP
iptables -A INPUT -i wlan0 -p tcp --dport 22 -j DROP
```

---

## 4. Two-Tier AI Classification Pipeline

1. **Tier 1 (Instant Lookup)**:
   - Evaluates incoming domains against curated blocklists and Redis cache (< 1 ms latency).
2. **Tier 2 (Dynamic AI Evaluation)**:
   - If domain is not cached, the classification worker fetches the target website's headers, `<title>`, `<meta name="description">`, and initial body text.
   - Text is sent to Ollama (`llama3.2:1b`) container inside the Podman network.
   - Model outputs binary classification (`GAMBLING: YES` or `GAMBLING: NO`).
   - Verdict is cached with a configurable 24-hour TTL.

---

## 5. Key Authorization & Dispatch Lifecycle (`$MOTHER`)

1. **Trigger**: Blocked user clicks "Request Unlock Key" on the blocked interception page.
2. **Key Generation**: 6-character cryptographic token (`secrets.token_hex(3).upper()`).
3. **Dispatch**: SMTP client delivers message directly to the email stored in the environment variable `MOTHER`.
4. **Validation**: Client submits token; if valid, temporary whitelist status is created for the client's IP / MAC for 60 minutes.
