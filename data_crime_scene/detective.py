"""Expedientes de investigación sobre los motores existentes.

La evidencia pública se construye mediante una lista de campos permitidos.
Las respuestas se derivan de esa evidencia, nunca de un umbral de puntuación.
El objeto privado no se serializa para descargar evidencia. Esta separación
evita spoilers involuntarios; no pretende impedir inspeccionar código local.
"""

from copy import deepcopy
from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import random

import numpy as np

from .experiments import run_experiment
from .generators import generate_groups, generate_selection, validate_seed
from .laboratory import engine_fingerprint
from .validation import validate_prediction_dict, validate_result


DETECTIVE_VERSION = "detective-v1"
DIAGNOSES = {
    "contaminated": "Hay contaminación en uno de los mecanismos investigados",
    "defensible": "No identifico esa contaminación con la evidencia disponible",
    "insufficient": "La información es insuficiente para concluir",
}
ACTIONS = {
    "remove_feature": "Retirar del modelo la variable que no existe al predecir",
    "group_split": "Separar las entidades entre entrenamiento y evaluación",
    "train_selector": "Ajustar la selección únicamente con entrenamiento",
    "maintain": "Mantener el procedimiento respecto a los mecanismos investigados",
    "request_time": "Solicitar cuándo está disponible cada variable",
    "request_fit": "Solicitar las filas y etiquetas usadas al ajustar la selección",
}

# Solo metadatos públicos. Ni el orden numérico ni los títulos codifican el
# veredicto. El orden de presentación se baraja con la semilla de sesión.
TEMPLATES = {
    "d01": {"id": "d01", "title": "La mesa norte", "story": "Una tienda entrega un informe para anticipar qué pedidos se devolverán. Examina las columnas y reconstruye cómo se obtuvo la evaluación."},
    "d02": {"id": "d02", "title": "El turno de las seis", "story": "Una fábrica entrega varias mediciones de cada máquina. Quiere utilizar el modelo con máquinas que aún no ha visto."},
    "d03": {"id": "d03", "title": "La sala de mediciones", "story": "Un laboratorio construye un control sintético: variables y etiquetas son independientes. Tras seleccionar columnas, presenta una evaluación que debes revisar."},
    "d04": {"id": "d04", "title": "El cuaderno azul", "story": "Otra revisión de pedidos llega a tu mesa. El objetivo es anticipar devoluciones al confirmar una compra, usando el inventario de datos entregado."},
    "d05": {"id": "d05", "title": "La estación central", "story": "Una segunda fábrica pide revisar un modelo que diagnosticará máquinas nuevas. Contrasta su objetivo con la partición utilizada."},
    "d06": {"id": "d06", "title": "El lote de la tarde", "story": "Recibes otro control sintético con etiquetas independientes de las mediciones. Debes revisar el recorrido de la selección supervisada y la evaluación."},
    "d07": {"id": "d07", "title": "El archivo diecisiete", "story": "Un equipo de pedidos entrega una tabla y sus resultados. La documentación recibida permite inspeccionar los datos y pedir detalles adicionales antes de proponer cambios."},
    "d08": {"id": "d08", "title": "El informe de la sala dos", "story": "Un laboratorio entrega un control sintético de etiquetas independientes. El informe describe el modelo y sus resultados; puedes solicitar documentación del procedimiento."},
}

# La fuente y el estado de documentación son privados: nunca se incorporan a
# public_case por expansión de diccionarios ni a través de asdict(case).
_SPECS = {
    "d01": ("future", "incorrect", None),
    "d02": ("groups", "incorrect", None),
    "d03": ("selection", "incorrect", None),
    "d04": ("future", "correct", None),
    "d05": ("groups", "correct", None),
    "d06": ("selection", "correct", None),
    "d07": ("future", "incorrect", "time"),
    "d08": ("selection", "correct", "fit"),
}
_ALIASES = {"reembolso_tramitado": "registro_c17"}
_LEGITIMATE = {"importe", "producto_fragil", "cliente_nuevo"}
_LIMITS = {
    "future": "La correlación no acredita una fuga. Importa cuándo existe el dato. Excluir esta columna no certifica todas las demás propiedades del experimento.",
    "groups": "Las particiones evalúan observaciones distintas y entrenan con distinta composición de máquinas. Su diferencia de puntuación no aísla un efecto causal puro de la contaminación.",
    "selection": "Las etiquetas son independientes de las variables por construcción. El resultado fluctúa por azar; usar un Pipeline solo sirve si el ajuste recibe exclusivamente train.",
}
_HINTS = {
    "future": ("Relaciona el instante de predicción con el inventario de variables.", "Comprueba si cada columna existe ya en ese instante. Si falta su fecha de disponibilidad, solicítala antes de concluir."),
    "groups": ("Relaciona la población objetivo con la unidad usada para dividir los datos.", "Compara las listas de entidades: identificadores de fila distintos pueden pertenecer a la misma máquina."),
    "selection": ("Reconstruye qué información recibió cada etapa durante el ajuste.", "Compara los índices de las filas y de las etiquetas del selector con los de evaluación. Si no constan, pide ese registro."),
}


def detective_fingerprint() -> str:
    digest = hashlib.sha256(Path(__file__).read_bytes())
    digest.update(engine_fingerprint().encode())
    return digest.hexdigest()


def _alias(name: str) -> str:
    if name.startswith("ruido_"):
        return name.replace("ruido_", "medicion_", 1)
    return _ALIASES.get(name, name)


@dataclass
class DetectiveCase:
    template_id: str
    seed: int
    version: str
    fingerprint: str
    _source_case: str
    _variant: str
    _missing: str | None
    _source: dict

    @property
    def title(self):
        return TEMPLATES[self.template_id]["title"]


def build_case(template_id: str, seed: int) -> DetectiveCase:
    if not isinstance(template_id, str) or template_id not in TEMPLATES:
        raise ValueError("Plantilla de investigación desconocida.")
    seed = validate_seed(seed)
    source_case, variant, missing = _SPECS[template_id]
    source = run_experiment(source_case, seed).to_dict()
    return DetectiveCase(template_id, seed, DETECTIVE_VERSION, detective_fingerprint(), source_case, variant, missing, source)


def validate_case(case: DetectiveCase, template_id=None, seed=None):
    if not isinstance(case, DetectiveCase) or case.template_id not in _SPECS:
        raise ValueError("El expediente no corresponde a una plantilla válida.")
    if (case.version != DETECTIVE_VERSION or case.fingerprint != detective_fingerprint()
            or (case._source_case, case._variant, case._missing) != _SPECS[case.template_id]):
        raise ValueError("Expediente incompatible con la versión actual. Ábrelo de nuevo.")
    if template_id is not None and case.template_id != template_id:
        raise ValueError("La plantilla no corresponde al expediente solicitado.")
    if seed is not None and case.seed != seed:
        raise ValueError("La semilla no corresponde al expediente solicitado.")
    validate_result(case._source, expected_case_id=case._source_case, expected_seed=case.seed)


def _identity(case):
    return {"template_id": case.template_id, "version": case.version, "seed": case.seed,
            "fingerprint": case.fingerprint}


def _case_seed(seed, template_id):
    ordinal = list(TEMPLATES).index(template_id) + 1
    return int(np.random.SeedSequence([seed, ordinal, 4107]).generate_state(1)[0])


def case_seed(session: dict, template_id: str) -> int:
    _validate_session(session)
    if template_id not in TEMPLATES:
        raise ValueError("Plantilla de investigación desconocida.")
    return _case_seed(session["seed"], template_id)


def _new_record(template_id, seed, fingerprint):
    return {"configuration": {"template_id": template_id, "version": DETECTIVE_VERSION, "seed": seed, "fingerprint": fingerprint},
            "phase": "initial", "answers": {}, "hints_used": 0, "requested_evidence": [],
            "revealed_phases": [], "consulted_solution": False, "revealed_before_answer": False, "intervention": None}


def new_session(seed: int = 42) -> dict:
    seed = validate_seed(seed)
    order = list(TEMPLATES)
    random.Random(seed).shuffle(order)
    fingerprint = detective_fingerprint()
    return {"version": DETECTIVE_VERSION, "fingerprint": fingerprint, "seed": seed, "order": order,
            "active_case_id": order[0],
            "records": {key: _new_record(key, _case_seed(seed, key), fingerprint) for key in TEMPLATES}}


def reset_session(session: dict, seed: int | None = None) -> dict:
    replacement = new_session(session["seed"] if seed is None else seed)
    session.clear()
    session.update(replacement)
    return session


def _validate_session(session):
    if (not isinstance(session, dict) or session.get("version") != DETECTIVE_VERSION
            or session.get("fingerprint") != detective_fingerprint()
            or len(session.get("order", [])) != len(TEMPLATES)
            or set(session.get("order", [])) != set(TEMPLATES)):
        raise ValueError("La sesión no corresponde a la versión actual. Reiníciala.")
    validate_seed(session["seed"])


def activate_case(session: dict, template_id: str):
    _validate_session(session)
    if template_id not in TEMPLATES:
        raise ValueError("Plantilla de investigación desconocida.")
    session["active_case_id"] = template_id


def get_record(session: dict, case: DetectiveCase) -> dict:
    _validate_session(session)
    validate_case(case, seed=case_seed(session, case.template_id))
    if session["active_case_id"] != case.template_id:
        raise ValueError("El expediente no corresponde a la investigación activa.")
    record = session["records"].get(case.template_id)
    if record is None or record.get("configuration") != _identity(case):
        # Nunca reciclar respuestas/pistas/intervenciones de otra configuración.
        record = _new_record(case.template_id, case.seed, case.fingerprint)
        session["records"][case.template_id] = record
    return record


def _check_record(case, record):
    if record is not None and record.get("configuration") != _identity(case):
        raise ValueError("El estado de investigación pertenece a otro expediente o configuración.")
    if record is not None:
        if record.get("phase") not in ("initial", "expanded") or not 0 <= record.get("hints_used", -1) <= 2:
            raise ValueError("Estado de investigación incompatible.")
        if record["phase"] == "expanded":
            needed = {"time": "request_time", "fit": "request_fit"}.get(case._missing)
            if needed is None or needed not in record["requested_evidence"]:
                raise ValueError("La información adicional requiere una solicitud explícita.")


def _public_variant(variant: dict) -> dict:
    # No copiar name, diagnostics, fit_scope, generator_params ni variantes
    # hermanas. Sus etiquetas históricas contienen la solución del recorrido.
    result = {key: deepcopy(variant[key]) for key in (
        "train_row_ids", "test_row_ids", "y_true", "y_pred", "metrics", "confusion_matrix",
        "baseline_predictions", "baseline_metrics")}
    result["feature_names"] = [_alias(name) for name in variant["feature_names"]]
    result["model"] = {"type": variant["model"]["type"], "params": deepcopy(variant["model"]["params"])}
    if "preprocessing" in variant["model"]:
        result["model"]["preprocessing"] = deepcopy(variant["model"]["preprocessing"])
    return result


def public_case(case: DetectiveCase, record: dict | None = None) -> dict:
    validate_case(case)
    _check_record(case, record)
    phase = record["phase"] if record is not None else "initial"
    expanded = phase == "expanded"
    variant = case._source["variants"][case._variant]
    public = {
        "template_id": case.template_id, "version": case.version, "seed": case.seed, "title": case.title,
        "story": TEMPLATES[case.template_id]["story"], "configuration": _identity(case),
        "runtime": deepcopy(case._source["protocol"]["runtime"]),
        "sample": {"n_samples": len(variant["train_row_ids"]) + len(variant["test_row_ids"]),
                   "n_used_features": len(variant["feature_names"])},
        "objective": {"future": "Predecir si un pedido será devuelto justo al confirmar su compra.",
                      "groups": "Diagnosticar el estado de fallo en máquinas nuevas, nunca vistas durante el entrenamiento.",
                      "selection": "Revisar una evaluación sobre variables y etiquetas sintéticas independientes."}[case._source_case],
        "prediction_time": {"future": "Al confirmar la compra, antes del envío y de cualquier devolución.",
                            "groups": "Al medir una máquina nueva.",
                            "selection": "Sin conocer las etiquetas de las filas reservadas para evaluación."}[case._source_case],
        "positive_class": {"future": "1 = pedido devuelto; 0 = pedido no devuelto.", "groups": "1 = máquina con fallo; 0 = sin fallo.",
                           "selection": "1 = clase positiva aleatoria; 0 = negativa. No hay señal generativa."}[case._source_case],
        "experiment": _public_variant(variant),
        "data_preview": [],
        "feature_catalog": [], "procedure": {"split_type": "", "selection": None},
        "evidence": {"availability": None, "groups": None, "fitting": None},
        "evidence_options": [], "diagnosis_options": [{"id": key, "label": label} for key, label in DIAGNOSES.items()],
        "action_options": [{"id": key, "label": label} for key, label in ACTIONS.items()],
        "phase": phase, "hints": list(_HINTS[case._source_case][:record["hints_used"]]) if record is not None else [],
    }
    # La vista de filas solo contiene predictores efectivamente utilizados,
    # además de IDs de auditoría y la etiqueta; no filtrar la hermana ausente.
    predictor_columns = set(variant["feature_names"])
    all_predictors = set().union(*(set(value["feature_names"]) for value in case._source["variants"].values()))
    public["data_preview"] = [{_alias(key): value for key, value in row.items()
                               if key not in all_predictors or key in predictor_columns}
                              for row in case._source["data_preview"]]
    if case._source_case == "selection":
        # La muestra histórica contiene las primeras seis columnas; no tienen
        # por qué estar seleccionadas. Mostrar seis predictores usados evita
        # una tabla de solo IDs/etiquetas sin revelar el alcance del ajuste.
        raw = generate_selection(case.seed)
        public["sample"]["n_candidate_features"] = raw.X.shape[1]
        columns = variant["feature_names"][:6]
        frame = raw.X.loc[:, columns].iloc[:12].copy()
        frame.insert(0, "fila_id", frame.index)
        frame[raw.y.name] = raw.y.loc[frame.index]
        public["data_preview"] = [{_alias(key): value for key, value in row.items()}
                                  for row in frame.reset_index(drop=True).to_dict(orient="records")]
    evidence = public["evidence"]
    if case._source_case == "future":
        for name in variant["feature_names"]:
            unknown = case._missing == "time" and not expanded and name == "reembolso_tramitado"
            available = None if unknown else name in _LEGITIMATE
            public["feature_catalog"].append({"variable": _alias(name), "available_at_prediction": available,
                                              "available_at": "No consta en el documento recibido" if unknown else "Al confirmar la compra" if available else "Después de tramitar la devolución"})
        evidence["availability"] = deepcopy(public["feature_catalog"])
        public["procedure"]["split_type"] = "Filas estratificadas 70/30; sin filas compartidas"
        options = [("timing", "Momento de disponibilidad de las variables"), ("objective", "Instante en el que se hará la predicción")]
        if case._missing == "time" and not expanded:
            options.append(("missing_time", "No consta cuándo existe registro_c17"))
    elif case._source_case == "groups":
        groups = generate_groups(case.seed).groups
        train = sorted(set(groups.loc[variant["train_row_ids"]]))
        test = sorted(set(groups.loc[variant["test_row_ids"]]))
        evidence["groups"] = {"objective_new_entities": True, "train_entities": train, "test_entities": test,
                              "shared_entities": sorted(set(train) & set(test)), "shared_entity_count": len(set(train) & set(test))}
        public["procedure"]["split_type"] = "Partición por registros" if case._variant == "incorrect" else "Partición por entidades"
        public["feature_catalog"] = [{"variable": _alias(name), "available_at": "Al medir la máquina", "available_at_prediction": True}
                                     for name in variant["feature_names"]]
        options = [("group_overlap", "Intersección real de entidades entre train y test"), ("objective", "Objetivo de generalizar a máquinas nuevas")]
    else:
        stage = variant["fit_stages"][0]
        unknown = case._missing == "fit" and not expanded
        fitting = {"stage": "Selección supervisada · SelectKBest(f_classif, k=25)",
                   "fit_row_ids": None if unknown else deepcopy(stage["row_ids"]),
                   "label_row_ids": None if unknown else deepcopy(stage["label_row_ids"])}
        evidence["fitting"] = fitting
        public["procedure"]["selection"] = {"method": "SelectKBest(f_classif)", "k": 25,
                                             "fit_row_ids": fitting["fit_row_ids"], "label_row_ids": fitting["label_row_ids"]}
        public["procedure"]["split_type"] = "Filas estratificadas 70/30; sin filas compartidas"
        public["feature_catalog"] = [{"variable": _alias(name), "available_at": "Generación sintética; etiqueta independiente", "available_at_prediction": True}
                                     for name in variant["feature_names"]]
        options = [("fit_scope", "Filas y etiquetas que recibió realmente la selección"), ("objective", "Evaluar filas cuyas etiquetas no participaron en el ajuste")]
        if unknown:
            options.append(("missing_fit", "No consta qué filas y etiquetas recibió el selector"))
    options.extend([("metric", "La puntuación es alta o baja"), ("sample_count", "El tamaño de muestra por sí solo")])
    public["evidence_options"] = [{"id": key, "label": label} for key, label in options]
    return public


def _solution_from_public(view: dict) -> dict:
    evidence, experiment = view["evidence"], view["experiment"]
    if evidence["availability"] is not None:
        timing = evidence["availability"]
        unknown = [item["variable"] for item in timing if item["available_at_prediction"] is None]
        posterior = [item["variable"] for item in timing if item["available_at_prediction"] is False]
        concept, limit = "Disponibilidad temporal", _LIMITS["future"]
        if unknown:
            diagnosis, required, actions = "insufficient", "missing_time", ["request_time"]
            explanation = f"No consta cuándo existe {', '.join(unknown)}. Las métricas no permiten suplir ese dato. Solicita su disponibilidad antes de decidir si se puede usar al predecir."
        elif posterior:
            diagnosis, required, actions = "contaminated", "timing", ["remove_feature"]
            explanation = f"{', '.join(posterior)} se utiliza como predictor pero solo existe después del instante de predicción. La evidencia es su disponibilidad temporal, no la puntuación."
        else:
            diagnosis, required, actions = "defensible", "timing", ["maintain"]
            explanation = "Todas las variables utilizadas existen al confirmar la compra. No se identifica la contaminación temporal investigada; esto no certifica el modelo completo."
    elif evidence["groups"] is not None:
        group = evidence["groups"]
        shared = set(group["train_entities"]) & set(group["test_entities"])
        concept, limit, required = "Generalización a entidades nuevas", _LIMITS["groups"], "group_overlap"
        if group["objective_new_entities"] and shared:
            diagnosis, actions = "contaminated", ["group_split"]
            explanation = f"El objetivo son máquinas nuevas, pero {len(shared)} máquinas aparecen en ambos conjuntos. Las huellas sensoriales permiten reconocer máquinas conocidas sin usar el ID como predictor."
        else:
            diagnosis, actions = "defensible", ["maintain", "group_split"]
            explanation = "Las entidades de entrenamiento y evaluación son disjuntas, conforme al objetivo de evaluar máquinas nuevas. No se identifica el solapamiento investigado."
    else:
        stage, test = evidence["fitting"], set(experiment["test_row_ids"])
        concept, limit = "Ajuste separado de la evaluación", _LIMITS["selection"]
        if stage["fit_row_ids"] is None or stage["label_row_ids"] is None:
            diagnosis, required, actions = "insufficient", "missing_fit", ["request_fit"]
            explanation = "No se conoce qué filas y etiquetas recibió el selector. Saber que existe una selección o un Pipeline no demuestra dónde se ajustó. Solicita ese registro antes de concluir."
        else:
            seen = (set(stage["fit_row_ids"]) | set(stage["label_row_ids"])) & test
            required = "fit_scope"
            if seen:
                diagnosis, actions = "contaminated", ["train_selector"]
                explanation = f"La selección supervisada consultó {len(seen)} filas o etiquetas de evaluación. Aunque el clasificador se ajuste después con train, test ya influyó en las columnas elegidas."
            else:
                diagnosis, actions = "defensible", ["maintain", "train_selector"]
                explanation = "El selector recibió únicamente las filas y etiquetas de entrenamiento. Test se transforma con esa selección ya ajustada. No se identifica la contaminación de ajuste investigada."
    return {"diagnosis": diagnosis, "label": DIAGNOSES[diagnosis], "explanation": explanation,
            "evidence_ids": [required], "optional_evidence_ids": ["objective"], "actions": actions,
            "concept": concept, "limitations": [limit, "Datos sintéticos; esta evaluación didáctica no acredita rendimiento en producción."]}


def confirm_answer(session, case, diagnosis, evidence_ids, action, notes="") -> dict:
    record = get_record(session, case)
    phase = record["phase"]
    if phase in record["answers"]:
        return deepcopy(record["answers"][phase]["feedback"])
    if diagnosis not in DIAGNOSES or action not in ACTIONS:
        raise ValueError("Selecciona un diagnóstico y una acción de las opciones disponibles.")
    if not isinstance(evidence_ids, (list, tuple, set)) or any(not isinstance(key, str) for key in evidence_ids):
        raise ValueError("La evidencia debe ser una lista de opciones del expediente.")
    if not isinstance(notes, str):
        raise ValueError("Las notas deben ser texto. No se evalúan automáticamente.")
    view = public_case(case, record)
    selected = set(evidence_ids)
    if not selected <= {item["id"] for item in view["evidence_options"]}:
        raise ValueError("La evidencia seleccionada no pertenece a la información disponible.")
    solution = _solution_from_public(view)
    required, permitted = set(solution["evidence_ids"]), set(solution["evidence_ids"] + solution["optional_evidence_ids"])
    feedback = {"diagnosis_correct": diagnosis == solution["diagnosis"],
                "evidence_correct": required <= selected <= permitted,
                "action_correct": action in solution["actions"],
                "independent": not record["revealed_before_answer"]}
    record["answers"][phase] = {"diagnosis": diagnosis, "evidence_ids": sorted(selected), "action": action,
                                "notes": notes, "feedback": feedback}
    return deepcopy(feedback)


def request_evidence(session, case, action) -> dict:
    record = get_record(session, case)
    if action not in ACTIONS:
        raise ValueError("Acción de investigación desconocida.")
    if action in record["requested_evidence"]:
        return {"performed": False, "status": "already_available", "error": "Esa evidencia ya está disponible."}
    solution = _solution_from_public(public_case(case, record))
    if action not in ("request_time", "request_fit") or action not in solution["actions"]:
        return {"performed": False, "status": "not_applicable", "error": "Esa solicitud no corresponde a información que falte en este expediente. No se ha cambiado el procedimiento."}
    record["requested_evidence"].append(action)
    record["phase"] = "expanded"
    record["intervention"] = None
    return {"performed": True, "status": "evidence_requested", "phase": "expanded", "evidence": public_case(case, record)["evidence"]}


def use_hint(session, case) -> str:
    record = get_record(session, case)
    if record["hints_used"] < 2:
        record["hints_used"] += 1
    return _HINTS[case._source_case][record["hints_used"] - 1]


def visible_solution(case, record) -> dict | None:
    _check_record(case, record)
    if record["phase"] not in record["revealed_phases"]:
        return None
    return _solution_from_public(public_case(case, record))


def reveal_solution(session, case) -> dict:
    record = get_record(session, case)
    phase = record["phase"]
    record["consulted_solution"] = True
    if phase not in record["answers"]:
        record["revealed_before_answer"] = True
    if phase not in record["revealed_phases"]:
        record["revealed_phases"].append(phase)
    return visible_solution(case, record)


def _intervention_diagnostics(case, variant):
    """Hechos comprobables para la comparación ya solicitada, sin flag global."""
    if case._source_case == "future":
        return {"variables_indisponibles_al_predecir": [_alias(name) for name in variant["feature_names"] if name not in _LEGITIMATE]}
    if case._source_case == "groups":
        groups = generate_groups(case.seed).groups
        return {"entidades_compartidas": len(set(groups.loc[variant["train_row_ids"]]) & set(groups.loc[variant["test_row_ids"]]))}
    stage = variant["fit_stages"][0]
    return {"filas_test_consultadas_por_selector": len((set(stage["row_ids"]) | set(stage["label_row_ids"])) & set(variant["test_row_ids"]))}


def execute_intervention(session, case, action) -> dict:
    record = get_record(session, case)
    if action not in ACTIONS:
        raise ValueError("Intervención desconocida. Solo se admiten las operaciones internas del expediente.")
    solution = _solution_from_public(public_case(case, record))
    if (record["phase"] not in record["answers"] and record["phase"] not in record["revealed_phases"]):
        return {"performed": False, "status": "not_applicable", "error": "Confirma tu respuesta o consulta la solución antes de ejecutar una intervención."}
    if action not in solution["actions"] or action in ("request_time", "request_fit"):
        return {"performed": False, "status": "not_applicable", "error": "Esa intervención no corresponde al procedimiento ni a la evidencia actual. No se ha entrenado ni aplicado otra acción en su lugar."}
    if record["intervention"] is not None and record["intervention"]["operation"] == action:
        return deepcopy(record["intervention"])
    before_raw = case._source["variants"][case._variant]
    if action == "maintain":
        after_raw = before_raw
    else:
        # Operaciones cerradas. Se vuelve a ejecutar el protocolo existente,
        # con idéntica semilla; nunca se ejecuta texto introducido por el usuario.
        repeated = run_experiment(case._source_case, case.seed).to_dict()
        after_raw = repeated["variants"]["correct"]
    before, after = _public_variant(before_raw), _public_variant(after_raw)
    before["diagnostics"] = _intervention_diagnostics(case, before_raw)
    after["diagnostics"] = _intervention_diagnostics(case, after_raw)
    changed = {"remove_feature": "Se retira registro_c17 del conjunto de predictores.",
               "group_split": "Se separan entidades completas entre entrenamiento y evaluación.",
               "train_selector": "La selección se ajusta dentro del Pipeline únicamente con entrenamiento.",
               "maintain": "Se mantiene el procedimiento. No se ha vuelto a entrenar ni se presenta una reparación ficticia."}[action]
    repeated_clean = case._variant == "correct" and action != "maintain"
    if repeated_clean:
        changed = "El procedimiento ya aplicaba esa operación. Se ha vuelto a entrenar con el mismo protocolo; no se ha reparado una contaminación nueva."
    same_rows = before["train_row_ids"] == after["train_row_ids"] and before["test_row_ids"] == after["test_row_ids"]
    comparison = ("Mismas filas de entrenamiento y evaluación; cambia únicamente el uso de información en el mecanismo revisado."
                  if same_rows else "Cambian las observaciones y composición de entidades de train y test. La diferencia de métricas no es una comparación emparejada.")
    if repeated_clean or action == "maintain":
        comparison = "Es el mismo procedimiento con las mismas filas y predicciones. Esta operación no constituye una comparación entre un protocolo contaminado y otro reparado."
    result = {"performed": action != "maintain", "status": "maintained" if action == "maintain" else "reconfirmed" if repeated_clean else "applied",
              "operation": action, "before": before, "after": after, "changed": changed,
              "held_constant": "Mismos datos sintéticos de partida, semilla, variables comparables, tipo de clasificador y parámetros.",
              "comparison": comparison,
              "limitations": [_LIMITS[case._source_case], "Una puntuación menor o mayor no determina si el procedimiento es defendible."]}
    record["intervention"] = deepcopy(result)
    return result


def session_summary(session: dict) -> dict:
    _validate_session(session)
    counts = {"total": len(TEMPLATES), "completed": 0, "diagnoses_correct": 0, "evidence_correct": 0,
              "actions_correct": 0, "independent_correct": 0, "hints_used": 0, "solutions_consulted": 0}
    concepts, details = set(), []
    for template_id in session["order"]:
        record = session["records"][template_id]
        answer = record["answers"].get(record["phase"])
        counts["hints_used"] += record["hints_used"]
        counts["solutions_consulted"] += int(record["consulted_solution"])
        if answer is not None:
            feedback = answer["feedback"]
            counts["completed"] += 1
            for target, key in (("diagnoses_correct", "diagnosis_correct"), ("evidence_correct", "evidence_correct"), ("actions_correct", "action_correct")):
                counts[target] += int(feedback[key])
            all_correct = all(feedback[key] for key in ("diagnosis_correct", "evidence_correct", "action_correct"))
            counts["independent_correct"] += int(all_correct and feedback["independent"])
            if not all_correct or not feedback["independent"]:
                concepts.add({"future": "Disponibilidad temporal", "groups": "Generalización a entidades nuevas", "selection": "Ajuste separado de la evaluación"}[_SPECS[template_id][0]])
        details.append({"template_id": template_id, "title": TEMPLATES[template_id]["title"], "completed": answer is not None,
                        "phase": record["phase"], "hints_used": record["hints_used"], "solution_consulted": record["consulted_solution"]})
    return {**counts, "concepts_to_review": sorted(concepts), "cases": details}


def export_investigation(session, case) -> str:
    record = get_record(session, case)
    public = public_case(case, record)
    investigation = {key: deepcopy(record[key]) for key in (
        "phase", "answers", "hints_used", "requested_evidence", "consulted_solution", "revealed_before_answer")}
    payload = {"schema_version": "detective-investigation/1", "identification": _identity(case),
               "evidence": public, "investigation": investigation}
    solution = visible_solution(case, record)
    if solution is not None:
        payload["solution"] = solution
    if record["intervention"] is not None:
        intervention = record["intervention"]
        for key in ("before", "after"):
            validate_prediction_dict(intervention[key])
        raw_before = case._source["variants"][case._variant]
        raw_after = raw_before if intervention["operation"] == "maintain" else case._source["variants"]["correct"]
        for key, raw in (("before", raw_before), ("after", raw_after)):
            expected = _public_variant(raw)
            expected["diagnostics"] = _intervention_diagnostics(case, raw)
            if intervention[key] != expected:
                raise ValueError("Los resultados de intervención no corresponden al expediente mostrado.")
        payload["intervention"] = deepcopy(record["intervention"])
    return json.dumps(payload, ensure_ascii=False, indent=2, allow_nan=False)
