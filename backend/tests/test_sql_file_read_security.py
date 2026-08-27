"""
Regression: DuckDB filesystem/introspection functions and file-path replacement
scans must never pass validate_sql (P0 arbitrary local file read / secret leak).

Root cause fixed in app/execution/sql.py::validate_sql — the validator previously
only blocked DDL/DML keywords and required a leading SELECT/WITH, so read_text(),
read_csv_auto(), read_blob(), sniff_csv(), glob(), duckdb_settings(), and the
`FROM '<path>'` replacement scan (all plain SELECTs) bypassed it and could read
.env / arbitrary files through the authenticated /query endpoint.
"""
import time
import pandas as pd
from fastapi.testclient import TestClient
from app.main import app
from app.core.database import init_db
from app.execution.sql import validate_sql, execute_sql

init_db()
client = TestClient(app)

ATTACKS = [
    "SELECT * FROM read_csv_auto('/etc/passwd')",
    "SELECT * FROM read_csv('/etc/passwd')",
    "SELECT content FROM read_text('.env')",
    "SELECT * FROM read_blob('.env')",
    "SELECT * FROM read_parquet('secret.parquet')",
    "SELECT * FROM parquet_scan('secret.parquet')",
    "SELECT * FROM read_json_auto('secret.json')",
    "SELECT * FROM sniff_csv('.env')",
    "SELECT * FROM glob('/*')",
    "SELECT * FROM duckdb_settings()",
    "SELECT current_setting('temp_directory')",
    # case-insensitive
    "SELECT content FROM ReAd_TeXt('.env')",
    # whitespace between name and paren
    "SELECT content FROM read_text\t('.env')",
    # nested subquery
    "SELECT (SELECT content FROM read_text('.env')) AS x",
    # CTE
    "WITH x AS (SELECT * FROM read_csv_auto('.env')) SELECT * FROM x",
    # replacement scan of a file path used as a table
    "SELECT * FROM '.env'",
    "SELECT * FROM 'C:/Windows/System32/drivers/etc/hosts'",
    "SELECT * FROM df JOIN '/etc/passwd' ON 1=1",
]

# Queries that must keep working — including value filters that contain words
# appearing in the forbidden list, and CTEs/aliases.
LEGIT = [
    "SELECT * FROM df",
    "SELECT status, COUNT(*) AS n FROM df GROUP BY status",
    "SELECT * FROM df WHERE status = 'set'",
    "SELECT * FROM df WHERE status = 'load'",
    "SELECT * FROM df WHERE note = 'please read_csv the docs'",
    "WITH t AS (SELECT category, revenue FROM df) SELECT * FROM t ORDER BY revenue DESC",
    "SELECT SUM(CASE WHEN status='set' THEN 1 ELSE 0 END)*100.0/COUNT(*) AS rate FROM df",
    "SELECT category AS asset_value FROM df",
]


def test_validate_sql_blocks_file_functions_and_replacement_scan():
    for sql in ATTACKS:
        ok, msg = validate_sql(sql)
        assert not ok, f"SECURITY: file-read SQL passed validation: {sql!r}"


def test_execute_sql_never_leaks_files():
    df = pd.DataFrame({
        "category": ["A", "B", "A"],
        "revenue": [100, 200, 150],
        "status": ["set", "load", "open"],
        "note": ["x", "y", "please read_csv the docs"],
    })
    for sql in ATTACKS:
        res = execute_sql(df, sql)
        assert res.get("success") is False, f"SECURITY: leaked via {sql!r}: {res.get('data')}"


def test_legitimate_queries_still_pass():
    df = pd.DataFrame({
        "category": ["A", "B", "A"],
        "revenue": [100, 200, 150],
        "status": ["set", "load", "open"],
        "note": ["x", "y", "please read_csv the docs"],
    })
    for sql in LEGIT:
        ok, msg = validate_sql(sql)
        assert ok, f"Legitimate query wrongly blocked: {sql!r} -> {msg}"
        res = execute_sql(df, sql)
        assert res.get("success") is True, f"Legitimate query failed to execute: {sql!r} -> {res.get('error')}"


def test_query_endpoint_rejects_file_read_e2e():
    email = f"sqlsec_{int(time.time()*1000)}@test.com"
    r = client.post("/api/auth/register", json={"email": email, "password": "password123"})
    assert r.status_code == 200, r.text
    token = r.json()["access_token"]
    h = {"Authorization": f"Bearer {token}"}
    csv_data = "col1,col2\n1,hello\n2,world\n"
    files = {"file": ("t.csv", csv_data, "text/csv")}
    r = client.post("/api/datasets/upload", files=files, headers=h)
    assert r.status_code == 200, r.text
    ds_id = r.json()["id"]

    # Attempt to read the server's .env through the raw-SQL query endpoint.
    r = client.post(f"/api/datasets/{ds_id}/query", headers=h,
                    json={"sql": "SELECT content FROM read_text('.env')"})
    assert r.status_code == 400, f"Expected 400, got {r.status_code}: {r.text}"
    assert "JWT_SECRET" not in r.text and "API_KEY" not in r.text

    # Replacement scan variant.
    r = client.post(f"/api/datasets/{ds_id}/query", headers=h,
                    json={"sql": "SELECT * FROM '.env'"})
    assert r.status_code == 400, f"Expected 400, got {r.status_code}: {r.text}"

    # A normal query on the dataset still works.
    r = client.post(f"/api/datasets/{ds_id}/query", headers=h,
                    json={"sql": "SELECT col1, col2 FROM df ORDER BY col1"})
    assert r.status_code == 200, r.text
    assert r.json()["row_count"] == 2
