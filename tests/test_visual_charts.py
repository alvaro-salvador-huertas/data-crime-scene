"""Visual integration must preserve the existing laboratory chart semantics.

The baseline below contains only pure chart functions/constants, extracted via
AST from the pre-integration ui/laboratory.py snapshot. It never imports or
executes the old app, engine, UI, caches or session state, and it does not rely
on the local artifacts folder being present when these tests run.
Source SHA256: 4e2750a9e2107948de174f1e8fa8c01c42e4ba6b0b26634840a2cb705f37b659
"""

import ast
from copy import deepcopy
import json

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import pytest

from ui import laboratory
from ui.plotly_theme import INK, PLOTLY_TEMPLATE, apply_template

_BASELINE_SOURCE = r'''
METRICS = {'balanced_accuracy': 'Balanced accuracy', 'accuracy': 'Accuracy', 'f1': 'F1'}
COLORS = {'incorrect': '#ffaf78', 'correct': '#8ce0c2', 'control': '#a6b8ff', 'baseline': '#aab5bf'}
VARIANTS = {'future': {'incorrect': 'Con dato posterior', 'correct': 'Solo legítimas', 'control': 'Control irrelevante', 'baseline': 'Baseline'}, 'groups': {'incorrect': 'Partición por filas', 'correct': 'Partición por grupos', 'baseline': 'Baseline'}, 'selection': {'incorrect': 'Selección global', 'correct': 'Selección en train', 'baseline': 'Baseline'}}
COMPARISONS = {'incorrect-correct': 'Sospechoso − corregido', 'control-correct': 'Control − legítimas', 'correct-baseline': 'Corregido − baseline', 'incorrect_minus_correct': 'Sospechoso − corregido', 'control_minus_correct': 'Control − legítimas', 'correct_minus_baseline': 'Corregido − baseline'}

def _chart_style(figure: go.Figure, title: str, delta: bool=False) -> go.Figure:
    figure.update_layout(title={'text': title, 'font': {'size': 15}}, template='plotly_dark', height=460, paper_bgcolor='#0d131a', plot_bgcolor='#0d131a', font={'family': 'Arial, sans-serif', 'color': '#d5e0e9', 'size': 11}, margin={'l': 10, 'r': 12, 't': 65, 'b': 155}, legend={'orientation': 'h', 'yanchor': 'top', 'y': -0.34, 'x': 0, 'font': {'size': 10}}, xaxis={'title': {'text': 'Nivel del factor', 'standoff': 12}, 'type': 'category', 'tickangle': 0}, yaxis={'title': 'Diferencia de puntuación' if delta else 'Puntuación', 'tickformat': '+.0%' if delta else '.0%', 'gridcolor': '#26333e'}, boxmode='group')
    if delta:
        figure.add_hline(y=0, line_color='#a1aebc', line_dash='dash', line_width=1)
    else:
        figure.update_yaxes(range=[-0.03, 1.04])
    return figure

def distribution_chart(rows: list[dict], case_id: str, metric: str, evaluation: str) -> go.Figure:
    """Una caja por nivel/modelo; cada punto corresponde a una semilla completa."""
    selected = [row for row in rows if row['evaluation'] == evaluation or (evaluation == 'internal' and row['evaluation'] == 'baseline')]
    figure = go.Figure()
    for key in dict.fromkeys((row['variant'] for row in selected)):
        subset = [row for row in selected if row['variant'] == key]
        figure.add_trace(_precomputed_box(subset, metric, VARIANTS[case_id].get(key, key), COLORS.get(key, '#aab5bf')))
    scope = 'test interno' if evaluation == 'internal' else 'cohorte nueva común'
    return _chart_style(figure, f'{METRICS[metric]} · {scope}')

def _precomputed_box(rows: list[dict], value_key: str, name: str, color: str) -> go.Box:
    """Plotly y pandas usan fórmulas distintas al llamar 'linear' al cuartil.

    Se proporcionan explícitamente los mismos cuartiles que usa la tabla.
    La matriz 2D conserva todos los puntos individuales dentro de cada caja.
    """
    levels = list(dict.fromkeys((row['level'] for row in rows)))
    grouped = [[row for row in rows if row['level'] == level] for level in levels]
    values = [[row[value_key] for row in group] for group in grouped]
    summaries = [pd.Series(value, dtype=float) for value in values]
    return go.Box(name=name, x=[str(level) for level in levels], y=values, q1=[float(series.quantile(0.25, interpolation='linear')) for series in summaries], median=[float(series.median()) for series in summaries], q3=[float(series.quantile(0.75, interpolation='linear')) for series in summaries], lowerfence=[min(value) for value in values], upperfence=[max(value) for value in values], text=np.asarray([[f'Semilla {row['seed']}' for row in group] for group in grouped], dtype=object), marker={'color': color, 'size': 4}, line={'color': color}, fillcolor='rgba(150,170,185,.10)', boxpoints='all', jitter=0.25, pointpos=0, hovertemplate='%{text}<br>Nivel %{x}<br>%{y:+.3f}<extra>%{fullData.name}</extra>')

def summary_table(rows: list[dict], metric: str, case_id: str) -> pd.DataFrame:
    frame = pd.DataFrame(rows)
    if frame.empty:
        return frame
    summary = []
    for (evaluation, level, variant), group in frame.groupby(['evaluation', 'level', 'variant'], sort=False):
        values = group[metric]
        summary.append({'Evaluación': {'internal': 'Test interno', 'cohort': 'Cohorte nueva', 'baseline': 'Baseline interno'}.get(evaluation, evaluation), 'Nivel': level, 'Modelo': VARIANTS[case_id].get(variant, variant), 'Semillas válidas': len(group), 'Q1': values.quantile(0.25, interpolation='linear'), 'Mediana': values.median(), 'Q3': values.quantile(0.75, interpolation='linear'), 'Mínimo': values.min(), 'Máximo': values.max()})
    return pd.DataFrame(summary)

def differences_chart(rows: list[dict], case_id: str) -> go.Figure:
    figure = go.Figure()
    for index, comparison in enumerate(dict.fromkeys((row['comparison'] for row in rows))):
        subset = [row for row in rows if row['comparison'] == comparison]
        color = ['#ffaf78', '#a6b8ff', '#8ce0c2'][index % 3]
        figure.add_trace(_precomputed_box(subset, 'delta', COMPARISONS.get(comparison, comparison), color))
    return _chart_style(figure, 'Diferencias emparejadas · balanced accuracy', delta=True)

def differences_summary(rows: list[dict]) -> pd.DataFrame:
    summary = []
    frame = pd.DataFrame(rows)
    if frame.empty:
        return frame
    for (level, comparison), group in frame.groupby(['level', 'comparison'], sort=False):
        values = group['delta']
        summary.append({'Nivel': level, 'Comparación': comparison, 'Semillas válidas': len(values), 'Q1': values.quantile(0.25, interpolation='linear'), 'Mediana': values.median(), 'Q3': values.quantile(0.75, interpolation='linear'), 'Mínimo': values.min(), 'Máximo': values.max()})
    return pd.DataFrame(summary)
'''


@pytest.fixture(scope="module")
def baseline():
    namespace = {"go": go, "np": np, "pd": pd}
    tree = ast.parse(_BASELINE_SOURCE)
    assert all(isinstance(node, (ast.Assign, ast.FunctionDef)) for node in tree.body)
    exec(compile(tree, "<frozen-chart-functions-before-visual-integration>", "exec"), namespace)
    return namespace


def _frozen_rows(case_id):
    """Hand-authored valid chart input covering order, filters and precision."""
    levels = {"future": [.5, 0, .25], "groups": [1.0, .035, .35], "selection": [1800, 50, 500]}[case_id]
    rows = []
    for evaluation in ("internal", "cohort"):
        for variant_index, variant in enumerate(laboratory.VARIANTS[case_id]):
            for level_index, level in enumerate(levels):
                for seed_index, seed in enumerate((42, 7, 2026)):
                    score = .4 + variant_index * .03 + level_index * .04 + seed_index * .017
                    rows.append({"variant": variant, "evaluation": "baseline" if variant == "baseline" else evaluation, "seed": seed, "level": level, "balanced_accuracy": score, "accuracy": score + .02, "f1": score - .03})
    return rows


def _semantic_figure(figure):
    """Remove only explicitly approved cosmetic changes, retain all data."""
    result = json.loads(figure.to_json())
    for trace in result["data"]:
        trace.pop("fillcolor", None)
        for style in ("marker", "line"):
            if style in trace:
                trace[style].pop("color", None)
    layout = result["layout"]
    for key in ("template", "font", "paper_bgcolor", "plot_bgcolor", "transition"):
        layout.pop(key, None)
    layout.get("title", {}).pop("font", None)
    layout.get("legend", {}).pop("font", None)
    layout.get("yaxis", {}).pop("gridcolor", None)
    for shape in layout.get("shapes", []):
        shape.get("line", {}).pop("color", None)
    return result


@pytest.mark.parametrize("case_id", ["future", "groups", "selection"])
@pytest.mark.parametrize("evaluation", ["internal", "cohort"])
@pytest.mark.parametrize("metric", ["balanced_accuracy", "accuracy", "f1"])
def test_distribution_matches_before_integration(baseline, case_id, evaluation, metric):
    rows = _frozen_rows(case_id)
    original_rows = deepcopy(rows)
    before = baseline["distribution_chart"](rows, case_id, metric, evaluation)
    after = laboratory.distribution_chart(rows, case_id, metric, evaluation)
    assert _semantic_figure(after) == _semantic_figure(before)
    assert rows == original_rows
    assert list(after.layout.yaxis.range) == [-.03, 1.04]
    assert after.layout.font.color == INK
    assert after.layout.transition.duration == 0
    pd.testing.assert_frame_equal(laboratory.summary_table(rows, metric, case_id), baseline["summary_table"](rows, metric, case_id))


@pytest.mark.parametrize("case_id", ["future", "groups", "selection"])
def test_paired_differences_keep_values_zero_line_and_units(baseline, case_id):
    rows = [
        {"comparison": comparison, "level": level, "seed": seed, "delta": delta + level * .01}
        for comparison in ("incorrect-correct", "control-correct", "correct-baseline")
        for level in (2, 0, 1)
        for seed, delta in ((42, -.125), (7, .025), (2026, .17))
    ]
    original_rows = deepcopy(rows)
    before = baseline["differences_chart"](rows, case_id)
    after = laboratory.differences_chart(rows, case_id)
    assert _semantic_figure(after) == _semantic_figure(before)
    assert rows == original_rows
    assert after.layout.yaxis.range is None
    assert after.layout.yaxis.tickformat == "+.0%"
    assert after.layout.shapes[0].y0 == after.layout.shapes[0].y1 == 0
    pd.testing.assert_frame_equal(laboratory.differences_summary(rows), baseline["differences_summary"](rows))


def test_theme_keeps_explicit_and_inherited_semantics_without_mutation():
    inherited = go.layout.Template({
        "layout": {
            "xaxis": {"type": "category", "range": [-.5, 1.5], "categoryorder": "array", "categoryarray": ["B", "A"], "title": {"text": "Original categories"}},
            "yaxis": {"type": "linear", "range": [0, 2], "tickformat": ".1%", "title": {"text": "Original units"}},
            "legend": {"traceorder": "reversed"},
        },
        "data": {
            "scatter": [{"mode": "lines+markers", "connectgaps": False, "marker": {"symbol": "diamond"}}],
            "box": [{"quartilemethod": "exclusive", "boxpoints": "all"}],
        },
    })
    source = go.Figure(go.Scatter(x=["B", "A"], y=[.23, .91]))
    source.update_layout(template=inherited, yaxis={"range": [0, 1]})
    before = deepcopy(source.to_plotly_json())
    themed = apply_template(source)
    after = themed.to_plotly_json()
    assert source.to_plotly_json() == before
    assert after["data"] == before["data"]
    old_template, new_template = before["layout"]["template"], after["layout"]["template"]
    assert new_template["data"] == old_template["data"]
    for axis in ("xaxis", "yaxis"):
        for key, value in old_template["layout"][axis].items():
            if key == "title":
                assert new_template["layout"][axis][key]["text"] == value["text"]
            else:
                assert new_template["layout"][axis][key] == value
    assert new_template["layout"]["legend"]["traceorder"] == "reversed"
    assert list(themed.layout.yaxis.range) == [0, 1]
    assert themed.layout.transition.duration == 0
    assert not themed.frames


def test_production_theme_has_no_sample_or_engine_dependencies():
    from pathlib import Path
    import ui.plotly_theme as theme

    tree = ast.parse(Path(theme.__file__).read_text())
    imports = [node.module or "" for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)]
    imports += [alias.name for node in ast.walk(tree) if isinstance(node, ast.Import) for alias in node.names]
    assert all(name == "copy" or name.startswith("plotly") for name in imports)
    assert "data" not in PLOTLY_TEMPLATE
