"""CLI reproducible: python -m data_crime_scene --seeds 7 42 2026."""

import argparse
import json
from pathlib import Path

from .cases import CASES
from .experiments import run_experiment


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Ejecuta los tres casos sintéticos sin interfaz ni conexión.")
    parser.add_argument("--seeds", type=int, nargs="+", default=[42], help="Semillas explícitas (por defecto: 42).")
    parser.add_argument("--cases", nargs="+", choices=list(CASES), default=list(CASES), help="Casos a ejecutar; por defecto los tres.")
    parser.add_argument("--output", type=Path, help="Guarda el informe completo JSON; crea el directorio si hace falta.")
    args = parser.parse_args(argv)
    try:
        results = [run_experiment(case_id, seed) for seed in args.seeds for case_id in args.cases]
    except ValueError as exc:
        parser.error(str(exc))
    payload = {"schema_version": "1.0", "experiments": [result.to_dict() for result in results]}
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(payload, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8")
    print("Caso       Semilla  Accuracy incorrecto  Accuracy corregido  Diagnóstico corregido")
    for result in results:
        wrong = result.variants["incorrect"]
        clean = result.variants["correct"]
        print(f"{result.case_id:10s} {result.seed:7d} {wrong.metrics['accuracy']:19.3f} {clean.metrics['accuracy']:19.3f}  "
              f"{'contaminación detectada' if clean.diagnostics['leakage_detected'] else 'sin la fuga estudiada'}")
    if args.output:
        print(f"Informe completo: {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
