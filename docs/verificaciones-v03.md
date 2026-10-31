# Comprobaciones de la intervención Detective

Este documento separa las comprobaciones actuales de la evidencia de versiones anteriores. Los resultados finales se incorporan después de ejecutar cada comprobación.

## Punto de partida y conservación

Se inspeccionaron generadores, particiones, modelos, validadores, estados de Streamlit, exportaciones, pruebas, protocolo e informe metodológico. No había instrucciones `AGENTS.md` aplicables. Git no reconocía un repositorio: `.git` era un directorio vacío protegido. Se inicializó localmente en `main`, sin staging, commits ni remoto.

La portada anterior comunicaba **115 pruebas en 13,79 s** y una repetición posterior de **20 pruebas de interfaz en 7,08 s**. Esa atribución histórica se conserva en el informe de [Laboratorio](revision-laboratorio.md); no se presenta como validación de Detective. También permanecen las capturas 01–08 y los artefactos de aquellas intervenciones.

Al inicio de esta intervención se ejecutaron explícitamente los seis archivos de pruebas existentes: **115 aprobadas en 13,66 s**. No incluían aún el nuevo modo. La portada anterior se guardó íntegra en `artifacts/v03/README-v02-original.md`, excluida de publicación, antes de sustituirla por una presentación más breve.

Las huellas SHA-256 de los artefactos anteriores se guardaron en `artifacts/publication-v3-preservation-baseline.json`; las de los seis módulos del motor en `artifacts/v03/engine-preservation.json`. El contraste final confirmó **21 artefactos históricos conservados, sin cambios ni ausencias**, y la misma huella del motor. El estudio de 90 combinaciones no se volvió a ejecutar. Su carga en la nueva interfaz comprueba compatibilidad y presentación, no convierte el estudio histórico en una evaluación de Detective.

## Instalación limpia

Se creó `.tmp/clean-install`, separado de `.venv` y excluido de Git. La primera descarga dentro del sandbox no pudo resolver el servidor de paquetes; se repitió con el acceso de red autorizado para instalar dependencias. La instalación desde `requirements.txt` terminó correctamente, con Python **3.12.3**, y se contrastó cada versión instalada con su pin. `pip check`: **sin dependencias incompatibles**.

Desde ese entorno limpio se ejecutó la batería integrada: **182 pruebas aprobadas en 31,28 s**. En el entorno habitual, la misma batería obtuvo **182 aprobadas en 31,36 s**. Ambas corridas se realizaron sobre el código de los tres modos; los logs y el inventario de las **45 versiones fijadas** quedan en `artifacts/v03/pytest-clean.log`, `pytest-main.log` y `clean-install.json`. `.venv` no se alteró para instalar o eliminar dependencias. El entorno temporal se eliminó después de las comprobaciones, conservando esos registros.

## Integración y navegación

Las 182 pruebas incluyen las ocho plantillas, columnas efectivamente utilizadas, intersecciones calculadas desde filas y entidades, índices reales del selector, predicciones, controles legítimos y los dos expedientes incompletos. También cubren intervenciones reales, alternativas válidas, negativa a ejecutar acciones ajenas, confirmaciones idempotentes, soluciones consultadas antes de responder, ausencia de respuestas privadas en exportaciones y notas libres inertes. Los fixtures de métricas extremas solo viven en pruebas aisladas: no son resultados fabricados de la aplicación.

AppTest comprueba los tres modos y estados simulados. Por separado, se realizó navegación real en **Chrome 156.0.8078.47 con Playwright 1.64.1**, en **1440 × 1000** y **390 × 844**:

- Recorrido guiado: entrenamiento, explicación y descarga actual, con métricas recalculadas.
- Laboratorio: ejecución puntual actual, evaluación de la cohorte y carga explícita del estudio histórico compatible, sin volver a ejecutarlo.
- Detective **La mesa norte**: evidencia inicial sin solución, pista, diagnóstico/evidencia/acción, confirmación sin revelación automática, solución explícita y reparación real. La descarga incluye predicciones antes/después y se recalcularon sus métricas y matrices.
- Detective **El cuaderno azul**: control legítimo mantenido, sin fingir otro entrenamiento ni una reparación.
- Detective **El archivo diecisiete**: información inicialmente insuficiente, solicitud de disponibilidad, fase ampliada y diagnóstico final. Las dos respuestas cuentan como un único expediente.
- Descarga de sesión, reinicio con progreso/pistas/soluciones a cero, cambio de semilla y activación de una pista mediante teclado.

El registro `artifacts/v03/browser/browser-check.json` contiene **cero errores JavaScript y cero peticiones externas**. Se comprobaron también el panel lateral estrecho y la ausencia de desbordamiento horizontal de página. El script sincroniza sus acciones con los reruns de Streamlit; esa sincronización de pruebas no requirió cambiar el procedimiento de evaluación.

Se inspeccionaron visualmente las cuatro capturas nuevas: [expediente](screenshots/09-detective-expediente.png), [intervención](screenshots/10-detective-intervencion.png), [vista estrecha](screenshots/11-detective-movil.png) y [Laboratorio actual](screenshots/12-laboratorio-v03.png). Se observaron textos y controles legibles, jerarquía clara y ausencia de solapamientos materiales. Las capturas 01–08 permanecen como evidencia histórica.

Para repetir la revisión sin sobrescribir capturas anteriores, arranca Streamlit e instala el extra opcional:

```bash
.venv/bin/python -m pip install -r requirements-browser.txt
.venv/bin/python scripts/check_detective_browser.py
```

El script requiere Chrome/Chromium ya instalado y guarda por defecto un directorio nuevo con fecha en `artifacts/`. No instala un navegador ni se ejecuta desde CI. No se ha revisado con otros navegadores, lectores de pantalla ni sistemas operativos.

## Publicación futura

El [workflow de CI](../.github/workflows/ci.yml) está preparado para `push` y `pull_request`, Ubuntu y Python 3.12. Su preparación y revisión local no equivalen a haberlo ejecutado en GitHub. No hay badge de éxito, remoto, staging, commit, push, PR, release ni despliegue. El [inventario publicable](publicacion.md) explica qué compartir y qué queda exclusivamente local.
