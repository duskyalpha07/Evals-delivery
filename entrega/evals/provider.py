"""Conector a la Edge Function jcv-asistente (la desplegada en Supabase).

Lo usan promptfoo (providers: file://evals/provider.py -> call_api) y
evals/run_evals.py (preguntar). Lee SUPABASE_URL y SUPABASE_ANON_KEY del entorno
o del .env de la raíz; la anon key es pública (va dentro de la app).

Cada llamada usa un id de dispositivo nuevo (uuid4), como un teléfono distinto:
el límite de 20 por día es por dispositivo; el de la IP (1000/día, 60/min) sigue.
"""
import json
import os
import pathlib
import time
import urllib.error
import urllib.request
import uuid

RAIZ = pathlib.Path(__file__).resolve().parents[1]


def _env() -> dict:
    env = {}
    ruta = RAIZ / ".env"
    if ruta.exists():
        for l in ruta.read_text(encoding="utf-8").splitlines():
            if "=" in l and not l.lstrip().startswith("#"):
                k, v = l.split("=", 1)
                env[k.strip()] = v.strip().strip("'\"")
    env.update({k: v for k, v in os.environ.items() if k.startswith("SUPABASE_") or k.startswith("JCV_")})
    return env


def preguntar(pregunta: str, historial=None, dispositivo: str | None = None, timeout: int = 45) -> dict:
    """POST a jcv-asistente. Regresa {"status", "body", "ms"}; nunca lanza por HTTP 4xx/5xx."""
    env = _env()
    url = env.get("JCV_ASISTENTE_URL") or f"{env['SUPABASE_URL'].rstrip('/')}/functions/v1/jcv-asistente"
    llave = env["SUPABASE_ANON_KEY"]
    cuerpo = {"pregunta": pregunta}
    if historial:
        cuerpo["historial"] = historial
    req = urllib.request.Request(url, data=json.dumps(cuerpo).encode(), method="POST", headers={
        "Authorization": f"Bearer {llave}", "apikey": llave, "Content-Type": "application/json",
        "x-jcv-dispositivo": dispositivo or str(uuid.uuid4())})
    t0 = time.monotonic()
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            status, raw = r.status, r.read()
    except urllib.error.HTTPError as e:
        status, raw = e.code, e.read()
    except (urllib.error.URLError, TimeoutError) as e:
        return {"status": 0, "body": {"error": f"red: {e}"}, "ms": int((time.monotonic() - t0) * 1000)}
    try:
        body = json.loads(raw)
    except ValueError:
        body = {"error": raw.decode("utf-8", "replace")[:300]}
    return {"status": status, "body": body, "ms": int((time.monotonic() - t0) * 1000)}


def call_api(prompt, options, context):
    """Interfaz de proveedor Python de promptfoo."""
    vars_ = (context or {}).get("vars", {})
    r = preguntar(vars_.get("pregunta", prompt), vars_.get("historial"))
    if r["status"] in (0, 429, 503):
        return {"error": f"jcv-asistente {r['status']}: {r['body']}"}
    return {"output": json.dumps(r, ensure_ascii=False)}
