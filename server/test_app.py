import pytest
from fastapi.testclient import TestClient
from app import app, verdict_cache, active_tokens, whitelisted_clients

client = TestClient(app)

@pytest.fixture(autouse=True)
def clean_state():
    verdict_cache.clear()
    active_tokens.clear()
    whitelisted_clients.clear()

def test_health_endpoint():
    res = client.get("/health")
    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "online"
    assert data["mother_configured"] is True
    assert data["ai_engine"] == "onnx"
    assert data["onnx_ready"] is True

def test_onnx_classifier_direct():
    from onnx_classifier import onnx_classifier
    assert onnx_classifier.is_ready is True
    
    is_gambling, score = onnx_classifier.predict("pokerstars.com")
    assert is_gambling is True
    assert score > 0.5
    
    is_safe, score_safe = onnx_classifier.predict("wikipedia.org")
    assert is_safe is False
    assert score_safe < 0.5

def test_block_gambling_domain():
    # 'betonline.ag' should be blocked
    res = client.get("/check-dns?domain=betonline.ag&client_ip=192.168.1.50")
    assert res.status_code == 200
    data = res.json()
    assert data["action"] == "BLOCK"
    assert "redirect_url" in data

def test_allow_safe_domain():
    # 'wikipedia.org' should be allowed
    res = client.get("/check-dns?domain=wikipedia.org&client_ip=192.168.1.50")
    assert res.status_code == 200
    data = res.json()
    assert data["action"] == "ALLOW"

def test_request_and_submit_key_workflow():
    domain = "casino-royale.test"
    client_ip = "192.168.1.75"

    # Step 1: Ensure it's blocked initially
    res = client.get(f"/check-dns?domain={domain}&client_ip={client_ip}")
    assert res.json()["action"] == "BLOCK"

    # Step 2: Request key
    res = client.post("/request-key", data={"domain": domain, "client_ip": client_ip})
    assert res.status_code == 200
    assert domain in active_tokens
    token = active_tokens[domain]["key"]
    assert len(token) == 6

    # Step 3: Test wrong key rejected
    res = client.post("/submit-key", data={"domain": domain, "key": "WRONG1", "client_ip": client_ip})
    assert res.status_code == 403

    # Step 4: Submit correct key
    res = client.post("/submit-key", data={"domain": domain, "key": token, "client_ip": client_ip})
    assert res.status_code == 200
    assert res.json()["status"] == "success"

    # Step 5: Verify DNS now permits access
    res = client.get(f"/check-dns?domain={domain}&client_ip={client_ip}")
    assert res.json()["action"] == "ALLOW"
    assert res.json()["reason"] == "whitelisted"
