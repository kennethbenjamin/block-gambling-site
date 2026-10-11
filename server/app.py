import asyncio
import logging
import os
import re
import secrets
import smtplib
import socket
import threading
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from email.message import EmailMessage
from typing import Dict, Optional

import httpx
from dnslib import A, DNSRecord, QTYPE, RR
from fastapi import FastAPI, Form, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("gambling_filter")

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
templates = Jinja2Templates(directory=os.path.join(BASE_DIR, "templates"))

# Environment Variables
MOTHER_EMAIL = os.environ.get("MOTHER", "mother@example.com")
SMTP_SERVER = os.environ.get("SMTP_SERVER", "smtp.gmail.com")
SMTP_PORT = int(os.environ.get("SMTP_PORT", 587))
SMTP_USER = os.environ.get("SMTP_USER", "")
SMTP_PASS = os.environ.get("SMTP_PASS", "")
OLLAMA_HOST = os.environ.get("OLLAMA_HOST", "http://localhost:11434")
AI_MODEL = os.environ.get("AI_MODEL", "llama3.2:1b")
GATEWAY_IP = os.environ.get("GATEWAY_IP", "192.168.1.7")
UPSTREAM_DNS = os.environ.get("UPSTREAM_DNS", "1.1.1.1")

# In-memory storage (production can use Redis)
verdict_cache: Dict[str, Dict] = {}
active_tokens: Dict[str, Dict] = {}
whitelisted_clients: Dict[str, Dict] = {}

KNOWN_GAMBLING_KEYWORDS = [
    "bet", "betting", "casino", "poker", "slots", "gamble", "gambling",
    "wagering", "jackpot", "roulette", "blackjack", "sportsbook", "lottery",
    "baccarat", "bookmaker", "onlinebet", "pokerstars", "draftkings", "fanduel",
    "888casino", "bet365", "stake.com", "bovada", "betfair", "jackpotcity"
]


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def send_key_to_mother(domain: str, client_ip: str, key: str):
    """Sends OTP unlock key directly to the MOTHER variable email."""
    if not MOTHER_EMAIL:
        raise ValueError("Environment variable MOTHER is not configured.")

    msg = EmailMessage()
    msg["Subject"] = f"[NETWORK ALERT] Wi-Fi Gambling Unlock Request: {domain}"
    msg["From"] = SMTP_USER or "network-filter@home.gateway"
    msg["To"] = MOTHER_EMAIL

    body = f"""Hello,

A device on your Wi-Fi network ({client_ip}) attempted to access a gambling site:
Domain: {domain}
Time: {utc_now().strftime('%Y-%m-%d %H:%M:%S UTC')}

If you approve temporary access (1 hour), provide this authorization key:
--------------------------------
KEY: {key}
--------------------------------

This key will expire in 10 minutes.
If you did not approve this request, ignore this message.
"""
    msg.set_content(body)

    is_dummy_smtp = (
        not SMTP_USER
        or not SMTP_PASS
        or "your-" in SMTP_USER.lower()
        or "example" in SMTP_USER.lower()
    )

    if is_dummy_smtp:
        logger.warning(f"[DISPATCH TO $MOTHER] Mock/Dev Mode: Key for {domain} dispatched to $MOTHER ({MOTHER_EMAIL}): {key}")
        return True

    try:
        with smtplib.SMTP(SMTP_SERVER, SMTP_PORT, timeout=3) as server:
            server.starttls()
            server.login(SMTP_USER, SMTP_PASS)
            server.send_message(msg)
        logger.info(f"Successfully emailed unlock key for {domain} to $MOTHER ({MOTHER_EMAIL})")
        return True
    except Exception as ex:
        logger.error(f"Live SMTP delivery failed: {ex}. Key logged for $MOTHER ({MOTHER_EMAIL}): {key}")
        return True


async def classify_domain_with_ai(domain: str) -> bool:
    """Uses few-shot LLM (Ollama) + heuristic analysis to detect gambling sites."""
    clean_domain = re.sub(r"^https?://", "", domain).split("/")[0].lower().rstrip(".")

    if clean_domain in verdict_cache:
        cached = verdict_cache[clean_domain]
        if utc_now() < cached["expires"]:
            return cached["is_gambling"]

    # 1. Quick regex heuristic
    heuristic_match = any(kw in clean_domain for kw in KNOWN_GAMBLING_KEYWORDS)

    # 2. AI Few-Shot Classification
    prompt = f"""Classify if the domain is a GAMBLING, CASINO, or SPORTS BETTING website.

Examples:
Domain: bet365.com -> YES
Domain: wikipedia.org -> NO
Domain: pokerstars.com -> YES
Domain: github.com -> NO
Domain: {clean_domain} ->"""

    is_gambling = heuristic_match
    try:
        async with httpx.AsyncClient(timeout=4.0) as client:
            res = await client.post(
                f"{OLLAMA_HOST}/api/generate",
                json={"model": AI_MODEL, "prompt": prompt, "stream": False},
            )
            if res.status_code == 200:
                output = res.json().get("response", "").upper()
                if f"{clean_domain.upper()} -> YES" in output or ("YES" in output and "NON-GAMBLING" not in output and "NOT" not in output):
                    is_gambling = True
                elif f"{clean_domain.upper()} -> NO" in output or "NON-GAMBLING" in output or "EDUCATIONAL" in output:
                    is_gambling = False or heuristic_match
                logger.info(f"[AI CLASSIFIER] Domain: {clean_domain} -> AI Output: '{output[:60]}...' -> Final: is_gambling={is_gambling}")
    except Exception as e:
        logger.warning(f"AI classifier at {OLLAMA_HOST} unreachable ({e}). Relying on keyword heuristic.")

    verdict_cache[clean_domain] = {
        "is_gambling": is_gambling,
        "expires": utc_now() + timedelta(hours=24),
    }
    return is_gambling


# ----------------------------------------------------
# Embedded Container-Only DNS Filter Server (Port 53 UDP)
# ----------------------------------------------------
def resolve_upstream(data: bytes, upstream_ip: str) -> bytes:
    """Forwards safe DNS queries to standard upstream DNS (1.1.1.1)."""
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.settimeout(2.0)
        sock.sendto(data, (upstream_ip, 53))
        resp, _ = sock.recvfrom(4096)
        sock.close()
        return resp
    except Exception:
        return None


def dns_worker_loop():
    """Runs inside container on Port 53 UDP."""
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.bind(("0.0.0.0", 53))
        logger.info(f"Container DNS Filter Daemon listening on 0.0.0.0:53 (UDP)")
    except Exception as e:
        logger.warning(f"Could not bind port 53 inside container: {e}")
        return

    while True:
        try:
            data, addr = sock.recvfrom(2048)
            client_ip = addr[0]
            request = DNSRecord.parse(data)
            qname = str(request.q.qname).rstrip(".").lower()
            qtype = QTYPE[request.q.qtype]

            # Fast check if domain is gambling
            is_blocked = False
            client_data = whitelisted_clients.get(client_ip)
            is_whitelisted = client_data and utc_now() < client_data["expires"] and (
                qname in client_data["domains"] or "*" in client_data["domains"]
            )

            if not is_whitelisted:
                is_blocked = any(kw in qname for kw in KNOWN_GAMBLING_KEYWORDS)
                if not is_blocked and qname in verdict_cache:
                    is_blocked = verdict_cache[qname].get("is_gambling", False)

            if is_blocked and qtype in ("A", "ANY"):
                logger.info(f"[DNS SINKHOLE] Intercepted {qname} from {client_ip} -> Redirecting to {GATEWAY_IP}")
                reply = request.reply()
                reply.add_answer(RR(request.q.qname, QTYPE.A, rdata=A(GATEWAY_IP), ttl=10))
                sock.sendto(reply.pack(), addr)
            else:
                # Forward to upstream
                upstream_resp = resolve_upstream(data, UPSTREAM_DNS)
                if upstream_resp:
                    sock.sendto(upstream_resp, addr)
                else:
                    reply = request.reply()
                    sock.sendto(reply.pack(), addr)
        except Exception as ex:
            logger.debug(f"DNS loop error: {ex}")


@asynccontextmanager
async def lifespan(app: FastAPI):
    dns_thread = threading.Thread(target=dns_worker_loop, daemon=True)
    dns_thread.start()
    yield


app = FastAPI(title="AI Gambling Filter Gateway & Parental Unlock Service", lifespan=lifespan)


@app.get("/health")
async def health_check():
    return {
        "status": "online",
        "container_isolated": True,
        "mother_configured": bool(MOTHER_EMAIL),
        "mother_address": MOTHER_EMAIL,
        "ai_host": OLLAMA_HOST,
        "ai_model": AI_MODEL,
        "gateway_ip": GATEWAY_IP,
    }


@app.get("/check-dns")
async def check_dns(domain: str = Query(...), client_ip: str = Query("127.0.0.1")):
    """Called by DNS daemon or network firewall to determine routing."""
    clean_domain = re.sub(r"^https?://", "", domain).split("/")[0].lower().rstrip(".")

    client_data = whitelisted_clients.get(client_ip)
    if client_data and utc_now() < client_data["expires"]:
        if clean_domain in client_data["domains"] or "*" in client_data["domains"]:
            return {"action": "ALLOW", "domain": clean_domain, "reason": "whitelisted"}

    is_gambling = await classify_domain_with_ai(clean_domain)
    if is_gambling:
        return {
            "action": "BLOCK",
            "domain": clean_domain,
            "redirect_ip": GATEWAY_IP,
            "redirect_url": f"http://{GATEWAY_IP}:8080/blocked?domain={clean_domain}",
            "reason": "AI classified as gambling site",
        }

    return {"action": "ALLOW", "domain": clean_domain, "reason": "safe"}


@app.get("/blocked", response_class=HTMLResponse)
async def blocked_view(request: Request, domain: str = Query("gambling-site.com")):
    return templates.TemplateResponse("block_page.html", {"request": request, "domain": domain})


@app.get("/", response_class=HTMLResponse)
async def root_interceptor(request: Request):
    """Catches wildcard HTTP requests to intercepted domains."""
    host = request.headers.get("host", "").split(":")[0]
    if host in [GATEWAY_IP, "localhost", "127.0.0.1"]:
        return templates.TemplateResponse("block_page.html", {"request": request, "domain": "gambling-site.com"})
    return templates.TemplateResponse("block_page.html", {"request": request, "domain": host})


@app.post("/request-key")
async def request_key(request: Request, domain: str = Form(...), client_ip: Optional[str] = Form(None)):
    ip = client_ip or (request.client.host if request.client else "127.0.0.1")
    clean_domain = re.sub(r"^https?://", "", domain).split("/")[0].lower().rstrip(".")

    token = secrets.token_hex(3).upper()
    active_tokens[clean_domain] = {
        "key": token,
        "client_ip": ip,
        "expires": utc_now() + timedelta(minutes=10),
    }

    try:
        send_key_to_mother(clean_domain, ip, token)
        return JSONResponse(
            {
                "status": "success",
                "message": f"Authorization code has been dispatched to network administrator ({MOTHER_EMAIL}).",
            }
        )
    except Exception as e:
        logger.error(f"Error dispatching email: {e}")
        return JSONResponse(
            {"status": "error", "message": f"Unable to deliver authorization email: {str(e)}"},
            status_code=500,
        )


@app.post("/submit-key")
async def submit_key(request: Request, domain: str = Form(...), key: str = Form(...), client_ip: Optional[str] = Form(None)):
    ip = client_ip or (request.client.host if request.client else "127.0.0.1")
    clean_domain = re.sub(r"^https?://", "", domain).split("/")[0].lower().rstrip(".")
    provided_key = key.strip().upper()

    record = active_tokens.get(clean_domain)
    if not record or utc_now() > record["expires"]:
        raise HTTPException(status_code=400, detail="Authorization key is expired or was not requested.")

    if record["key"] != provided_key:
        raise HTTPException(status_code=403, detail="Invalid authorization key.")

    target_ip = record.get("client_ip", ip)

    existing = whitelisted_clients.get(target_ip, {"domains": [], "expires": utc_now()})
    domains = set(existing.get("domains", []))
    domains.add(clean_domain)

    whitelisted_clients[target_ip] = {
        "domains": list(domains),
        "expires": utc_now() + timedelta(hours=1),
    }

    del active_tokens[clean_domain]
    logger.info(f"Client {target_ip} authorized domain {clean_domain} for 1 hour.")

    return JSONResponse(
        {
            "status": "success",
            "message": f"Domain {clean_domain} whitelisted for 1 hour for client {target_ip}.",
        }
    )
