"""Presentación compartida: sin muestras, estado, entrenamiento ni evaluación."""
from html import escape
from pathlib import Path

import streamlit as st


def load_styles() -> None:
    st.html(Path(__file__).with_name("style.css"))


def caption(text: str) -> None:
    """Texto auxiliar con contraste explícito, sin rebajar su opacidad."""
    st.html(f'<p class="dcs-caption">{escape(text)}</p>')


def brief_card(objective: str, prediction_time: str) -> None:
    """Solo recibe información que la vista pública ya permite mostrar."""
    st.html(
        '<section class="brief-card"><dl>'
        f'<div><dt>Objetivo declarado</dt><dd>{escape(objective)}</dd></div>'
        f'<div><dt>Momento de predicción</dt><dd>{escape(prediction_time)}</dd></div>'
        '</dl></section>'
    )


def skip_link() -> None:
    st.html('<a class="dcs-skip" href="#dcs-main">Saltar al contenido</a>'
            '<span id="dcs-main" tabindex="-1"></span>')
