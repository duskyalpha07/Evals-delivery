"""Assertion Python de promptfoo: corre los oráculos deterministas del caso."""
import json
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from oracles import evaluar  # noqa: E402


def get_assert(output, context):
    resp = json.loads(output) if isinstance(output, str) else output
    meta = (context.get("test") or {}).get("metadata") or {}
    r = evaluar(resp, meta, (context.get("vars") or {}).get("pregunta", ""))
    return {
        "pass": r["pass"],
        "score": sum(c["pass"] for c in r["checks"].values()) / max(1, len(r["checks"])),
        "reason": "; ".join(f"{k}: {c['razon']}" for k, c in r["checks"].items() if not c["pass"]) or "todos los oráculos pasan",
        "componentResults": [{"pass": c["pass"], "score": float(c["pass"]), "reason": f"{k}: {c['razon']}"} for k, c in r["checks"].items()],
    }
