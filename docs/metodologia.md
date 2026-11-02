# Metodología de Data Crime Scene

Este laboratorio usa datos **sintéticos** generados por el motor: en el equipo que ejecuta la aplicación local o en el servidor de la demo alojada. Los modelos se entrenan y predicen de verdad; los resultados no están escritos de antemano. En el recorrido guiado, cada expediente compara un procedimiento deliberadamente incorrecto con otro que corrige el mecanismo estudiado. El modo Laboratorio añade controles y variabilidad entre semillas. No es una estimación del rendimiento de un producto real.

## Antes de mirar las puntuaciones

Una evaluación responde a una pregunta concreta: ¿qué se conoce en el momento de predecir y sobre qué población se quiere generalizar? El conjunto de entrenamiento, o **train**, sirve para ajustar el procedimiento. El conjunto de prueba, o **test**, sirve para evaluar sus predicciones. **Data leakage** significa que el experimento permite utilizar información que no debería estar disponible según esa pregunta.

El protocolo de cada caso fija generación, partición, variables, modelo y métricas antes de entrenar. La aplicación conserva su semilla y esos parámetros en el informe JSON, junto con filas de train/test, etiquetas, predicciones y diagnósticos. Las semillas predeterminadas de revisión son 7, 42 y 2026; no se elige automáticamente la más llamativa.

Los diagnósticos conocen el mecanismo deliberado de estos generadores. No son un detector universal de fugas para datasets arbitrarios ni certifican que no exista ningún otro problema.

Una puntuación menor al corregir el experimento es compatible con haber eliminado una ventaja indebida, pero **no demuestra que todo el experimento sea correcto**. Una puntuación igual o mayor tampoco invalida el diagnóstico de fuga. La prueba decisiva es el recorrido de la información.

## Caso 1: la pista que llegó del futuro

**Pregunta:** predecir si un pedido se devolverá, utilizando lo conocido al comprarlo.

Hay variables legítimas anteriores o contemporáneas a la compra, y una variable creada durante la tramitación posterior de una devolución. La variante incorrecta utiliza también esta última. Aunque aparezca como una columna normal en una tabla histórica, no existe cuando debe emitirse la predicción. Es una fuga relacionada con el objetivo: un dato posterior revela parte de la respuesta.

La variante corregida excluye esa variable. Conserva las mismas filas de entrenamiento y prueba, el mismo clasificador y los mismos parámetros comparables. Esto permite atribuir la diferencia entre procedimientos al conjunto de variables con mucha más claridad que si también se cambiase la partición.

**Diagnóstico:** revisar el instante de disponibilidad de cada columna y las variables que llegan al modelo. La correlación alta no basta: una señal muy predictiva puede ser totalmente legítima si está disponible a tiempo. La tabla temporal del expediente es más importante que buscar una correlación espectacular.

**Límites:** excluir una columna conocida no garantiza que no existan otras variables derivadas del futuro. Tampoco resuelve cambios de población, calidad de etiquetas o falta de representatividad de datos reales.

## Caso 2: el mismo sospechoso en ambos lados

**Pregunta:** predecir sobre entidades nunca vistas, con varias observaciones por entidad.

Las observaciones de una misma entidad comparten una huella numérica y se parecen mucho. Una partición aleatoria por filas puede colocar observaciones de la misma entidad en train y test. Un modelo de vecinos cercanos puede aprovechar ese parecido para reconocer entidades ya vistas. Una evaluación así responde principalmente a otra pregunta: cómo se comporta sobre nuevas observaciones de entidades conocidas.

El identificador de entidad se reserva para agrupar; el identificador de fila se reserva para auditar. Ninguno entra como variable predictiva. La fuga puede ocurrir incluso sin introducir identificadores explícitos: la huella compartida también permite reconocer a una entidad.

La corrección separa por entidad y comprueba que la intersección de grupos sea **cero**. No elimina observaciones repetidas indiscriminadamente: las medidas repetidas son parte del problema que queremos estudiar.

**Diagnóstico:** contar entidades compartidas entre train y test y contrastar ese número con el objetivo declarado. Una repetición no es un error universal. Si el objetivo fuese predecir otras observaciones de dispositivos conocidos, otra partición podría ser pertinente.

**Límite de la comparación:** al cambiar la partición cambian también las observaciones evaluadas. La diferencia de puntuaciones no es una comparación perfectamente emparejada ni una medida aislada del efecto de la fuga. La corrección tampoco demuestra generalización a otros hospitales, fábricas, épocas o poblaciones que no se hayan simulado.

## Caso 3: el laboratorio contaminó las pruebas

**Pregunta:** qué ocurre al seleccionar variables utilizando etiquetas que debían quedar reservadas para evaluar.

Este caso es un **control sin señal predictiva real**: las etiquetas se generan independientemente de las variables. Entre muchas columnas de ruido pueden aparecer correlaciones accidentales. La variante incorrecta elige columnas mirando todo el dataset, incluidas las etiquetas de test. Después entrena el clasificador solo con train, pero test ya ha influido en qué variables recibe. La contaminación sucede antes del entrenamiento del clasificador.

La variante corregida ajusta el selector supervisado únicamente con train, dentro de un `Pipeline`: una secuencia de transformaciones y un estimador. Al predecir, test se transforma con la selección ya aprendida, sin volver a ajustarla. Ambas variantes mantienen la misma partición, el mismo número de variables seleccionadas y el mismo clasificador con sus parámetros fijos.

**Diagnóstico:** comprobar qué filas y etiquetas participaron en el ajuste de cada etapa. La selección incorrecta alcanza etiquetas de test; la correcta no. El informe conserva también las columnas elegidas. No hace falta que cada semilla produzca una diferencia mínima concreta.

**Límites:** un `Pipeline` no arregla automáticamente cualquier fuga. Si se ajusta con todo el dataset, si recibe una variable del futuro o si la partición mezcla entidades indebidamente, el problema permanece. Una puntuación alta en este control contaminado no demuestra capacidad predictiva; las etiquetas son independientes por construcción. Una puntuación limpia distinta de 0,5 en una muestra pequeña puede aparecer por azar.

## Métricas y baseline

La clase positiva es la etiqueta **1**; su significado concreto se indica en cada expediente. La matriz de confusión usa filas para clase real y columnas para clase predicha, en orden `[0, 1]`: `[[TN, FP], [FN, TP]]`.

- **Accuracy:** fracción de predicciones acertadas. Puede parecer buena si una clase domina.
- **Balanced accuracy:** promedio del recall de cada clase; da el mismo peso a ambas.
- **F1:** media armónica entre precisión y recall de la clase positiva; no resume por sí sola el comportamiento sobre negativos.

El baseline aprende la clase mayoritaria usando solamente train y la predice para todos los ejemplos de test. Sirve como referencia sencilla y se calcula con la misma partición que cada variante. En el caso por grupos los baselines también pueden diferir, porque cambian las filas y la distribución de clases.

No se buscan hiperparámetros ni se reajusta el modelo hasta conseguir una historia concreta. Repetir estos experimentos durante el desarrollo hace que su test forme parte de una demostración didáctica; no debe presentarse como una evaluación final independiente.

## El estudio del modo Laboratorio

El [protocolo previo](protocolo-laboratorio.md) fija preguntas, niveles, diez semillas, comparaciones y límites computacionales antes del estudio. Balanced accuracy es su métrica principal. Cada combinación conserva sus predicciones; los agregados describen puntuaciones por semilla con mediana y cuartiles. No se interpretan como intervalos de confianza ni se agrupan filas de diferentes ejecuciones como réplicas independientes.

En futuro, el control regula la **probabilidad de invertir la etiqueta** al construir la variable posterior; no un «porcentaje de fuga». El valor 0,5 elimina su asociación generativa con la etiqueta, pero no hace que exista al comprar. Se añade una columna irrelevante independiente como control del hecho de añadir una variable.

En entidades, una cohorte común de máquinas nuevas permite evaluar las dos versiones sobre las mismas observaciones. Sus entrenamientos siguen teniendo distinta composición y diversidad; la diferencia sobre esa cohorte es descriptiva y no identifica un efecto causal puro de la fuga. Las mediciones de una máquina no equivalen a entidades independientes.

En selección, el generador anidado del laboratorio mantiene etiquetas, columnas comunes y partición entre niveles. El generador histórico del recorrido guiado se conserva para reproducir sus ejecuciones anteriores; no sirve para aislar el efecto de aumentar el número de variables, porque su secuencia aleatoria cambia también otros datos.

Los hallazgos y resultados efectivos de la intervención se recogen en el [informe de revisión](revision-laboratorio.md). Las preguntas con [respuestas separadas](defensa-tecnica.md) ayudan a distinguir lo observado de las expectativas didácticas.

## Qué comprueban las pruebas

Las pruebas del motor verifican propiedades de los datos, separación, recorrido del ajuste y consistencia entre predicciones, métricas e informe. Las pruebas de Streamlit comprueban estados e interacciones de la aplicación. Estas comprobaciones no equivalen a una inspección visual en navegador: el estado real de ambas revisiones se recoge en el README.

## Fuentes primarias

Consultadas el 28 de octubre de 2026. Las páginas `stable` pueden cambiar; el README registra las versiones instaladas y comprobadas en este proyecto.

- [scikit-learn: Common pitfalls and recommended practices](https://scikit-learn.org/stable/common_pitfalls.html), apartado de data leakage: separar antes de aprender transformaciones y reservar el ajuste para entrenamiento; incluye selección de variables como ejemplo de contaminación.
- [scikit-learn: Cross-validation](https://scikit-learn.org/stable/modules/cross_validation.html), particiones para datos agrupados: la unidad de separación debe responder a la dependencia entre observaciones y a la generalización buscada. También explica el riesgo de tomar decisiones repetidas utilizando test.
- [Streamlit: AppTest](https://docs.streamlit.io/develop/api-reference/app-testing/st.testing.v1.apptest): ejecución simulada para inspeccionar elementos y modificar widgets, con una nueva llamada explícita a `run()` después de cambiarlos. No sustituye a un navegador.

La aplicación concreta, sus generadores y sus controles son decisiones didácticas del proyecto, no resultados empíricos de esas páginas.
