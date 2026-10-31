# Protocolo previo del laboratorio · lab-v1

Fijado el 28 de octubre de 2026, **antes de ejecutar o inspeccionar resultados agregados**. Este estudio es descriptivo y sintético; no es una confirmación independiente de decisiones de desarrollo de la primera versión.

Métrica principal: **balanced accuracy**. Accuracy y F1 son secundarias. Cada combinación produce predicciones, etiquetas y matrices reales. Baseline: clase mayoritaria aprendida solo en train. No se mezclan filas de diferentes semillas como réplicas independientes.

Semillas, en este orden: **7, 42, 2026, 11, 23, 101, 314, 1234, 4096, 65535**. Exactamente tres casos × tres niveles × diez semillas = **90 combinaciones previstas**; no se eliminan resultados por su puntuación. Los errores de ejecución se guardan como errores, sin convertirlos en puntuaciones ni omitirlos del denominador.

| Caso y pregunta | Factor y niveles fijados | Constantes |
| --- | --- | --- |
| Futuro: ¿qué ocurre al debilitar una señal posterior derivada de la respuesta? | Probabilidad de invertir la etiqueta al construir la variable posterior: **0, 0,25, 0,5**. Es ruido binario simétrico, **no porcentaje de fuga**. | 600 pedidos; mismas etiquetas, variables legítimas, uniformes de inversión y split estratificado 70/30 por semilla. StandardScaler(train) + LogisticRegression(C=1, solver=liblinear, max_iter=1000, random_state=seed). Tres variantes: legítimas, legítimas+posterior, legítimas+control Bernoulli(0,5) independiente disponible al comprar. |
| Entidades: ¿cómo cambia la ventaja de reconocer perfiles al aumentar la variación entre mediciones? | Desviación típica del ruido de medición: **0,035, 0,35, 1,0**, en las unidades sintéticas de sensores Normal(0,1). | 90 máquinas × 6 observaciones, ocho sensores, mismos perfiles/estados, mismas particiones por semilla; 1-NN euclídeo sin búsqueda. Una cohorte independiente de **30 máquinas nuevas × 6 observaciones**, compartida por ambos modelos, generada con un flujo separado; no se utiliza para decidir configuraciones. |
| Selección: ¿qué ocurre al ampliar la búsqueda entre variables sin señal? | Número de variables irrelevantes: **50, 500, 1800**. | 220 muestras, etiquetas Bernoulli(0,5) independientes, idénticas entre niveles; columnas comunes idénticas; mismo split estratificado 70/30. SelectKBest(f_classif, **k=25 fijo**) y misma LogisticRegression. Selección global deliberadamente contaminada frente a Pipeline ajustado solo con train y baseline. |

## Comparaciones e interpretación

- Futuro y selección: diferencias **emparejadas por semilla**, con las mismas filas y etiquetas de test. En futuro se muestran posterior−legítimas y control−legítimas. En selección, global−train y train−baseline. Las columnas adicionales pueden afectar también regularización y ajuste; el control irrelevante no iguala todas las propiedades de la señal posterior.
- Entidades: el test interno por filas y el test interno por grupos **no están emparejados**. Se muestran tamaños, proporciones de clases y entidades compartidas. En la cohorte común sí pueden emparejarse las evaluaciones de ambos modelos, pero sus entrenamientos tienen distinta composición/diversidad de entidades; la diferencia no identifica un efecto causal puro de la fuga. Las 180 observaciones de cohorte no equivalen a 180 máquinas independientes.
- Cada punto agregado representa una **semilla**, no una fila. Resumen: mediana, primer y tercer cuartil (interpolación lineal) y todos los puntos. El intervalo entre cuartiles describe estas semillas; **no es un intervalo de confianza**.
- Con inversión 0,5, la columna posterior es independiente de la etiqueta por construcción, aunque sigue sin estar disponible al comprar. Disponibilidad temporal y ventaja predictiva son preguntas diferentes. Una caída concreta o una tendencia monótona no son requisitos de validez.
- La regresión del primer caso usa importe crudo mientras el generador usa log(importe): no es un predictor óptimo ni la caída estima una cantidad pura de fuga. Se conserva igual entre variantes y niveles.

## Coste y ejecución

Solo CPU. Máxima matriz principal: 220 × 1800 (aproximadamente 3,2 MB de valores float64); modelos sin búsquedas ni redes. Antes del estudio se ejecutará una prueba de coste de **una combinación por caso, semilla 42 y nivel intermedio**, que registrará tiempo y una estimación para 90 combinaciones. Presupuesto previsto: **180 segundos** para el estudio; si la estimación lo excede, se revisarán explícitamente tamaños antes del conjunto. La comprobación de coste no selecciona niveles por sus métricas.

Comandos independientes de Streamlit:

```bash
.venv/bin/python -m data_crime_scene.study --preflight
.venv/bin/python -m data_crime_scene.study --output artifacts/laboratory-study.json
```

El archivo contendrá el protocolo, su huella, la huella del motor, versiones, fecha de generación y las 90 entradas previstas con estado válido/error. Cargarlo verificará compatibilidad y consistencia; abrir la aplicación no ejecutará el estudio. Si cambia el diseño tras observar agregados, se registrará aquí y en el informe como análisis posterior.

## Registro de cambios posteriores al diseño

Sin cambios posteriores registrados al fijar este protocolo. El informe final distinguirá cualquier modificación y sus motivos.
