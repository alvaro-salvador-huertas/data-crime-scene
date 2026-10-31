# Revisión crítica y laboratorio experimental

## Qué sostiene la primera versión

La revisión partió del código y los archivos existentes, no del resumen anterior. `artifacts/experiments.json` contenía nueve ejecuciones: los tres casos con semillas 7, 42 y 2026. El registro `artifacts/browser-check.json` contenía tres recorridos y tamaños de escritorio y móvil; esto acredita la existencia del registro, no sustituye una nueva ejecución de las comprobaciones.

- **Información futura:** `_future` en `experiments.py` construye una única partición y ajusta el mismo tipo de pipeline en ambas variantes. Solo cambia la columna posterior. `generate_future` deriva esa columna del desenlace con ruido; el modelo corregido la excluye. Se demuestra la indisponibilidad temporal prevista, no una regla general basada en correlaciones.
- **Entidades compartidas:** `_groups` utiliza realmente `GroupShuffleSplit`; los identificadores no entran en `X`. La etiqueta se comparte dentro de cada máquina y las mediciones tienen una huella estable. La partición por filas permite reconocer entidades; la corregida mantiene sus grupos separados. Cambia también la composición evaluada, por lo que la diferencia entre ambos tests no identifica aisladamente el efecto de la fuga.
- **Selección contaminada:** `_selection` ajusta el selector incorrecto con todo `X, y`; el correcto recibe solo train dentro de un `Pipeline`. El clasificador, sus parámetros y la partición se mantienen. `AuditedSelectKBest.fit` registra las filas realmente recibidas. Las etiquetas se generan independientemente de las variables.
- **Resultados reales:** las llamadas a `predict` alimentan etiquetas, predicciones, métricas y matrices. El baseline se ajusta con train. `test_metrics_and_confusion_match_actual_predictions` recalcula las métricas y `test_selector_fit_calls_observe_only_training_in_pipeline` intercepta entradas reales de ajuste: son evidencias más fuertes que comprobar únicamente un indicador escrito por el propio experimento.

Estas comprobaciones justifican los mecanismos concretos. No certifican un experimento científico completo ni un detector universal de fugas. El acuerdo entre revisores no se utiliza como prueba.

## Defectos y límites encontrados

**Confusor al ampliar ingenuamente el caso de selección.** El generador guiado usa el mismo RNG para una matriz con forma `(n_samples, n_features)` y, después, las etiquetas. Cambiar `n_features` cambia las etiquetas y también valores de columnas anteriores. Una microprueba con semilla 42, 80 muestras y 50 frente a 100 variables produjo 46 etiquetas distintas y un prefijo de variables diferente. Eso no invalida la comparación guiada con configuración fija; sí impediría aislar el factor «número de variables» en el laboratorio.

**Defensas incompletas.** Las pruebas iniciales contrastaban métricas y ajuste, pero no demostraban que una predicción modificada o un informe ajeno fueran rechazados al exportar o recuperar resultados. Un objeto mutable podía conservar métricas desactualizadas. La revisión amplía esa frontera con validación y errores deliberados en pruebas aisladas.

**Diferencias que deben seguir visibles.** En entidades, igualar números de filas no iguala diversidad de máquinas en train. En futuro, añadir una columna cambia dimensionalidad y regularización; un control irrelevante ayuda a interpretar esa diferencia, pero no iguala todas sus propiedades. Además, el generador usa `log(importe)` y el modelo recibe el importe crudo: el modelo legítimo no es óptimo y la caída no mide una «cantidad pura de fuga».

**Disponibilidad y señal son distintas.** Con probabilidad de inversión 0,5, la variable posterior es independiente de la etiqueta por construcción. Continúa indisponible al comprar, aunque no deba aportar ventaja predictiva sistemática. Una bandera temporal no significa que se haya observado mejora ni constituye una falsa alarma sobre esa mejora.

## Cambios del laboratorio

El [protocolo previo](protocolo-laboratorio.md) fija tres niveles por caso y diez semillas antes de observar agregados. La métrica principal es balanced accuracy. Se conservan todas las combinaciones previstas, incluidos errores; mediana, cuartiles y puntos describen semillas, sin presentar el rango como intervalo de confianza ni agrupar sus filas como observaciones independientes.

La ruta guiada y su generador histórico de selección se conservan. El laboratorio usa un generador anidado con etiquetas y columnas comunes invariantes entre niveles. Futuro añade una variable irrelevante independiente y controla la inversión binaria de la columna posterior. Entidades evalúa ambos modelos sobre una cohorte común de 30 máquinas nuevas, separada de las decisiones de configuración.

Durante la integración se detectó otro defecto, esta vez en el gráfico nuevo: el método llamado `linear` de Plotly no calcula los cuartiles con la misma convención que `numpy.quantile` utilizada en la tabla. La interpolación de [Plotly](https://raw.githubusercontent.com/plotly/plotly.js/master/src/lib/stats.js) usa la posición `q·n−0,5`; el método lineal predeterminado de [NumPy](https://numpy.org/doc/stable/reference/generated/numpy.quantile.html) usa `q·(n−1)`. Se corrigió pasando al gráfico los cuartiles ya calculados por la misma función que el resumen, y una prueba usa un contraejemplo donde las convenciones difieren. Esto corrige una discrepancia de presentación; no cambia niveles, semillas ni resultados del diseño.

## Resultados y comprobaciones de esta intervención

La prueba de coste guardada en `artifacts/lab-preflight.json` ejecutó una combinación intermedia por caso: **0,0681 / 0,0723 / 0,0473 s**. La estimación para el conjunto fue **5,63 s**, por debajo del presupuesto de 180 s. No se redujeron tamaños ni niveles.

`artifacts/laboratory-study.json` conserva las **90 combinaciones previstas, 90 válidas y cero errores**, calculadas en **5,37 s**. Incluye configuración, predicciones, protocolo, versiones y huellas de compatibilidad. Los siguientes resúmenes se calcularon leyendo ese archivo, sin reentrenar ni descartar semillas. Cada celda de puntuación es una **mediana de balanced accuracy sobre diez semillas**; las diferencias se calculan primero dentro de cada semilla y después se resumen.

### 1. Futuro: una columna posterior puede no mejorar la puntuación

| Probabilidad de inversión | Legítimas | + Posterior | + Control independiente | Mediana de posterior − legítimas |
| --- | ---: | ---: | ---: | ---: |
| 0 | 59,6 % | 100,0 % | 58,8 % | +40,4 puntos |
| 0,25 | 59,6 % | 71,5 % | 58,8 % | +11,7 puntos |
| 0,5 | 59,6 % | 58,2 % | 58,8 % | −0,2 puntos |

Con inversión 0,5, la columna posterior mejoró la puntuación en tres semillas, empató en dos y la empeoró en cinco. El control independiente también mejoró tres, empató dos y empeoró cinco, con una mediana de diferencia de −0,2 puntos. Esto conserva visibles mejoras accidentales con columnas sin señal; el control no exige que añadir ruido perjudique siempre.

La tendencia agregada concuerda con debilitar la señal posterior. El diagnóstico temporal no depende de esa tendencia: con inversión 0,5 la columna continúa indisponible al comprar, aunque por construcción no aporte información generativa sobre la etiqueta.

### 2. Entidades: el resultado interno excelente no se traslada a máquinas nuevas

| Ruido de medición | Test por filas | Test por grupos | Cohorte: modelo por filas | Cohorte: modelo por grupos |
| --- | ---: | ---: | ---: | ---: |
| 0,035 | 100,0 % | 54,2 % | 52,8 % | 52,9 % |
| 0,35 | 96,3 % | 53,2 % | 53,1 % | 54,7 % |
| 1,0 | 56,9 % | 49,3 % | 49,3 % | 51,9 % |

En todas las configuraciones, la partición por filas compartió **75–84 máquinas**; la corregida compartió **cero**. Ambos entrenamientos tienen 378 filas, pero el primero incluye 90 máquinas y el segundo 63. La fracción positiva en los tests internos varía entre **46,9–53,1 %** por filas y **40,7–55,6 %** por grupos. Son diferencias de composición que balanced accuracy ayuda a interpretar, sin eliminarlas todas.

Sobre la cohorte común, las medianas de las diferencias emparejadas «modelo por filas − modelo por grupos» son aproximadamente **0,0 / −3,0 / −2,8 puntos** al aumentar el ruido. No hay una superioridad universal del modelo corregido. La gran puntuación interna del modelo por filas con ruido bajo describe reconocimiento de entidades conocidas; las diferencias entre modelos sobre la cohorte también dependen de sus entrenamientos distintos.

### 3. Selección: crece la evaluación contaminada, pero no de forma monótona en cada semilla

| Variables irrelevantes | Selección global | Selección solo train | Baseline | Mediana de global − train |
| --- | ---: | ---: | ---: | ---: |
| 50 | 56,7 % | 48,8 % | 50,0 % | +5,3 puntos |
| 500 | 76,4 % | 53,1 % | 50,0 % | +23,7 puntos |
| 1800 | 79,6 % | 50,6 % | 50,0 % | +29,1 puntos |

El aumento agregado concuerda con encontrar asociaciones accidentales al buscar entre más columnas. Sin embargo, las semillas **11, 314 y 65535** bajan su puntuación contaminada al pasar de 500 a 1800 variables. Por ejemplo, la semilla 314 pasa de **83,2 % a 77,6 %**. No se cambió el diseño para ocultarlo: selección, estimación finita y ajuste regularizado no garantizan monotonía individual.

Con 50 variables y semilla 65535, las dos variantes empatan en **47,0 %**, por debajo del baseline, aunque el selector global sí consultó test. Con 500 variables, la versión limpia supera al baseline en ocho de diez semillas y alcanza una mediana de 53,1 %. Ninguno de esos hechos crea señal real: las etiquetas siguen siendo independientes por construcción y el estudio es descriptivo.

La batería completa terminó con **115 pruebas aprobadas en 13,79 s**, incluidas las rutas guiada y Laboratorio, controles legítimos y mutaciones aisladas. Entre ellas se introducen entidades compartidas, una columna futura en la variante legítima, etiquetas de test en el ajuste, predicciones con métricas obsoletas, resultados de caché de otra configuración e informes ajenos. La validación comprueba filas, etiquetas y cálculos, sin aceptar una bandera de diagnóstico como prueba. La prueba de caché también verifica que la aplicación rechace la entrada incorrecta y pueda recuperarse en una nueva ejecución válida.

Después de retirar una validación duplicada al cargar el estudio, las **20 pruebas de interfaz pasaron de nuevo en 7,08 s**. También se recorrieron otra vez los tres casos guiados en Chrome: pistas, explicación, cambio de caso/semilla y descargas, sin errores ni peticiones externas. Ninguno de estos ajustes requirió repetir el estudio.

También se comprobó el Laboratorio en **Chrome con Playwright**, en **1440 × 1000** y **390 × 844**. Se recorrieron los tres casos y dos niveles de futuro, la invalidación al cambiar caso/semilla/nivel, la recarga del estudio y las descargas. Las métricas de las cuatro ejecuciones descargadas se recalcularon; la exportación del estudio coincidió con el archivo completo de 90 entradas. Se verificaron los puntos del gráfico de entidades y selección y los cuartiles renderizados en JavaScript frente a NumPy. El registro `artifacts/browser-lab-check.json` no contiene errores de página ni peticiones externas.

Se inspeccionaron las capturas de [escritorio](screenshots/05-laboratorio-escritorio.png), [móvil](screenshots/06-laboratorio-movil.png), [distribución móvil](screenshots/07-laboratorio-distribucion-movil.png) y [diferencias en móvil](screenshots/08-laboratorio-diferencias-movil.png): texto y gráficos legibles, sin solapamientos observados. Esta revisión visual es distinta de AppTest, que comprueba estados y elementos. No se ha comprobado accesibilidad con lectores de pantalla ni otros navegadores. El estudio no se repitió por los cambios documentales o de presentación que no alteran el motor.

## Qué no podremos concluir

Los datos sintéticos no demuestran rendimiento en producción. Diez semillas no son diez poblaciones reales y no justifican por sí solas inferencia estadística. Una cohorte nueva del mismo generador examina entidades nuevas bajo esa simulación; no prueba resistencia a otro dominio o a cambios temporales. Tampoco una diferencia emparejada elimina todos los efectos de la especificación del modelo.

Antes de presentarlo, hay que poder seguir qué información recibe cada llamada a ajuste y distinguir **mecanismo comprobado**, **resultado observado** y **expectativa previa**. Las [preguntas de defensa técnica](defensa-tecnica.md) permiten ensayarlo sin atribuir al autor un dominio que el repositorio por sí solo no acredita.
