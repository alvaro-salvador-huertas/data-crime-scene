# Cinco preguntas para defender los experimentos

Intenta responder antes de leer la segunda parte. Usa índices, columnas y predicciones del informe para apoyar tu explicación.

## Preguntas

1. El procedimiento corregido supera al contaminado en una semilla. ¿Se refuta la existencia de fuga? ¿Qué evidencia revisarías antes de interpretar la métrica?
2. Al variar el número de variables del caso 3 mantienes la misma semilla. ¿Por qué eso no garantiza que hayas cambiado un único factor? ¿Qué comprobarías en el generador?
3. La variable posterior se construye invirtiendo la etiqueta con probabilidad 0,5. El diagnóstico sigue indicando indisponibilidad temporal. ¿Contradice esto que la variable no tenga señal predictiva real?
4. Ambos modelos del caso 2 se evalúan sobre las mismas máquinas nuevas. ¿La diferencia de balanced accuracy mide ahora exclusivamente el efecto de la fuga? ¿Qué permanece distinto?
5. El laboratorio muestra diez puntos y un rango intercuartílico por nivel. ¿Por qué no puedes tratar las filas de todas las ejecuciones como réplicas independientes ni llamar intervalo de confianza a ese rango?

---

## Respuestas orientativas

**1.** No. La fuga es una propiedad del recorrido de la información; la diferencia de métricas en una muestra es aleatoria. Revisaría disponibilidad temporal de las columnas, entidades de cada partición y filas/etiquetas que recibió el selector al ajustarse. Recalcularía las métricas desde predicciones antes de explicar una diferencia. Corregir una fuga concreta no certifica la ausencia de otras.

**2.** Una semilla solo reproduce la secuencia de un generador bajo su misma configuración. Cambiar la forma de la matriz puede redistribuir números entre columnas y desplazar el punto de generación de etiquetas. Comprobaría igualdad de etiquetas, índices de train/test y todas las columnas comunes entre niveles. El generador anidado del laboratorio usa flujos separados y conserva esos prefijos; el guiado histórico no se usa para ese contraste entre niveles.

**3.** No. Con ruido binario simétrico de probabilidad 0,5, la salida es independiente de la etiqueta en la distribución generativa. Aun así, la columna se registra después del momento permitido para predecir. El diagnóstico comprueba ese incumplimiento temporal; no afirma una ganancia observada. En una muestra finita, una variable independiente puede mejorar o empeorar una puntuación por azar.

**4.** La evaluación sobre la cohorte común permite emparejar sus predicciones, pero los entrenamientos siguen teniendo distintas máquinas y diversidad de perfiles. La diferencia mezcla esas decisiones de entrenamiento y su variación muestral. Puede describirse sobre esa cohorte; no identifica un efecto causal puro de la fuga. Las seis mediciones de cada máquina tampoco son seis entidades independientes.

**5.** Las filas comparten entrenamiento y, en entidades, dependen de una misma máquina. Los niveles de una misma semilla comparten además datos deliberadamente. El punto de resumen es la semilla, no cada predicción agrupada. El rango intercuartílico describe la dispersión de estas diez puntuaciones; un intervalo de confianza requeriría especificar cantidad objetivo, supuestos y procedimiento inferencial.
