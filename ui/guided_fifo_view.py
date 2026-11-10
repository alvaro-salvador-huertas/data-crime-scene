"""Opt-in Guided UI; no changes to Laboratory or Detective views."""
import streamlit as st

from data_crime_scene.cases import CASES
from ui.guided_fifo import get_guided_session
from ui.presentation import brief_card, caption


def render_status(session):
    # Imports are deferred to avoid a cycle while app.py defines the renderers.
    from app import render_comparison, render_evidence, render_metrics, section

    session.poll()
    notices = {
        "pending_configuration": "Ya tienes un trabajo pendiente. Conservamos la configuración enviada; espera a que termine antes de enviar otra.",
        "duplicate": "Esta solicitud ya está aceptada. Conservamos el mismo trabajo; no hemos añadido otro cálculo.",
        "queue_full": "La cola está llena. Esta solicitud no se ha aceptado. Espera e inténtalo de nuevo.",
        "session_interval": "Espera 3 segundos entre solicitudes nuevas. Tu trabajo anterior se conserva.",
        "retained_job_capacity": "Has alcanzado el límite temporal de trabajos. Espera a que caduquen antes de enviar otro.",
        "session_capacity": "La demo ha alcanzado su límite temporal de sesiones. Espera antes de volver a intentarlo.",
        "expired": "Este trabajo ya no está disponible: ha caducado o se ha reiniciado la demo. Hemos retirado el resultado y su descarga. No se ha vuelto a enviar.",
        "session_lost": "Se ha perdido el acceso al trabajo anterior. No se ha vuelto a enviar. Puedes solicitar otro cálculo de forma explícita.",
        "invalid_result": "El resultado recibido no coincide con la solicitud enviada. No mostramos ni descargamos ese informe.",
    }
    if session.notice:
        st.info(notices.get(session.notice, "No se ha podido confirmar el estado del trabajo. No se ha reenviado automáticamente."))
    job = session.job
    if not job:
        st.info("Sesión nueva. Si has recargado la página, has perdido el acceso al trabajo anterior, que puede seguir en curso. No se ha vuelto a enviar automáticamente.")
        caption("Elige expediente y semilla y pulsa «Ejecutar experimento» para solicitarlo.")
        return
    caption(f"Solicitud enviada · caso {job['case']} · semilla {job['seed']}")
    caption(f"Referencia del trabajo: {job['id']}")
    state = job["state"]
    if state == "queued":
        position = (f"posición {job['position']}" if job["position"] else "turno de ejecución reservado")
        st.info(f"En cola · {position}. Tu solicitud ya está aceptada; no hace falta volver a pulsar.")
        if job.get("wait_reason") == "other_mode":
            caption("Otro cálculo ocupa el turno compartido de la demo. Tu trabajo empezará cuando quede libre y haya cupo.")
    elif state == "waiting_budget":
        reason = ("Termina el intervalo de 3 segundos de esta sesión." if job.get("wait_reason") == "session_interval"
                  else "Empezará automáticamente al liberarse el presupuesto compartido de 12 cálculos o reutilizaciones por minuto.")
        st.info("Esperando cupo. Tu solicitud ya está aceptada; no hace falta volver a pulsar. "+reason)
    elif state == "running":
        st.info("Calculándose. Tu solicitud ya está aceptada; no hace falta volver a pulsar.")
    elif state == "failed":
        st.error("El cálculo ha fallado. No hay resultado ni descarga. Repetir la misma solicitud conserva el fallo; cambia la semilla o espera a que caduque para solicitar otro.")
    elif state == "succeeded" and session.result is not None:
        st.success("Terminado. El resultado y la descarga corresponden a la solicitud enviada.")
        result, case = session.result, CASES[job["case"]]
        caption(f"Cálculo real · caso {result.case_id} · semilla {result.seed}")
        render_metrics(result.variants["incorrect"])
        render_evidence(case, result)
        section("03", "Tu hipótesis")
        choice = st.radio(case.hypothesis_question, case.hypothesis_options, index=None,
                          key="fifo_hypothesis_"+job["id"])
        if st.button("Revelar explicación y comparar", key="fifo_reveal"):
            session.revealed = True
        if session.revealed:
            if choice is not None:
                message = ("Tu hipótesis identifica el mecanismo de la fuga. Contrástala con las pruebas de abajo."
                           if choice == case.hypothesis_options[case.correct_option]
                           else "Puedes revisar tu hipótesis: sigue qué información estaba disponible y qué datos se usaron para ajustar cada etapa.")
                st.info(message)
            render_comparison(case, result)


@st.fragment(run_every=1)
def status_fragment():
    render_status(st.session_state.guided_fifo_session)


def render_guided_fifo():
    from app import section

    session = get_guided_session()
    ids = list(CASES)
    with st.sidebar, st.container(key="dcs_guided_controls"):
        st.markdown("### Mesa de investigación")
        case = st.selectbox("Expediente", ids, format_func=lambda k: CASES[k].title, key="case_selector")
        seed = int(st.number_input("Semilla del experimento", min_value=0, max_value=2**32-1,
                                   value=42, step=1, key="seed_input"))
        if st.button("Ejecutar experimento", type="primary", width="stretch", key="run_experiment"):
            session.submit(case, seed)
        st.button("Actualizar estado", key="fifo_refresh")
        caption("Guiado espera su turno automáticamente. Recargar pierde el acceso al trabajo anterior y no lo reenvía.")
    st.title("Data Crime Scene")
    caption("Recorrido guiado · espera automática con cola acotada")
    if session.job and (case, seed) != (session.job["case"], session.job["seed"]):
        st.warning(f"Has cambiado la selección a {case} / semilla {seed}. El trabajo conservado corresponde a {session.job['case']} / semilla {session.job['seed']}; cambiar los controles no lo modifica ni envía otro.")
    presented = CASES[session.job["case"]] if session.job else CASES[case]
    section("01", "El informe inicial")
    st.subheader(presented.title)
    st.write(presented.story)
    brief_card(presented.objective, presented.prediction_time)
    caption("El estado se actualiza cada segundo. Los resultados caducan cinco minutos después de terminar. Recargar inicia otra sesión y puede dejar un trabajo anterior en curso.")
    status_fragment()
