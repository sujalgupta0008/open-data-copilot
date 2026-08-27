import pandas as pd
import numpy as np
import ast
import io
import traceback
import math
import re
import statistics
import builtins as _builtins_mod
from collections import Counter
from contextlib import redirect_stdout, redirect_stderr

ALLOWED_IMPORTS = {"pandas", "numpy", "math", "re", "datetime", "json", "collections", "statistics"}


def _ast_safety_error(code: str):
    """
    Static defense against in-process sandbox escapes.

    The restricted-builtins exec below is NOT a real sandbox on its own: every
    known escape (``().__class__.__base__.__subclasses__()`` -> subprocess.Popen,
    ``<fn>.__globals__['__builtins__']`` / ``catch_warnings()._module.__builtins__``
    -> real ``__import__`` -> read process secrets) works purely by traversing
    private/dunder attributes of live objects. Legitimate pandas/numpy analytics
    never needs those. So we parse the code and reject ANY access to an attribute
    whose name starts with ``_`` (blocks ``__class__``, ``__globals__``,
    ``__subclasses__``, ``__builtins__``, ``_module``, ``__init__`` ...) and any
    bare dunder name reference. This closes the escape without changing the
    execution model. Returns an error string, or None if the code is acceptable.
    """
    try:
        tree = ast.parse(code, mode="exec")
    except SyntaxError as e:
        return f"Syntax error in code: {e.msg}"
    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute):
            if node.attr.startswith("_"):
                return (
                    f"Access to private attribute '.{node.attr}' is not allowed. "
                    "Python execution is limited to pandas/numpy analytics on the "
                    "preloaded DataFrame 'df'; introspection of internals is blocked."
                )
        elif isinstance(node, ast.Name):
            if node.id.startswith("__"):
                return (
                    f"Use of the reserved name '{node.id}' is not allowed. "
                    "Python execution is limited to pandas/numpy analytics."
                )
    return None

def execute_python(df: pd.DataFrame, code: str, timeout: int=10) -> dict:
    """
    Production sandbox review:
    - Local/demo execution: in-process exec with restricted globals, pattern block, no network/fs.
    - Production-safe: should run in isolated container / gVisor / WASM with CPU/mem/time limits, no host fs, no secrets. Current in-process sandbox is for demo; for prod, replace with containerized execution (see docs).
    Limits: code ≤ 5k chars, df limited copy, timeout 10s, output ≤ 500 rows, no imports beyond pandas/numpy.
    """
    if len(code) > 5000:
        return {"success": False, "error": "Code too large (max 5000 chars). Simplify your analysis."}
    if len(df) > 200000:
        return {"success": False, "error": "Dataset too large for in-process Python execution (max 200k rows). Use SQL instead."}
    # Basic sandbox: restrict builtins and check for dangerous operations
    dangerous = [
        r"os\.", r"sys\.", r"subprocess", r"open\s*\(", r"eval\s*\(", r"exec\s*\(", r"__import__", r"socket", r"requests", r"urllib", r"http\.", r"pathlib", r"shutil", r"glob", r"pickle", r"marshal", r"import\s+os", r"import\s+sys", r"from\s+os", r"from\s+sys", r"\.to_csv", r"\.to_excel", r"\.to_parquet", r"to_pickle", r"to_json\s*\(",
        # str.format attribute traversal, e.g. "{0.__class__.__base__}".format(())
        r"\{[^{}]*\.\s*_",
    ]
    # BUG1 FIX: Pre-inject safe imports via preamble, keep matplotlib blocked, handle numpy
    # Replace matplotlib code with print placeholder (no display server)
    if re.search(r"matplotlib", code, re.IGNORECASE) or re.search(r"\bplt\.", code):
        lines = code.split("\n")
        new_lines = []
        for _line in lines:
            if re.search(r"matplotlib", _line, re.IGNORECASE) or re.search(r"\bplt\.", _line):
                new_lines.append('print("Chart generation skipped in sandbox")')
            else:
                new_lines.append(_line)
        code = "\n".join(new_lines)

    for pat in dangerous:
        if re.search(pat, code):
            return {"success": False, "error": f"Forbidden pattern blocked for safety: {pat}. Python execution is limited to pandas/numpy analytics; no file/network access."}
    # AST-level defense against introspection-based sandbox escapes (see _ast_safety_error).
    ast_err = _ast_safety_error(code)
    if ast_err:
        return {"success": False, "error": ast_err}
    # Safe __import__ that only allows pre-approved modules (BUG1: fixes __import__ not found while keeping sandbox)
    _original_import = _builtins_mod.__import__
    def _safe_import(name, globals=None, locals=None, fromlist=(), level=0):
        base = (name or "").split(".")[0]
        allowed = {"re", "math", "collections", "statistics", "numpy", "pandas", "datetime", "json", "io"}
        # include ALLOWED_IMPORTS as allowed bases
        if base not in allowed and base not in ALLOWED_IMPORTS:
            raise ImportError(f"Import of '{name}' is not allowed in sandbox")
        return _original_import(name, globals, locals, fromlist, level)

    # Create limited globals — include safe __import__ for preamble/user imports
    restricted_builtins = {"len": len, "range": range, "enumerate": enumerate, "str": str, "int": int, "float": float, "list": list, "dict": dict, "set": set, "sum": sum, "min": min, "max": max, "abs": abs, "round": round, "sorted": sorted, "print": print, "__import__": _safe_import}
    # Pre-inject safe modules so user code can use re/math/Counter/statistics without explicit import
    local_vars = {"df": df.copy(), "pd": pd, "np": np, "pandas": pd, "numpy": np, "re": re, "math": math, "Counter": Counter, "statistics": statistics, "collections": __import__("collections")}
    # BUG1: preamble with safe imports (not part of user code) — numpy injected if available else skipped
    _preamble = "import re\nimport math\nfrom collections import Counter\nimport statistics\n"
    # numpy preamble: inject if available else skip (already in local_vars as np)
    try:
        import numpy as _np_check  # noqa: F401
        _preamble += "import numpy as np\n"
    except Exception:
        pass
    # Execute preamble + user code together; preamble populates same local_vars scope
    code = _preamble + "\n" + code
    stdout = io.StringIO()
    stderr = io.StringIO()
    def _run():
        with redirect_stdout(stdout), redirect_stderr(stderr):
            exec(code, {"__builtins__": restricted_builtins, "pd": pd, "np": np, "re": re, "math": math, "Counter": Counter, "statistics": statistics}, local_vars)
    try:
        # Timeout via thread (works on Windows + Unix) — hardened: cancel orphan thread on timeout to prevent resource leak
        import concurrent.futures
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
            fut = executor.submit(_run)
            try:
                fut.result(timeout=timeout)
            except concurrent.futures.TimeoutError:
                try:
                    fut.cancel()
                except Exception:
                    pass
                try:
                    executor.shutdown(wait=False, cancel_futures=True)
                except TypeError:
                    # Python <3.9 fallback: shutdown without cancel_futures
                    try:
                        executor.shutdown(wait=False)
                    except Exception:
                        pass
                return {"success": False, "error": f"Python execution timed out after {timeout}s. Simplify the code or use SQL for large aggregations."}
        output = stdout.getvalue() + stderr.getvalue()
        # Try to capture result variable if defined
        result_data = None
        columns = None
        # If 'result' in local_vars
        if "result" in local_vars:
            res = local_vars["result"]
            if isinstance(res, pd.DataFrame):
                # clean
                res = res.where(pd.notnull(res), None)
                # if index is not default, reset
                if not isinstance(res.index, pd.RangeIndex):
                    res = res.reset_index()
                data = res.head(500).to_dict(orient="records")
                return {"success": True, "data": data, "columns": list(res.columns), "row_count": len(data), "output": output}
            elif isinstance(res, pd.Series):
                res_df = res.to_frame().reset_index()
                data = res_df.head(500).to_dict(orient="records")
                return {"success": True, "data": data, "columns": list(res_df.columns), "row_count": len(data), "output": output}
            elif isinstance(res, (list, dict)):
                return {"success": True, "data": res, "columns": None, "row_count": 1 if isinstance(res, dict) else len(res), "output": output}
            else:
                return {"success": True, "data": [{"value": str(res)}], "columns": ["value"], "output": output}
        # If no result but stdout has content, try to parse
        if output.strip():
            return {"success": True, "data": [{"output": line} for line in output.strip().split("\n")[:50]], "columns": ["output"], "output": output}
        return {"success": True, "data": [], "columns": [], "output": output or "No output"}
    except Exception as e:
        tb = traceback.format_exc()
        return {"success": False, "error": str(e), "traceback": tb, "output": stdout.getvalue()}
