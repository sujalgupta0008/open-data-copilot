"""
Regression: the /python execution sandbox must not be escapable via object
introspection. Before the fix (app/execution/python_exec.py), an authenticated
user could run:

    subs = ().__class__.__base__.__subclasses__()          # -> subprocess.Popen (RCE)
    cw = [x for x in subs if x.__name__ == 'catch_warnings'][0]
    bi = cw()._module.__builtins__
    imp = bi['__im' + 'port__']
    imp('sys').modules['app.core.config'].settings.JWT_SECRET   # exfiltrate JWT secret

The JWT secret signs auth tokens whose `sub` is the user id, so leaking it means
forging a token for ANY user (full account takeover). The GEMINI_API_KEY leaked
the same way. Root cause: a regex denylist + restricted-builtins exec never
checked private/dunder attribute access. Fix: AST pass rejects any attribute whose
name starts with '_' and any dunder name reference, layered on the denylist.
"""
import time
import pytest
from fastapi.testclient import TestClient
from app.main import app
from app.core.database import init_db
from app.core.config import settings
from app.execution.python_exec import execute_python, _ast_safety_error

import pandas as pd

init_db()
client = TestClient(app)

DF = pd.DataFrame({"region": ["A", "A", "B"], "sales": [10, 20, 30]})

# Escapes the AST pass is responsible for: private/dunder attribute access or a
# bare dunder name reference.
AST_ESCAPES = [
    "subs = ().__class__.__base__.__subclasses__()\nresult = {'n': len(subs)}",
    "cw = ().__class__\nresult = {'x': cw}",
    ("subs = ().__class__.__base__.__subclasses__()\n"
     "cw = [x for x in subs if x.__name__ == 'catch_warnings'][0]\n"
     "bi = cw()._module.__builtins__\n"
     "imp = bi['__im' + 'port__']\n"
     "result = {'s': imp('sys').modules['app.core.config'].settings.JWT_SECRET}"),
    "b = pd.read_csv.__globals__['__builtins__']\nresult = {'x': 1}",
    "result = {'b': __builtins__}",
    "f = [c for c in ().__class__.__mro__]\nresult = {'n': len(f)}",
]

# Escapes caught by the regex denylist layer (str.format attribute traversal).
DENYLIST_ESCAPES = [
    "result = {'c': '{0.__class__.__base__}'.format(())}",
]

# The real security invariant: execute_python must refuse ALL of these, whichever
# layer catches them, and never leak a secret.
ESCAPE_SNIPPETS = AST_ESCAPES + DENYLIST_ESCAPES

LEGIT_SNIPPETS = [
    "result = df.describe()\nprint(result)",
    ("result = df.isnull().sum().to_frame('missing_count')\n"
     "result['missing_pct'] = (result['missing_count']/len(df)*100).round(2)\nprint(result)"),
    "result = df.select_dtypes(include='number').corr()\nprint(result)",
    "result = df.groupby('region')['sales'].sum().reset_index()\nprint(result)",
    "result = df[['region']].head()\nprint(result)",
    "result = df['sales'].mean()\nprint(result)",
]


@pytest.mark.parametrize("code", AST_ESCAPES)
def test_ast_blocks_escape_snippets(code):
    assert _ast_safety_error(code) is not None, f"escape not blocked: {code!r}"


@pytest.mark.parametrize("code", LEGIT_SNIPPETS)
def test_ast_allows_legit_snippets(code):
    assert _ast_safety_error(code) is None, f"legit code wrongly blocked: {code!r}"


@pytest.mark.parametrize("code", ESCAPE_SNIPPETS)
def test_execute_python_refuses_escape_and_leaks_no_secret(code):
    res = execute_python(DF, code)
    assert res.get("success") is False, f"escape executed: {code!r} -> {res}"
    blob = str(res)
    assert settings.JWT_SECRET not in blob
    assert (settings.GEMINI_API_KEY or "\x00never\x00") not in blob


def test_execute_python_runs_legit_analytics():
    res = execute_python(DF, "result = df.groupby('region')['sales'].sum().reset_index()\nprint(result)")
    assert res.get("success") is True, res
    assert res.get("row_count") == 2


def test_endpoint_blocks_escape_and_allows_legit():
    email = f"sandbox_{int(time.time()*1000)}@t.com"
    r = client.post("/api/auth/register", json={"email": email, "password": "password123"})
    assert r.status_code == 200, r.text
    h = {"Authorization": f"Bearer {r.json()['access_token']}"}
    files = {"file": ("t.csv", "region,sales\nA,10\nA,20\nB,30\n", "text/csv")}
    ds = client.post("/api/datasets/upload", files=files, headers=h).json()["id"]

    evil = ("subs = ().__class__.__base__.__subclasses__()\n"
            "cw = [x for x in subs if x.__name__ == 'catch_warnings'][0]\n"
            "bi = cw()._module.__builtins__\n"
            "imp = bi['__im' + 'port__']\n"
            "result = {'s': imp('sys').modules['app.core.config'].settings.JWT_SECRET}")
    r = client.post(f"/api/datasets/{ds}/python", json={"code": evil}, headers=h)
    assert r.status_code == 400, r.text
    assert settings.JWT_SECRET not in r.text

    r = client.post(f"/api/datasets/{ds}/python", json={"code": "result = df.groupby('region')['sales'].sum().reset_index()"}, headers=h)
    assert r.status_code == 200, r.text
    assert r.json().get("success") is True
