# Tu primera visita: 35–45 minutos

El objetivo es poder explicar qué información atraviesa indebidamente cada experimento y localizarlo en el código. No necesitas memorizar scikit-learn ni entender todos los estilos de la interfaz.

## 0–5 minutos: abrir y orientarte

Sigue los comandos de instalación y arranque del [README](../README.md). Si el entorno local ya está instalado, ejecuta desde la raíz:

```bash
.venv/bin/python -m streamlit run app.py --server.address 127.0.0.1
```

Localiza el selector de caso, la semilla y el botón de ejecución. Mantén primero la semilla **42**. Todos los datos son sintéticos. Train significa entrenamiento; test significa prueba.

## 5–13 minutos: caso 1, el tiempo importa

1. Lee qué se quiere predecir y en qué instante.
2. Ejecuta el experimento y examina la muestra de datos y su línea temporal.
3. Formula una hipótesis antes de abrir la solución; usa una pista si hace falta.
4. Revela la explicación y compara las variables usadas por las dos variantes.
5. Descarga el informe JSON y busca la semilla, las filas de test y las predicciones.

Anota en una frase por qué la variable sospechosa llega demasiado tarde. No utilices «tiene mucha correlación» como única explicación.

## 13–21 minutos: caso 2, la unidad de generalización

Repite el recorrido con el caso de entidades. Mira cuántas aparecen en ambos lados de cada partición. Identifica qué información recibe el modelo y qué identificador se utiliza solo para agrupar.

Antes de mirar métricas, responde: «¿este test representa entidades nuevas?». Después comprueba la advertencia sobre el cambio de observaciones evaluadas. No interpretes la diferencia de puntuaciones como un experimento perfectamente emparejado.

## 21–29 minutos: caso 3, el ajuste también forma parte del modelo

Lee primero el aviso de que las etiquetas son independientes de las variables. Inspecciona qué filas se usan para ajustar el selector y cuáles para entrenar el clasificador.

Revela la solución y sigue las dos versiones de código. Busca la diferencia entre `fit` y `transform`. Cambia a la semilla **7** y vuelve a ejecutar: los números pueden cambiar, pero el diagnóstico debe seguir explicándose por los datos que participaron en el ajuste.

## 29–35 minutos: leer el código y contrastar el informe

Lee estos archivos en este orden:

1. [`cases.py`](../data_crime_scene/cases.py): historias y protocolos declarados antes de entrenar.
2. [`generators.py`](../data_crime_scene/generators.py): cómo se crean la señal, las huellas y el ruido.
3. [`experiments.py`](../data_crime_scene/experiments.py): particiones, ajuste y evaluación. Empieza por un caso.
4. [`results.py`](../data_crime_scene/results.py): el objeto que comparten interfaz y exportación.
5. [`test_engine.py`](../tests/test_engine.py): propiedades que deben cumplirse aunque cambien las métricas.
6. [`app.py`](../app.py): cómo se presenta el resultado y cuándo se ejecuta el motor.

Ejecuta también la ruta sin interfaz:

```bash
.venv/bin/python -m data_crime_scene --seeds 7 42 2026 --output artifacts/experiments.json
.venv/bin/python -m pytest
```

Compara un informe con la pantalla de la misma semilla. Las predicciones y las métricas deben proceder del mismo objeto, no de números preparados por separado.

## Cinco preguntas que deberías poder contestar

1. ¿Por qué una variable muy correlacionada con la respuesta puede ser legítima y otra constituir fuga? ¿Qué instante debes conocer?
2. ¿Qué diferencia hay entre evaluar nuevas observaciones de una entidad conocida y evaluar entidades nunca vistas?
3. ¿Cómo puede contaminarse test aunque el clasificador solo haya recibido train en su llamada a `fit`?
4. ¿Por qué un `Pipeline` ajustado sobre todo el dataset no garantiza una evaluación limpia?
5. ¿Qué demostraría una caída de F1 al corregir un caso y qué cosas seguirían sin estar demostradas?

Si alguna respuesta depende exclusivamente de que una puntuación haya bajado, vuelve a la tabla temporal, la intersección de grupos o las filas utilizadas para ajustar.

## 35–45 minutos: dos ejercicios para resolver tú

No están implementados como funcionalidades de esta versión. Haz uno por sesión y conserva el protocolo antes de comparar resultados.

Después de modificar generadores o protocolos, detén y reinicia Streamlit para vaciar su caché en memoria antes de comparar. La interfaz distingue caso y semilla; los demás parámetros están fijados en el código.

### Ejercicio 1: una nueva pista disponible a tiempo

Añade al generador del caso 1 una variable sintética conocida al comprar. Decide cómo influirá en la probabilidad de devolución, registra su disponibilidad en el catálogo y úsala en ambas variantes. Conserva la variable futura solo en la incorrecta.

Antes de ejecutar, escribe qué esperas que ocurra y qué resultado te haría revisar esa expectativa. Comprueba que las dos variantes conservan las mismas filas de train y test y que la nueva columna no deriva de la etiqueta futura. No busques una caída mínima de métricas.

### Ejercicio 2: medir cuánto comparten las observaciones

Localiza el parámetro que controla la variación entre observaciones de una misma entidad en el caso 2. Prepara una comparación pequeña entre dos valores fijados de antemano, con las semillas 7, 42 y 2026 y el mismo resto del protocolo.

Antes de entrenar, escribe cómo esperas que cambien los parecidos entre observaciones y qué partición representa entidades nuevas. Registra el solapamiento y las métricas de cada variante. Explica por qué esta comparación no permite afirmar que cualquier repetición sea una fuga ni que la diferencia entre particiones esté perfectamente emparejada.

## Guion de demostración: unos dos minutos

- **0:00–0:20.** «Data Crime Scene es un laboratorio sintético para investigar evaluaciones de machine learning. Los modelos se entrenan de verdad y las semillas permiten repetir los experimentos».
- **0:20–0:50.** Abre el caso 1 y ejecútalo. «La predicción ocurre al comprar; este dato solo aparece al tramitar una devolución. La corrección lo excluye, manteniendo las mismas filas».
- **0:50–1:15.** Cambia al caso 2 y ejecútalo. «Queremos entidades nuevas. Dividir por filas permite reconocer entidades conocidas; separar por grupo elimina esa intersección. Aquí cambia también el conjunto evaluado».
- **1:15–1:45.** Cambia al caso 3 y ejecútalo. «No hay señal real por construcción. Seleccionar columnas mirando etiquetas de test puede convertir azar en una evaluación optimista. El selector debe ajustarse únicamente con train».
- **1:45–2:00.** Descarga el JSON. «Conservo parámetros, predicciones y diagnósticos. La métrica no valida sola el experimento: hay que comprobar el recorrido de la información».

El proyecto se desarrolló con asistencia de IA. Para presentarlo como aprendizaje propio, céntrate en lo que hayas revisado, ejecutado y puedas explicar; no implica experiencia profesional en machine learning.

## Después del recorrido: diez minutos en el Laboratorio

1. Lee la tabla del [protocolo previo](protocolo-laboratorio.md): identifica el factor que cambia y las constantes de cada caso.
2. Abre el modo **Laboratorio**. Distingue una ejecución interactiva de un estudio guardado: revisa configuración, procedencia y versiones antes de comparar.
3. En futuro, compara la variable posterior con la variable irrelevante y las legítimas. Explica por qué el ruido 0,5 no convierte un dato posterior en uno disponible al comprar.
4. En entidades, diferencia tests internos y cohorte nueva. Mira composición de clases, máquinas compartidas y diversidad del entrenamiento antes de atribuir una diferencia a la fuga.
5. En selección, comprueba que cambiar el número de columnas conserva etiquetas, columnas comunes y partición. Inspecciona puntos individuales y cuartiles: no son intervalos de confianza.

Lee tres observaciones efectivas en el [informe de revisión](revision-laboratorio.md) y contesta las [cinco preguntas de defensa técnica](defensa-tecnica.md) antes de mirar sus respuestas. Abrir la aplicación no ejecuta el estudio completo; su comando explícito se encuentra en el README y el protocolo.
