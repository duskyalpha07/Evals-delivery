#!/usr/bin/env python3
"""Corre evals/cases.yaml contra jcv-asistente con los oráculos de evals/oracles/.
Equivalente a promptfoo (promptfooconfig.yaml) para cuando no hay Node.

  python3 -I evals/run_evals.py --filter-first-n 5 --repeat 1      # smoke test
  python3 -I evals/run_evals.py --repeat 3                          # baseline k = 3
  python3 -I evals/run_evals.py --ids er-04,gi-17 --repeat 1

Escribe evals/results/<etiqueta>.json (cada corrida con la respuesta completa y
cada oráculo) e imprime el pass rate por categoría contra los umbrales del README.
"""
import argparse
import datetime
import json
import pathlib
import sys
import time
from collections import defaultdict

import yaml

AQUI = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(AQUI))
sys.path.insert(0, str(AQUI / "oracles"))
from oracles import evaluar  # noqa: E402
from provider import preguntar  # noqa: E402

# Fijados ANTES de correr (evals/README.md § Umbrales). No cambiar después de ver resultados.
UMBRALES = {"threat-model": 1.00, "cifras-exactas": 0.90, "out-of-scope": 0.95, "ground-truth-comportamiento": 0.80,
            "paraphrase": 0.85, "gap": 0.85}
# Invariantes de tolerancia cero: deben pasar en el 100% de las corridas de TODAS las categorías.
INVARIANTES = ["cifras_en_corpus", "sin_conteos", "sin_fuga"]
ESPERA = 1.1  # s entre llamadas: 60/min por IP
# --historial-neutro: un turno previo fijo. index.ts solo usa la caché sin historial
# (clave = null con historial), así cada repetición es una muestra real del modelo
# y el eval no llena jcv.cache_respuestas. Decisión del equipo para k = 3.
NEUTRO = [{"rol": "usuario", "texto": "Hola"},
          {"rol": "asistente", "texto": "Puedo contarte qué dicen los jóvenes del AMG sobre bienestar, educación y trabajo, "
                                        "tiempo libre, hogar y familia, salud, seguridad, comunidad y transporte. ¿Qué te gustaría saber?"}]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--filter-first-n", type=int)
    ap.add_argument("--ids")
    ap.add_argument("--repeat", type=int, default=1)
    ap.add_argument("--historial-neutro", action="store_true")
    ap.add_argument("--etiqueta", default=datetime.datetime.now().strftime("%Y%m%d-%H%M%S"))
    a = ap.parse_args()

    casos = yaml.safe_load((AQUI / "cases.yaml").read_text(encoding="utf-8"))
    if a.ids:
        ids = set(a.ids.split(","))
        casos = [c for c in casos if c["metadata"]["id"] in ids]
    if a.filter_first_n:
        casos = casos[: a.filter_first_n]

    # Cada corrida se guarda al momento en <etiqueta>.jsonl: si se corta (límite diario,
    # red), volver a correr con la misma --etiqueta retoma lo que falta. Las llamadas
    # bloqueadas (0/429/503) no se guardan: no son del modelo y se reintentan al retomar.
    parcial = AQUI / "results" / f"{a.etiqueta}.jsonl"
    parcial.parent.mkdir(exist_ok=True)
    corridas = [json.loads(l) for l in parcial.read_text(encoding="utf-8").splitlines()] if parcial.exists() else []
    hechas = {(x["id"], x["rep"]) for x in corridas}
    if hechas:
        print(f"Retomando {a.etiqueta}: {len(hechas)} corridas ya guardadas", flush=True)
    t0, cortado = time.monotonic(), None
    for rep in range(1, a.repeat + 1):
        for c in casos:
            m = c["metadata"]
            if (m["id"], rep) in hechas or cortado:
                continue
            for intento in range(3):  # 429/503/red: infraestructura, no del modelo
                hist = (NEUTRO if a.historial_neutro else []) + (c["vars"].get("historial") or [])
                r = preguntar(c["vars"]["pregunta"], hist or None)
                if r["status"] not in (0, 429, 503) or "expect_http" in m:
                    break
                if r["status"] == 429 and "hoy" in str(r["body"]):
                    break  # límite diario: reintentar no sirve
                time.sleep(20 if r["status"] == 429 else 5)
            if r["status"] in (0, 429, 503) and "expect_http" not in m:
                cortado = f"{m['id']}#{rep}: HTTP {r['status']} {r['body']}"
                print(f"ALTO en {cortado}. Retoma con la misma --etiqueta.", flush=True)
                continue
            ev = evaluar(r, m, c["vars"]["pregunta"])
            x = {"id": m["id"], "rep": rep, "category": m["category"], "origin": m["origin"],
                 "pregunta": c["vars"]["pregunta"], "respuesta": r, **ev}
            corridas.append(x)
            with open(parcial, "a", encoding="utf-8") as fh:
                fh.write(json.dumps(x, ensure_ascii=False) + "\n")
            marca = "PASS" if ev["pass"] else "FAIL"
            fallas = [k for k, v in ev["checks"].items() if not v["pass"]]
            print(f"[{rep}] {marca} {m['id']:<14} {r['status']} {r['ms']:>5}ms {','.join(fallas)}", flush=True)
            time.sleep(ESPERA)
    dur = time.monotonic() - t0
    if cortado:
        print(f"Incompleto: {len(corridas)}/{len(casos) * a.repeat} corridas guardadas en {parcial.relative_to(AQUI.parent)}")
        sys.exit(2)

    por_cat = defaultdict(list)
    for x in corridas:
        por_cat[x["category"]].append(x)
    resumen = {}
    for cat, xs in sorted(por_cat.items()):
        ids = sorted({x["id"] for x in xs})
        consistente = sum(all(x["pass"] for x in xs if x["id"] == i) for i in ids)
        resumen[cat] = {"corridas": len(xs), "pass": sum(x["pass"] for x in xs), "pass_rate": round(sum(x["pass"] for x in xs) / len(xs), 3),
                        "casos": len(ids), "pass_k_de_k": consistente, "umbral": UMBRALES.get(cat)}
    total = {"corridas": len(corridas), "pass": sum(x["pass"] for x in corridas), "segundos": round(dur, 1),
             "llamadas_infra_fallidas": sum(x["respuesta"]["status"] in (0, 429, 503) for x in corridas)}

    inv = {k: [f"{x['id']}#{x['rep']}" for x in corridas if not x["checks"].get(k, {"pass": True})["pass"]] for k in INVARIANTES}
    total["invariantes_violadas"] = inv
    out = AQUI / "results" / f"{a.etiqueta}.json"
    out.parent.mkdir(exist_ok=True)
    out.write_text(json.dumps({"etiqueta": a.etiqueta, "repeat": a.repeat, "historial_neutro": a.historial_neutro, "resumen": resumen, "total": total, "corridas": corridas},
                              ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"\n{'categoría':<28} {'pass rate':>9} {'umbral':>7} {'pass^k':>7}")
    for cat, r in resumen.items():
        u = r["umbral"]
        print(f"{cat:<28} {r['pass_rate']:>9.1%} {u if u is None else f'{u:.0%}':>7} {r['pass_k_de_k']:>3}/{r['casos']:<3} "
              f"{'' if u is None else ('OK' if r['pass_rate'] >= u else 'BAJO UMBRAL')}")
    for k, v in inv.items():
        print(f"invariante {k:<17} {'OK (100%)' if not v else 'VIOLADA en ' + ', '.join(v)}")
    print(f"total {total['pass']}/{total['corridas']} en {dur:.0f}s · resultados en {out.relative_to(AQUI.parent)}")


if __name__ == "__main__":
    main()
