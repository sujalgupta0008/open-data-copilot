from fastapi import APIRouter, Depends, HTTPException
from app.core.config import settings
from app.core.deps import get_current_user
from app.models.models import User
import httpx
import re

router = APIRouter(prefix="/api/ai", tags=["ai"])

def get_status_payload():
    provider = (settings.AI_PROVIDER or "mock").strip().lower()
    # Groq primary + fallback (Gemini kept for backwards compat but deprecated)
    groq_key = settings.groq_api_key
    groq_model = settings.groq_model
    groq_fallback_key = settings.groq_fallback_api_key
    groq_fallback_model = settings.groq_fallback_model
    gemini_key = settings.gemini_api_key
    gemini_model = settings.gemini_model
    api_key = settings.AI_API_KEY or ""
    model = settings.AI_MODEL or ("qwen/qwen3-32b" if provider=="groq" else "gemini-1.5-flash" if provider=="gemini" else "gpt-4o-mini" if provider=="openai" else "llama3.1" if provider=="ollama" else "gpt-4o-mini")
    # effective groq values
    if provider == "groq":
        api_key = groq_key
        model = groq_model
        base_url = settings.groq_base_url
    elif provider == "gemini":
        api_key = gemini_key
        model = gemini_model
        base_url = settings.gemini_base_url or settings.AI_BASE_URL or "https://generativelanguage.googleapis.com/v1beta/models"
    else:
        base_url_default = "http://localhost:11434" if provider=="ollama" else "https://api.openai.com/v1/chat/completions"
        base_url = settings.AI_BASE_URL or base_url_default
        if provider == "groq":
            base_url = settings.groq_base_url
    if provider == "gemini" and settings.gemini_base_url:
        base_url = settings.gemini_base_url
    configured = False
    mode = "Deterministic Analysis"
    status = "not_configured"
    groq_configured = bool(groq_key and groq_key.strip())
    groq_fallback_configured = bool(groq_fallback_key and groq_fallback_key.strip()) or (groq_fallback_model and groq_fallback_model.strip() and groq_configured)
    message = "AI provider not configured — using deterministic analysis (MockProvider). All SQL generation is local and heuristic-based."
    # determine configured
    if provider == "openai":
        if api_key and api_key.strip():
            configured = True
            mode = "LLM-powered"
            status = "configured"
            message = f"OpenAI LLM provider configured (model {model}). Schema + execution results will be sent to external LLM for explanations."
        else:
            configured = False
            mode = "Deterministic Analysis"
            status = "missing_key"
            message = "AI_PROVIDER is set to 'openai' but AI_API_KEY is missing or invalid. Set AI_API_KEY in .env (e.g., sk-...). Falling back to deterministic analysis."
    elif provider == "groq":
        # Groq primary → Groq fallback → Deterministic
        if groq_key and groq_key.strip():
            configured = True
            mode = "LLM-powered"
            status = "configured"
            fallback_note = f" Groq fallback {'configured' if groq_fallback_configured else 'not configured'} ({groq_fallback_model});"
            message = f"Groq primary ({groq_model}).{fallback_note} Automatic fallback: Groq ({groq_model}) → Groq fallback ({groq_fallback_model}) → Deterministic. Schema + result sample sent for explanations; full raw dataset never sent."
        else:
            configured = False
            mode = "Deterministic Analysis"
            status = "missing_key"
            message = "AI_PROVIDER is set to 'groq' but GROQ_API_KEY is missing. Set GROQ_API_KEY (and optionally GROQ_FALLBACK_API_KEY) in .env. Falling back to deterministic analysis."
            groq_fallback_configured = False
    elif provider == "gemini":
        if gemini_key and gemini_key.strip():
            configured = True
            mode = "LLM-powered"
            status = "configured"
            fallback_note = f" Groq fallback {'configured' if groq_configured else 'not configured'} ({groq_model});" if True else ""
            message = f"Gemini primary ({gemini_model}).{fallback_note} Automatic fallback: Gemini → Groq → Deterministic. Schema + result sample sent for explanations; full raw dataset never sent."
        else:
            configured = False
            mode = "Deterministic Analysis"
            status = "missing_key"
            message = "AI_PROVIDER is set to 'gemini' but GEMINI_API_KEY (or AI_API_KEY) is missing. Set GEMINI_API_KEY in .env. Falling back to deterministic analysis."
            groq_configured = False
    elif provider == "ollama":
        configured = True
        mode = "LLM-powered (local)"
        status = "configured"
        message = f"Ollama local provider configured (model {model}, base {base_url}). No external cloud call; runs locally. Failures fall back to deterministic."
    elif provider == "mock":
        configured = False
        mode = "Deterministic Analysis"
        status = "deterministic"
        groq_configured = False
        groq_fallback_configured = False
        message = "Running in deterministic mode (MockProvider). No external API call is made; SQL is generated locally from schema heuristics."
    else:
        configured = bool(api_key)
        mode = "LLM-powered" if configured else "Deterministic Analysis"
        status = "configured" if configured else "not_configured"
        message = f"Provider '{provider}' — {'configured' if configured else 'not configured'}."
    return {
        "provider": provider,
        "model": model,
        "base_url": base_url if provider in ("openai","gemini","ollama","groq") else None,
        "configured": configured,
        "mode": mode,
        "status": status,
        "message": message,
        # Groq primary/fallback info — informational, no key exposure
        "groq_configured": groq_configured,
        "groq_model": groq_model if groq_configured else None,
        "groq_fallback_configured": groq_fallback_configured,
        "groq_fallback_model": groq_fallback_model if groq_fallback_configured else None,
        "fallback_enabled": True,
        "fallback_chain": ["groq", "groq_fallback", "deterministic"] if provider == "groq" else ["gemini", "groq", "deterministic"],
        # never expose key
        "key_present": bool(api_key),
        "key_preview": (api_key[:4] + "…"+ api_key[-4:] ) if api_key and len(api_key) > 8 else None
    }

@router.get("/status")
def ai_status(current_user: User = Depends(get_current_user)):
    return get_status_payload()

@router.post("/test")
async def ai_test(current_user: User = Depends(get_current_user)):
    st = get_status_payload()
    provider = st["provider"]
    if provider == "mock":
        return {"status": "ok", "mode": "deterministic", "message": "Deterministic mode — no external test needed. MockProvider generates SQL locally.", "provider_status": st}
    if provider == "groq":
        # Test Groq primary (and implicitly fallback)
        api_key = settings.groq_api_key or ""
        if not api_key or not api_key.strip():
            raise HTTPException(status_code=400, detail="GROQ_API_KEY is missing. Add GROQ_API_KEY (and GROQ_FALLBACK_API_KEY) to .env when AI_PROVIDER=groq.")
        model = settings.groq_model or "llama-3.3-70b-versatile"
        fallback_model = settings.groq_fallback_model or "qwen/qwen3-32b"
        base_url = settings.groq_base_url or "https://api.groq.com/openai/v1/chat/completions"
        headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
        payload = {"model": model, "messages": [{"role": "user", "content": "Reply with JSON: {\"ok\": true}"}], "max_tokens": 10, "temperature": 0}
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.post(base_url, headers=headers, json=payload)
                if resp.status_code == 200:
                    return {"status": "ok", "mode": "llm", "message": f"✓ Groq provider connected (model {model}, fallback {fallback_model})", "provider_status": st}
                elif resp.status_code in (401, 403):
                    raise HTTPException(status_code=400, detail=f"Groq authentication failed ({resp.status_code}): check GROQ_API_KEY. Response: {resp.text[:300]}")
                elif resp.status_code == 429:
                    raise HTTPException(status_code=429, detail=f"Groq rate limited ({resp.status_code}). Try fallback {fallback_model} or deterministic. Response: {resp.text[:300]}")
                elif resp.status_code >= 500:
                    raise HTTPException(status_code=502, detail=f"Groq transient failure {resp.status_code}: {resp.text[:300]}")
                else:
                    raise HTTPException(status_code=502, detail=f"Groq provider error {resp.status_code}: {resp.text[:300]}")
        except HTTPException:
            raise
        except Exception as e:
            raise HTTPException(status_code=502, detail=f"Groq connection failed: {str(e)[:400]}")
    if provider == "gemini":
        api_key = settings.gemini_api_key or ""
        if not api_key or not api_key.strip():
            raise HTTPException(status_code=400, detail="GEMINI_API_KEY is missing. Add AI_API_KEY (Gemini API key) to .env when AI_PROVIDER=gemini.")
        model = settings.gemini_model or "gemini-1.5-flash"
        base = settings.gemini_base_url or f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
        url = base if "generateContent" in base else f"{base.rstrip('/')}/v1beta/models/{model}:generateContent"
        sep = "&" if "?" in url else "?"
        url = f"{url}{sep}key={api_key}"
        payload = {"contents": [{"role": "user", "parts": [{"text": "Reply with JSON: {\"ok\": true}"}]}], "generationConfig": {"temperature": 0, "maxOutputTokens": 10}}
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.post(url, headers={"Content-Type": "application/json", "x-goog-api-key": api_key}, json=payload)
                if resp.status_code == 200:
                    return {"status": "ok", "mode": "llm", "message": f"✓ Gemini provider connected (model {model})", "provider_status": st}
                elif resp.status_code in (401, 403):
                    raise HTTPException(status_code=400, detail=f"Gemini authentication failed ({resp.status_code}): check AI_API_KEY. Response: {resp.text[:300]}")
                elif resp.status_code == 429:
                    raise HTTPException(status_code=400, detail=f"Gemini rate limited (429): quota exceeded. Try again later or use deterministic mode. Response: {resp.text[:300]}")
                elif resp.status_code >= 500:
                    raise HTTPException(status_code=502, detail=f"Gemini transient failure {resp.status_code}: {resp.text[:300]}")
                else:
                    raise HTTPException(status_code=502, detail=f"Gemini error {resp.status_code}: {resp.text[:300]}")
        except HTTPException:
            raise
        except Exception as e:
            raise HTTPException(status_code=502, detail=f"Gemini connection failed: {str(e)[:400]}")
    if provider == "ollama":
        base = settings.AI_BASE_URL or "http://localhost:11434"
        url = base.rstrip("/") + "/api/generate" if "api/generate" not in base else base
        model = settings.AI_MODEL or "llama3.1"
        payload = {"model": model, "prompt": "Reply with JSON: {\"ok\": true}", "stream": False, "format": "json"}
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.post(url, json=payload)
                if resp.status_code == 200:
                    return {"status": "ok", "mode": "llm-local", "message": f"✓ Ollama provider connected (model {model}) at {base}", "provider_status": st}
                elif resp.status_code == 429:
                    raise HTTPException(status_code=400, detail=f"Ollama rate limited (429): {resp.text[:300]}")
                elif resp.status_code >= 500:
                    raise HTTPException(status_code=502, detail=f"Ollama transient failure {resp.status_code}")
                else:
                    raise HTTPException(status_code=502, detail=f"Ollama error {resp.status_code}: {resp.text[:300]}")
        except HTTPException:
            raise
        except Exception as e:
            raise HTTPException(status_code=502, detail=f"Ollama connection failed at {base}: {str(e)[:400]}. Ensure Ollama is running.")
    if provider == "openai":
        api_key = settings.AI_API_KEY or ""
        if not api_key or not api_key.strip():
            raise HTTPException(status_code=400, detail="AI_API_KEY is missing. Add AI_API_KEY=sk-... to your .env and restart the backend.")
        # test with minimal request
        model = settings.AI_MODEL or "gpt-4o-mini"
        base_url = settings.AI_BASE_URL or "https://api.openai.com/v1/chat/completions"
        headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
        payload = {
            "model": model,
            "messages": [{"role": "user", "content": "Reply with JSON: {\"ok\": true}"}],
            "max_tokens": 10,
            "temperature": 0
        }
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.post(base_url, headers=headers, json=payload)
                if resp.status_code == 200:
                    return {"status": "ok", "mode": "llm", "message": f"✓ AI provider connected (model {model})", "provider_status": st}
                elif resp.status_code in (401, 403):
                    raise HTTPException(status_code=400, detail=f"AI provider authentication failed ({resp.status_code}): check AI_API_KEY. Response: {resp.text[:300]}")
                elif resp.status_code == 429:
                    raise HTTPException(status_code=429, detail=f"AI provider rate limited ({resp.status_code}): {resp.text[:300]}")
                else:
                    raise HTTPException(status_code=502, detail=f"AI provider error {resp.status_code}: {resp.text[:500]}")
        except HTTPException:
            raise
        except Exception as e:
            raise HTTPException(status_code=502, detail=f"AI provider connection failed: {str(e)[:500]}")
    raise HTTPException(status_code=400, detail=f"Unknown AI_PROVIDER '{provider}'")
