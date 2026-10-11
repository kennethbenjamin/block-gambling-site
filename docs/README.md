# AI-Powered Network Gambling Site Blocker & Parental Override System (Podman Edition)

This directory contains the complete architecture, implementation plan, automated deployment scripts, and virtual testing environment setup for enforcing network-wide gambling restrictions on Wi-Fi networks with dynamic AI classification and mother-authorized override keys.

---

## Documentation Index

- [`DEPLOYMENT_GUIDE.md`](DEPLOYMENT_GUIDE.md): **Start Here** — Automated installation script manual, exact Podman CLI commands, and router configuration.
- [`ARCHITECTURE.md`](ARCHITECTURE.md): Full system architecture, gateway-level anti-bypass mechanisms, AI classification pipeline, and Podman network security model.
- [`VIRTUAL_ENVIRONMENT_SETUP.md`](VIRTUAL_ENVIRONMENT_SETUP.md): Step-by-step guide to run and validate the complete solution with **Podman** / `podman-compose` with automated SMTP dispatch to `$MOTHER`.

---

## Quick Start Deployment

```bash
cd /Users/ibmbendev/workspace/block-gambling-site

# 1. Deploy the stack
./deploy.sh

# 2. Run automated verification tests
./scripts/test_filter.sh

# 3. View live traffic and unlock logs
podman logs -f filter-gateway
```
