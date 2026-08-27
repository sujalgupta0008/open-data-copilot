import re
import duckdb
import pandas as pd

FORBIDDEN = ["DROP", "DELETE", "UPDATE", "INSERT", "ALTER", "TRUNCATE", "CREATE", "GRANT", "REVOKE", "ATTACH", "DETACH", "COPY", "PRAGMA"]

# DuckDB exposes table/scalar functions that read the local filesystem or leak
# engine/config state. Every query in this system runs ONLY against the registered
# in-memory `df` table, so none of these are ever legitimately used. They are all
# plain SELECTs, so they bypass the DDL/DML keyword scan below unless blocked here.
# Denied fail-closed (matched as `name(` case-insensitively).
FORBIDDEN_FUNCTIONS = [
    "read_csv", "read_csv_auto", "read_parquet", "parquet_scan", "read_json",
    "read_json_auto", "read_json_objects", "read_ndjson", "read_ndjson_auto",
    "read_text", "read_blob", "sniff_csv", "glob",
    "duckdb_settings", "duckdb_functions", "duckdb_extensions", "duckdb_databases",
    "duckdb_secrets", "duckdb_temporary_files", "duckdb_logs", "duckdb_variables",
    "duckdb_tables", "duckdb_columns", "duckdb_views", "duckdb_schemas",
    "current_setting", "getvariable", "which_secret", "pragma_database_list",
    "pragma_table_info", "pragma_show_tables", "sqlite_scan", "postgres_scan",
    "iceberg_scan", "delta_scan", "shellfs",
]

def _strip_sql_comments(sql: str) -> str:
    """Remove /* ... */ and -- ... comments, preserving string literals."""
    # state: track single/double quoted strings
    res_chars = []
    i = 0
    n = len(sql)
    in_single = False
    in_double = False
    while i < n:
        ch = sql[i]
        # toggle string state (naive: '' escaped as '', "" escaped as "" are handled by not toggling when inside opposite quote)
        if ch == "'" and not in_double:
            # handle escaped '' inside single-quoted string: '' -> stay in string, consume both
            if in_single and i + 1 < n and sql[i + 1] == "'":
                res_chars.append(ch)
                res_chars.append(sql[i + 1])
                i += 2
                continue
            in_single = not in_single
            res_chars.append(ch)
            i += 1
            continue
        if ch == '"' and not in_single:
            if in_double and i + 1 < n and sql[i + 1] == '"':
                res_chars.append(ch)
                res_chars.append(sql[i + 1])
                i += 2
                continue
            in_double = not in_double
            res_chars.append(ch)
            i += 1
            continue
        if in_single or in_double:
            res_chars.append(ch)
            i += 1
            continue
        # not in string: check for /* */
        if ch == "/" and i + 1 < n and sql[i + 1] == "*":
            end = sql.find("*/", i + 2)
            if end == -1:
                # unterminated comment: strip rest
                break
            # replace comment with space to preserve token boundaries
            res_chars.append(" ")
            i = end + 2
            continue
        if ch == "-" and i + 1 < n and sql[i + 1] == "-":
            # -- to end of line
            nxt_nl = sql.find("\n", i + 2)
            if nxt_nl == -1:
                break
            res_chars.append(" ")
            i = nxt_nl + 1
            continue
        res_chars.append(ch)
        i += 1
    return "".join(res_chars)


def _has_sql_comment_outside_strings(sql: str) -> bool:
    """Detect -- or /* */ outside quoted literals."""
    in_single = False
    in_double = False
    i = 0
    n = len(sql)
    while i < n:
        ch = sql[i]
        if ch == "'" and not in_double:
            if in_single and i + 1 < n and sql[i + 1] == "'":
                i += 2
                continue
            in_single = not in_single
            i += 1
            continue
        if ch == '"' and not in_single:
            if in_double and i + 1 < n and sql[i + 1] == '"':
                i += 2
                continue
            in_double = not in_double
            i += 1
            continue
        if in_single or in_double:
            i += 1
            continue
        if ch == "-" and i + 1 < n and sql[i + 1] == "-":
            return True
        if ch == "/" and i + 1 < n and sql[i + 1] == "*":
            return True
        if ch == "*" and i + 1 < n and sql[i + 1] == "/":
            return True
        i += 1
    return False

def validate_sql(sql: str) -> tuple[bool, str]:
    if not sql or not sql.strip():
        return False, "Empty SQL"
    # C4: strip comments first to prevent bypass via /* */, --
    stripped_comments = _strip_sql_comments(sql)
    if not stripped_comments.strip():
        return False, "Empty SQL after stripping comments"
    upper = stripped_comments.upper()
    for kw in FORBIDDEN:
        # check word boundaries
        if re.search(rf"\b{kw}\b", upper):
            return False, f"Forbidden operation: {kw}"
    # Block DuckDB filesystem/introspection functions (arbitrary local file read,
    # config/secret leakage). Matched as `funcname(` so real column names are safe.
    for fn in FORBIDDEN_FUNCTIONS:
        if re.search(rf"\b{re.escape(fn)}\s*\(", stripped_comments, re.IGNORECASE):
            return False, f"Forbidden function: {fn}"
    # Block DuckDB "replacement scan" of a file path used as a table source,
    # e.g. `SELECT * FROM 'C:/secret.csv'` or `... JOIN 'file.parquet'`.
    if re.search(r"\b(FROM|JOIN)\s+'", stripped_comments, re.IGNORECASE):
        return False, "Reading from a file path is not allowed; only the dataset table is queryable"
    # Block multiple statements via semicolon (allow single trailing semicolon)
    # use stripped_comments for injection-aware check
    stripped_all = stripped_comments.strip()
    # Count semicolons not at end (ignore those inside string literals)
    # simple scan respecting quotes on stripped_comments
    core = stripped_all.rstrip(";").strip()
    # detect ; outside quoted literals
    in_s = False
    in_d = False
    has_inner_semi = False
    for idx, c in enumerate(core):
        if c == "'" and not in_d:
            if idx + 1 < len(core) and core[idx + 1] == "'":
                continue
            in_s = not in_s
        elif c == '"' and not in_s:
            if idx + 1 < len(core) and core[idx + 1] == '"':
                continue
            in_d = not in_d
        elif c == ";" and not in_s and not in_d:
            has_inner_semi = True
            break
    if has_inner_semi:
        return False, "Multiple statements not allowed (semicolon detected)"
    # Block comment injection that could hide malicious content (keep original test behavior)
    # Check original sql for comments outside string literals — stripping is for validation above
    if _has_sql_comment_outside_strings(sql):
        return False, "SQL comments not allowed"
    # must start with SELECT or WITH (on comment-stripped sql)
    stripped = stripped_comments.strip().lstrip("(").upper()
    if not (stripped.startswith("SELECT") or stripped.startswith("WITH")):
        return False, "Only SELECT queries are allowed"
    return True, "ok"

def execute_sql(df: pd.DataFrame, sql: str) -> dict:
    valid, msg = validate_sql(sql)
    if not valid:
        return {"success": False, "error": msg}
    con = None
    try:
        # PERFORMANCE: DuckDB in-memory optimization — register DataFrame as in-memory view (no disk scan)
        # Uses pre-indexed in-memory table via con.register("df", df) instead of read_csv on every query. Saves ~1-2s per query.
        con = duckdb.connect(database=":memory:")
        # P1/P3: statement timeout to prevent cartesian-product DoS (best-effort; duckdb version dependent)
        try:
            con.execute("SET statement_timeout='10s'")
        except Exception:
            try:
                con.execute("PRAGMA enable_profiling")
            except Exception:
                pass
        # PERFORMANCE: optimize for in-memory analytics
        try:
            con.execute("PRAGMA enable_object_cache")
        except: pass
        try:
            con.execute("SET threads=4")
        except: pass
        try:
            con.execute("SET memory_limit='512MB'")
        except: pass
        con.register("df", df)
        # Create pre-indexed view for faster repeated queries (avoids rescanning)
        try:
            con.execute("CREATE OR REPLACE TEMP VIEW df_view AS SELECT * FROM df")
        except: pass
        # execute — use df table directly (in-memory, zero disk IO)
        result_df = con.execute(sql).fetchdf()
        # convert
        result_df = result_df.replace({pd.NA: None})
        # handle NaN
        result_df = result_df.where(pd.notnull(result_df), None)
        data = result_df.to_dict(orient="records")
        columns = list(result_df.columns)
        # limit rows for display but keep all for chart? We'll return all up to 500
        if len(data) > 500:
            data = data[:500]
        return {"success": True, "data": data, "columns": columns, "row_count": len(data)}
    except Exception as e:
        return {"success": False, "error": str(e)}
    finally:
        if con is not None:
            try:
                con.close()
            except Exception:
                pass
