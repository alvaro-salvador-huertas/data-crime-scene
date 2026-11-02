# Investigar con Modo Detective

Elige **Modo Detective** en el selector de modos. Recibes una evaluación y tienes que decidir qué permite concluir, qué prueba sostiene tu decisión y qué acción corresponde. Una puntuación llamativa no es la respuesta.

## Una sesión

La **semilla de sesión** determina el orden de los ocho expedientes y una semilla de datos para cada uno. El orden es reproducible y se baraja. Cambiar esa semilla o pulsar **Reiniciar sesión** retira respuestas, pistas, soluciones consultadas e intervenciones de la sesión anterior. No hay usuarios, base de datos ni almacenamiento persistente del progreso.

Seleccionar un expediente no entrena: pulsa **Abrir expediente**. Los números se calculan con los modelos existentes, en CPU. Volver al mismo expediente conserva su investigación en esta sesión y reutiliza el informe calculado.

Los ocho títulos son neutrales:

| Identificador | Expediente |
| --- | --- |
| d01 | La mesa norte |
| d02 | El turno de las seis |
| d03 | La sala de mediciones |
| d04 | El cuaderno azul |
| d05 | La estación central |
| d06 | El lote de la tarde |
| d07 | El archivo diecisiete |
| d08 | El informe de la sala dos |

Hay tres procedimientos contaminados, tres controles legítimos y dos informes inicialmente incompletos. La semilla cambia los datos y las puntuaciones; cada plantilla fija la estructura metodológica. No hay un requisito de puntuación alta ni de caída tras la corrección.

## El recorrido

1. Lee el **objetivo declarado** y el instante de predicción.
2. Inspecciona la muestra, las variables efectivamente utilizadas, métricas, partición y documentación del ajuste. El panel de trazabilidad permite examinar índices, modelo y predicciones.
3. Si lo necesitas, consulta la primera pista y después la segunda. Solo se descargan las pistas que has abierto.
4. Separa **diagnóstico**, **evidencia** y **acción**. Las notas libres se conservan, pero no se califican por palabras clave ni por un LLM.
5. Confirma. Se registra un único intento por fase de evidencia. Los reruns, otra confirmación o volver de otro modo no duplican aciertos.
6. Consulta la solución cuando decidas contrastar tu respuesta. Confirmar no la revela automáticamente. Si la abres antes de responder, el resumen registra que hubo ayuda de la solución.
7. Ejecuta la acción elegida si corresponde. Las reparaciones llaman al motor real con la misma semilla. Una acción ajena al expediente muestra el motivo y no aplica otra silenciosamente.
8. Revisa qué cambió, qué se mantuvo y los límites de la comparación. Pasa al siguiente expediente o vuelve a uno anterior.

**Mantener** un procedimiento legítimo no simula una reparación ni otro entrenamiento: muestra que se conserva su evaluación. Reejecutar una partición o selección que ya era adecuada puede ser una alternativa válida; se identifica como una recomprobación sin cambio de diseño.

## Cuando falta información

Si el informe no permite conocer la disponibilidad temporal o las entradas de una etapa, **información insuficiente** es un diagnóstico válido. Elige qué dato necesitas y pulsa **Solicitar la información elegida**.

La información añadida abre otra fase con decisiones nuevas. La respuesta inicial queda en el JSON, pero el resumen no cuenta dos expedientes. El veredicto de la primera fase se calcula solo con la evidencia que ya podías ver; conocer el resultado privado del experimento no se utiliza para exigir una respuesta imposible.

Si ya consultaste la solución inicial, el expediente sigue marcado como consultado con solución incluso después de recibir nuevos datos. Las conclusiones se limitan a la documentación y al mecanismo investigado: «no identifico esa contaminación» no significa «modelo completamente fiable».

## Descargas y progreso

- **Evidencia disponible:** configuración, semilla, versiones, datos mostrados, predicciones, métricas, procedimiento documentado y pistas abiertas. Excluye la respuesta esperada, explicaciones privadas y variantes hermanas.
- **Investigación:** añade tus respuestas, notas, solicitudes, uso de pistas e intervenciones reales. Incluye la solución de la fase actual únicamente cuando la has revelado explícitamente.
- **Resumen de sesión:** expedientes completados, decisiones acertadas, pistas, soluciones consultadas y conceptos que conviene repasar. Cada expediente aparece una sola vez; no hay rankings ni certificados.

La separación evita spoilers accidentales al descargar un archivo. No es protección antitrampas: el código público puede inspeccionarse tanto en el uso local como en la demo alojada. Las descargas pueden contener tus notas; los archivos locales de `artifacts/` se excluyen de Git.

## Dónde leer el código

`data_crime_scene/detective.py` separa metadatos públicos, fuentes privadas, evidencia, decisiones y estado. Reutiliza `experiments.py` sin cambiar modelos ni generadores históricos. `ui/detective.py` presenta el recorrido y mantiene los formularios separados de los intentos confirmados. Las pruebas `test_detective.py`, `test_detective_adversarial.py` y `test_detective_app.py` verifican columnas, entidades, índices, predicciones, ausencia de soluciones prematuras y comportamiento de la sesión.

Consulta [metodología](metodologia.md) para los límites de cada mecanismo y el [guion de dos minutos](demo-dos-minutos.md) para preparar una presentación. El [registro de comprobaciones](verificaciones-v03.md) atribuye por separado las pruebas automáticas, instalación limpia y navegador real.
