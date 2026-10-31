"""Historias y protocolos fijados antes de ejecutar los experimentos.

Las variantes ``incorrect`` demuestran errores deliberados. No son recetas
recomendadas para reutilizar en otros proyectos.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class CaseDefinition:
    id: str
    title: str
    subtitle: str
    objective: str
    prediction_time: str
    positive_class: str
    story: str
    hypothesis_question: str
    hypothesis_options: tuple[str, ...]
    correct_option: int
    hints: tuple[str, ...]
    explanation: str
    correction: str
    comparison_caveat: str
    code_wrong: str
    code_correct: str


# Parámetros y decisiones declarados ANTES de generar o ajustar. No se buscan
# semillas ni hiperparámetros contra test. Son demostraciones, no benchmarks.
PROTOCOLS = {
    "future": {
        "generation": "600 pedidos sintéticos; señal legítima logística y una variable posterior con ruido.",
        "split": "train_test_split estratificado por etiqueta, 70/30, random_state=seed; mismas filas en ambas variantes.",
        "features": "Tres variables al comprar; incorrect añade reembolso_tramitado, conocido después de la devolución.",
        "model": "StandardScaler + LogisticRegression(C=1.0, solver=liblinear, max_iter=1000, random_state=seed).",
        "metrics": ["accuracy", "balanced_accuracy", "f1"],
        "positive_label": 1,
        "baseline": "DummyClassifier(strategy=most_frequent), ajustado solo con train en cada partición.",
        "comparison": "Mismas filas, etiquetas, modelo y parámetros; solo cambia la inclusión de la variable futura.",
    },
    "groups": {
        "generation": "90 máquinas × 6 registros; huella sensorial estable, ruido por observación y estado por máquina.",
        "split": "Incorrecto: filas estratificadas 70/30. Correcto: GroupShuffleSplit 70/30 por máquina, random_state=seed.",
        "features": "8 mediciones continuas; máquina_id y fila_id se reservan para auditoría, nunca predicen.",
        "model": "KNeighborsClassifier(n_neighbors=1, weights=uniform, metric=minkowski, p=2).",
        "metrics": ["accuracy", "balanced_accuracy", "f1"],
        "positive_label": 1,
        "baseline": "DummyClassifier(strategy=most_frequent), ajustado solo con train en cada partición.",
        "comparison": "Mismo generador, variables y estimador; cambian las filas de evaluación: no es una comparación emparejada.",
    },
    "selection": {
        "generation": "220 filas × 1800 variables gaussianas independientes; etiquetas Bernoulli independientes: control sin señal.",
        "split": "train_test_split estratificado 70/30 con random_state=seed; mismas filas en ambas variantes.",
        "features": "SelectKBest(f_classif, k=25), sin búsqueda de hiperparámetros.",
        "model": "LogisticRegression(C=1.0, solver=liblinear, max_iter=1000, random_state=seed).",
        "metrics": ["accuracy", "balanced_accuracy", "f1"],
        "positive_label": 1,
        "baseline": "DummyClassifier(strategy=most_frequent), ajustado solo con train.",
        "comparison": "Mismas filas, k, clasificador y parámetros. Solo cambia con qué filas/etiquetas se ajusta la selección.",
    },
}


CASES = {
    "future": CaseDefinition(
        id="future",
        title="La pista que llegó del futuro",
        subtitle="Expediente 01 · Información posterior al evento",
        objective="Predecir si un pedido será devuelto al confirmar la compra.",
        prediction_time="Justo al confirmar la compra; antes del envío y de cualquier devolución.",
        positive_class="1 = pedido que termina siendo devuelto; 0 = no devuelto.",
        story="Una tienda presenta un modelo para anticipar devoluciones. El equipo entrega métricas llamativas y un extracto de variables: reconstruye el experimento y verifica si serviría al confirmar una compra.",
        hypothesis_question="¿Qué dato no podrías consultar al confirmar la compra?",
        hypothesis_options=("El importe del carrito", "La señal de reembolso tramitado", "La condición de cliente nuevo"),
        correct_option=1,
        hints=(
            "Sitúa la predicción en un instante concreto: la confirmación de la compra.",
            "Una correlación alta no es una prueba de fuga. Pregunta cuándo se registra cada variable.",
            "reembolso_tramitado se genera tras conocer la devolución; no existe al comprar.",
        ),
        explanation="reembolso_tramitado revela con ruido un desenlace que todavía no ha ocurrido al predecir. Es una fuga de objetivo mediante información futura. El importe, el tipo de producto y si el cliente es nuevo sí existen al comprar y contienen señal legítima. Una correlación fuerte puede ser válida si la variable está disponible a tiempo; aquí la prueba es su procedencia temporal.",
        correction="Excluir reembolso_tramitado antes de entrenar. Las filas de train y test, sus etiquetas, el escalado y la regresión logística mantienen el mismo protocolo. El escalador se ajusta solo con train.",
        comparison_caveat="La bajada de una puntuación no demuestra por sí sola corrección. Comprueba la disponibilidad temporal y la exclusión efectiva. Esta simulación no valida que una tienda real pueda predecir devoluciones.",
        code_wrong="features = legitimate + ['reembolso_tramitado']\nmodel.fit(X.iloc[train][features], y.iloc[train])",
        code_correct="features = legitimate\nmodel.fit(X.iloc[train][features], y.iloc[train])\npred = model.predict(X.iloc[test][features])",
    ),
    "groups": CaseDefinition(
        id="groups",
        title="El mismo sospechoso en ambos lados",
        subtitle="Expediente 02 · Entidades compartidas",
        objective="Detectar el estado de fallo en máquinas nuevas, nunca vistas durante el entrenamiento.",
        prediction_time="Al tomar una medición de diagnóstico en una máquina nueva.",
        positive_class="1 = máquina con estado de fallo; 0 = máquina sin fallo.",
        story="Cada máquina deja una huella sensorial estable y aporta seis registros parecidos. Un vecino más cercano puede reconocer esa huella. Pero el objetivo del informe es funcionar con máquinas nuevas: ¿qué significa entonces separar los datos correctamente?",
        hypothesis_question="Para evaluar máquinas nuevas, ¿cómo debe construirse test?",
        hypothesis_options=("Reservando registros al azar de cada máquina", "Separando máquinas completas entre train y test", "Eliminando todas las mediciones parecidas"),
        correct_option=1,
        hints=(
            "El identificador se usa para auditar la partición; no es una variable del clasificador.",
            "Dos registros distintos pueden compartir casi toda su huella sensorial.",
            "Cuenta las máquinas presentes a la vez en train y test, no solo los identificadores de fila.",
        ),
        explanation="La partición por filas deja observaciones de las mismas máquinas en train y test. Como su estado es estable y sus mediciones se parecen, 1-NN puede recordar la máquina en vez de generalizar su relación con el fallo. El ID no entra como predictor: las mediciones bastan para reconocer perfiles. La fuga depende del objetivo: compartir máquinas podría ser pertinente si se evaluasen nuevas mediciones de máquinas conocidas, bajo otro protocolo temporal.",
        correction="GroupShuffleSplit mantiene cada máquina completa en un solo conjunto. No elimina registros repetidos: conserva todas las observaciones y cambia la unidad de partición para evaluar entidades nuevas.",
        comparison_caveat="Las dos particiones evalúan observaciones distintas y pueden tener distintas proporciones de clases. La diferencia de métricas no está perfectamente emparejada. Comprueba la intersección de máquinas igual a cero en el protocolo corregido.",
        code_wrong="train, test = train_test_split(rows, test_size=.3,\n                               stratify=y, random_state=seed)",
        code_correct="split = GroupShuffleSplit(n_splits=1, test_size=.3,\n                          random_state=seed)\ntrain, test = next(split.split(X, y, groups=machine_id))",
    ),
    "selection": CaseDefinition(
        id="selection",
        title="El laboratorio contaminó las pruebas",
        subtitle="Expediente 03 · Selección supervisada antes de dividir",
        objective="Comprobar una evaluación cuando no existe señal predictiva real.",
        prediction_time="Antes de observar las etiquetas de las filas reservadas para evaluación.",
        positive_class="1 = clase sintética positiva; 0 = negativa. Las etiquetas son independientes de las variables.",
        story="Un laboratorio genera muchas variables y etiquetas al azar. Tras reducir el número de columnas, presenta un resultado llamativo. Reconstruye cómo eligió esas variables y decide si la evaluación es fiable.",
        hypothesis_question="¿Qué información puede consultar el selector supervisado?",
        hypothesis_options=("Las etiquetas de todas las filas", "Solo variables y etiquetas de train", "Las etiquetas de test si después uso un Pipeline"),
        correct_option=1,
        hints=(
            "SelectKBest usa las etiquetas para puntuar variables: forma parte del ajuste.",
            "Con 1800 variables de ruido, algunas correlaciones accidentales parecerán convincentes.",
            "Pregunta si el selector ha visto alguna fila o etiqueta del conjunto de test.",
        ),
        explanation="El selector incorrecto consulta también y_test al elegir las 25 variables. La evaluación queda condicionada a esa consulta. En este control no hay relación generativa entre variables y etiqueta: una puntuación alta tras seleccionar globalmente no descubre señal real. El Pipeline corregido ajusta la selección exclusivamente con train y después transforma test sin volver a ajustarla.",
        correction="Ajustar Pipeline([SelectKBest(f_classif, k=25), LogisticRegression(...)]) con X_train e y_train. Se mantienen las mismas filas, el número de variables seleccionadas y los parámetros del clasificador. La instrumentación registra los índices que recibe fit del selector.",
        comparison_caveat="Un Pipeline no elimina cualquier fuga: si lo ajustas con todos los datos, también contamina test. El resultado corregido fluctúa por azar y puede subir o bajar en una ejecución. El diagnóstico se apoya en las filas consultadas, no en exigir una caída de métricas.",
        code_wrong="X_selected = selector.fit_transform(X, y)  # ERROR deliberado\nmodel.fit(X_selected[train], y.iloc[train])",
        code_correct="model = Pipeline([('selector', SelectKBest(f_classif, k=25)),\n                  ('classifier', LogisticRegression(...))])\nmodel.fit(X_train, y_train)\npred = model.predict(X_test)",
    ),
}
