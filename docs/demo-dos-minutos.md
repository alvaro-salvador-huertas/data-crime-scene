# Guion de demostración · unos dos minutos

Antes de comenzar, arranca la aplicación desde la raíz del repositorio:

```bash
.venv/bin/python -m streamlit run app.py --server.address 127.0.0.1
```

Si quieres mostrar las distribuciones del Laboratorio, genera el estudio antes de la demostración, conservando los archivos históricos que ya tengas:

```bash
.venv/bin/python -m data_crime_scene.study --output artifacts/laboratory-demo.json
```

Este comando hace cálculos reales. No hace falta ejecutarlo durante la presentación. En una copia recién descargada, los informes locales excluidos de Git todavía no existen.

| Tiempo | Acción y explicación |
| --- | --- |
| 0:00–0:15 | «Data Crime Scene permite investigar si una evaluación de machine learning responde a la pregunta que promete. Entrena modelos pequeños con datos sintéticos; una puntuación alta, por sí sola, no demuestra ni descarta una fuga». |
| 0:15–0:45 | Abre Modo Detective, conserva la semilla de sesión 42 y elige **La mesa norte**. Enseña el objetivo, la muestra y la disponibilidad de `registro_c17`. «Tengo que separar tres decisiones: diagnóstico, evidencia y acción. Si falta un dato metodológico, pedirlo es una respuesta posible». |
| 0:45–1:10 | Confirma el diagnóstico apoyado en la disponibilidad temporal, consulta la explicación y ejecuta retirar la variable posterior. «La operación usa el mismo motor. Compruebo columnas, entidades o filas de ajuste; no premio simplemente que baje la puntuación». |
| 1:10–1:40 | Pasa a Laboratorio. Carga `artifacts/laboratory-demo.json` o el estudio local previamente conservado y muestra un nivel y sus diez semillas. «Cada punto es una semilla. Las cajas muestran mediana y cuartiles, no intervalos de confianza. El archivo conserva parámetros, predicciones y versiones». |
| 1:40–2:00 | «Los resultados son sintéticos. En el caso de entidades también cambian los entrenamientos, así que ni una cohorte común identifica un efecto causal puro de la fuga. El proyecto se desarrolló con asistencia de IA y ofrece material para aprender y discutir estas decisiones». |

La guía de [Modo Detective](modo-detective.md) permite escoger un expediente adecuado antes de ensayar. Mantén los casos legítimos y los incompletos en la demostración si dispones de más tiempo: ayudan a evitar la regla equivocada de que toda puntuación llamativa es contaminación.
