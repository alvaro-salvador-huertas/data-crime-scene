"""Estudio fijo de 90 combinaciones. Importar este módulo nunca lo ejecuta."""

import argparse
from copy import deepcopy
from datetime import datetime, timezone
import json
from pathlib import Path
import time

import numpy as np

from .laboratory import (
    LAB_CASES, SEEDS, STUDY_PROTOCOL, canonical_json, compatible_engine, engine_fingerprint, lab_config,
    protocol_hash, run_lab_experiment, runtime_versions, validate_lab_result,
)


def _manifest():
    return {"schema_version": "lab-study/1", "created_at": datetime.now(timezone.utc).isoformat(),
            "engine_fingerprint": engine_fingerprint(), "protocol_hash": protocol_hash(),
            "runtime": runtime_versions(), "protocol": deepcopy(STUDY_PROTOCOL)}


def planned_configs():
    return [lab_config(case, seed, level) for case, info in LAB_CASES.items()
            for level in info["levels"] for seed in SEEDS]


def run_preflight():
    """Mide tres combinaciones predefinidas; no elige niveles por puntuación."""
    checks = []
    for case, info in LAB_CASES.items():
        started = time.perf_counter()
        config = lab_config(case, 42, info["levels"][1])
        try:
            run_lab_experiment(case, 42, config["level"])
            check = {"config": config, "status": "ok"}
        except Exception as exc:
            check = {"config": config, "status": "error", "error": {"type": type(exc).__name__, "message": str(exc)}}
        check["seconds"] = time.perf_counter() - started
        checks.append(check)
    estimated = sum(check["seconds"] for check in checks) * 30
    return {**_manifest(), "checks": checks, "estimated_study_seconds": estimated,
            "budget_seconds": STUDY_PROTOCOL["budget_seconds"],
            "within_budget": all(check["status"] == "ok" for check in checks) and estimated <= STUDY_PROTOCOL["budget_seconds"],
            "note": "Estimación de coste, no garantía temporal ni selección según métricas. Matriz máxima: 220×1800 float64."}


def run_study():
    study = {**_manifest(), "entries": []}
    started = time.perf_counter()
    for config in planned_configs():
        entry = {"config": config}
        iteration = time.perf_counter()
        try:
            if time.perf_counter() - started > STUDY_PROTOCOL["budget_seconds"]:
                raise TimeoutError("Presupuesto temporal alcanzado antes de esta ejecución prevista.")
            entry["result"] = run_lab_experiment(config["case_id"], config["seed"], config["level"])
            entry["status"] = "ok"
        except Exception as exc:
            # No se descarta ninguna combinación, ni se reintenta por su puntuación.
            entry["status"] = "error"
            entry["error"] = {"type": type(exc).__name__, "message": str(exc)}
        entry["seconds"] = time.perf_counter() - iteration
        study["entries"].append(entry)
    study["elapsed_seconds"] = time.perf_counter() - started
    return study


def validate_study(study):
    try:
        if (study["schema_version"] != "lab-study/1" or not compatible_engine(study["engine_fingerprint"])
                or study["protocol_hash"] != protocol_hash() or study["runtime"] != runtime_versions()
                or canonical_json(study["protocol"]) != canonical_json(STUDY_PROTOCOL)):
            raise ValueError("Estudio incompatible con el código, protocolo o versiones actuales. Ejecuta el estudio de nuevo.")
        expected = planned_configs()
        entries = study["entries"]
        if len(entries) != len(expected) or [entry["config"] for entry in entries] != expected:
            raise ValueError("El estudio no contiene exactamente las 90 combinaciones previstas, en el orden declarado.")
        for entry in entries:
            if entry["status"] == "ok":
                config = entry["config"]
                validate_lab_result(entry["result"], config["case_id"], config["seed"], config["level"])
            elif entry["status"] == "error":
                if "result" in entry or not isinstance(entry["error"]["message"], str) or not isinstance(entry["error"]["type"], str):
                    raise ValueError("Registro de error incoherente.")
            else:
                raise ValueError("Estado desconocido; los errores no son puntuaciones válidas.")
    except (KeyError, TypeError, AttributeError, IndexError) as exc:
        raise ValueError("Estudio incompleto o mal formado.") from exc


def load_study(path):
    path = Path(path)
    try:
        study = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ValueError(f"No se puede leer {path}. Genera primero el estudio mediante el comando indicado.") from exc
    validate_study(study)
    return study


def study_rows(study, case_id):
    """Cada fila es una métrica de una semilla, nunca una observación sintética."""
    rows = []
    for entry in study["entries"]:
        if entry["status"] != "ok" or entry["config"]["case_id"] != case_id:
            continue
        config, result = entry["config"], entry["result"]
        for key, variant in result["variants"].items():
            base = {"case_id": case_id, "seed": config["seed"], "level": config["level"], "variant": key,
                    "evaluation": "internal", "train_size": variant["train_size"], "test_size": variant["test_size"]}
            rows.append({**base, **variant["metrics"]})
            if case_id == "selection" and key == "correct":
                rows.append({**base, "variant": "baseline", **variant["baseline_metrics"]})
            if case_id == "groups":
                evaluation = result["cohort"][key]
                rows.append({**base, "evaluation": "cohort", "test_size": evaluation["n_samples"], **evaluation["metrics"]})
    return rows


def paired_differences(study, case_id):
    rows = []
    metric = STUDY_PROTOCOL["primary_metric"]
    for entry in study["entries"]:
        if entry["status"] != "ok" or entry["config"]["case_id"] != case_id:
            continue
        result, config = entry["result"], entry["config"]
        variants = result["cohort"] if case_id == "groups" else result["variants"]
        left, right = variants["incorrect"], variants["correct"]
        ids_key = "row_ids" if case_id == "groups" else "test_row_ids"
        if left[ids_key] != right[ids_key] or left["y_true"] != right["y_true"]:
            raise ValueError("No se pueden emparejar métricas sobre filas o etiquetas diferentes.")
        base = {"seed": config["seed"], "level": config["level"], "evaluation": "cohort" if case_id == "groups" else "internal"}
        label = {"future": "Posterior − legítimas", "groups": "Filas − grupos · cohorte común", "selection": "Global − train"}[case_id]
        rows.append({**base, "comparison": label, "delta": left["metrics"][metric] - right["metrics"][metric]})
        if case_id == "future":
            control = variants["control"]
            if control[ids_key] != right[ids_key] or control["y_true"] != right["y_true"]:
                raise ValueError("Control no emparejado.")
            rows.append({**base, "comparison": "Control − legítimas", "delta": control["metrics"][metric] - right["metrics"][metric]})
        elif case_id == "selection":
            rows.append({**base, "comparison": "Train − baseline", "delta": right["metrics"][metric] - right["baseline_metrics"][metric]})
    return rows


def summarize(study):
    rows = [row for case in LAB_CASES for row in study_rows(study, case)]
    groups = {}
    for row in rows:
        key = row["case_id"], row["level"], row["variant"], row["evaluation"]
        groups.setdefault(key, []).append(row["balanced_accuracy"])
    return [{"case_id": key[0], "level": key[1], "variant": key[2], "evaluation": key[3], "n_seeds": len(scores),
             "median": float(np.median(scores)), "q1": float(np.quantile(scores, 0.25)), "q3": float(np.quantile(scores, 0.75))}
            for key, scores in groups.items()]


def main(argv=None):
    parser = argparse.ArgumentParser(description="Estudio predefinido local: 3 casos × 3 niveles × 10 semillas.")
    parser.add_argument("--preflight", action="store_true", help="Mide solo tres combinaciones predefinidas antes del estudio.")
    parser.add_argument("--output", type=Path, help="Ruta JSON. Por defecto artifacts/laboratory-study.json o artifacts/lab-preflight.json.")
    args = parser.parse_args(argv)
    output = args.output or Path("artifacts/lab-preflight.json" if args.preflight else "artifacts/laboratory-study.json")
    value = run_preflight() if args.preflight else run_study()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8")
    if args.preflight:
        print(json.dumps({"checks": value["checks"], "estimated_study_seconds": value["estimated_study_seconds"],
                          "within_budget": value["within_budget"]}, ensure_ascii=False, indent=2))
        return 0 if value["within_budget"] else 1
    successes = sum(entry["status"] == "ok" for entry in value["entries"])
    print(f"{successes}/90 válidas; {90 - successes} errores registrados; {value['elapsed_seconds']:.2f} s. {output}")
    for row in summarize(value):
        print(f"{row['case_id']:9s} {str(row['level']):>5s} {row['variant']:9s} {row['evaluation']:8s} "
              f"n={row['n_seeds']:2d} balanced_accuracy mediana={row['median']:.3f} Q1={row['q1']:.3f} Q3={row['q3']:.3f}")
    return 0 if successes == 90 else 1


if __name__ == "__main__":
    raise SystemExit(main())
