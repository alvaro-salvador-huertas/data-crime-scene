"""Experimentos controlados del laboratorio, sin Streamlit ni ejecución al importar."""

from copy import deepcopy
from dataclasses import asdict
import hashlib
import json
from pathlib import Path
import platform

import numpy as np
import pandas as pd
import sklearn
from sklearn.metrics import confusion_matrix
from sklearn.model_selection import GroupShuffleSplit, train_test_split
from sklearn.neighbors import KNeighborsClassifier
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler

from .experiments import (
    _logistic, _preview, _selection, _stage, _variant, classification_metrics,
    future_feature_diagnostic, group_diagnostic,
)
from .generators import generate_future, generate_groups, generate_selection_nested, validate_seed
from .validation import assert_training_scope, validate_prediction_dict, validate_rows


LAB_VERSION = "lab-v1"
# Reviewed predecessor: only validation/compatibility changed, not the experiment.
# Keep its provenance intact and run ALL current checks on imported reports.
# Reassess this compatibility if data, fitting, metrics or protocol change.
COMPATIBLE_HISTORICAL_ENGINES = ("ec9f68561a319618c8f301b2462be4f7166704afcb69bc24996d4cff96d0b28e",)
LAB_CASES = {
    "future": {
        "factor": "refund_flip_probability", "label": "Probabilidad de invertir la señal posterior",
        "levels": (0.0, 0.25, 0.5),
        "description": "Ruido binario simétrico aplicado al desenlace para crear una señal posterior; no es un porcentaje de fuga.",
        "expectation": "Hipótesis didáctica: al aumentar el ruido suele disminuir la ventaja predictiva de la columna posterior.",
        "caveat": "Con ruido 0,5 no hay información sobre la etiqueta por construcción, pero la columna sigue sin existir al comprar. El control independiente no iguala todas las propiedades de la señal posterior.",
    },
    "groups": {
        "factor": "measurement_noise_std", "label": "Desviación típica del ruido entre mediciones",
        "levels": (0.035, 0.35, 1.0),
        "description": "Mismas 90 máquinas, seis mediciones y ocho sensores: cambia la dispersión alrededor de la huella de cada máquina.",
        "expectation": "Hipótesis didáctica: perfiles menos parecidos pueden dificultar el reconocimiento de máquinas conocidas.",
        "caveat": "El objetivo es generalizar a máquinas nuevas. Los tests internos no están emparejados. Los modelos también entrenan con distinta composición de máquinas; ni la cohorte común aísla un efecto causal puro de la fuga.",
    },
    "selection": {
        "factor": "n_features", "label": "Número de variables irrelevantes",
        "levels": (50, 500, 1800),
        "description": "Etiquetas independientes del ruido por construcción. Las etiquetas y columnas compartidas permanecen idénticas entre niveles; k=25 está fijado antes de evaluar.",
        "expectation": "Hipótesis didáctica: buscar entre más columnas puede encontrar más asociaciones accidentales con las etiquetas de evaluación.",
        "caveat": "No hay señal predictiva real. Un resultado limpio superior o inferior al azar en una semilla es posible. El Pipeline solo corrige este ajuste si recibe exclusivamente train.",
    },
}
SEEDS = (7, 42, 2026, 11, 23, 101, 314, 1234, 4096, 65535)
STUDY_PROTOCOL = {
    "version": LAB_VERSION, "seeds": list(SEEDS),
    "levels": {case: list(info["levels"]) for case, info in LAB_CASES.items()},
    "primary_metric": "balanced_accuracy", "secondary_metrics": ["accuracy", "f1"],
    "cases": json.loads(json.dumps(LAB_CASES)),
    "constants": {"future_n_samples": 600, "group_n_entities": 90, "group_observations_per_entity": 6,
                  "cohort_n_entities": 30, "selection_n_samples": 220, "selector_k": 25,
                  "test_fraction": 0.3, "logistic_C": 1.0, "logistic_solver": "liblinear",
                  "logistic_max_iter": 1000, "knn_neighbors": 1},
    "summary": "Un punto por semilla; mediana y cuartiles lineales. IQR no es un intervalo de confianza.",
    "budget_seconds": 180, "planned_combinations": 90,
    "paired": {"future": "Mismas filas y etiquetas internas", "selection": "Mismas filas y etiquetas internas",
               "groups": "Solo cohorte común; diferentes entrenamientos, no efecto causal aislado"},
}


def canonical_json(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def protocol_hash():
    return hashlib.sha256(canonical_json(STUDY_PROTOCOL).encode()).hexdigest()


def engine_fingerprint():
    """Incluye código que afecta datos, entrenamiento, validación o protocolo; no CSS/docs."""
    digest = hashlib.sha256()
    for name in ("generators.py", "experiments.py", "results.py", "validation.py", "laboratory.py", "study.py"):
        digest.update(name.encode())
        digest.update(Path(__file__).with_name(name).read_bytes())
    return digest.hexdigest()


def runtime_versions():
    return {"python": platform.python_version(), "numpy": np.__version__, "pandas": pd.__version__, "scikit_learn": sklearn.__version__}


def compatible_engine(fingerprint):
    """Accept the current source or the explicitly reviewed historical engine."""
    return fingerprint in (engine_fingerprint(), *COMPATIBLE_HISTORICAL_ENGINES)


def lab_config(case_id, seed, level):
    if not isinstance(case_id, str) or case_id not in LAB_CASES:
        raise ValueError("Caso de laboratorio desconocido.")
    seed = validate_seed(seed)
    if isinstance(level, bool) or not isinstance(level, (int, float)) or level not in LAB_CASES[case_id]["levels"]:
        raise ValueError("Nivel incompatible con el protocolo de laboratorio.")
    level = int(level) if case_id == "selection" else float(level)
    return {"case_id": case_id, "seed": seed, "factor": LAB_CASES[case_id]["factor"], "level": level, "protocol_version": LAB_VERSION}


def generate_lab_data(case_id, seed, level):
    """Sin entrenamiento. Flujos y datos comunes permiten comprobar los emparejamientos."""
    config = lab_config(case_id, seed, level)
    if case_id == "future":
        data = generate_future(seed, refund_flip_probability=level)
        control_rng = np.random.default_rng(np.random.SeedSequence([seed, 151]))
        data.X["control_irrelevante"] = control_rng.binomial(1, 0.5, len(data.X))
        data.params["control_distribution"] = "Bernoulli(0.5), flujo SeedSequence([seed,151]), independiente"
        return data, None
    if case_id == "selection":
        return generate_selection_nested(seed, n_features=config["level"]), None
    data = generate_groups(seed, measurement_noise_std=level)
    cohort_seed = int(np.random.SeedSequence([seed, 997]).generate_state(1)[0])
    cohort = generate_groups(cohort_seed, n_entities=30, measurement_noise_std=level)
    index = pd.Index([f"cohorte_{value}" for value in cohort.X.index], name="fila_id")
    cohort.X.index, cohort.y.index, cohort.groups.index = index, index, index
    cohort.groups = "cohorte_" + cohort.groups
    data.params["cohort"] = {**cohort.params, "seed": cohort_seed, "rng_stream": "SeedSequence([seed,997]).generate_state(1)"}
    return data, cohort


def class_distribution(y):
    values = np.asarray(y)
    return {"count0": int((values == 0).sum()), "count1": int((values == 1).sum()),
            "positive_rate": float((values == 1).mean())}


def _serialize_variant(variant, data):
    payload = asdict(variant)
    payload["train_size"], payload["test_size"] = len(variant.train_row_ids), len(variant.test_row_ids)
    payload["diagnostics"]["class_distribution"] = {
        "train": class_distribution(data.y.loc[variant.train_row_ids]),
        "test": class_distribution(data.y.loc[variant.test_row_ids]),
    }
    return payload


def _future_lab(data, seed):
    train, test = train_test_split(np.arange(len(data.X)), test_size=0.3, stratify=data.y, random_state=seed)
    legitimate = ["importe", "producto_fragil", "cliente_nuevo"]
    variants = {}
    for key, extra in (("correct", []), ("incorrect", ["reembolso_tramitado"]), ("control", ["control_irrelevante"])):
        features = legitimate + extra
        model = Pipeline([("scaler", StandardScaler()), ("classifier", _logistic(seed))])
        model.fit(data.X.iloc[train][features], data.y.iloc[train])
        pred = model.predict(data.X.iloc[test][features])
        variant = _variant(data, key, "Filas estratificadas 70/30 · emparejadas", train, test, features,
                           model.named_steps["classifier"], pred, future_feature_diagnostic(features),
                           [_stage("StandardScaler", data.X.index[train]), _stage("LogisticRegression", data.X.index[train])])
        variant.model["preprocessing"] = {"type": "StandardScaler", "params": model.named_steps["scaler"].get_params()}
        variants[key] = _serialize_variant(variant, data)
    return variants


def _cohort_evaluation(model, cohort, train_y):
    pred = model.predict(cohort.X)
    # Exactamente el mismo baseline de clase mayoritaria que DummyClassifier (empate -> 0).
    majority = int(np.bincount(np.asarray(train_y, dtype=int), minlength=2).argmax())
    baseline = [majority] * len(cohort.y)
    return {"row_ids": cohort.X.index.tolist(), "entity_ids": cohort.groups.tolist(),
            "y_true": cohort.y.astype(int).tolist(), "y_pred": pred.astype(int).tolist(),
            "metrics": classification_metrics(cohort.y, pred),
            "confusion_matrix": confusion_matrix(cohort.y, pred, labels=[0, 1]).tolist(),
            "baseline_predictions": baseline, "baseline_metrics": classification_metrics(cohort.y, baseline),
            "class_distribution": class_distribution(cohort.y), "n_samples": len(cohort.y),
            "n_entities": int(cohort.groups.nunique())}


def _groups_lab(data, cohort, seed):
    row_split = train_test_split(np.arange(len(data.X)), test_size=0.3, stratify=data.y, random_state=seed)
    group_split = next(GroupShuffleSplit(n_splits=1, test_size=0.3, random_state=seed).split(data.X, data.y, data.groups))
    variants, evaluations = {}, {}
    for key, (train, test) in (("incorrect", row_split), ("correct", group_split)):
        model = KNeighborsClassifier(n_neighbors=1, weights="uniform", metric="minkowski", p=2)
        model.fit(data.X.iloc[train], data.y.iloc[train])
        pred = model.predict(data.X.iloc[test])
        variant = _variant(data, key, "Por filas" if key == "incorrect" else "Por máquinas", train, test,
                           data.X.columns, model, pred, group_diagnostic(data.groups.iloc[train], data.groups.iloc[test]),
                           [_stage("1-NN", data.X.index[train])])
        variants[key] = _serialize_variant(variant, data)
        evaluations[key] = _cohort_evaluation(model, cohort, data.y.iloc[train])
    return variants, evaluations


def run_lab_experiment(case_id, seed, level):
    config = lab_config(case_id, seed, level)
    data, cohort = generate_lab_data(case_id, seed, level)
    if data.y.nunique() != 2:
        raise ValueError("Esta generación no contiene dos clases; no puede ajustarse el protocolo.")
    cohort_results = {}
    if case_id == "future":
        variants = _future_lab(data, seed)
    elif case_id == "groups":
        variants, cohort_results = _groups_lab(data, cohort, seed)
    else:
        raw, _, _ = _selection(data, seed)
        variants = {key: _serialize_variant(value, data) for key, value in raw.items()}
    preview = _preview(data)
    if case_id == "future":
        catalog = [{"variable": name, "available_at": "Después de la devolución" if name == "reembolso_tramitado" else "Al comprar",
                    "available_at_prediction": name != "reembolso_tramitado"} for name in data.X]
    else:
        catalog = [{"variable": "maquina_id / fila_id" if case_id == "groups" else "Variables de ruido",
                    "available_at": "Solo auditoría; nunca predictores" if case_id == "groups" else "Generación sintética independiente de la etiqueta"}]
    result = {
        "schema_version": "lab-run/1", "config": config, "engine_fingerprint": engine_fingerprint(),
        "protocol_hash": protocol_hash(), "runtime": runtime_versions(), "generator_params": data.params,
        "protocol": deepcopy(STUDY_PROTOCOL), "variants": variants, "cohort": cohort_results,
        "diagnostics": {"paired_internal": case_id != "groups", "paired_cohort": case_id == "groups",
                        "scope": "Comprobaciones del mecanismo sintético estudiado, no certificación global",
                        "labels_independent_of_features": case_id == "selection"},
        "data_preview": preview, "feature_catalog": catalog,
    }
    validate_lab_result(result, case_id, seed, level)
    return result


def validate_lab_result(result, case_id=None, seed=None, level=None):
    """Comprueba configuración, datos regenerados y predicciones; nunca reajusta modelos."""
    try:
        config = result["config"]
        expected = lab_config(config["case_id"] if case_id is None else case_id,
                              config["seed"] if seed is None else seed, config["level"] if level is None else level)
        if config != expected:
            raise ValueError("El resultado no corresponde a los parámetros solicitados (posible caché antigua).")
        if (result["schema_version"] != "lab-run/1" or not compatible_engine(result["engine_fingerprint"])
                or result["protocol_hash"] != protocol_hash() or result["runtime"] != runtime_versions()
                or canonical_json(result["protocol"]) != canonical_json(STUDY_PROTOCOL)):
            raise ValueError("Resultado incompatible con el código, protocolo o versiones actuales. Vuelve a calcularlo.")
        data, cohort = generate_lab_data(config["case_id"], config["seed"], config["level"])
        if result["generator_params"] != data.params:
            raise ValueError("Parámetros del generador incompatibles.")
        variants = result["variants"]
        required = {"incorrect", "correct", "control"} if config["case_id"] == "future" else {"incorrect", "correct"}
        if set(variants) != required:
            raise ValueError("Faltan variantes del protocolo.")
        for variant in variants.values():
            validate_rows(variant, data.y.to_dict())
            if not set(variant["feature_names"]) <= set(data.X):
                raise ValueError("Identificadores o variables desconocidas como predictores.")
            for name, row_ids in (("train", variant["train_row_ids"]), ("test", variant["test_row_ids"])):
                if variant["diagnostics"]["class_distribution"][name] != class_distribution(data.y.loc[row_ids]):
                    raise ValueError("Distribución de clases incompatible con las filas.")
        clean = variants["correct"]
        if config["case_id"] != "groups":
            if any(value["train_row_ids"] != clean["train_row_ids"] or value["test_row_ids"] != clean["test_row_ids"]
                   for value in variants.values()):
                raise ValueError("Comparación no emparejada: cambian filas de test o train.")
        if config["case_id"] == "future":
            legitimate = {"importe", "producto_fragil", "cliente_nuevo"}
            if set(clean["feature_names"]) != legitimate or set(variants["control"]["feature_names"]) != legitimate | {"control_irrelevante"}:
                raise ValueError("Variable posterior en la variante legítima o en el control.")
        elif config["case_id"] == "selection":
            stage = clean["fit_stages"][0]
            assert_training_scope(stage["row_ids"], stage["label_row_ids"], clean["train_row_ids"], clean["test_row_ids"])
        else:
            group_map = data.groups.to_dict()
            if {group_map[row] for row in clean["train_row_ids"]} & {group_map[row] for row in clean["test_row_ids"]}:
                raise ValueError("Entidades compartidas en la partición corregida.")
            for variant in variants.values():
                actual = group_diagnostic(data.groups.loc[variant["train_row_ids"]], data.groups.loc[variant["test_row_ids"]])
                if any(variant["diagnostics"][key] != value for key, value in actual.items()):
                    raise ValueError("Diagnóstico de entidades incoherente con las filas.")
            if set(result["cohort"]) != required:
                raise ValueError("Falta una evaluación de la cohorte común.")
            for key, evaluation in result["cohort"].items():
                training_labels = data.y.loc[variants[key]["train_row_ids"]]
                majority = int(np.bincount(np.asarray(training_labels, dtype=int), minlength=2).argmax())
                if evaluation.get("baseline_predictions") != [majority] * len(cohort.y):
                    raise ValueError("El baseline de cohorte no corresponde a la clase mayoritaria de entrenamiento.")
                validate_prediction_dict(evaluation)
                if (evaluation["row_ids"] != cohort.X.index.tolist() or evaluation["entity_ids"] != cohort.groups.tolist()
                        or evaluation["y_true"] != cohort.y.tolist() or set(evaluation["entity_ids"]) & set(data.groups)
                        or evaluation["n_samples"] != len(cohort.y) or evaluation["n_entities"] != cohort.groups.nunique()
                        or evaluation["class_distribution"] != class_distribution(cohort.y)):
                    raise ValueError("Cohorte incompatible o entidades compartidas con desarrollo.")
    except (KeyError, TypeError, AttributeError, IndexError) as exc:
        raise ValueError("Informe de laboratorio incompleto o mal formado.") from exc
