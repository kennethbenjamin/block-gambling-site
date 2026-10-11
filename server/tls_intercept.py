import asyncio
import logging
import os
import ssl
import tempfile
import threading
from datetime import datetime, timedelta, timezone
from typing import Dict, Optional

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID

logger = logging.getLogger("gambling_filter.tls")

CERT_DIR = os.environ.get("CERT_DIR", "/certs")
CA_KEY_PATH = os.path.join(CERT_DIR, "ca.key")
CA_CRT_PATH = os.path.join(CERT_DIR, "ca.crt")
BACKEND = ("127.0.0.1", 8080)

_ca_key = None
_ca_cert: Optional[x509.Certificate] = None
_leaf_ctx: Dict[str, ssl.SSLContext] = {}
_lock = threading.RLock()


def _ensure_ca():
    global _ca_key, _ca_cert
    if _ca_cert:
        return
    with _lock:
        if _ca_cert:
            return
        os.makedirs(CERT_DIR, exist_ok=True)
        if os.path.exists(CA_KEY_PATH) and os.path.exists(CA_CRT_PATH):
            try:
                with open(CA_KEY_PATH, "rb") as f:
                    key_data = f.read()
                with open(CA_CRT_PATH, "rb") as f:
                    crt_data = f.read()
                if not key_data or not crt_data:
                    raise ValueError("empty CA file")
                _ca_key = serialization.load_pem_private_key(key_data, password=None)
                _ca_cert = x509.load_pem_x509_certificate(crt_data)
                logger.info("[TLS] Loaded CA from %s", CERT_DIR)
                return
            except Exception as e:
                logger.warning("[TLS] Bad CA on disk (%s), regenerating", e)
                _ca_key = None
                _ca_cert = None

        _ca_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        now = datetime.now(timezone.utc)
        name = x509.Name([
            x509.NameAttribute(NameOID.COMMON_NAME, "Home Gambling Filter CA"),
        ])
        _ca_cert = (
            x509.CertificateBuilder()
            .subject_name(name)
            .issuer_name(name)
            .public_key(_ca_key.public_key())
            .serial_number(x509.random_serial_number())
            .not_valid_before(now - timedelta(minutes=5))
            .not_valid_after(now + timedelta(days=3650))
            .add_extension(x509.BasicConstraints(ca=True, path_length=0), critical=True)
            .add_extension(
                x509.KeyUsage(
                    digital_signature=True, content_commitment=False,
                    key_encipherment=False, data_encipherment=False,
                    key_agreement=False, key_cert_sign=True, crl_sign=True,
                    encipher_only=False, decipher_only=False,
                ),
                critical=True,
            )
            .sign(_ca_key, hashes.SHA256())
        )
        with open(CA_KEY_PATH, "wb") as f:
            f.write(_ca_key.private_bytes(
                serialization.Encoding.PEM,
                serialization.PrivateFormat.TraditionalOpenSSL,
                serialization.NoEncryption(),
            ))
        with open(CA_CRT_PATH, "wb") as f:
            f.write(_ca_cert.public_bytes(serialization.Encoding.PEM))
        os.chmod(CA_KEY_PATH, 0o600)
        logger.info("[TLS] Generated CA at %s", CA_CRT_PATH)


def _make_leaf(hostname: str):
    _ensure_ca()
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    now = datetime.now(timezone.utc)
    cert = (
        x509.CertificateBuilder()
        .subject_name(x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, hostname)]))
        .issuer_name(_ca_cert.subject)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - timedelta(minutes=5))
        .not_valid_after(now + timedelta(days=825))
        .add_extension(x509.SubjectAlternativeName([x509.DNSName(hostname)]), critical=False)
        .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
        .sign(_ca_key, hashes.SHA256())
    )

    cf = tempfile.NamedTemporaryFile("w", suffix=".pem", delete=False)
    kf = tempfile.NamedTemporaryFile("w", suffix=".key", delete=False)
    try:
        cf.write(cert.public_bytes(serialization.Encoding.PEM).decode())
        kf.write(key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.TraditionalOpenSSL,
            serialization.NoEncryption(),
        ).decode())
        cf.close()
        kf.close()
        ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        ctx.minimum_version = ssl.TLSVersion.TLSv1_2
        ctx.load_cert_chain(certfile=cf.name, keyfile=kf.name)
    finally:
        os.unlink(cf.name)
        os.unlink(kf.name)
    return ctx


def _leaf_context(hostname: str) -> ssl.SSLContext:
    hostname = (hostname or "").lower().rstrip(".")
    ctx = _leaf_ctx.get(hostname)
    if ctx:
        return ctx
    with _lock:
        ctx = _leaf_ctx.get(hostname)
        if ctx:
            return ctx
        ctx = _make_leaf(hostname)
        _leaf_ctx[hostname] = ctx
        logger.info("[TLS] Issued leaf cert for %s", hostname)
        return ctx


def _sni_callback(sock: ssl.SSLSocket, hostname: Optional[str], base_ctx: ssl.SSLContext):
    if not hostname:
        return
    try:
        sock.context = _leaf_context(hostname)
    except Exception as e:
        logger.warning("[TLS] SNI fail %s: %s", hostname, e)


async def _pump(src: asyncio.StreamReader, dst: asyncio.StreamWriter, label: str = ""):
    try:
        while True:
            data = await src.read(65536)
            if not data:
                logger.debug("[TLS-PUMP%s] EOF", label)
                break
            logger.debug("[TLS-PUMP%s] %d bytes", label, len(data))
            dst.write(data)
            await dst.drain()
    except Exception as e:
        logger.debug("[TLS-PUMP%s] err %s", label, e)
    finally:
        try:
            dst.write_eof()
        except Exception:
            pass


async def _handle_tls(reader: asyncio.StreamReader, writer: asyncio.StreamWriter):
    peer = writer.get_extra_info("peername")
    logger.info("[TLS] conn from %s", peer)
    try:
        remote_reader, remote_writer = await asyncio.open_connection(*BACKEND)
        logger.info("[TLS] backend connected")
    except Exception as e:
        logger.error("[TLS] backend connect fail: %s", e)
        writer.close()
        return
    try:
        await asyncio.gather(
            _pump(reader, remote_writer, "c2b"),
            _pump(remote_reader, writer, "b2c"),
        )
    finally:
        remote_writer.close()
        writer.close()


def start_https_intercept(host: str = "0.0.0.0", port: int = 443):
    _ensure_ca()
    base_ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    base_ctx.minimum_version = ssl.TLSVersion.TLSv1_2
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    now = datetime.now(timezone.utc)
    cert = (
        x509.CertificateBuilder()
        .subject_name(x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "blocked.local")]))
        .issuer_name(_ca_cert.subject)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - timedelta(minutes=5))
        .not_valid_after(now + timedelta(days=825))
        .add_extension(
            x509.SubjectAlternativeName([x509.DNSName("blocked.local"), x509.DNSName("localhost")]),
            critical=False,
        )
        .sign(_ca_key, hashes.SHA256())
    )
    cpath = os.path.join(CERT_DIR, "default.crt")
    kpath = os.path.join(CERT_DIR, "default.key")
    with open(cpath, "wb") as f:
        f.write(cert.public_bytes(serialization.Encoding.PEM))
    with open(kpath, "wb") as f:
        f.write(key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.TraditionalOpenSSL,
            serialization.NoEncryption(),
        ))
    base_ctx.load_cert_chain(certfile=cpath, keyfile=kpath)
    base_ctx.sni_callback = _sni_callback

    def run():
        async def _serve():
            server = await asyncio.start_server(
                _handle_tls, host=host, port=port, ssl=base_ctx,
            )
            logger.info("[TLS] HTTPS intercept on %s:%s", host, port)
            async with server:
                await server.serve_forever()

        asyncio.run(_serve())

    t = threading.Thread(target=run, daemon=True, name="https-intercept")
    t.start()
    return t


def ca_cert_pem() -> bytes:
    _ensure_ca()
    with open(CA_CRT_PATH, "rb") as f:
        return f.read()
