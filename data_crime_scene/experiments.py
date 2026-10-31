"""Entrenamiento real de los tres protocolos. No depende de Streamlit.

``incorrect`` identifica exclusivamente demostraciones deliberadas de errores.
"""

from copy import deepcopy
import platform

import numpy as np
import pandas as pd
import sklearn
from sklearn.dummy import DummyClassifier
from sklearn.feature_selection import SelectKBest, f_classif
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import accuracy_score, balanced_accuracy_score, confusion_matrix, f1_score
from sklearn.model_selection import GroupShuffleSplit, train_test_split
from sklearn.neighbors import KNeighborsClassifier
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler

from .cases import CASES, PROTOCOLS
from .generators import SyntheticDataset, generate_future, generate_groups, generate_selection, validate_seed
from .results import ExperimentResult, VariantResult
from .validation import assert_training_scope


class AuditedSelectKBest(SelectKBest):
    """Registra las filas recibidas realmente por fit, antes de seleccionar.

    La auditoría no cambia la selección ni utiliza las etiquetas de test.
    El índice del DataFrame es metadato, nunca una variable predictiva.
    """

    def fit(self, X, y):
        self.fit_row_ids_ = [str(value) for value in X.index]
        self.fit_label_row_ids_ = [str(value) for value in y.index]
        return super().fit(X, y)


def classification_metrics(y_true, y_pred) -> dict[str, float]:
    return {
        "accuracy": float(accuracy_score(y_true, y_pred)),
        "balanced_accuracy": float(balanced_accuracy_score(y_true, y_pred)),
        "f1": float(f1_score(y_true, y_pred, pos_label=1, zero_division=0)),
    }


def future_feature_diagnostic(feature_names: list[str]) -> dict:
    """Diagnóstico de procedencia temporal, sin umbrales de correlación."""
    future = sorted(set(feature_names) & {"reembolso_tramitado"})
    return {"leakage_detected": bool(future), "future_features_used": future,
            "mechanism": "Variables disponibles después del instante de predicción"}


def group_diagnostic(train_groups, test_groups) -> dict:
    train = set(map(str, train_groups))
    test = set(map(str, test_groups))
    shared = sorted(train & test)
    return {"leakage_detected": bool(shared), "mechanism": "Máquinas compartidas al evaluar máquinas nuevas",
            "shared_entity_count": len(shared), "shared_entities": shared,
            "train_entity_count": len(train), "test_entity_count": len(test),
            "train_entities": sorted(train), "test_entities": sorted(test)}


def _stage(stage: str, row_ids, contaminated: bool = False) -> dict:
    rows = [str(row) for row in row_ids]
    return {"stage": stage, "fit_scope": "Train y test (contaminado)" if contaminated else "Solo train",
            "n_rows": len(rows), "row_ids": rows}


def _logistic(seed: int) -> LogisticRegression:
    return LogisticRegression(C=1.0, solver="liblinear", max_iter=1000, random_state=seed)


def _model_description(classifier) -> dict:
    # Todos los parámetros del clasificador, sin objetos no serializables.
    return {"type": type(classifier).__name__, "params": classifier.get_params(deep=False)}


def _variant(data: SyntheticDataset, name: str, split_type: str, train, test, features,
             classifier, predictions, diagnostics: dict, fit_stages: list[dict]) -> VariantResult:
    baseline = DummyClassifier(strategy="most_frequent")
    # Solo el número de filas importa a DummyClassifier; no precisa copiar miles de columnas.
    baseline.fit(np.zeros((len(train), 1)), data.y.iloc[train])
    baseline_pred = baseline.predict(np.zeros((len(test), 1)))
    y_true = data.y.iloc[test].to_numpy()
    return VariantResult(
        name=name, split_type=split_type,
        train_row_ids=data.X.index[train].tolist(), test_row_ids=data.X.index[test].tolist(),
        feature_names=list(features), model=_model_description(classifier),
        y_true=[int(value) for value in y_true], y_pred=[int(value) for value in predictions],
        metrics=classification_metrics(y_true, predictions),
        confusion_matrix=confusion_matrix(y_true, predictions, labels=[0, 1]).astype(int).tolist(),
        baseline_metrics=classification_metrics(y_true, baseline_pred), diagnostics=diagnostics,
        fit_stages=fit_stages, baseline_predictions=[int(value) for value in baseline_pred],
    )


def _preview(data: SyntheticDataset) -> list[dict]:
    # La vista se limita a doce filas y, para el control de ruido, seis variables.
    preview = data.X.iloc[:12, :6].copy()
    preview.insert(0, "fila_id", preview.index)
    if data.groups is not None:
        preview.insert(1, "maquina_id", data.groups.loc[preview.index])
    preview[data.y.name] = data.y.loc[preview.index]
    return preview.reset_index(drop=True).to_dict(orient="records")


def _future(data: SyntheticDataset, seed: int):
    rows = np.arange(len(data.X))
    train, test = train_test_split(rows, test_size=0.3, stratify=data.y, random_state=seed)
    legitimate = ["importe", "producto_fragil", "cliente_nuevo"]
    variants = {}
    for key, features in (("incorrect", legitimate + ["reembolso_tramitado"]), ("correct", legitimate)):
        model = Pipeline([("scaler", StandardScaler()), ("classifier", _logistic(seed))])
        model.fit(data.X.iloc[train][features], data.y.iloc[train])
        pred = model.predict(data.X.iloc[test][features])
        variant = _variant(data, "Incorrecto · incluye información futura" if key == "incorrect" else "Corregido · datos disponibles al comprar",
                           "Filas estratificadas 70/30 (misma partición)", train, test, features,
                           model.named_steps["classifier"], pred, future_feature_diagnostic(features),
                           [_stage("StandardScaler", data.X.index[train]), _stage("LogisticRegression", data.X.index[train])])
        variant.model["preprocessing"] = {"type": "StandardScaler", "params": model.named_steps["scaler"].get_params()}
        variants[key] = variant
    catalog = [{"variable": name, "available_at": "Después de la devolución" if name == "reembolso_tramitado" else "Al comprar",
                "role": "Variable posterior; fuga deliberada" if name == "reembolso_tramitado" else "Señal legítima disponible al predecir",
                "used_in_incorrect": True, "used_in_correct": name != "reembolso_tramitado"} for name in data.X.columns]
    return variants, {"prediction_time": CASES["future"].prediction_time, "future_feature": "reembolso_tramitado",
                      "same_train_rows": True, "same_test_rows": True}, catalog


def _groups(data: SyntheticDataset, seed: int):
    rows = np.arange(len(data.X))
    row_split = train_test_split(rows, test_size=0.3, stratify=data.y, random_state=seed)
    group_split = next(GroupShuffleSplit(n_splits=1, test_size=0.3, random_state=seed).split(data.X, data.y, data.groups))
    variants = {}
    for key, (train, test) in (("incorrect", row_split), ("correct", group_split)):
        model = KNeighborsClassifier(n_neighbors=1, weights="uniform", metric="minkowski", p=2)
        model.fit(data.X.iloc[train], data.y.iloc[train])
        pred = model.predict(data.X.iloc[test])
        diagnostics = group_diagnostic(data.groups.iloc[train], data.groups.iloc[test])
        variants[key] = _variant(data, "Incorrecto · divide registros" if key == "incorrect" else "Corregido · separa máquinas",
                                 "Filas estratificadas 70/30" if key == "incorrect" else "GroupShuffleSplit por máquina 70/30",
                                 train, test, data.X.columns, model, pred, diagnostics,
                                 [_stage("KNeighborsClassifier (1-NN)", data.X.index[train])])
    catalog = [{"variable": name, "available_at": "Al medir la máquina", "role": "Medición continua de la huella sensorial",
                "used_in_incorrect": True, "used_in_correct": True} for name in data.X.columns]
    catalog.extend([{"variable": name, "available_at": "Al registrar la observación", "role": "Solo auditoría; no se usa para predecir",
                     "used_in_incorrect": False, "used_in_correct": False} for name in ("maquina_id", "fila_id")])
    return variants, {"objective": "Generalizar a máquinas nuevas", "features_exclude_ids": True,
                      "comparison_is_paired": False, "entity_label_is_stable": True}, catalog


def _selection_diagnostic(selector: AuditedSelectKBest, test_ids, feature_names):
    seen = sorted(set(selector.fit_row_ids_) & set(test_ids))
    return {"leakage_detected": bool(seen), "mechanism": "Selección supervisada que consulta etiquetas de test",
            "selector_fit_row_count": len(selector.fit_row_ids_), "selector_test_rows_seen": len(seen),
            "selector_test_row_ids": seen, "selected_feature_count": len(feature_names),
            "selected_features": list(feature_names)}


def _selection(data: SyntheticDataset, seed: int):
    train, test = train_test_split(np.arange(len(data.X)), test_size=0.3, stratify=data.y, random_state=seed)
    # ERROR DELIBERADO: el selector supervisado ve también las etiquetas de test.
    contaminated_selector = AuditedSelectKBest(score_func=f_classif, k=25)
    contaminated_X = contaminated_selector.fit_transform(data.X, data.y)
    contaminated_model = _logistic(seed)
    contaminated_model.fit(contaminated_X[train], data.y.iloc[train])
    contaminated_pred = contaminated_model.predict(contaminated_X[test])

    # La misma selección y clasificador; ahora fit solo recibe train.
    clean_model = Pipeline([("selector", AuditedSelectKBest(score_func=f_classif, k=25)),
                            ("classifier", _logistic(seed))])
    clean_model.fit(data.X.iloc[train], data.y.iloc[train])
    assert_training_scope(clean_model.named_steps["selector"].fit_row_ids_,
                          clean_model.named_steps["selector"].fit_label_row_ids_,
                          data.X.index[train], data.X.index[test])
    clean_pred = clean_model.predict(data.X.iloc[test])
    variants = {}
    for key, selector, classifier, pred in (
        ("incorrect", contaminated_selector, contaminated_model, contaminated_pred),
        ("correct", clean_model.named_steps["selector"], clean_model.named_steps["classifier"], clean_pred),
    ):
        names = data.X.columns[selector.get_support()].tolist()
        variants[key] = _variant(data, "Incorrecto · selecciona mirando test" if key == "incorrect" else "Corregido · Pipeline ajustado con train",
                                 "Filas estratificadas 70/30 (misma partición)", train, test, names, classifier, pred,
                                 _selection_diagnostic(selector, data.X.index[test], names),
                                 [_stage("SelectKBest(f_classif, k=25)", selector.fit_row_ids_, key == "incorrect"),
                                  _stage("LogisticRegression", data.X.index[train])])
        variants[key].model["selection"] = {"type": "SelectKBest", "score_func": "f_classif", "k": 25,
                                             "inside_pipeline": key == "correct"}
        variants[key].fit_stages[0]["label_row_ids"] = selector.fit_label_row_ids_
    selected_wrong = set(variants["incorrect"].feature_names)
    selected_correct = set(variants["correct"].feature_names)
    catalog = [{"variable": name, "available_at": "Generación local; etiqueta independiente", "role": "Ruido sin señal generativa",
                "used_in_incorrect": name in selected_wrong, "used_in_correct": name in selected_correct}
               for name in sorted(selected_wrong | selected_correct)]
    return variants, {"null_control": True, "labels_independent_of_features": True,
                      "selector": "SelectKBest(f_classif, k=25)", "same_train_rows": True, "same_test_rows": True,
                      "all_feature_count": data.X.shape[1], "catalog_scope": "Unión de variables seleccionadas por ambas variantes"}, catalog


def run_experiment(case_id: str, seed: int = 42) -> ExperimentResult:
    """Ejecuta un protocolo fijo. Semilla y caso identifican todos sus parámetros.

    No hay caché en el motor. La interfaz puede cachear esta función usando
    ambos argumentos. Un caso o una semilla inválidos fallan antes del ajuste.
    """
    if not isinstance(case_id, str) or case_id not in CASES:
        raise ValueError(f"Caso desconocido: {case_id!r}. Usa future, groups o selection.")
    seed = validate_seed(seed)
    # Se fija una copia del protocolo antes de generar y entrenar.
    protocol = deepcopy(PROTOCOLS[case_id])
    protocol["runtime"] = {"python": platform.python_version(), "numpy": np.__version__,
                           "pandas": pd.__version__, "scikit_learn": sklearn.__version__}
    generators = {"future": generate_future, "groups": generate_groups, "selection": generate_selection}
    runners = {"future": _future, "groups": _groups, "selection": _selection}
    data = generators[case_id](seed)
    if data.y.nunique() != 2:
        raise ValueError("La generación no produjo las dos clases; el protocolo no puede evaluarse con esta semilla.")
    variants, diagnostics, catalog = runners[case_id](data, seed)
    return ExperimentResult(case_id=case_id, seed=seed, generator_params=data.params, protocol=protocol,
                            variants=variants, diagnostics=diagnostics, data_preview=_preview(data), feature_catalog=catalog,
                            teaching_notes=[CASES[case_id].positive_class, CASES[case_id].comparison_caveat,
                                            "Todos los datos son sintéticos. Este test es una demostración didáctica, no evidencia de rendimiento en producción.",
                                            "Las semillas 7, 42 y 2026 son comprobaciones predeterminadas, no una búsqueda del mejor resultado."])
