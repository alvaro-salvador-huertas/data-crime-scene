"""Generadores pequeños, locales y con semillas explícitas. No hay I/O."""

from dataclasses import dataclass

import numpy as np
import pandas as pd


@dataclass
class SyntheticDataset:
    X: pd.DataFrame
    y: pd.Series
    params: dict
    groups: pd.Series | None = None


def validate_seed(seed: int) -> int:
    if isinstance(seed, bool) or not isinstance(seed, (int, np.integer)):
        raise ValueError("La semilla debe ser un entero entre 0 y 4294967295.")
    if not 0 <= int(seed) <= 2**32 - 1:
        raise ValueError("La semilla debe estar entre 0 y 4294967295.")
    return int(seed)


def _integer(name: str, value: int, minimum: int, maximum: int) -> int:
    if isinstance(value, bool) or not isinstance(value, (int, np.integer)) or not minimum <= value <= maximum:
        raise ValueError(f"{name} debe ser un entero entre {minimum} y {maximum}.")
    return int(value)


def generate_future(seed: int, n_samples: int = 600, refund_flip_probability: float = 0.04) -> SyntheticDataset:
    seed = validate_seed(seed)
    n_samples = _integer("n_samples", n_samples, 40, 10000)
    if isinstance(refund_flip_probability, bool) or not isinstance(refund_flip_probability, (int, float)) or not np.isfinite(refund_flip_probability) or not 0 <= refund_flip_probability <= 0.5:
        raise ValueError("refund_flip_probability debe estar entre 0 y 0.5.")
    rng = np.random.default_rng(seed)
    amount = rng.lognormal(mean=4.2, sigma=0.55, size=n_samples)
    fragile = rng.binomial(1, 0.4, n_samples)
    new_customer = rng.binomial(1, 0.35, n_samples)
    logit = -1.35 + 0.7 * ((np.log(amount) - 4.2) / 0.55) + 0.85 * fragile + 0.5 * new_customer
    y = rng.binomial(1, 1 / (1 + np.exp(-logit)))
    # Posterior al evento: la tramitación informa del desenlace con 4 % de ruido.
    refund = np.logical_xor(y, rng.random(n_samples) < refund_flip_probability).astype(int)
    index = pd.Index([f"pedido_{i:05d}" for i in range(n_samples)], name="fila_id")
    X = pd.DataFrame({"importe": amount, "producto_fragil": fragile, "cliente_nuevo": new_customer,
                      "reembolso_tramitado": refund}, index=index)
    return SyntheticDataset(X, pd.Series(y, index=index, name="devuelto"),
                            {"n_samples": n_samples, "refund_flip_probability": float(refund_flip_probability),
                             "amount_log_mean": 4.2, "amount_log_sigma": 0.55,
                             "fragile_probability": 0.4, "new_customer_probability": 0.35,
                             "label_logit_coefficients": [-1.35, 0.7, 0.85, 0.5]})


def generate_groups(seed: int, n_entities: int = 90, observations_per_entity: int = 6,
                    measurement_noise_std: float = 0.035) -> SyntheticDataset:
    seed = validate_seed(seed)
    n_entities = _integer("n_entities", n_entities, 10, 1000)
    observations_per_entity = _integer("observations_per_entity", observations_per_entity, 2, 30)
    if isinstance(measurement_noise_std, bool) or not isinstance(measurement_noise_std, (int, float)) or not np.isfinite(measurement_noise_std) or not 0 <= measurement_noise_std <= 2:
        raise ValueError("measurement_noise_std debe estar entre 0 y 2.")
    rng = np.random.default_rng(seed)
    fingerprints = rng.normal(size=(n_entities, 8))
    probability = 1 / (1 + np.exp(-0.7 * fingerprints[:, 0]))
    status = rng.binomial(1, probability)
    measurements = np.repeat(fingerprints, observations_per_entity, axis=0)
    measurements += rng.normal(0, measurement_noise_std, measurements.shape)
    n_samples = len(measurements)
    index = pd.Index([f"registro_{i:05d}" for i in range(n_samples)], name="fila_id")
    X = pd.DataFrame(measurements, columns=[f"sensor_{i + 1:02d}" for i in range(8)], index=index)
    y = pd.Series(np.repeat(status, observations_per_entity), index=index, name="fallo")
    groups = pd.Series(np.repeat([f"maquina_{i:03d}" for i in range(n_entities)], observations_per_entity),
                       index=index, name="maquina_id")
    return SyntheticDataset(X, y, {"n_entities": n_entities, "observations_per_entity": observations_per_entity,
                                   "n_samples": n_samples, "n_sensors": 8, "measurement_noise_std": float(measurement_noise_std),
                                   "population_signal_coefficient": 0.7}, groups)


def generate_selection(seed: int, n_samples: int = 220, n_features: int = 1800) -> SyntheticDataset:
    seed = validate_seed(seed)
    n_samples = _integer("n_samples", n_samples, 40, 2000)
    n_features = _integer("n_features", n_features, 25, 5000)
    rng = np.random.default_rng(seed)
    index = pd.Index([f"muestra_{i:05d}" for i in range(n_samples)], name="fila_id")
    X = pd.DataFrame(rng.normal(size=(n_samples, n_features)),
                     columns=[f"ruido_{i:04d}" for i in range(n_features)], index=index)
    y = pd.Series(rng.binomial(1, 0.5, n_samples), index=index, name="clase_aleatoria")
    return SyntheticDataset(X, y, {"n_samples": n_samples, "n_features": n_features,
                                   "feature_distribution": "Normal(0, 1), independientes",
                                   "label_probability": 0.5, "labels_independent_of_features": True,
                                   "selected_feature_count": 25})


def generate_selection_nested(seed: int, n_samples: int = 220, n_features: int = 1800) -> SyntheticDataset:
    """Control del laboratorio: etiquetas y columnas comunes fijas entre niveles.

    Se conserva generate_selection para reproducir el recorrido guiado v1.
    Cada columna consume n_samples valores consecutivos, con un flujo distinto
    del de etiquetas. Aumentar n_features solo añade nuevas columnas.
    """
    seed = validate_seed(seed)
    n_samples = _integer("n_samples", n_samples, 40, 2000)
    n_features = _integer("n_features", n_features, 25, 5000)
    feature_stream, label_stream = np.random.SeedSequence(seed).spawn(2)
    index = pd.Index([f"muestra_{i:05d}" for i in range(n_samples)], name="fila_id")
    X = pd.DataFrame(np.random.default_rng(feature_stream).normal(size=(n_features, n_samples)).T,
                     columns=[f"ruido_{i:04d}" for i in range(n_features)], index=index)
    y = pd.Series(np.random.default_rng(label_stream).binomial(1, 0.5, n_samples), index=index, name="clase_aleatoria")
    return SyntheticDataset(X, y, {"n_samples": n_samples, "n_features": n_features,
                                   "feature_distribution": "Normal(0, 1), independientes",
                                   "label_probability": 0.5, "labels_independent_of_features": True,
                                   "selected_feature_count": 25, "generator_version": "nested-v1",
                                   "rng_streams": "SeedSequence(seed).spawn(2): columnas, etiquetas"})
