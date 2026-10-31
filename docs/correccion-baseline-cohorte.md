# Corrección del baseline de cohorte

30 de octubre de 2026. Cambio interno del validador; sin nuevas funcionalidades, cambios visuales, entrenamiento del estudio ni modificación de resultados históricos.

## Defecto y fuente de verdad

`validate_lab_result` verificaba las predicciones y métricas de cada cohorte, pero no contrastaba su baseline con la mayoría del entrenamiento de esa variante. Un baseline constante de la clase contraria, con métricas recalculadas, pasaba tanto ese validador como `validate_study`.

El informe guarda configuración, semilla, parámetros y `train_row_ids` por variante. El generador determinista permite reconstruir las etiquetas correspondientes a esas filas. Esa es la fuente de verdad utilizada, después de validar las particiones; no se elige la mayoría con etiquetas de test, etiquetas de cohorte, métricas o diagnósticos declarados. La comparación usa el entrenamiento de cada variante, no una mayoría global compartida.

La corrección adopta el contraste propuesto por la auditoría, revisado frente al código actual. Conserva `np.bincount(..., minlength=2).argmax()` y el desempate a **0**, como el generador existente. No añade reglas de tipos: los valores numéricos binarios que ya acepta el formato, incluidos `0.0` y `False`, siguen aceptándose; cadenas, clases ajenas y longitudes incorrectas se rechazan. No se han modificado generadores, modelos, particiones, semillas, métricas ni protocolo.

## Compatibilidad histórica explícita

Aplicar solamente el parche de auditoría cambia la huella y hace rechazar los archivos históricos por incompatibilidad, antes de comprobar su contenido. Se conserva la huella real del código nuevo y se admite además **una única versión histórica revisada**:

```text
ec9f68561a319618c8f301b2462be4f7166704afcb69bc24996d4cff96d0b28e
```

`compatible_engine` se usa en los validadores de ejecución y estudio. No altera la huella de los informes ni omite comprobaciones: esa versión debe pasar los mismos controles nuevos, además de protocolo, versiones, parámetros, filas, etiquetas y métricas. Se siguen rechazando huellas desconocidas. La caché de ejecuciones nuevas continúa exigiendo la huella actual. Esta compatibilidad debe reevaluarse si cambia el experimento; no autoriza futuras versiones arbitrarias. La huella actual se conserva en el cierre local de la intervención.

Los seis módulos incluidos en la huella se contrastaron con la instantánea previa y la copia de la auditoría. Solo se modifican el validador de cohorte y la aceptación explícita de esa versión; los archivos del estudio permanecen intactos.

## Reproducción y regresión

La reproducción utiliza una copia temporal de la entrada `groups`, semilla 42, ruido 0,35, de `artifacts/laboratory-study.json`. Su entrenamiento corregido contiene 186 positivos entre 378 filas: corresponde predecir 0. Se sustituyen las 180 predicciones del baseline de cohorte por 1 y se fijan las métricas aritméticamente coherentes: accuracy 0,4; balanced accuracy 0,5; F1 4/7. El original siempre se acepta. Antes, ambos validadores aceptaban el mutante; después, ambos lo rechazan por no corresponder al entrenamiento.

Las [regresiones publicables](../tests/test_cohort_baseline.py) usan ocho filas de desarrollo y cuatro de cohorte, sin ajustar modelos ni depender de archivos históricos. La mayoría esperada es explícita; las métricas del mutante se especifican mediante fracciones independientes del código validado. Cubren ambas variantes con mayorías distintas, baseline válido, mutantes con métricas obsoletas o recalculadas, empate, tipos y longitudes, carga de versiones actual e histórica y rechazo de otros metadatos incompatibles. El recorrido de interfaz comprueba carga, valores de la tabla, disponibilidad de descarga y retirada del estudio alterado, con entrenamiento prohibido en la prueba.

Comando acotado:

```bash
.venv/bin/python -m pytest -q tests/test_cohort_baseline.py tests/test_laboratory.py tests/test_lab_app.py
```

## Resultados efectivos

| Comprobación | Resultado |
| --- | --- |
| Regresión antes del cambio (`-k 'not load_study'`) | 3 fallos por ausencia de rechazo, 11 aprobadas, 2 excluidas; 1,36 s. |
| Pruebas afectadas, estado final | **56 aprobadas en 7,78 s**. |
| Suite completa, ejecutada una vez sobre el código final | **226 aprobadas en 33,36 s**, sin fallos ni saltos. |
| Entorno existente | Python 3.12.3, 45/45 pins coincidentes, `pip check` correcto. No se repitió la instalación limpia. |
| Históricos | **21/21 identidades SHA-256 y tamaños intactos**. Diez informes aceptados, con 196 resultados incluyendo duplicados; no son 196 experimentos independientes. |
| Carga real del estudio histórico mediante AppTest | 90 entradas; 120 filas de métricas de entidades, 60 de cohorte; descarga con el mismo contenido JSON; cero errores/excepciones, sin entrenamiento. |
| Arranque de Streamlit | HTTP `200`, cuerpo `ok`, en un puerto libre de loopback; proceso cerrado al finalizar. |
| CI remota | **No ejecutada**. |

Durante la preparación hubo dos fallos de la prueba nueva de interfaz: el fixture carecía de `train_size`/`test_size` y buscaba texto de cohorte en `markdown` aunque se presenta en otros elementos. Se completó el fixture y se comprobó directamente la tabla de cohorte, con ambas variantes y sus métricas esperadas. Los logs de los intentos fallidos se conservan; no se cambió la interfaz ni se rebajó la validación del baseline. El primer intento de comprobar el arranque no pudo crear sockets en el sandbox; la comprobación posterior con permiso de ejecución local terminó correctamente.

Las 182 pruebas de Detective y 205 de integración visual siguen atribuidas a sus intervenciones anteriores. No sustituyen las 226 actuales. No se repitió la revisión visual ni el estudio de 90 combinaciones.

## Evidencias locales y revisión

Directorio excluido de publicación: `artifacts/cohort-baseline-20261030/`.

- `before/`, `before.json`, `git-before.txt`: instantánea de los 87 archivos publicables originales, sus identidades y el estado sin commits ni staging.
- `reproduce.py`, `reproduction-before.json`, `reproduction-after.json`: reproducción sobre copia temporal y rechazo posterior. Repetible con `.venv/bin/python artifacts/cohort-baseline-20261030/reproduce.py` en este checkout, donde están los históricos.
- `regression-before.txt`, `pytest-affected.txt`, `pytest-affected-final.txt`, `pytest-affected-verified.txt`: regresión inicial, dos fallos del fixture de interfaz y corrida afectada correcta.
- `pytest-full.txt`, `pytest-full.xml`: única suite completa posterior al cambio.
- `historical-before.json`, `historical-validation.json`, `preservation-final.json`: identidades y comprobaciones finales. Los logs de navegador, el preflight y las imágenes solo reciben comprobación de identidad; no se presentan como informes de predicciones validados.
- `ui-history.json`, `environment.json`, `startup.json`: carga del histórico, dependencias y arranque.
- `intervention.patch`: diff íntegro del código, pruebas y documentación de esta intervención respecto de `before/`, incluidos archivos nuevos; separado de los cambios anteriores aún sin seguimiento.
- `publication-manifest.json`, `excluded-paths.txt`, `evidence-manifest.json`: inventarios exactos con identidades del contenido publicable y de las evidencias locales, y exclusiones efectivas.

El [inventario público](archivos-publicacion.txt) enumera los archivos propuestos. [Publicación](publicacion.md) detalla exclusiones, comandos y la licencia MIT autorizada posteriormente, el 31 de octubre. Al cierre de esta corrección del 30 de octubre no hubo staging, commits, push, PR, remoto ni despliegue. Auditoría externa, portfolio, ShiftLab y galería ajena no fueron editados; se conservaron también todos los artefactos previos y las capturas del proyecto.

## Límites

La comprobación acredita correspondencia con las etiquetas regeneradas y las filas de entrenamiento declaradas y validadas. No autentica el autor del informe ni demuestra que un modelo se entrenara realmente sobre esas filas: no se archivan pesos o una traza autenticada para demostrarlo sin reajustar. La huella tampoco es una firma. Un objeto aislado de predicciones, sin configuración y filas de entrenamiento, solo permite comprobar consistencia numérica; `validate_prediction_dict` no pretende acreditar la mayoría de un entrenamiento desconocido. Tampoco se añade la exigencia de reproducir exactamente la partición original ni un detector universal de fuga. Persisten los límites metodológicos ya documentados de datos sintéticos y comparación descriptiva.
