"""Interfaz local. El motor de los experimentos se ejecuta también sin Streamlit."""

from html import escape

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from data_crime_scene.cases import CASES
from data_crime_scene.laboratory import engine_fingerprint
from data_crime_scene.experiments import run_experiment
from data_crime_scene.validation import validate_result
from ui.presentation import brief_card, caption, load_styles, skip_link
from ui.plotly_theme import apply_template, INK, TEAL


METRICS = {
    "accuracy": "Accuracy",
    "balanced_accuracy": "Balanced accuracy",
    "f1": "F1 · clase positiva",
}
COLORS = {"incorrect": "#8A530C", "correct": TEAL}
LABELS = {"incorrect": "⚠ Procedimiento contaminado", "correct": "✓ Procedimiento corregido"}


@st.cache_data(show_spinner=False, max_entries=24)
def cached_experiment(case_id: str, seed: int, fingerprint: str):
    """Datos sintéticos compartidos por copia; clave con contexto y motor."""
    if fingerprint != engine_fingerprint():
        raise ValueError("La versión del motor cambió. Vuelve a ejecutar el experimento.")
    return run_experiment(case_id, seed)


def section(number: str, title: str) -> None:
    st.markdown(f'<div class="section-kicker">{number} / EXPEDIENTE</div>', unsafe_allow_html=True)
    st.header(title)


def render_metrics(variant) -> None:
    for column, (key, label) in zip(st.columns(3), METRICS.items()):
        column.metric(label, f"{variant.metrics[key]:.1%}", border=True)


def metric_chart(result) -> go.Figure:
    figure = go.Figure()
    for key in ("incorrect", "correct"):
        variant = result.variants[key]
        figure.add_bar(
            name=LABELS[key],
            x=list(METRICS.values()),
            y=[variant.metrics[metric] for metric in METRICS],
            marker_color=COLORS[key],
            text=[f"{variant.metrics[metric]:.1%}" for metric in METRICS],
            textposition="outside",
            hovertemplate="%{x}: %{y:.1%}<extra>%{fullData.name}</extra>",
        )
    figure.update_layout(
        title="Evaluación en test · dos procedimientos",
        barmode="group", height=450,
        paper_bgcolor="#FFFFFF", plot_bgcolor="#FFFFFF",
        font={"family": "Arial, sans-serif", "color": INK, "size": 12},
        margin={"l": 10, "r": 10, "t": 65, "b": 150},
        legend={"orientation": "h", "y": -0.36, "yanchor": "top", "x": 0, "font": {"size": 11}},
        yaxis={"title": "Puntuación (0–1)", "range": [0, 1.15], "tickformat": ".0%", "gridcolor": "#DCE3E7"},
        xaxis={
            "title": {"text": "Métrica", "standoff": 12},
            "tickmode": "array", "tickvals": list(METRICS.values()),
            "ticktext": ["Accuracy", "Balanced<br>accuracy", "F1"], "tickangle": 0,
        },
    )
    return apply_template(figure)


def render_evidence(case, result) -> None:
    section("02", "Las pruebas")
    st.write("Inspecciona las filas y el origen de los datos. El objetivo es encontrar qué información cruzó la frontera de la evaluación.")
    data = pd.DataFrame(result.data_preview)
    caption(f"Datos sintéticos · muestra de {len(data)} filas. Train es entrenamiento; test es evaluación.")
    st.dataframe(data, hide_index=True, width="stretch")
    if result.feature_catalog:
        with st.expander("Registro de variables y disponibilidad"):
            catalog = pd.DataFrame(result.feature_catalog)
            # La cronología es evidencia; el diagnóstico se reserva para la solución.
            visible = [col for col in ("variable", "available_at") if col in catalog.columns]
            st.dataframe(catalog[visible].rename(columns={"variable": "Variable", "available_at": "Cuándo existe"}), hide_index=True, width="stretch")
    incorrect = result.variants["incorrect"]
    with st.expander("Partición y modelo del informe inicial"):
        st.write(f"**Partición:** {incorrect.split_type}")
        st.write(f"**Filas:** {len(incorrect.train_row_ids)} en train · {len(incorrect.test_row_ids)} en test.")
        st.write("**Variables predictivas:** " + ", ".join(f"`{name}`" for name in incorrect.feature_names))
        st.json(incorrect.model, expanded=False)
        if case.id == "groups":
            shared = incorrect.diagnostics.get("shared_entity_count", 0)
            st.warning(f"{shared} entidades aparecen en train y en test en esta partición.")
        if case.id == "selection":
            stages = pd.DataFrame(incorrect.fit_stages).drop(columns=["row_ids"], errors="ignore")
            stages["fit_scope"] = stages["fit_scope"].str.replace(" (contaminado)", "", regex=False)
            st.dataframe(
                stages,
                hide_index=True, width="stretch",
            )
    st.markdown("**Pistas · ábrelas en orden si las necesitas**")
    for index, hint in enumerate(case.hints, 1):
        with st.expander(f"Pista {index}"):
            st.write(hint)


def render_comparison(case, result) -> None:
    section("04", "La explicación")
    st.write(case.explanation)
    st.info("Data leakage o fuga de información: datos que el procedimiento no debería conocer influyen en el entrenamiento o en la evaluación.")
    section("05", "La corrección")
    st.write(case.correction)
    caption("Corregido significa que se elimina el mecanismo estudiado; no certifica la ausencia de cualquier otra fuga o limitación.")
    st.markdown(f"**Qué cambia y qué se mantiene:** {result.protocol['comparison']}")
    with st.expander("Inventario de variables · procedimiento sospechoso y corregido"):
        st.dataframe(pd.DataFrame(result.feature_catalog).rename(columns={
            "variable": "Variable", "available_at": "Cuándo existe", "role": "Procedencia",
            "used_in_incorrect": "Incluida · sospechoso", "used_in_correct": "Incluida · corregido",
        }), hide_index=True, width="stretch")
    left, right = st.columns(2, gap="large")
    for column, key in ((left, "incorrect"), (right, "correct")):
        variant = result.variants[key]
        with column:
            css_class = "status-suspect" if key == "incorrect" else "status-correct"
            st.markdown(f'<span class="status-label {css_class}">{escape(LABELS[key])}</span>', unsafe_allow_html=True)
            caption(f"{len(variant.train_row_ids)} train / {len(variant.test_row_ids)} test · {len(variant.feature_names)} variables")
            st.write(f"**Partición:** {variant.split_type}")
            if case.id == "groups":
                st.metric("Entidades compartidas entre train y test", variant.diagnostics["shared_entity_count"])
            if case.id == "selection":
                st.metric("Filas de test consultadas por el selector", variant.diagnostics["selector_test_rows_seen"])
            with st.expander("Etapas y datos utilizados para ajustar"):
                st.dataframe(pd.DataFrame(variant.fit_stages).drop(columns=["row_ids"], errors="ignore"), hide_index=True, width="stretch")
            st.code(case.code_wrong if key == "incorrect" else case.code_correct, language="python")
    for note in result.teaching_notes:
        st.markdown(f"- {note}")
    section("06", "La comparación")
    st.plotly_chart(metric_chart(result), theme=None, width="stretch", config={"displayModeBar": False})
    rows = []
    for key in ("incorrect", "correct"):
        variant = result.variants[key]
        rows.append({"Evaluación": LABELS[key], **{label: f"{variant.metrics[metric]:.1%}" for metric, label in METRICS.items()}})
        if case.id == "groups":
            baseline_label = "por filas" if key == "incorrect" else "por entidades"
            rows.append({"Evaluación": f"Baseline · partición {baseline_label}", **{label: f"{variant.baseline_metrics[metric]:.1%}" for metric, label in METRICS.items()}})
    if case.id != "groups":
        baseline = result.variants["correct"].baseline_metrics
        rows.append({"Evaluación": "Baseline · clase mayoritaria en train", **{label: f"{baseline[metric]:.1%}" for metric, label in METRICS.items()}})
    st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch")
    caption("Baseline: modelo que siempre predice la clase más frecuente en train. Ayuda a situar las puntuaciones.")
    with st.expander("Cómo leer las métricas y las matrices de confusión"):
        st.write(f"**Clase positiva (1):** {case.positive_class}")
        st.write("**Accuracy:** proporción total de aciertos. **Balanced accuracy:** media del acierto en cada clase; da el mismo peso a ambas. **F1:** combina precisión y sensibilidad de la clase positiva; no cuenta los verdaderos negativos.")
        caption("Matrices calculadas con las predicciones reales. Filas: etiqueta real. Columnas: etiqueta predicha.")
        for column, key in zip(st.columns(2), ("incorrect", "correct")):
            with column:
                st.markdown(f"**{LABELS[key]}**")
                matrix = pd.DataFrame(result.variants[key].confusion_matrix, index=["Real 0", "Real 1"], columns=["Predicho 0", "Predicho 1"])
                st.dataframe(matrix, width="stretch")
    st.warning(case.comparison_caveat)
    caption("Una puntuación menor no demuestra que un experimento sea correcto. Evalúa el mecanismo, la disponibilidad de los datos y el objetivo de generalización.")
    with st.expander("Protocolo y diagnósticos reproducibles"):
        st.json({"caso": result.case_id, "semilla": result.seed, "generador": result.generator_params, "protocolo": result.protocol, "diagnosticos": result.diagnostics}, expanded=False)
    st.download_button(
        "↓ Descargar informe completo · JSON", data=result.to_json(),
        file_name=f"data-crime-scene_{result.case_id}_seed-{result.seed}.json",
        mime="application/json", key="download_report", on_click="ignore",
        help="Incluye el protocolo, las filas, etiquetas, predicciones, métricas y diagnósticos del mismo resultado que muestra la interfaz.",
    )


def main(*, public_demo: bool = False) -> None:
    st.set_page_config(page_title="Data Crime Scene · laboratorio", page_icon="🔎", layout="wide", initial_sidebar_state="auto")
    load_styles()
    skip_link()
    with st.container(key="dcs_root"):
        if public_demo:
            caption("Demo pública · datos sintéticos · cálculo en el servidor. Sin cuentas; el progreso de esta sesión no es persistente.")
        _render_main(public_demo=public_demo)


def _render_main(*, public_demo: bool = False) -> None:
    with st.sidebar, st.container(key="dcs_navigation"):
        mode = st.radio("Modo", ["Recorrido guiado", "Laboratorio", "Modo Detective"], key="mode_selector")
    if mode == "Modo Detective":
        from ui.detective import render_detective

        render_detective(public_demo=public_demo)
        return
    if mode == "Laboratorio":
        from ui.laboratory import render_laboratory

        render_laboratory(public_demo=public_demo)
        return
    case_ids = list(CASES)
    with st.sidebar, st.container(key="dcs_guided_controls"):
        label = "Demo pública" if public_demo else "Laboratorio local"
        st.markdown(f'<div class="brand-label">DCS / {label}</div>', unsafe_allow_html=True)
        st.markdown("### Mesa de investigación")
        caption("Tres expedientes. Tres formas de contaminar una evaluación.")
        case_id = st.selectbox("Expediente", case_ids, format_func=lambda value: f"{case_ids.index(value) + 1:02d} · {CASES[value].title}", key="case_selector")
        seed = int(st.number_input("Semilla del experimento", min_value=0, max_value=2**32 - 1, value=42, step=1, key="seed_input", help="La misma semilla y el mismo caso reproducen los datos, la partición y los resultados."))
        caption("Semillas de comprobación: 7 · 42 · 2026. Puedes explorar otras sin buscar una caída concreta.")
        run = st.button("Ejecutar experimento", type="primary", width="stretch", key="run_experiment")
        environment = "CPU DEL SERVIDOR<br>Alojamiento externo; sin cuentas de la aplicación." if public_demo else "CPU LOCAL<br>Sin cuentas ni servicios externos."
        st.markdown(f'<div class="sidebar-footer">DATOS SINTÉTICOS · {environment}<br>Las interacciones reutilizan el resultado; el entrenamiento comienza al ejecutar.</div>', unsafe_allow_html=True)
    fingerprint = engine_fingerprint()
    context = (case_id, seed, fingerprint)
    if st.session_state.get("active_context") != context:
        st.session_state["parameters_changed"] = "active_context" in st.session_state
        st.session_state["active_context"] = context
        st.session_state.pop("result", None)
        st.session_state["revealed"] = False
    case = CASES[case_id]
    st.markdown('<div class="eyebrow">Laboratorio de errores de evaluación · recorrido guiado</div>', unsafe_allow_html=True)
    st.title("Data Crime Scene")
    st.markdown('<div class="hero-rule"><p class="hero-subtitle">Investiga por qué un modelo parece funcionar demasiado bien.</p></div>', unsafe_allow_html=True)
    number = case_ids.index(case_id) + 1
    st.markdown(f'<div class="case-number">Expediente {number:02d} / 03 · semilla {seed}</div>', unsafe_allow_html=True)
    st.markdown(f'<h2 class="case-title">{escape(case.title)}</h2>', unsafe_allow_html=True)
    st.markdown(f'<p class="case-subtitle">{escape(case.subtitle)}</p>', unsafe_allow_html=True)
    st.markdown('<div class="path"><span><b>01</b> Informe</span><span><b>02</b> Pruebas</span><span><b>03</b> Hipótesis</span><span><b>04–06</b> Explicación y comparación</span></div>', unsafe_allow_html=True)
    section("01", "El informe inicial")
    st.write(case.story)
    brief_card(case.objective, case.prediction_time)
    if run:
        st.session_state.pop("result", None)
        st.session_state["revealed"] = False
        try:
            with st.spinner("Generando datos, entrenando y evaluando los dos procedimientos…"):
                candidate = cached_experiment(case_id, seed, fingerprint)
                validate_result(candidate, expected_case_id=case_id, expected_seed=seed)
                st.session_state["result"] = candidate
                st.session_state["revealed"] = False
                st.session_state["parameters_changed"] = False
        except (ValueError, RuntimeError) as error:
            clear = getattr(cached_experiment, "clear", None)
            if callable(clear):
                clear(case_id, seed, fingerprint)
            st.error(f"No se ha podido ejecutar el experimento: {error}. Revisa la semilla y vuelve a intentarlo.")
    result = st.session_state.get("result")
    if result is not None:
        try:
            validate_result(result, expected_case_id=case_id, expected_seed=seed)
        except ValueError as error:
            clear = getattr(cached_experiment, "clear", None)
            if callable(clear):
                clear(case_id, seed, fingerprint)
            st.session_state.pop("result", None)
            st.session_state["revealed"] = False
            result = None
            st.error(f"Resultado incompatible o alterado; vuelve a ejecutar: {error}")
    if result is None:
        if st.session_state.get("parameters_changed"):
            st.info("Has cambiado el caso o la semilla. Ejecuta el experimento para generar un informe con estos parámetros.")
        else:
            st.info("El expediente está preparado. Pulsa «Ejecutar experimento» para calcular el informe y abrir las pruebas.")
        caption("Primero inspecciona las pruebas y plantea una hipótesis. Después podrás revelar la corrección y descargar el informe.")
    else:
        st.markdown('<span class="status-label status-suspect">⚠ Resultado del experimento sospechoso</span>', unsafe_allow_html=True)
        render_metrics(result.variants["incorrect"])
        caption(f"Cálculo real · caso {result.case_id} · semilla {result.seed} · clase positiva: {case.positive_class}")
        st.divider()
        render_evidence(case, result)
        st.divider()
        section("03", "Tu hipótesis")
        choice = st.radio(case.hypothesis_question, case.hypothesis_options, index=None, key=f"hypothesis_{case_id}_{seed}")
        if st.button("Revelar explicación y comparar", key="reveal_answer"):
            st.session_state["revealed"] = True
        if st.session_state.get("revealed"):
            if choice is not None:
                if choice == case.hypothesis_options[case.correct_option]:
                    st.success("Tu hipótesis identifica el mecanismo de la fuga. Contrástala con las pruebas de abajo.")
                else:
                    st.info("Puedes revisar tu hipótesis: sigue qué información estaba disponible y qué datos se usaron para ajustar cada etapa.")
            st.divider()
            render_comparison(case, result)
    st.markdown('<div class="lab-footer">Data Crime Scene · Demostración didáctica con datos sintéticos. El test forma parte de esta demostración y no acredita rendimiento en producción.</div>', unsafe_allow_html=True)


if __name__ == "__main__":
    main()
