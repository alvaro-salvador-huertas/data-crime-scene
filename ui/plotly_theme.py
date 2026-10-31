"""Reusable Plotly appearance only: no sample data, engine or Streamlit imports.

Apply to figures whose values, units, scales, order, quartiles and pairing
have already been validated by the application. No example data is included.
"""

from copy import deepcopy

import plotly.graph_objects as go

INK = "#182A35"
MUTED = "#4D6370"
TEAL = "#126B66"
VIOLET = "#6945A0"

# Defaults only: theme never assigns axis ranges, category orders, values,
# quartile algorithms, trace types, units or data transitions.
PLOTLY_TEMPLATE = {
    "layout": {
        "font": {"family": "Arial, Helvetica, sans-serif", "size": 13, "color": INK},
        "paper_bgcolor": "#FFFFFF",
        "plot_bgcolor": "#FFFFFF",
        "colorway": [TEAL, VIOLET, "#8A530C", "#A42D3D"],
        "margin": {"l": 42, "r": 18, "t": 24, "b": 72},
        "hoverlabel": {"bgcolor": "#FFFFFF", "bordercolor": MUTED, "font": {"color": INK, "size": 13}},
        "legend": {"orientation": "h", "yanchor": "top", "y": -0.25, "x": 0, "font": {"size": 12}},
        "xaxis": {"automargin": True, "gridcolor": "#DCE3E7", "linecolor": "#93A2AA", "tickfont": {"color": MUTED}, "zeroline": False, "title": {"standoff": 14}},
        "yaxis": {"automargin": True, "gridcolor": "#DCE3E7", "linecolor": "#93A2AA", "tickfont": {"color": MUTED}, "zeroline": False, "title": {"standoff": 10}},
        "transition": {"duration": 0},
    }
}

PLOTLY_CONFIG = {
    "displaylogo": False,
    "responsive": True,
    "scrollZoom": False,
    "displayModeBar": True,
}


def apply_template(figure: go.Figure) -> go.Figure:
    """Return a styled copy, preserving the caller's data and axis semantics.

    Merge appearance into a copy of the caller's existing template. Semantic
    defaults (axis ranges/types/order, labels, trace defaults) are retained;
    explicit source layout continues to override all template defaults.
    No animation is added. The caller remains responsible for the meaning of
    data, ranges and pairing.
    """
    styled = go.Figure(figure)
    merged_template = go.layout.Template(styled.layout.template)
    merged_template.update(deepcopy(PLOTLY_TEMPLATE))
    styled.update_layout(template=merged_template, transition={"duration": 0})
    return styled
