"""Investigación con evidencia pública y progreso local a una sesión de Streamlit."""

from html import escape
import json

import pandas as pd
import streamlit as st

from ui.presentation import brief_card, caption

from data_crime_scene.detective import (
    TEMPLATES,
    activate_case,
    build_case,
    case_seed,
    confirm_answer,
    detective_fingerprint,
    execute_intervention,
    export_investigation,
    get_record,
    new_session,
    public_case,
    request_evidence,
    reveal_solution,
    session_summary,
    use_hint,
    validate_case,
    visible_solution,
)


METRICS = {"accuracy": "Accuracy", "balanced_accuracy": "Balanced accuracy", "f1": "F1"}
REQUESTS = {"request_time", "request_fit"}


def _json(value) -> str:
    return json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False)


def _limitations(value) -> None:
    st.warning(value if isinstance(value, str) else "\n\n".join(value))


def _reset_ui() -> None:
    st.session_state["detective_ui_epoch"] = st.session_state.get("detective_ui_epoch", 0) + 1
    st.session_state.pop("detective_context", None)
    st.session_state["detective_cases"] = {}
    st.session_state["detective_drafts"] = {}
    for key in list(st.session_state):
        if key.startswith("detective_answer_"):
            del st.session_state[key]


def _next_case() -> None:
    session = st.session_state["detective_session"]
    order = session["order"]
    current = st.session_state["detective_case_selector"]
    index = order.index(current)
    st.session_state["detective_case_selector"] = order[(index + 1) % len(order)]


def _metrics(experiment: dict) -> None:
    for column, (key, label) in zip(st.columns(3), METRICS.items()):
        column.metric(label, f"{experiment['metrics'][key]:.1%}", border=True)
    baseline = experiment["baseline_metrics"]
    caption("Baseline de clase mayoritaria aprendido en train: " + " · ".join(f"{label} {baseline[key]:.1%}" for key, label in METRICS.items()))


def _evidence(view: dict) -> None:
    st.header("01 · Panel de pruebas")
    _metrics(view["experiment"])
    caption(f"Datos sintéticos · clase positiva: {view['positive_class']}. Train significa entrenamiento y test, evaluación.")
    st.markdown("**Muestra de los datos**")
    st.dataframe(pd.DataFrame(view["data_preview"]), hide_index=True, width="stretch")
    catalog = pd.DataFrame(view["feature_catalog"])
    if not catalog.empty:
        catalog = catalog.rename(columns={"variable": "Variable", "available_at": "Cuándo existe", "available_at_prediction": "Disponible al predecir"})
        if "Disponible al predecir" in catalog:
            catalog["Disponible al predecir"] = catalog["Disponible al predecir"].map({True: "Sí", False: "No", None: "Sin informar"}).fillna("Sin informar")
        st.dataframe(catalog, hide_index=True, width="stretch")
    experiment, procedure = view["experiment"], view["procedure"]
    sample = view.get("sample", {})
    if sample:
        description = f"{sample['n_samples']} observaciones sintéticas · {sample['n_used_features']} predictores utilizados"
        if sample.get("n_candidate_features") is not None:
            description += f" · {sample['n_candidate_features']} variables candidatas antes de seleccionar"
        caption(description)
    st.markdown(f"**Procedimiento declarado:** {procedure['split_type']}")
    st.write(f"**Tamaños:** {len(experiment['train_row_ids'])} filas de train · {len(experiment['test_row_ids'])} filas de test.")
    st.write("**Variables que recibe el modelo:** " + ", ".join(f"`{name}`" for name in experiment["feature_names"]))
    evidence = view["evidence"]
    groups = evidence.get("groups")
    if groups is not None:
        st.write(f"**Entidades:** {len(groups['train_entities'])} en train · {len(groups['test_entities'])} en test · **{groups['shared_entity_count']} compartidas**.")
    if procedure.get("selection") is not None:
        selection = procedure["selection"]
        st.write(f"**Selección:** {selection['method']} · k={selection['k']}.")
        fit_rows = selection.get("fit_row_ids")
        label_rows = selection.get("label_row_ids")
        if fit_rows is None or label_rows is None:
            st.info("El informe no especifica qué filas y etiquetas recibió la etapa de selección durante su ajuste.")
        else:
            test_ids = set(experiment["test_row_ids"])
            seen = len(set(label_rows) & test_ids)
            st.write(f"**Ajuste del selector:** {len(fit_rows)} filas y {len(label_rows)} etiquetas recibidas; {seen} etiquetas pertenecen a test.")
    with st.expander("Índices, modelo y trazabilidad de la evaluación"):
        st.json({"configuration": view["configuration"], "runtime": view.get("runtime", {}), "model": experiment["model"], "procedure": procedure, "evidence": evidence}, expanded=False)
        st.dataframe(pd.DataFrame({"fila de test": experiment["test_row_ids"], "etiqueta real": experiment["y_true"], "predicción": experiment["y_pred"]}).head(12), hide_index=True, width="stretch")
        caption("Matriz de confusión real. Filas: etiqueta real; columnas: predicción, en orden 0, 1.")
        st.dataframe(pd.DataFrame(experiment["confusion_matrix"], index=["Real 0", "Real 1"], columns=["Predicho 0", "Predicho 1"]), width="stretch")


def _hints(session, case, record: dict, view: dict) -> None:
    st.markdown("**Pistas progresivas**")
    used = record["hints_used"]
    first, second = st.columns(2)
    if first.button("Consultar pista 1", key="detective_hint_1", disabled=used >= 1, width="stretch"):
        use_hint(session, case)
        st.rerun()
    if second.button("Consultar pista 2", key="detective_hint_2", disabled=used != 1, width="stretch"):
        use_hint(session, case)
        st.rerun()
    for index, hint in enumerate(view["hints"], 1):
        st.info(f"Pista {index}: {hint}")


def _answer(session, case, record: dict, view: dict) -> str | None:
    st.header("02 · Tu investigación")
    phase = view["phase"]
    submitted = record["answers"].get(phase)
    draft_key = (case.template_id, case.seed, phase)
    defaults = submitted or st.session_state["detective_drafts"].get(draft_key, {})
    prefix = f"detective_answer_{st.session_state['detective_ui_epoch']}_{case.template_id}_{case.seed}_{phase}"
    diagnosis_labels = {option["id"]: option["label"] for option in view["diagnosis_options"]}
    evidence_labels = {option["id"]: option["label"] for option in view["evidence_options"]}
    action_labels = {option["id"]: option["label"] for option in view["action_options"]}
    diagnosis_options = list(diagnosis_labels)
    action_options = list(action_labels)
    default_diagnosis = defaults.get("diagnosis")
    default_action = defaults.get("action")
    diagnosis = st.radio(
        "Diagnóstico", diagnosis_options, format_func=diagnosis_labels.get,
        index=diagnosis_options.index(default_diagnosis) if default_diagnosis in diagnosis_options else None,
        disabled=submitted is not None, key=f"{prefix}_diagnosis",
    )
    evidence = st.multiselect(
        "Evidencia que sostiene tu diagnóstico", list(evidence_labels),
        format_func=evidence_labels.get, default=defaults.get("evidence_ids", []),
        disabled=submitted is not None, key=f"{prefix}_evidence",
        help="Selecciona hechos del expediente. Una puntuación alta o baja, por sí sola, no establece el recorrido de la información.",
    )
    action = st.selectbox(
        "Acción propuesta", action_options, format_func=action_labels.get,
        index=action_options.index(default_action) if default_action in action_options else None,
        disabled=submitted is not None, key=f"{prefix}_action",
    )
    notes = st.text_area("Notas de investigación · no se califican", value=defaults.get("notes", ""), disabled=submitted is not None, key=f"{prefix}_notes", help="Este texto se conserva en el resumen. No se puntúa mediante palabras clave ni mediante un modelo de lenguaje.")
    if submitted is None:
        st.session_state["detective_drafts"][draft_key] = {"diagnosis": diagnosis, "evidence_ids": evidence, "action": action, "notes": notes}
    if st.button("Confirmar respuesta", type="primary", key="detective_confirm", disabled=submitted is not None):
        if diagnosis is None or action is None:
            st.error("Elige un diagnóstico y una acción antes de confirmar.")
        else:
            confirm_answer(session, case, diagnosis, evidence, action, notes=notes)
            st.rerun()
    if submitted is not None:
        st.success("Respuesta registrada. Los reruns y las visitas a este expediente conservan un único intento por fase de evidencia.")
        feedback = submitted["feedback"]
        labels = {"diagnosis_correct": "Diagnóstico", "evidence_correct": "Evidencia", "action_correct": "Acción"}
        st.write(" · ".join(f"{'✓' if feedback[key] else '↻'} {label}: {'adecuado' if feedback[key] else 'para revisar'}" for key, label in labels.items()))
        if not feedback["independent"]:
            caption("La solución se consultó antes de esta respuesta; se registra como investigación con ayuda de la solución.")
    if action in REQUESTS:
        if st.button("Solicitar la información elegida", key="detective_request_evidence"):
            response = request_evidence(session, case, action)
            if response.get("performed") is False:
                st.info(response.get("error", "Esta solicitud no corresponde a la información ausente de este expediente."))
            else:
                st.rerun()
    return action


def _solution(session, case, record: dict, action: str | None) -> None:
    st.header("03 · Contrastar y actuar")
    solution = visible_solution(case, record)
    if st.button("Revelar solución y explicación", key="detective_reveal", disabled=solution is not None):
        reveal_solution(session, case)
        st.rerun()
    if solution is None:
        caption("Puedes contrastar tu respuesta cuando lo decidas. Si consultas la solución antes de responder, quedará registrado.")
    else:
        with st.container(key="dcs_verdict"):
            st.markdown(f"**Diagnóstico del expediente:** {solution['label']}")
            st.write(solution["explanation"])
            _limitations(solution["limitations"])
    phase = record["phase"]
    can_act = bool(record["answers"].get(phase)) or solution is not None
    if action is not None and action not in REQUESTS and can_act:
        if st.button("Ejecutar la acción elegida", key="detective_intervene", type="primary"):
            response = execute_intervention(session, case, action)
            if response.get("status") == "not_applicable":
                st.info(response.get("error", "La acción elegida no corresponde al expediente. No se ha ejecutado otra acción."))
            else:
                st.rerun()
    elif not can_act:
        caption("Confirma una respuesta o consulta la explicación para habilitar la intervención delimitada.")
    intervention = record.get("intervention")
    if intervention is not None and intervention.get("operation") == action:
        if intervention.get("status") == "not_applicable":
            st.info(intervention.get("error", "La acción elegida no corresponde al expediente. No se ha ejecutado otra acción."))
        else:
            st.markdown("**Resultado de la intervención**")
            status = "Procedimiento conservado" if intervention.get("status") == "maintained" else "Intervención calculada"
            st.success(status)
            for label, key in (("Qué cambió", "changed"), ("Qué se mantuvo", "held_constant"), ("Comparación válida", "comparison")):
                st.write(f"**{label}:** {intervention[key]}")
            rows = []
            for label, key in (("Antes", "before"), ("Después", "after")):
                value = intervention[key]
                rows.append({"Evaluación": label, **{name: f"{value['metrics'][metric]:.1%}" for metric, name in METRICS.items()}})
            st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch")
            with st.expander("Diagnósticos antes y después"):
                st.json({"antes": intervention["before"].get("diagnostics"), "después": intervention["after"].get("diagnostics")}, expanded=False)
            _limitations(intervention["limitations"])
            caption("La validez se evalúa mediante columnas, disponibilidad e índices; una subida o bajada de la métrica no decide el veredicto.")


def _summary(session) -> None:
    summary = session_summary(session)
    with st.expander("Resumen de la sesión", expanded=summary["completed"] > 0):
        for column, (key, label) in zip(st.columns(4), (("completed", "Expedientes completados"), ("diagnoses_correct", "Diagnósticos acertados"), ("evidence_correct", "Evidencias identificadas"), ("actions_correct", "Acciones adecuadas"))):
            column.metric(label, summary[key])
        caption(f"{summary['independent_correct']} expedientes con diagnóstico, evidencia y acción adecuados sin solución previa · {summary['hints_used']} pistas consultadas · {summary['solutions_consulted']} soluciones consultadas.")
        concepts = summary["concepts_to_review"]
        if concepts:
            st.markdown("**Conceptos que conviene repasar**")
            for concept in concepts:
                st.markdown(f"- {concept}")
        st.dataframe(pd.DataFrame(summary["cases"]).rename(columns={
            "template_id": "Identificador", "title": "Expediente", "completed": "Respuesta registrada",
            "phase": "Fase de evidencia", "hints_used": "Pistas", "solution_consulted": "Solución consultada",
        }), hide_index=True, width="stretch")
        caption("Progreso de esta sesión. Estos recuentos ayudan a repasar; no son una certificación de conocimientos ni una evaluación profesional.")
        st.download_button("↓ Descargar resumen de sesión · JSON", _json(summary), file_name="detective-sesion.json", mime="application/json", on_click="ignore", key="detective_download_session")


def render_detective(*, public_demo: bool = False) -> None:
    fingerprint = detective_fingerprint()
    if "detective_session" not in st.session_state:
        st.session_state["detective_session"] = new_session(42)
        _reset_ui()
    session = st.session_state["detective_session"]
    if st.session_state.get("detective_fingerprint") != fingerprint:
        st.session_state["detective_fingerprint"] = fingerprint
        st.session_state["detective_session"] = session = new_session(session["seed"])
        _reset_ui()
    with st.sidebar, st.container(key="dcs_detective_controls"):
        st.markdown('<div class="brand-label">DCS / Mesa de investigación</div>', unsafe_allow_html=True)
        seed = int(st.number_input("Semilla de sesión", min_value=0, max_value=2**32-1, value=session["seed"], step=1, key="detective_session_seed", help="Fija el orden de los ocho expedientes y sus semillas de datos. Cambiarla inicia una sesión nueva y borra su progreso."))
        caption("Cambiar la semilla inicia otra sesión: se retiran respuestas, pistas y resultados anteriores.")
        reset = st.button("Reiniciar sesión", key="detective_reset", width="stretch")
        if reset or seed != session["seed"]:
            st.session_state["detective_session"] = session = new_session(seed)
            _reset_ui()
            st.session_state["detective_case_selector"] = session["order"][0]
        case_id = st.selectbox("Expediente de la sesión", session["order"], index=session["order"].index(session["active_case_id"]), format_func=lambda key: TEMPLATES[key]["title"], key="detective_case_selector")
        open_case = st.button("Abrir expediente", type="primary", width="stretch", key="detective_open")
        caption("Ocho expedientes con datos sintéticos. La selección del expediente no lanza un entrenamiento: ábrelo explícitamente.")
    experiment_seed = case_seed(session, case_id)
    context = (case_id, experiment_seed, fingerprint)
    if st.session_state.get("detective_context") != context:
        st.session_state["detective_context"] = context
        st.session_state["detective_ui_epoch"] += 1
        for key in list(st.session_state):
            if key.startswith("detective_answer_"):
                del st.session_state[key]
        activate_case(session, case_id)
    st.markdown('<div class="eyebrow">Ocho expedientes · evidencia antes que intuición</div>', unsafe_allow_html=True)
    st.title("Modo Detective")
    st.write("Investiga una evaluación, identifica las pruebas y elige una acción. Una métrica llamativa abre una pregunta; el recorrido de la información permite responderla.")
    st.markdown(f'<div class="case-number">Expediente {escape(case_id)} · semilla {experiment_seed}</div>', unsafe_allow_html=True)
    st.header(TEMPLATES[case_id]["title"])
    cases = st.session_state["detective_cases"]
    if open_case:
        try:
            if context not in cases:
                with st.spinner("Abriendo el expediente: generando datos y calculando su evaluación…"):
                    candidate = build_case(case_id, experiment_seed)
                    validate_case(candidate, template_id=case_id, seed=experiment_seed)
                    cases[context] = candidate
        except (ValueError, RuntimeError) as error:
            cases.pop(context, None)
            st.error(f"No se pudo abrir el expediente: {error}")
    case = cases.get(context)
    if case is not None:
        try:
            validate_case(case, template_id=case_id, seed=experiment_seed)
            record = get_record(session, case)
            view = public_case(case, record)
            phase = view["phase"]
            status = "Respuesta registrada" if phase in record["answers"] else "En investigación"
            if visible_solution(case, record) is not None:
                status += " · solución consultada"
            st.markdown(f'<div class="small-label">{escape(status)} · {escape(view["version"])}</div>', unsafe_allow_html=True)
            if phase == "expanded":
                st.info("Has recibido nueva evidencia. Completa el diagnóstico con esta información; la respuesta inicial se conserva en el informe.")
            st.write(view["story"])
            brief_card(view["objective"], view["prediction_time"])
            _evidence(view)
            _hints(session, case, record, view)
            st.download_button("↓ Descargar evidencia disponible · JSON", _json(view), file_name=f"detective_{case_id}_{experiment_seed}_evidencia.json", mime="application/json", on_click="ignore", key="detective_download_evidence")
            st.divider()
            action = _answer(session, case, record, view)
            st.divider()
            _solution(session, case, record, action)
            st.download_button("↓ Descargar investigación · JSON", export_investigation(session, case), file_name=f"detective_{case_id}_{experiment_seed}_investigacion.json", mime="application/json", on_click="ignore", key="detective_download_investigation")
            st.button("Siguiente expediente", on_click=_next_case, key="detective_next")
        except ValueError as error:
            cases.pop(context, None)
            st.error(f"El expediente no corresponde a esta configuración o fue alterado: {error}. Ábrelo de nuevo.")
    else:
        st.write(TEMPLATES[case_id]["story"])
        st.info("Pulsa «Abrir expediente» para calcular su informe e inspeccionar las pruebas. La solución permanece oculta hasta que decidas revelarla.")
    st.divider()
    _summary(session)
    environment = "Investigación en el servidor" if public_demo else "Investigación local"
    st.markdown(f'<div class="lab-footer">{environment} con datos sintéticos. Las descargas evitan spoilers involuntarios; el código público puede inspeccionarse. Las conclusiones se limitan a los mecanismos investigados.</div>', unsafe_allow_html=True)
