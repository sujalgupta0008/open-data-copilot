from fastapi.testclient import TestClient
from app.main import app
from app.core.config import settings
from unittest.mock import AsyncMock, patch
import uuid

client = TestClient(app)

def make_user_and_dataset(csv="Source,Price,Airline\nDelhi,5000,IndiGo\nMumbai,7000,Air India\nDelhi,6000,IndiGo\nMumbai,8000,Air India\nDelhi,4000,SpiceJet\n"):
    email = f"groq{uuid.uuid4().hex[:6]}@test.com"
    r = client.post("/api/auth/register", json={"email": email, "password": "pass123", "name": "GroqTest"})
    assert r.status_code == 200, r.text
    token = r.json()["access_token"]
    h = {"Authorization": f"Bearer {token}"}
    files = {"file": ("flight.csv", csv, "text/csv")}
    r = client.post("/api/datasets/upload", files=files, headers=h)
    assert r.status_code == 200, r.text
    return h, r.json()["id"]

def _expected_rows():
    # Delhi 5000, Mumbai 7500
    return {"Delhi": 5000.0, "Mumbai": 7500.0}

# TEST 1 — Gemini success
def test_groq_chain_gemini_success():
    h, did = make_user_and_dataset()
    mock_result = {
        "intent": "sql",
        "code": 'SELECT "Source", AVG("Price") AS average_price FROM df GROUP BY "Source" ORDER BY average_price DESC LIMIT 10',
        "explanation": "Gemini says Mumbai highest average price 7500.",
        "chart_type": "bar",
        "chart_config_hint": {"x": "Source", "y": "average_price"}
    }
    orig_p, orig_k = settings.AI_PROVIDER, settings.AI_API_KEY
    orig_gk, orig_gm = settings.GROQ_API_KEY, settings.GROQ_MODEL
    settings.AI_PROVIDER = "gemini"
    settings.AI_API_KEY = "fake-gemini-key-12345678"
    settings.GROQ_API_KEY = "fake-groq-key-12345678"
    try:
        with patch("app.ai.provider.GeminiProvider.generate", new=AsyncMock(return_value=mock_result)):
            r = client.post(f"/api/datasets/{did}/analyze", json={"question": "Which Source has the highest average Price?"}, headers=h)
            assert r.status_code == 200, r.text
            j = r.json()
            assert j["ai_provider"] == "gemini"
            assert j["ai_mode"] == "LLM-powered"
            assert j["is_fallback"] is False
            assert j["execution_result"]["success"] is True
            rows = {row["Source"]: row["average_price"] for row in j["execution_result"]["data"]}
            exp = _expected_rows()
            for k, v in exp.items():
                assert abs(rows[k] - v) < 0.01, f"numerical mismatch {k} {rows[k]} vs {v}"
            assert "Gemini" in j["message"]["content"] or "mumbai" in j["message"]["content"].lower()
    finally:
        settings.AI_PROVIDER, settings.AI_API_KEY = orig_p, orig_k
        settings.GROQ_API_KEY, settings.GROQ_MODEL = orig_gk, orig_gm

# TEST 2 — Gemini 429 → Groq success
def test_gemini_429_groq_success():
    h, did = make_user_and_dataset()
    groq_result = {
        "intent": "sql",
        "code": 'SELECT "Source", AVG("Price") AS average_price FROM df GROUP BY "Source" ORDER BY average_price DESC LIMIT 10',
        "explanation": "Groq says Mumbai highest average price 7500.",
        "chart_type": "bar",
        "chart_config_hint": {"x": "Source", "y": "average_price"}
    }
    orig_p, orig_k = settings.AI_PROVIDER, settings.AI_API_KEY
    orig_gk = settings.GROQ_API_KEY
    settings.AI_PROVIDER = "gemini"
    settings.AI_API_KEY = "fake-gemini-key-12345678"
    settings.GROQ_API_KEY = "fake-groq-key-12345678"
    try:
        with patch("app.ai.provider.GeminiProvider.generate", new=AsyncMock(side_effect=Exception("Gemini provider rate limited — quota exceeded (429)"))) as mock_gemini:
            with patch("app.ai.provider.GroqProvider.generate", new=AsyncMock(return_value=groq_result)) as mock_groq:
                r = client.post(f"/api/datasets/{did}/analyze", json={"question": "Which Source has the highest average Price?"}, headers=h)
                assert r.status_code == 200, r.text
                j = r.json()
                assert mock_gemini.call_count == 1
                assert mock_groq.call_count == 1
                assert j["ai_provider"] == "groq"
                assert j["ai_mode"] == "LLM-powered"
                assert j["is_fallback"] is True
                assert j["execution_result"]["success"] is True
                rows = {row["Source"]: row["average_price"] for row in j["execution_result"]["data"]}
                exp = _expected_rows()
                for k, v in exp.items():
                    assert abs(rows[k] - v) < 0.01
                assert "Groq" in j["message"]["content"] or "mumbai" in j["message"]["content"].lower()
                # no raw error in content
                assert "rate limit" not in j["message"]["content"].lower()
    finally:
        settings.AI_PROVIDER, settings.AI_API_KEY = orig_p, orig_k
        settings.GROQ_API_KEY = orig_gk

# TEST 3 — Gemini timeout → Groq
def test_gemini_timeout_groq():
    h, did = make_user_and_dataset()
    groq_result = {
        "intent": "sql",
        "code": 'SELECT "Source", AVG("Price") AS average_price FROM df GROUP BY "Source" ORDER BY average_price DESC LIMIT 10',
        "explanation": "Groq explanation after timeout.",
        "chart_type": "bar",
        "chart_config_hint": None
    }
    orig_p, orig_k = settings.AI_PROVIDER, settings.AI_API_KEY
    orig_gk = settings.GROQ_API_KEY
    settings.AI_PROVIDER = "gemini"
    settings.AI_API_KEY = "fake-gemini-key-12345678"
    settings.GROQ_API_KEY = "fake-groq-key-12345678"
    try:
        with patch("app.ai.provider.GeminiProvider.generate", new=AsyncMock(side_effect=Exception("Gemini provider timed out after 30s."))):
            with patch("app.ai.provider.GroqProvider.generate", new=AsyncMock(return_value=groq_result)):
                r = client.post(f"/api/datasets/{did}/analyze", json={"question": "Which Source has the highest average Price?"}, headers=h)
                assert r.status_code == 200
                j = r.json()
                assert j["ai_provider"] == "groq"
                assert j["is_fallback"] is True
    finally:
        settings.AI_PROVIDER, settings.AI_API_KEY = orig_p, orig_k
        settings.GROQ_API_KEY = orig_gk

# TEST 4 — Gemini 5xx → Groq
def test_gemini_5xx_groq():
    h, did = make_user_and_dataset()
    groq_result = {
        "intent": "sql",
        "code": 'SELECT "Source", AVG("Price") AS average_price FROM df GROUP BY "Source" ORDER BY average_price DESC LIMIT 10',
        "explanation": "Groq after 5xx",
        "chart_type": "bar",
        "chart_config_hint": None
    }
    orig_p, orig_k = settings.AI_PROVIDER, settings.AI_API_KEY
    orig_gk = settings.GROQ_API_KEY
    settings.AI_PROVIDER = "gemini"
    settings.AI_API_KEY = "fake-gemini-key-12345678"
    settings.GROQ_API_KEY = "fake-groq-key-12345678"
    try:
        with patch("app.ai.provider.GeminiProvider.generate", new=AsyncMock(side_effect=Exception("Gemini provider transient failure 500: Internal Server Error"))):
            with patch("app.ai.provider.GroqProvider.generate", new=AsyncMock(return_value=groq_result)):
                r = client.post(f"/api/datasets/{did}/analyze", json={"question": "Which Source has the highest average Price?"}, headers=h)
                assert r.status_code == 200
                assert r.json()["ai_provider"] == "groq"
    finally:
        settings.AI_PROVIDER, settings.AI_API_KEY = orig_p, orig_k
        settings.GROQ_API_KEY = orig_gk

# TEST 5 — Gemini malformed → Groq
def test_gemini_malformed_groq():
    h, did = make_user_and_dataset()
    groq_result = {
        "intent": "sql",
        "code": 'SELECT "Source", AVG("Price") AS average_price FROM df GROUP BY "Source" ORDER BY average_price DESC LIMIT 10',
        "explanation": "Groq after malformed",
        "chart_type": "bar",
        "chart_config_hint": None
    }
    orig_p, orig_k = settings.AI_PROVIDER, settings.AI_API_KEY
    orig_gk = settings.GROQ_API_KEY
    settings.AI_PROVIDER = "gemini"
    settings.AI_API_KEY = "fake-gemini-key-12345678"
    settings.GROQ_API_KEY = "fake-groq-key-12345678"
    try:
        with patch("app.ai.provider.GeminiProvider.generate", new=AsyncMock(side_effect=Exception("Gemini provider returned malformed/invalid response"))):
            with patch("app.ai.provider.GroqProvider.generate", new=AsyncMock(return_value=groq_result)):
                r = client.post(f"/api/datasets/{did}/analyze", json={"question": "Which Source has the highest average Price?"}, headers=h)
                assert r.status_code == 200
                assert r.json()["ai_provider"] == "groq"
    finally:
        settings.AI_PROVIDER, settings.AI_API_KEY = orig_p, orig_k
        settings.GROQ_API_KEY = orig_gk

# TEST 6 — Gemini 429 + Groq 429 → Deterministic
def test_gemini_groq_both_429_deterministic():
    h, did = make_user_and_dataset()
    orig_p, orig_k = settings.AI_PROVIDER, settings.AI_API_KEY
    orig_gk = settings.GROQ_API_KEY
    settings.AI_PROVIDER = "gemini"
    settings.AI_API_KEY = "fake-gemini-key-12345678"
    settings.GROQ_API_KEY = "fake-groq-key-12345678"
    try:
        with patch("app.ai.provider.GeminiProvider.generate", new=AsyncMock(side_effect=Exception("rate limited (429)"))):
            with patch("app.ai.provider.GroqProvider.generate", new=AsyncMock(side_effect=Exception("Groq provider rate limited — quota exceeded (429)"))):
                r = client.post(f"/api/datasets/{did}/analyze", json={"question": "Which Source has the highest average Price?"}, headers=h)
                assert r.status_code == 200, r.text
                j = r.json()
                assert j["ai_provider"] == "deterministic"
                assert j["ai_mode"] == "Deterministic Analysis"
                assert j["is_fallback"] is True
                assert j["execution_result"]["success"] is True
                rows = {row["Source"]: row["average_price"] for row in j["execution_result"]["data"]}
                exp = _expected_rows()
                for k, v in exp.items():
                    assert abs(rows[k] - v) < 0.01
                assert "average" in j["message"]["content"].lower()
                assert "rate limit" not in j["message"]["content"].lower()
    finally:
        settings.AI_PROVIDER, settings.AI_API_KEY = orig_p, orig_k
        settings.GROQ_API_KEY = orig_gk

# TEST 7 — Gemini unavailable + Groq unavailable → Deterministic
def test_gemini_groq_unavailable_deterministic():
    h, did = make_user_and_dataset()
    orig_p, orig_k = settings.AI_PROVIDER, settings.AI_API_KEY
    orig_gk = settings.GROQ_API_KEY
    settings.AI_PROVIDER = "gemini"
    settings.AI_API_KEY = "fake-gemini-key-12345678"
    settings.GROQ_API_KEY = "fake-groq-key-12345678"
    try:
        with patch("app.ai.provider.GeminiProvider.generate", new=AsyncMock(side_effect=Exception("provider unavailable"))):
            with patch("app.ai.provider.GroqProvider.generate", new=AsyncMock(side_effect=Exception("Groq provider connection failed: provider unavailable"))):
                r = client.post(f"/api/datasets/{did}/analyze", json={"question": "Which Source has the highest average Price?"}, headers=h)
                assert r.status_code == 200
                assert r.json()["ai_provider"] == "deterministic"
                assert r.json()["ai_mode"] == "Deterministic Analysis"
    finally:
        settings.AI_PROVIDER, settings.AI_API_KEY = orig_p, orig_k
        settings.GROQ_API_KEY = orig_gk

# TEST 8 — No infinite retry
def test_no_infinite_retry_gemini_groq():
    h, did = make_user_and_dataset()
    orig_p, orig_k = settings.AI_PROVIDER, settings.AI_API_KEY
    orig_gk = settings.GROQ_API_KEY
    settings.AI_PROVIDER = "gemini"
    settings.AI_API_KEY = "fake-gemini-key-12345678"
    settings.GROQ_API_KEY = "fake-groq-key-12345678"
    try:
        mock_gem = AsyncMock(side_effect=Exception("rate limited (429)"))
        mock_groq = AsyncMock(side_effect=Exception("Groq provider rate limited — quota exceeded (429)"))
        with patch("app.ai.provider.GeminiProvider.generate", mock_gem):
            with patch("app.ai.provider.GroqProvider.generate", mock_groq):
                r = client.post(f"/api/datasets/{did}/analyze", json={"question": "Which Source has the highest average Price?"}, headers=h)
                assert r.status_code == 200
                assert mock_gem.call_count == 1, f"Gemini should be called once, got {mock_gem.call_count}"
                assert mock_groq.call_count == 1, f"Groq should be called once, got {mock_groq.call_count}"
    finally:
        settings.AI_PROVIDER, settings.AI_API_KEY = orig_p, orig_k
        settings.GROQ_API_KEY = orig_gk

# TEST 9 — Numerical correctness across provider paths
def test_numerical_correctness_all_paths():
    cases = [
        ("gemini_success", None, None),
        ("gemini_429_groq", "429", "groq_success"),
        ("both_fail_deterministic", "429", "429"),
    ]
    for case, gem_exc, groq_exc in cases:
        h, did = make_user_and_dataset()
        orig_p, orig_k = settings.AI_PROVIDER, settings.AI_API_KEY
        orig_gk = settings.GROQ_API_KEY
        settings.AI_PROVIDER = "gemini"
        settings.AI_API_KEY = "fake-gemini-key-12345678"
        settings.GROQ_API_KEY = "fake-groq-key-12345678"
        try:
            if case == "gemini_success":
                mock_result = {
                    "intent": "sql",
                    "code": 'SELECT "Source", AVG("Price") AS average_price FROM df GROUP BY "Source" ORDER BY average_price DESC LIMIT 10',
                    "explanation": "Gemini numeric test",
                    "chart_type": "bar",
                    "chart_config_hint": None
                }
                with patch("app.ai.provider.GeminiProvider.generate", new=AsyncMock(return_value=mock_result)):
                    r = client.post(f"/api/datasets/{did}/analyze", json={"question": "Which Source has the highest average Price?"}, headers=h)
                    assert r.status_code == 200
                    rows = {row["Source"]: row["average_price"] for row in r.json()["execution_result"]["data"]}
                    exp = _expected_rows()
                    for k, v in exp.items():
                        assert abs(rows[k] - v) < 0.01, f"{case} numerical mismatch"
            elif case == "gemini_429_groq":
                groq_result = {
                    "intent": "sql",
                    "code": 'SELECT "Source", AVG("Price") AS average_price FROM df GROUP BY "Source" ORDER BY average_price DESC LIMIT 10',
                    "explanation": "Groq numeric test",
                    "chart_type": "bar",
                    "chart_config_hint": None
                }
                with patch("app.ai.provider.GeminiProvider.generate", new=AsyncMock(side_effect=Exception("429"))):
                    with patch("app.ai.provider.GroqProvider.generate", new=AsyncMock(return_value=groq_result)):
                        r = client.post(f"/api/datasets/{did}/analyze", json={"question": "Which Source has the highest average Price?"}, headers=h)
                        assert r.status_code == 200
                        rows = {row["Source"]: row["average_price"] for row in r.json()["execution_result"]["data"]}
                        exp = _expected_rows()
                        for k, v in exp.items():
                            assert abs(rows[k] - v) < 0.01
            else:
                with patch("app.ai.provider.GeminiProvider.generate", new=AsyncMock(side_effect=Exception("429"))):
                    with patch("app.ai.provider.GroqProvider.generate", new=AsyncMock(side_effect=Exception("429"))):
                        r = client.post(f"/api/datasets/{did}/analyze", json={"question": "Which Source has the highest average Price?"}, headers=h)
                        assert r.status_code == 200
                        rows = {row["Source"]: row["average_price"] for row in r.json()["execution_result"]["data"]}
                        exp = _expected_rows()
                        for k, v in exp.items():
                            assert abs(rows[k] - v) < 0.01
        finally:
            settings.AI_PROVIDER, settings.AI_API_KEY = orig_p, orig_k
            settings.GROQ_API_KEY = orig_gk

# TEST 10 — API key security
def test_groq_keys_never_exposed():
    h, did = make_user_and_dataset()
    orig_p, orig_k = settings.AI_PROVIDER, settings.AI_API_KEY
    orig_gk = settings.GROQ_API_KEY
    settings.AI_PROVIDER = "gemini"
    settings.AI_API_KEY = "sk-gemini-super-secret-12345"
    settings.GROQ_API_KEY = "gsk_groq-super-secret-67890"
    try:
        r = client.get("/api/ai/status", headers=h)
        assert r.status_code == 200
        txt = r.text
        assert "sk-gemini-super-secret" not in txt
        assert "gsk_groq-super-secret" not in txt
        assert "super-secret" not in txt
        data = r.json()
        # Groq key should not be exposed even as preview
        assert "gsk_groq" not in txt
        # Privacy endpoint also should not leak keys
        r2 = client.get("/api/privacy", headers=h)
        assert "gsk_groq-super-secret" not in r2.text
        assert "sk-gemini-super-secret" not in r2.text
        # Analyze response should not contain keys
        mock_result = {
            "intent": "sql",
            "code": 'SELECT "Source", AVG("Price") AS average_price FROM df GROUP BY "Source" ORDER BY average_price DESC LIMIT 10',
            "explanation": "ok",
            "chart_type": "bar",
            "chart_config_hint": None
        }
        with patch("app.ai.provider.GeminiProvider.generate", new=AsyncMock(return_value=mock_result)):
            r3 = client.post(f"/api/datasets/{did}/analyze", json={"question": "Which Source has the highest average Price?"}, headers=h)
            assert "sk-gemini-super-secret" not in r3.text
            assert "gsk_groq-super-secret" not in r3.text
    finally:
        settings.AI_PROVIDER, settings.AI_API_KEY = orig_p, orig_k
        settings.GROQ_API_KEY = orig_gk
