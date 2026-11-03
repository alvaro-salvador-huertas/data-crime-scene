"""Exploración local: una ejecución solicitada o un estudio previamente guardado.

Este módulo presenta resultados del motor; no lanza el estudio completo.
"""

import json
from pathlib import Path

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from ui.presentation import caption
from ui.public_limits import PublicLimitError, public_action

from data_crime_scene.cases import CASES
from data_crime_scene.laboratory import (
    LAB_CASES,
    engine_fingerprint,
    run_lab_experiment,
    validate_lab_result,
)
from data_crime_scene.study import (
    load_study,
    paired_differences,
    study_rows,
    validate_study,
)
from ui.plotly_theme import INK, MUTED, TEAL, VIOLET, apply_template


PROJECT = Path(__file__).resolve().parents[1]
PUBLIC_STUDY = PROJECT / "demo" / "study.json"
METRICS = {"balanced_accuracy": "Balanced accuracy", "accuracy": "Accuracy", "f1": "F1"}
COLORS = {"incorrect": "#8A530C", "correct": TEAL, "control": VIOLET, "baseline": MUTED}
VARIANTS = {
    "future": {"incorrect": "Con dato posterior", "correct": "Solo legítimas", "control": "Control irrelevante", "baseline": "Baseline"},
    "groups": {"incorrect": "Partición por filas", "correct": "Partición por grupos", "baseline": "Baseline"},
    "selection": {"incorrect": "Selección global", "correct": "Selección en train", "baseline": "Baseline"},
}
COMPARISONS = {
    "incorrect-correct": "Sospechoso − corregido",
    "control-correct": "Control − legítimas",
    "correct-baseline": "Corregido − baseline",
    "incorrect_minus_correct": "Sospechoso − corregido",
    "control_minus_correct": "Control − legítimas",
    "correct_minus_baseline": "Corregido − baseline",
}


def json_payload(value: dict) -> str:
    return json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False)


@st.cache_data(show_spinner=False, max_entries=48)
def cached_lab_experiment(case_id: str, seed: int, level: float | int, fingerprint: str) -> dict:
    """La huella del código forma parte de la clave junto a todos los controles."""
    if fingerprint != engine_fingerprint():
        raise ValueError("La versión del motor cambió. Vuelve a ejecutar la configuración.")
    return run_lab_experiment(case_id, seed, level)


def table_metrics(result: dict, case_id: str, evaluation: str = "internal") -> pd.DataFrame:
    source = result["variants"] if evaluation == "internal" else result["cohort"]
    rows = []
    for key, variant in source.items():
        rows.append({"Modelo": VARIANTS[case_id].get(key, key), **{label: f"{variant['metrics'][metric]:.1%}" for metric, label in METRICS.items()}})
        if case_id == "groups":
            rows.append({"Modelo": f"Baseline · {VARIANTS[case_id].get(key, key).lower()}", **{label: f"{variant['baseline_metrics'][metric]:.1%}" for metric, label in METRICS.items()}})
    if case_id != "groups":
        baseline = source["correct"]["baseline_metrics"]
        rows.append({"Modelo": "Baseline · clase mayoritaria en train", **{label: f"{baseline[metric]:.1%}" for metric, label in METRICS.items()}})
    return pd.DataFrame(rows)


def _composition(result: dict, case_id: str) -> pd.DataFrame:
    rows = []
    for key, variant in result["variants"].items():
        distribution = variant["diagnostics"].get("class_distribution", {})
        for split in ("train", "test"):
            counts = distribution.get(split, {})
            rows.append({
                "Modelo": VARIANTS[case_id].get(key, key), "Conjunto": split,
                "Filas": variant.get(f"{split}_size", len(variant[f"{split}_row_ids"])),
                "Clase 0": counts.get("count0"), "Clase 1": counts.get("count1"),
                "Proporción positiva": counts.get("positive_rate"),
                "Entidades": variant["diagnostics"].get(f"{split}_entity_count"),
            })
    return pd.DataFrame(rows).dropna(axis=1, how="all")


def _chart_style(figure: go.Figure, title: str, delta: bool = False) -> go.Figure:
    figure = apply_template(figure)
    figure.update_layout(
        title={"text": title, "font": {"size": 16}},
        height=460,
        paper_bgcolor="#FFFFFF", plot_bgcolor="#FFFFFF",
        font={"family": "Arial, Helvetica, sans-serif", "color": INK, "size": 12},
        margin={"l": 10, "r": 12, "t": 65, "b": 155},
        legend={"orientation": "h", "yanchor": "top", "y": -0.34, "x": 0, "font": {"size": 11}},
        xaxis={"title": {"text": "Nivel del factor", "standoff": 12}, "type": "category", "tickangle": 0},
        yaxis={"title": "Diferencia de puntuación" if delta else "Puntuación", "tickformat": "+.0%" if delta else ".0%", "gridcolor": "#DCE3E7"},
        boxmode="group",
    )
    if delta:
        figure.add_hline(y=0, line_color=MUTED, line_dash="dash", line_width=1)
    else:
        figure.update_yaxes(range=[-0.03, 1.04])
    return figure


def distribution_chart(rows: list[dict], case_id: str, metric: str, evaluation: str) -> go.Figure:
    """Una caja por nivel/modelo; cada punto corresponde a una semilla completa."""
    selected = [row for row in rows if row["evaluation"] == evaluation or (evaluation == "internal" and row["evaluation"] == "baseline")]
    figure = go.Figure()
    for key in dict.fromkeys(row["variant"] for row in selected):
        subset = [row for row in selected if row["variant"] == key]
        figure.add_trace(_precomputed_box(subset, metric, VARIANTS[case_id].get(key, key), COLORS.get(key, MUTED)))
    scope = "test interno" if evaluation == "internal" else "cohorte nueva común"
    return _chart_style(figure, f"{METRICS[metric]} · {scope}")


def _precomputed_box(rows: list[dict], value_key: str, name: str, color: str) -> go.Box:
    """Plotly y pandas usan fórmulas distintas al llamar 'linear' al cuartil.

    Se proporcionan explícitamente los mismos cuartiles que usa la tabla.
    La matriz 2D conserva todos los puntos individuales dentro de cada caja.
    """
    levels = list(dict.fromkeys(row["level"] for row in rows))
    grouped = [[row for row in rows if row["level"] == level] for level in levels]
    values = [[row[value_key] for row in group] for group in grouped]
    summaries = [pd.Series(value, dtype=float) for value in values]
    return go.Box(
        name=name, x=[str(level) for level in levels], y=values,
        q1=[float(series.quantile(.25, interpolation="linear")) for series in summaries],
        median=[float(series.median()) for series in summaries],
        q3=[float(series.quantile(.75, interpolation="linear")) for series in summaries],
        lowerfence=[min(value) for value in values], upperfence=[max(value) for value in values],
        # El validador de strings de Plotly convierte listas 2D en strings;
        # ndarray(object) conserva las etiquetas individuales por caja.
        text=np.asarray([[f"Semilla {row['seed']}" for row in group] for group in grouped], dtype=object),
        marker={"color": color, "size": 4}, line={"color": color},
        fillcolor="rgba(77,99,112,.08)", boxpoints="all", jitter=.25, pointpos=0,
        hovertemplate="%{text}<br>Nivel %{x}<br>%{y:+.3f}<extra>%{fullData.name}</extra>",
    )


def summary_table(rows: list[dict], metric: str, case_id: str) -> pd.DataFrame:
    frame = pd.DataFrame(rows)
    if frame.empty:
        return frame
    summary = []
    for (evaluation, level, variant), group in frame.groupby(["evaluation", "level", "variant"], sort=False):
        values = group[metric]
        summary.append({
            "Evaluación": {"internal": "Test interno", "cohort": "Cohorte nueva", "baseline": "Baseline interno"}.get(evaluation, evaluation),
            "Nivel": level, "Modelo": VARIANTS[case_id].get(variant, variant), "Semillas válidas": len(group),
            "Q1": values.quantile(.25, interpolation="linear"),
            "Mediana": values.median(), "Q3": values.quantile(.75, interpolation="linear"),
            "Mínimo": values.min(), "Máximo": values.max(),
        })
    return pd.DataFrame(summary)


def differences_chart(rows: list[dict], case_id: str) -> go.Figure:
    figure = go.Figure()
    for index, comparison in enumerate(dict.fromkeys(row["comparison"] for row in rows)):
        subset = [row for row in rows if row["comparison"] == comparison]
        color = ["#8A530C", VIOLET, TEAL][index % 3]
        figure.add_trace(_precomputed_box(subset, "delta", COMPARISONS.get(comparison, comparison), color))
    return _chart_style(figure, "Diferencias emparejadas · balanced accuracy", delta=True)


def differences_summary(rows: list[dict]) -> pd.DataFrame:
    summary = []
    frame = pd.DataFrame(rows)
    if frame.empty:
        return frame
    for (level, comparison), group in frame.groupby(["level", "comparison"], sort=False):
        values = group["delta"]
        summary.append({
            "Nivel": level, "Comparación": comparison, "Semillas válidas": len(values),
            "Q1": values.quantile(.25, interpolation="linear"), "Mediana": values.median(),
            "Q3": values.quantile(.75, interpolation="linear"), "Mínimo": values.min(), "Máximo": values.max(),
        })
    return pd.DataFrame(summary)


def render_single_result(result: dict, case_id: str) -> None:
    st.header("Resultado de la configuración")
    config = result["config"]
    caption(f"Ejecución puntual solicitada en esta sesión · semilla {config['seed']} · nivel {config['level']}. Una configuración idéntica puede reutilizarse desde la caché en memoria del proceso.")
    st.dataframe(table_metrics(result, case_id), hide_index=True, width="stretch")
    caption("Las métricas proceden de las predicciones de esta ejecución. Corregido significa que se elimina el mecanismo estudiado; no certifica la ausencia de cualquier otro problema.")
    if case_id == "future":
        st.info("La variable posterior sigue sin existir al confirmar la compra en los tres niveles. Con inversión 0,5 no aporta señal predictiva por construcción; disponibilidad temporal y ganancia observada son preguntas diferentes.")
        st.dataframe(pd.DataFrame(result["feature_catalog"]), hide_index=True, width="stretch")
        clean = result["variants"]["correct"]["metrics"]["balanced_accuracy"]
        posterior = result["variants"]["incorrect"]["metrics"]["balanced_accuracy"]
        control = result["variants"]["control"]["metrics"]["balanced_accuracy"]
        st.write(f"**Observado en esta semilla:** posterior − legítimas = {(posterior-clean)*100:+.1f} puntos porcentuales; control − legítimas = {(control-clean)*100:+.1f} puntos porcentuales de balanced accuracy.")
    if case_id == "groups":
        st.markdown("**Evaluación interna · objetivo: entidades nuevas**")
        for key in ("incorrect", "correct"):
            shared = result["variants"][key]["diagnostics"]["shared_entity_count"]
            st.write(f"{VARIANTS[case_id][key]}: **{shared} entidades compartidas** entre train y test.")
        st.dataframe(_composition(result, case_id), hide_index=True, width="stretch")
        st.markdown("**Cohorte separada de entidades nuevas · los dos modelos ya ajustados**")
        st.dataframe(table_metrics(result, case_id, "cohort"), hide_index=True, width="stretch")
        for key, cohort in result["cohort"].items():
            caption(f"{VARIANTS[case_id][key]}: {cohort['n_samples']} observaciones / {cohort['n_entities']} entidades nuevas · composición {cohort['class_distribution']}.")
        st.warning("Los test internos contienen observaciones distintas. En la cohorte común sí se comparan las mismas observaciones, pero los modelos se entrenaron con distinta composición y diversidad de máquinas. La diferencia no aísla un efecto causal puro de la fuga.")
    if case_id == "selection":
        st.info("Control sin señal: las etiquetas son independientes de todas las variables por construcción. k=25 permanece fijo; el número de variables candidatas cambia sin consultar test para elegir k.")
        for key in ("incorrect", "correct"):
            count = result["variants"][key]["diagnostics"]["selector_test_rows_seen"]
            st.write(f"{VARIANTS[case_id][key]}: **{count} filas de test consultadas durante el ajuste del selector**.")
    with st.expander("Datos, tamaños y configuración de esta ejecución"):
        st.dataframe(pd.DataFrame(result["data_preview"]), hide_index=True, width="stretch")
        st.dataframe(_composition(result, case_id), hide_index=True, width="stretch")
        st.json({key: result[key] for key in ("config", "generator_params", "protocol", "runtime", "engine_fingerprint", "protocol_hash", "diagnostics")}, expanded=False)
    with st.expander("Etiquetas, predicciones y matrices"):
        for key, variant in result["variants"].items():
            st.markdown(f"**{VARIANTS[case_id].get(key, key)}**")
            caption("Matriz: filas = etiqueta real; columnas = predicción, ambas en orden 0, 1.")
            st.dataframe(pd.DataFrame(variant["confusion_matrix"], index=["Real 0", "Real 1"], columns=["Predicho 0", "Predicho 1"]), width="stretch")
            st.dataframe(pd.DataFrame({"fila": variant["test_row_ids"], "real": variant["y_true"], "predicción": variant["y_pred"]}).head(12), hide_index=True, width="stretch")
    st.download_button("↓ Descargar ejecución puntual · JSON", json_payload(result), file_name=f"laboratorio_{case_id}_seed-{config['seed']}_nivel-{config['level']}.json", mime="application/json", key="lab_download_run", on_click="ignore")


def render_study(study: dict, source_path: str, case_id: str, metric: str) -> None:
    # Se valida de nuevo antes de mostrar y serializar; nunca se reconstruye otro informe.
    validate_study(study)
    entries = study["entries"]
    valid = [entry for entry in entries if entry["status"] == "ok"]
    errors = [entry for entry in entries if entry["status"] != "ok"]
    st.markdown("### Estudio cargado · resultados calculados anteriormente")
    caption("Los controles laterales configuran la ejecución puntual. Este estudio conserva sus tres niveles y diez semillas fijados previamente para cada caso.")
    caption(f"Procedencia: {source_path}")
    st.write(f"**Generado:** {study['created_at']} · **Combinaciones previstas:** {len(entries)} · **Válidas:** {len(valid)} · **Errores:** {len(errors)}.")
    caption(f"Motor {study['engine_fingerprint']} · protocolo {study['protocol_hash']}")
    with st.expander("Procedencia, semillas y versiones del estudio"):
        st.json({key: study[key] for key in ("schema_version", "created_at", "protocol", "runtime", "engine_fingerprint", "protocol_hash")}, expanded=False)
    if errors:
        st.error(f"El estudio contiene {len(errors)} errores de ejecución. Se conservan en el informe y no se convierten en puntuaciones.")
        st.dataframe(pd.DataFrame([{"Configuración": json_payload(entry["config"]), "Error": str(entry.get("error", "Error sin detalle"))} for entry in errors]), hide_index=True, width="stretch")
    rows = study_rows(study, case_id)
    if rows:
        caption("Cada punto representa una semilla completa. Las cajas muestran mediana y cuartiles (Q1–Q3, interpolación lineal de pandas); los bigotes van del mínimo al máximo. Describen estas semillas y no son intervalos de confianza. No se combinan filas de distintas ejecuciones como observaciones independientes.")
        st.plotly_chart(distribution_chart(rows, case_id, metric, "internal"), theme=None, width="stretch", config={"displayModeBar": False}, key="lab_study_internal")
        if case_id == "groups":
            st.warning("La comparación interna por filas frente a grupos no está emparejada. Consulta abajo la composición de cada partición; no atribuyas toda la diferencia a la fuga.")
            st.plotly_chart(distribution_chart(rows, case_id, metric, "cohort"), theme=None, width="stretch", config={"displayModeBar": False}, key="lab_study_cohort")
        st.markdown(f"**Resumen observado · {METRICS[metric]}**")
        st.dataframe(summary_table(rows, metric, case_id), hide_index=True, width="stretch", column_config={name: st.column_config.NumberColumn(format="%.3f") for name in ("Q1", "Mediana", "Q3", "Mínimo", "Máximo")})
        deltas = paired_differences(study, case_id)
        if deltas:
            st.plotly_chart(differences_chart(deltas, case_id), theme=None, width="stretch", config={"displayModeBar": False}, key="lab_study_differences")
            caption("Los deltas usan balanced accuracy, la métrica principal fijada previamente. Un delta de 0,05 equivale a 5 puntos porcentuales. Solo se emparejan evaluaciones con las mismas filas y etiquetas; en grupos se usa exclusivamente la cohorte nueva común.")
            st.dataframe(differences_summary(deltas), hide_index=True, width="stretch", column_config={name: st.column_config.NumberColumn(format="%+.3f") for name in ("Q1", "Mediana", "Q3", "Mínimo", "Máximo")})
            if case_id == "groups":
                caption("Emparejar las predicciones de cohorte no iguala los entrenamientos. El delta describe estos dos modelos, sin identificar una cantidad pura de fuga.")
            with st.expander("Diferencias individuales por semilla"):
                st.dataframe(pd.DataFrame(deltas), hide_index=True, width="stretch")
        st.markdown("**Resultados individuales · sin filtrar por puntuación**")
        st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch")
        with st.expander("Diagnósticos, tamaños y composición por configuración"):
            details = []
            for entry in valid:
                result = entry["result"]
                if result["config"]["case_id"] != case_id:
                    continue
                for key, variant in result["variants"].items():
                    diagnostics = variant["diagnostics"]
                    composition = diagnostics.get("class_distribution", {})
                    details.append({
                        "Semilla": result["config"]["seed"], "Nivel": result["config"]["level"], "Modelo": VARIANTS[case_id].get(key, key),
                        "Train": len(variant["train_row_ids"]), "Test": len(variant["test_row_ids"]),
                        "Train · clase 0": composition.get("train", {}).get("count0"),
                        "Train · clase 1": composition.get("train", {}).get("count1"),
                        "Test · clase 0": composition.get("test", {}).get("count0"),
                        "Test · clase 1": composition.get("test", {}).get("count1"),
                        "Entidades compartidas": diagnostics.get("shared_entity_count"),
                        "Filas de test vistas por selector": diagnostics.get("selector_test_rows_seen"),
                        "Diagnóstico específico de fuga": diagnostics.get("leakage_detected"),
                    })
            st.dataframe(pd.DataFrame(details).dropna(axis=1, how="all"), hide_index=True, width="stretch")
    else:
        st.warning("No hay ejecuciones válidas para este caso. Los errores permanecen en el informe completo.")
    st.download_button("↓ Descargar estudio cargado completo · JSON", json_payload(study), file_name="laboratorio-estudio.json", mime="application/json", key="lab_download_study", on_click="ignore", help="Descarga el mismo estudio del que proceden los puntos y tablas, incluidos todos sus casos y errores.")


def _study_controls(public_demo: bool) -> None:
    if st.session_state.get("lab_study_public_demo") != public_demo:
        st.session_state["lab_study_public_demo"] = public_demo
        st.session_state.pop("lab_study", None)
        st.session_state.pop("lab_study_source", None)
    if public_demo:
        if not PUBLIC_STUDY.is_file():
            st.session_state.pop("lab_study", None)
            st.info("Esta demo no incluye un estudio agregado. Puedes ejecutar configuraciones puntuales reales con los controles laterales.")
        elif st.button("Cargar estudio de la demo", key="lab_load_public_study"):
            try:
                with public_action(public_demo):
                    st.session_state.pop("lab_study", None)
                    st.session_state["lab_study"] = load_study(PUBLIC_STUDY)
                    st.session_state["lab_study_source"] = "Estudio incluido en la demo"
            except PublicLimitError as error:
                st.warning(str(error))
            except (ValueError, OSError):
                st.warning("El estudio de la demo no está disponible o no es compatible con este entorno. La ejecución puntual sigue disponible.")
        return
    st.write("Carga resultados ya calculados para observar su variabilidad. El estudio completo se ejecuta con un comando separado y conserva también los errores.")
    with st.expander("Comandos de comprobación de coste y ejecución del estudio"):
        st.code(".venv/bin/python -m data_crime_scene.study --preflight\n.venv/bin/python -m data_crime_scene.study --output artifacts/laboratory-study.json", language="bash")
    study_path = st.text_input("Archivo local del estudio", value="artifacts/laboratory-study.json", key="lab_study_path")
    if st.session_state.get("lab_study_requested_path") != study_path:
        st.session_state["lab_study_requested_path"] = study_path
        st.session_state.pop("lab_study", None)
        st.session_state.pop("lab_study_source", None)
    if st.button("Cargar estudio local", key="lab_load_study"):
        st.session_state.pop("lab_study", None)
        try:
            resolved = (PROJECT / study_path).resolve()
            if not resolved.is_relative_to(PROJECT):
                raise ValueError("El archivo debe estar dentro del proyecto.")
            with st.spinner("Cargando y verificando protocolo, versiones, predicciones y configuración…"):
                study = load_study(resolved)
                st.session_state["lab_study"] = study
                st.session_state["lab_study_source"] = str(resolved)
        except (ValueError, OSError) as error:
            st.error(f"No se ha cargado el estudio: {error}")


def render_laboratory(*, public_demo: bool = False) -> None:
    fingerprint = engine_fingerprint()
    with st.sidebar, st.container(key="dcs_lab_controls"):
        st.markdown('<div class="brand-label">DCS / Laboratorio experimental</div>', unsafe_allow_html=True)
        case_id = st.selectbox("Caso de laboratorio", list(LAB_CASES), format_func=lambda key: CASES[key].title, key="lab_case_selector")
        spec = LAB_CASES[case_id]
        level = st.select_slider(spec["label"], options=spec["levels"], value=spec["levels"][1], key=f"lab_level_{case_id}")
        seed = int(st.number_input("Semilla puntual", min_value=0, max_value=2**32-1, value=42, step=1, key="lab_seed_input"))
        run = st.button("Ejecutar configuración", type="primary", width="stretch", key="lab_run")
        caption("Este botón ejecuta una combinación; abrir la vista no entrena modelos ni lanza el estudio de 90 combinaciones.")
    st.markdown('<div class="eyebrow">Tres mecanismos · controles · variabilidad</div>', unsafe_allow_html=True)
    st.title("Laboratorio")
    st.write("Explora la intensidad del problema y comprueba qué sostienen los resultados. La hipótesis didáctica y las observaciones se presentan por separado.")
    st.header(CASES[case_id].title)
    st.write(spec["description"])
    st.markdown(f"**Objetivo:** {CASES[case_id].objective}")
    caption(f"Clase positiva: {CASES[case_id].positive_class}")
    expectation = spec["expectation"].removeprefix("Hipótesis didáctica: ")
    st.info(f"Hipótesis didáctica que se pone a prueba: {expectation}")
    caption(f"Métrica principal: balanced accuracy · niveles fijados: {', '.join(map(str, spec['levels']))} · semilla puntual {seed}.")
    context = (case_id, seed, level, fingerprint)
    if st.session_state.get("lab_context") != context:
        st.session_state["lab_context"] = context
        st.session_state.pop("lab_result", None)
    if run:
        try:
            with public_action(public_demo), st.spinner("Generando los controles, entrenando y evaluando esta configuración…"):
                st.session_state.pop("lab_result", None)
                candidate = cached_lab_experiment(case_id, seed, level, fingerprint)
                validate_lab_result(candidate, case_id=case_id, seed=seed, level=level)
                st.session_state["lab_result"] = candidate
        except PublicLimitError as error:
            st.warning(str(error))
        except (ValueError, RuntimeError) as error:
            clear = getattr(cached_lab_experiment, "clear", None)
            if callable(clear):
                clear(case_id, seed, level, fingerprint)
            st.error(f"No se muestra la ejecución: {error}")
    result = st.session_state.get("lab_result")
    if result is not None:
        try:
            validate_lab_result(result, case_id=case_id, seed=seed, level=level)
            render_single_result(result, case_id)
        except ValueError as error:
            clear = getattr(cached_lab_experiment, "clear", None)
            if callable(clear):
                clear(case_id, seed, level, fingerprint)
            st.session_state.pop("lab_result", None)
            st.error(f"Resultado incompatible o alterado; vuelve a ejecutar: {error}")
    else:
        st.info("Elige nivel y semilla y pulsa «Ejecutar configuración». Los resultados anteriores se retiran al cambiar los controles.")
    st.warning(spec["caveat"])
    st.divider()
    st.header("Estudio predefinido · tres niveles y diez semillas")
    _study_controls(public_demo)
    metric = st.selectbox("Métrica del resumen del estudio", list(METRICS), format_func=METRICS.get, key="lab_study_metric")
    study = st.session_state.get("lab_study")
    if study is not None:
        try:
            render_study(study, st.session_state["lab_study_source"], case_id, metric)
        except ValueError as error:
            st.session_state.pop("lab_study", None)
            if public_demo:
                st.warning("El estudio de la demo no es compatible con este entorno. La ejecución puntual sigue disponible.")
            else:
                st.error(f"Estudio incompatible o alterado; vuelve a cargarlo: {error}")
    else:
        caption("No hay un estudio cargado. La ejecución puntual y el estudio guardado mantienen procedencias y resultados separados.")
    st.markdown('<div class="lab-footer">Datos sintéticos y modelos pequeños en CPU. Ninguna puntuación certifica un experimento completo ni acredita rendimiento en producción.</div>', unsafe_allow_html=True)
