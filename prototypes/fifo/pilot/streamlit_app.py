"""Separate local entrypoint: Guided + FIFO, with requests made on the server."""
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import streamlit as st

from app import render_comparison, render_evidence, render_metrics, section
from data_crime_scene.cases import CASES
from prototypes.fifo.pilot.client import Client, Session
from ui.presentation import brief_card, caption, load_styles, skip_link


NOTICES = {
    "pending_configuration": "Ya tienes un trabajo pendiente. Conservamos la configuración enviada; espera a que termine antes de enviar otra.",
    "duplicate": "Esta solicitud ya está aceptada. Conservamos el mismo trabajo; no hemos añadido otro cálculo.",
    "queue_full": "La cola está llena. Esta solicitud no se ha aceptado. Espera e inténtalo de nuevo.",
    "session_interval": "Espera 3 segundos entre solicitudes nuevas. Tu trabajo anterior se conserva.",
    "retained_job_capacity": "Has alcanzado el límite temporal de trabajos. Espera a que caduquen antes de enviar otro.",
    "session_capacity": "El servicio ha alcanzado su límite de sesiones. Espera antes de volver a intentarlo.",
    "capacity": "El servicio no ha aceptado esta solicitud. Espera antes de volver a intentarlo.",
    "unavailable": "No podemos confirmar el estado con el servicio. No reenviamos automáticamente. Consulta de nuevo; si el envío quedó sin confirmar, repite la misma configuración para recuperar el mismo trabajo.",
    "session_lost": "Se ha perdido la sesión del servicio. No podemos recuperar su resultado y no se ha vuelto a enviar el trabajo. Puedes iniciar otro cálculo de forma explícita.",
    "expired": "Este trabajo ya no está disponible: ha caducado o se ha reiniciado el servicio. Hemos retirado su resultado y descarga. No se ha vuelto a enviar; puedes solicitar un nuevo cálculo.",
    "invalid_result": "No podemos validar el resultado recibido con la configuración enviada. No mostramos ni descargamos ese informe. Consulta de nuevo.",
    "not_ready": "El resultado aún no está disponible. Tu solicitud sigue aceptada; consulta de nuevo.",
}


def render_job(session):
    session.poll()
    if session.notice:
        message = NOTICES.get(session.notice, "No se ha podido completar la operación. Consulta de nuevo.")
        if session.notice in {"invalid_result", "session_lost", "expired"}:
            st.error(message)
        else:
            st.info(message)
    if session.unconfirmed and not session.job:
        st.warning("Envío sin confirmar. Conservamos su configuración para que puedas repetirlo sin duplicarlo.")
    if not session.job:
        st.info("Sesión nueva. Si has recargado la página, la sesión anterior se ha perdido: no podemos recuperar su trabajo, que puede seguir en el servicio. No se ha vuelto a enviar automáticamente.")
        st.write("Elige un expediente y pulsa «Ejecutar experimento» para solicitarlo.")
        return
    job = session.job
    st.caption(f"Solicitud enviada · caso {job['case']} · semilla {job['seed']}")
    st.caption(f"Referencia del trabajo: {job['id']}")
    state = job["state"]
    if state == "queued":
        st.info(f"En cola · posición {job['position']}. Tu solicitud ya está aceptada; no hace falta volver a pulsar.")
    elif state == "waiting_budget":
        st.info("Esperando cupo. Tu solicitud ya está aceptada; no hace falta volver a pulsar. Empezará automáticamente cuando se libere el cupo de 12 cálculos o reutilizaciones por minuto.")
    elif state == "running":
        st.info("Calculándose. Tu solicitud ya está aceptada; no hace falta volver a pulsar.")
    elif state == "failed":
        st.error("El cálculo ha fallado. No hay resultado ni descarga. Repetir la misma solicitud conserva este fallo y no ejecuta otro cálculo; cambia la semilla o espera a que caduque para enviar uno nuevo.")
    elif state == "succeeded" and session.result is not None:
        st.success("Terminado. El resultado y la descarga corresponden a la solicitud enviada.")
        case, result = CASES[job["case"]], session.result
        caption(f"Cálculo real · caso {result.case_id} · semilla {result.seed}")
        render_metrics(result.variants["incorrect"])
        render_evidence(case, result)
        section("03", "Tu hipótesis")
        choice = st.radio(case.hypothesis_question, case.hypothesis_options, index=None,
                          key="pilot_hypothesis_"+job["id"])
        if st.button("Revelar explicación y comparar", key="pilot_reveal"):
            session.revealed = True
        if session.revealed:
            if choice is not None:
                st.info("Contrasta tu hipótesis con las pruebas y con la explicación.")
            render_comparison(case, result)


@st.fragment(run_every=1)
def job_fragment():
    render_job(st.session_state.pilot)


def main():
    st.set_page_config(page_title="Data Crime Scene · piloto FIFO", page_icon="🔎", layout="wide")
    load_styles()
    skip_link()
    if "pilot" not in st.session_state:
        st.session_state.pilot = Session(Client(os.environ.get("DCS_FIFO_URL", "http://127.0.0.1:8877")))
    session = st.session_state.pilot
    with st.container(key="dcs_root"):
        st.title("Data Crime Scene")
        st.caption("Piloto local · recorrido guiado con espera automática")
        st.write("Investiga por qué un modelo parece funcionar demasiado bien.")
        left, right = st.columns([2, 1])
        with left:
            case = st.selectbox("Expediente", list(CASES), format_func=lambda k: CASES[k].title, key="pilot_case")
        with right:
            seed = int(st.number_input("Semilla del experimento", min_value=0, max_value=2**32-1,
                                       value=42, step=1, key="pilot_seed"))
        if session.job and (session.job["case"], session.job["seed"]) != (case, seed):
            st.warning(f"Has cambiado la selección a {case} / semilla {seed}. El trabajo conservado corresponde a {session.job['case']} / semilla {session.job['seed']}; cambiar los controles no lo modifica ni envía otro.")
        send, refresh = st.columns([1, 1])
        with send:
            if st.button("Ejecutar experimento", type="primary", key="pilot_submit"):
                session.submit(case, seed)
        with refresh:
            st.button("Actualizar estado", key="pilot_refresh")
        st.caption("El estado se actualiza automáticamente cada segundo. Los resultados caducan cinco minutos después de terminar. Recargar la página inicia otra sesión y puede dejar un trabajo anterior en el servicio.")
        # Present the brief for the submitted configuration, even after editing controls.
        presented = CASES[session.job["case"]] if session.job else CASES[case]
        section("01", "El informe inicial")
        st.subheader(presented.title)
        st.write(presented.story)
        brief_card(presented.objective, presented.prediction_time)
        job_fragment()


if __name__ == "__main__":
    main()
