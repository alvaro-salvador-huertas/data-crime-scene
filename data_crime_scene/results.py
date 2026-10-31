"""Objetos compartidos por motor, interfaz y exportación JSON."""

from dataclasses import asdict, dataclass, field
import json


@dataclass
class VariantResult:
    name: str
    split_type: str
    train_row_ids: list[str]
    test_row_ids: list[str]
    feature_names: list[str]
    model: dict
    y_true: list[int]
    y_pred: list[int]
    metrics: dict[str, float]
    confusion_matrix: list[list[int]]
    baseline_metrics: dict[str, float]
    diagnostics: dict
    fit_stages: list[dict]
    baseline_predictions: list[int] = field(default_factory=list)


@dataclass
class ExperimentResult:
    case_id: str
    seed: int
    generator_params: dict
    protocol: dict
    variants: dict[str, VariantResult]
    diagnostics: dict
    data_preview: list[dict]
    feature_catalog: list[dict]
    teaching_notes: list[str]
    schema_version: str = "1.0"

    def to_dict(self) -> dict:
        """Devuelve una copia completa; es la única fuente de la exportación."""
        from .validation import validate_result
        validate_result(self)
        payload = asdict(self)
        for variant in payload["variants"].values():
            # Se derivan de las mismas filas que cuenta la interfaz.
            variant["train_size"] = len(variant["train_row_ids"])
            variant["test_size"] = len(variant["test_row_ids"])
        return payload

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False, indent=2, allow_nan=False)
