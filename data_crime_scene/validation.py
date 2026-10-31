"""Defensas de consistencia, no un detector universal de data leakage.

Se verifican datos, índices y predicciones; nunca se confía en el indicador
``leakage_detected`` como sustituto de esas comprobaciones.
"""

from dataclasses import asdict, is_dataclass
import json
import math

from sklearn.metrics import accuracy_score, balanced_accuracy_score, confusion_matrix, f1_score

from .generators import generate_future, generate_groups, generate_selection, validate_seed


def assert_training_scope(fit_row_ids, fit_label_row_ids, train_row_ids, test_row_ids):
    train, test = set(train_row_ids), set(test_row_ids)
    if list(fit_row_ids) != list(fit_label_row_ids):
        raise ValueError("Índices de variables y etiquetas desalineados durante el ajuste del selector.")
    for observed in (fit_row_ids, fit_label_row_ids):
        if set(observed) != train or len(observed) != len(train) or set(observed) & test:
            raise ValueError("Ajuste contaminado: las entradas efectivas del selector deben ser solo train.")


def validate_prediction_dict(value: dict):
    """Recalcula métricas y matrices sin usar sus diagnósticos declarados."""
    y, pred = value["y_true"], value["y_pred"]
    if not y or len(y) != len(pred) or any(item not in (0, 1) for item in y + pred):
        raise ValueError("Etiquetas/predicciones binarias vacías o de longitud incompatible.")
    expected = {
        "accuracy": accuracy_score(y, pred), "balanced_accuracy": balanced_accuracy_score(y, pred),
        "f1": f1_score(y, pred, zero_division=0),
    }
    for metric, actual in expected.items():
        if not math.isclose(float(value["metrics"][metric]), float(actual), rel_tol=0, abs_tol=1e-12):
            raise ValueError(f"Métricas incoherentes con las predicciones: {metric}.")
    if value["confusion_matrix"] != confusion_matrix(y, pred, labels=[0, 1]).tolist():
        raise ValueError("Matriz de confusión incoherente con las predicciones.")
    if "baseline_predictions" in value:
        baseline = value["baseline_predictions"]
        if len(baseline) != len(y) or any(item not in (0, 1) for item in baseline):
            raise ValueError("Predicciones del baseline incompatibles.")
        scores = {"accuracy": accuracy_score(y, baseline), "balanced_accuracy": balanced_accuracy_score(y, baseline),
                  "f1": f1_score(y, baseline, zero_division=0)}
        if any(not math.isclose(float(value["baseline_metrics"][key]), float(score), rel_tol=0, abs_tol=1e-12)
               for key, score in scores.items()):
            raise ValueError("Métricas del baseline incoherentes.")


def validate_rows(variant: dict, labels: dict):
    train, test = variant["train_row_ids"], variant["test_row_ids"]
    if (len(set(train)) != len(train) or len(set(test)) != len(test) or set(train) & set(test)
            or set(train + test) != set(labels)):
        raise ValueError("Partición de filas incoherente: solapamiento, filas repetidas o incompletas.")
    if [int(labels[row]) for row in test] != variant["y_true"]:
        raise ValueError("Las etiquetas de test no corresponden a sus filas.")
    majority = int(sum(int(labels[row]) for row in train) > len(train) / 2)
    if variant.get("baseline_predictions") != [majority] * len(test):
        raise ValueError("El baseline no corresponde a la clase mayoritaria de entrenamiento.")
    for key, rows in (("train_size", train), ("test_size", test)):
        if key in variant and variant[key] != len(rows):
            raise ValueError("Tamaño de la partición incoherente.")
    validate_prediction_dict(variant)


def validate_result(result, expected_case_id=None, expected_seed=None):
    payload = asdict(result) if is_dataclass(result) else result
    case, seed = payload["case_id"], validate_seed(payload["seed"])
    if expected_case_id is not None and case != expected_case_id:
        raise ValueError("El resultado no corresponde al caso solicitado.")
    if expected_seed is not None and seed != expected_seed:
        raise ValueError("El resultado no corresponde a la semilla solicitada (posible caché antigua).")
    generators = {"future": generate_future, "groups": generate_groups, "selection": generate_selection}
    if case not in generators:
        raise ValueError("Caso desconocido en el informe.")
    data = generators[case](seed)
    if payload["generator_params"] != data.params:
        raise ValueError("Configuración del generador incompatible con el recorrido guiado.")
    variants = payload["variants"]
    if set(variants) != {"incorrect", "correct"}:
        raise ValueError("Variantes incompatibles.")
    for variant in variants.values():
        validate_rows(variant, data.y.to_dict())
        if not set(variant["feature_names"]) <= set(data.X.columns):
            raise ValueError("Variables desconocidas o identificadores introducidos como predictores.")
    clean, wrong = variants["correct"], variants["incorrect"]
    if case in ("future", "selection"):
        if clean["train_row_ids"] != wrong["train_row_ids"] or clean["test_row_ids"] != wrong["test_row_ids"]:
            raise ValueError("La comparación requiere las mismas filas en ambas variantes.")
    if case == "future":
        legitimate = {"importe", "producto_fragil", "cliente_nuevo"}
        if not set(clean["feature_names"]) <= legitimate:
            raise ValueError("Variable posterior no disponible al predecir incluida en variables legítimas.")
    elif case == "groups":
        groups = data.groups.to_dict()
        if {groups[row] for row in clean["train_row_ids"]} & {groups[row] for row in clean["test_row_ids"]}:
            raise ValueError("Entidades compartidas en la evaluación corregida por grupos.")
    else:
        stage = clean["fit_stages"][0]
        assert_training_scope(stage["row_ids"], stage.get("label_row_ids", stage["row_ids"]),
                              clean["train_row_ids"], clean["test_row_ids"])


def validate_export(json_text: str, shown_result):
    expected = shown_result.to_dict() if is_dataclass(shown_result) else shown_result
    try:
        exported = json.loads(json_text)
    except (ValueError, TypeError) as exc:
        raise ValueError("El informe no es JSON válido.") from exc
    if exported != expected:
        raise ValueError("El JSON exportado no corresponde al experimento mostrado.")
