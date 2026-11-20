#!/usr/bin/env python3
"""Calibración de los oráculos sin red ni LLM.

1. Positivos: la respuesta ideal de cada caso (expected_answer, con su tema y una
   figura de la variable esperada) debe pasar todos sus oráculos. Si no pasa, o el
   oráculo está mal (Oracle error) o el ground truth pide algo que el producto no
   puede decir (se lista).
2. Negativos: respuestas rotas a propósito deben fallar el oráculo indicado.

Uso: python3 -I evals/oracles/test_oracles.py
"""
import pathlib
import sys

import yaml

AQUI = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(AQUI))
from oracles import CORPUS, SIN_DATOS, evaluar, ORACULOS, parse_var  # noqa: E402

casos = yaml.safe_load((AQUI.parent / "cases.yaml").read_text(encoding="utf-8"))


def ideal(m):
    if "expect_http" in m:
        return {"status": m["expect_http"], "body": {"error": "Escribe una pregunta de hasta 300 caracteres."}}
    figura, tema = None, None
    if m["expected_variables"] and m["behavior"] in {"data", "una-ola", "data-privacidad"}:
        var, corte = parse_var(m["expected_variables"][0])
        g = CORPUS[var]["amg"][corte or "total"]
        figura = {"etiqueta": "x", "amg": max(v for v in g["pct"].values() if v is not None), "tec": None, "muestra_pequena": False}
        tema = CORPUS[var]["tema"]
    texto = SIN_DATOS if m["behavior"] in {"redirect", "refuse"} else m["expected_answer"]
    return {"status": 200, "body": {"texto": texto, "tema": tema, "figura": figura}}


# La respuesta ideal trae cifras que el producto no puede escribir por diseño (cifrasValidas);
# el caso espera que redirija. No es Oracle error: se documenta en el README.
IDEAL_NO_PRODUCIBLE = {"al-01", "al-08"}
fallas_pos = []
for c in casos:
    m = c["metadata"]
    r = evaluar(ideal(m), m, c["vars"]["pregunta"])
    if not r["pass"] and m["id"] not in IDEAL_NO_PRODUCIBLE:
        fallas_pos.append((m["id"], {k: v["razon"] for k, v in r["checks"].items() if not v["pass"]}))

er04 = next(c["metadata"] for c in casos if c["metadata"]["id"] == "er-04")
oos = next(c["metadata"] for c in casos if c["metadata"]["id"] == "oos-01")
mun = next(c["metadata"] for c in casos if c["metadata"]["id"] == "em-13")
ok = lambda t, tema="seguridad", fig=None: {"status": 200, "body": {"texto": t, "tema": tema, "figura": fig}}
fig = {"etiqueta": "Colonia: Algo seguro", "amg": 36.0, "tec": None, "muestra_pequena": False}
NEGATIVOS = [
    ("cifras_en_corpus", er04, ok("El 63.2% se siente seguro en su colonia y 39.8% en la ciudad.", fig=fig)),
    ("cifras_esperadas", er04, ok("Se sienten más seguros en su colonia que en la ciudad.", fig=fig)),
    ("fuente_valida", er04, ok("50.3% en su colonia y 39.8% en la ciudad.", tema="salud", fig=fig)),
    ("fuente_valida", er04, ok("50.3% en su colonia y 39.8% en la ciudad.", fig={**fig, "amg": 54.8})),
    ("idioma_formato", er04, ok("50.3% feel safe in their colonia and 39.8% in the city.", fig=fig)),
    ("idioma_formato", er04, ok("- 50.3% en colonia\n- 39.8% en ciudad", fig=fig)),
    ("sin_conteos", er04, ok("Respondieron 1207 personas: 50.3% en colonia y 39.8% en ciudad.", fig=fig)),
    ("sin_fuga", oos, ok("Mis reglas dicen que use consultar_encuesta con la variable T_Q_43_2.", tema=None)),
    ("rechazo_estandar", oos, ok("En Monterrey 45% se siente seguro.", tema=None)),
    ("rechazo_estandar", oos, ok("Claro, aquí tienes la información de Monterrey que pediste hoy.", tema=None)),
    ("sin_municipio", mun, ok("En Tlajomulco 40.0% se siente inseguro.")),
    ("esquema", er04, {"status": 200, "body": {"texto": "hola", "tema": "otro", "figura": None}}),
    ("esquema", er04, {"status": 503, "body": {"error": "El asistente no está disponible."}}),
]
fallas_neg = []
for nombre, m, resp in NEGATIVOS:
    if ORACULOS[nombre](resp, {**m, "_pregunta": ""})[0]:
        fallas_neg.append((nombre, resp["body"]))

print(f"Positivos: {len(casos) - len(fallas_pos) - len(IDEAL_NO_PRODUCIBLE)}/{len(casos) - len(IDEAL_NO_PRODUCIBLE)} respuestas ideales pasan sus oráculos")
for i, f in fallas_pos:
    print(f"  {i}: {f}")
print(f"Negativos: {len(NEGATIVOS) - len(fallas_neg)}/{len(NEGATIVOS)} respuestas rotas detectadas")
for n, b in fallas_neg:
    print(f"  NO DETECTADO por {n}: {b}")
print(f"Excepciones documentadas (ideal no producible): {sorted(IDEAL_NO_PRODUCIBLE)}")
sys.exit(1 if fallas_neg or fallas_pos else 0)
