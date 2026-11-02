# Preparación de la demo pública

2 de noviembre de 2026. Este documento conserva la evidencia del cierre de la preparación local para Streamlit Community Cloud, anterior a su publicación mediante PR. El despliegue sigue sin realizarse. Parte del commit público `d1be2c01e9aa4d95bc3d97b449a6a20322bb4f3e`; sus 226 pruebas y su CI son evidencia anterior a esta intervención.

## Probar en local

Desde la raíz, con las dependencias fijadas ya instaladas:

```bash
.venv/bin/python -m streamlit run demo/streamlit_app.py --server.address 127.0.0.1 --server.port 8502
```

Abrir `http://127.0.0.1:8502`. El comando local habitual sigue siendo:

```bash
.venv/bin/python -m streamlit run app.py --server.address 127.0.0.1
```

La entrada `demo/streamlit_app.py` llama a `main(public_demo=True)`. Reutiliza los tres modos y el motor; únicamente cambia la presentación del entorno y la carga de estudios. No ofrece un campo de rutas ni instrucciones para ejecutar comandos en el ordenador del visitante. Los cálculos ocurren en el servidor que ejecute Streamlit. Los datos son sintéticos, no hay cuentas de la aplicación y el progreso no es persistente.

## Estudio agregado y versiones

Esta preparación **no incorpora un estudio agregado** ni copia los históricos. El Laboratorio explica su ausencia y mantiene disponibles todas las configuraciones puntuales reales. Nunca ejecuta las 90 combinaciones al arrancar o en un rerun.

La única ubicación opcional del estudio público es `demo/study.json`, fijada por el código, sin entrada del visitante. Si se incorporase en una intervención futura, debe revisarse su contenido, procedencia, tamaño y compatibilidad antes de incluirlo en el inventario. Su carga sería explícita y pasaría por `load_study` y todos sus validadores. Un archivo ausente, ilegible o incompatible deja disponible la ejecución puntual; el mensaje público no expone la ruta del servidor ni ordena recalcular el estudio. El uso local conserva su campo de ruta y sus comandos actuales.

`runtime_versions()` registra `platform.python_version()` y el estudio exige igualdad exacta de versiones. Seleccionar **Python 3.12** en Community Cloud no acredita **Python 3.12.3**, que es el parche de los históricos. No se modifica la versión declarada de ningún informe ni se relaja esa comparación. La ausencia de un estudio en esta primera demo evita presentarlo como compatible con un parche remoto todavía desconocido.

## Sesiones, cachés y recursos

Guiado conserva una caché de datos de 24 entradas; Laboratorio, de 48. Incluyen los parámetros y la huella del motor en sus claves. `st.cache_data` serializa resultados y devuelve copias por llamada: no se comparten objetos mutables de las investigaciones. Las cachés no contienen respuestas, notas ni revelados y no se persisten en disco.

Detective conserva los expedientes abiertos, borradores, respuestas, pistas, revelados e intervenciones únicamente en `st.session_state`. Hay ocho expedientes por semilla; cambiarla o reiniciar retira los anteriores. Las intervenciones reales siguen siendo explícitas e idempotentes. No se añade una caché global de sesiones ni se comparten notas entre visitantes. La memoria total depende también de las sesiones concurrentes y de las bibliotecas; los límites de entradas no equivalen a un límite global de RAM.

La protección evita spoilers accidentales en componentes y descargas; no es un sistema antitrampas frente a quien inspeccione el código público. Las descargas se construyen a partir de los resultados y el estado de la sesión activa.

## Despliegue futuro, pendiente de autorización

| Campo | Valor preparado |
| --- | --- |
| Repositorio | `alvaro-salvador-huertas/data-crime-scene` |
| Rama de la preparación | `feat/demo-publica`; propuesta para revisión contra `main`. |
| Rama futura del alojamiento | La rama que se autorice a publicar; usar `feat/demo-publica` si se publica esta rama, o `main` tras una integración autorizada. |
| Punto de entrada | `demo/streamlit_app.py` |
| Python | Seleccionar explícitamente 3.12 en Advanced settings; verificar después el parche real. |
| Dependencias | `requirements.txt` en la raíz, sin cambiar pins. `requirements-browser.txt` solo sirve para QA local. |
| Secretos | Ninguno necesario. No subir `.env`, credenciales ni `secrets.toml`. |
| Almacenamiento | Sin archivos privados, `artifacts/` imprescindible ni escrituras persistentes de la aplicación. |

La configuración raíz mantiene `server.address = "127.0.0.1"`. La configuración del subdirectorio `demo/.streamlit/config.toml` cambia únicamente la dirección a `0.0.0.0` para el alojamiento; hereda el tema raíz. Streamlit 1.66.1 lee la configuración del directorio del punto de entrada después de la del proyecto. La opción CLI del comando local anterior tiene precedencia y devuelve la escucha a loopback. No se configura la dirección desde el script una vez iniciado el servidor.

Community Cloud impone `browser.gatherUsageStats = true`, aunque el archivo del proyecto declare `false`. Por eso la demo alojada no promete ausencia de telemetría ni de servicios externos. La prueba local hereda la configuración local, no reproduce esa imposición del proveedor.

Fuentes oficiales consultadas para estas decisiones: [despliegue y selección de Python](https://docs.streamlit.io/deploy/streamlit-community-cloud/deploy-your-app/deploy), [configuración impuesta y estructura de archivos](https://docs.streamlit.io/deploy/streamlit-community-cloud/status), [dependencias](https://docs.streamlit.io/deploy/streamlit-community-cloud/deploy-your-app/app-dependencies), [precedencia de configuración](https://docs.streamlit.io/develop/api-reference/configuration/config.toml) y [cachés y copias](https://docs.streamlit.io/develop/concepts/architecture/caching).

Tras un despliegue autorizado habrá que comprobar acceso público sin credenciales del visitante, logs y versiones efectivas, tres modos, aislamiento de dos sesiones, descargas, consumo de RAM bajo concurrencia y recuperación tras suspensión/reinicio. Los tiempos locales no acreditan prestaciones en cloud. No se han creado recursos externos ni modificado el portfolio.

## Validación de esta preparación

Las pruebas nuevas están en `tests/test_public_demo.py`; el recorrido de navegador se puede repetir con Chrome/Chromium y el extra opcional, con el servidor ya iniciado:

```bash
.venv/bin/python scripts/check_public_demo.py --url http://127.0.0.1:8502 --output-dir artifacts/demo-browser-nuevo
```

El directorio de salida debe ser nuevo para conservar evidencias anteriores. Las evidencias locales se guardan en `artifacts/demo-publica-20261102/`; no se añaden al conjunto publicable.

| Comprobación | Resultado efectivo |
| --- | --- |
| Primera selección de pruebas afectadas | 51 aprobadas en 26,86 s. |
| Pruebas públicas finales, incluida evidencia adicional | 15 aprobadas en 9,63 s. |
| Suite completa, una sola ejecución sobre el código final | **241 aprobadas en 43,29 s**, sin fallos ni saltos. |
| Instalación limpia | Python 3.12.3, 45 pins coincidentes, `pip check` correcto. Entorno separado; `.venv` habitual conservada. |
| Copia limpia | 97 archivos previstos, sin `artifacts/`, secretos ni entornos copiados. Arranque y navegador con el Python recién instalado. |
| Navegador | Chrome headless, 1440×1000 y 390×844, tres modos en ambos tamaños y dos contextos independientes. Siete grupos de comprobaciones aprobados; cero errores de página/consola o peticiones externas durante esta prueba local. |
| Sesiones y resultados | Evidencia y notas aisladas, descargas antes/después del revelado, intervención real y repetición idempotente; reiniciar una sesión conserva la otra. Métricas y matrices del JSON recalculadas por aritmética independiente; valores visibles de Guiado y Detective cotejados con sus descargas. |
| Conservación | Los diez módulos de `data_crime_scene/`, dependencias, configuración raíz y 21 históricos conservan sus bytes. Diez informes históricos aceptados, con 196 resultados contando duplicados. No se ejecutó el estudio. |
| Remoto al cerrar la preparación local | Todavía sin CI nueva ni publicación de la rama. La CI de 226 pruebas corresponde al commit anterior. El resultado de la CI de esta PR debe consultarse en GitHub Actions. No hay despliegue. |

Se inspeccionaron las seis capturas de los tres modos a ambos anchos: sin desbordamiento horizontal de página ni cambios de diseño; el nuevo texto de entorno es legible. El primer recorrido se detuvo al enfocar un multiselect móvil sin abrir su menú. Se corrigió el script de QA para abrirlo con teclado, sin cambios en la aplicación ni rebaja de aserciones, y se repitió con éxito. Se conservan ambos informes y logs. La primera descarga de paquetes falló por DNS del sandbox; la instalación posterior con acceso de red terminó correctamente.

Medidas del segundo recorrido local, sin ejecutar estudios grandes:

| Operación | Tiempo observado |
| --- | --- |
| Proceso hasta respuesta `/_stcore/health` | 0,42 s; todavía no incluye la carga de la primera página. |
| Primera página, primer contexto | 2,13 s. |
| Guiado, ejecución explícita inicial | 0,38 s. |
| Laboratorio, entidades, semilla 42, nivel 0,35 | 0,31 s. |
| Abrir Detective d01 | 0,30 s. |
| Intervención real d01 | 0,54 s. |
| Repetición idempotente de la intervención | 0,41 s, sin nuevo entrenamiento. |

Los tiempos de interacción incluyen red local, renderizado y una espera de sincronización de 250 ms del script; no son tiempos puros de entrenamiento. El segundo contexto puede aprovechar la caché sintética. El máximo de RSS observado del servidor Python fue **254.084 KiB (248,1 MiB)**; excluye Chrome y no estima el consumo con muchos visitantes. Muestras de payload JSON: Guiado 97.174 bytes, Laboratorio de entidades 119.665 bytes e investigación Detective 28.617 bytes antes y 74.239 después. No son cotas para todas las semillas ni equivalen al tamaño de los objetos en RAM. No se ha probado presión de memoria, concurrencia masiva, dispositivos reales, otros navegadores ni prestaciones remotas.

`pytest-full.txt`/`pytest-full.xml`, `browser-run2/browser.json`, `environment-clean.json`, `config-precedence.json`, `payload-sizes.json`, `historical-validation.json` y `preservation-final.json` conservan el detalle. `browser-run1/` mantiene el intento fallido. Los dos servidores temporales se cerraron; los registros de limpieza identifican sus PID. El diff completo respecto del commit de referencia, incluidos archivos nuevos, está en `intervention.patch`; el inventario con hashes, en `publication-manifest.json`.

## Archivos de esta intervención

Nuevos: `demo/streamlit_app.py`, `demo/.streamlit/config.toml`, `tests/test_public_demo.py`, `scripts/check_public_demo.py` y este documento.

Modificados: `app.py`, `ui/laboratory.py`, `ui/detective.py`, `.gitignore`, `README.md`, `docs/archivos-publicacion.txt`, `docs/metodologia.md`, `docs/modo-detective.md` y `docs/publicacion.md`. Son 14 archivos nuevos o modificados; el [inventario propuesto](archivos-publicacion.txt) contiene 97 en total. La exclusión adicional cubre secretos de Streamlit también en subdirectorios. Al cerrar esa preparación no se había hecho staging, commit, push ni PR. La revisión posterior para publicar esta rama cotejó los 97 archivos con el manifiesto y reutilizó la validación local; solo actualizó este documento y `docs/publicacion.md` para precisar ese momento. La publicación del código no incluye merge, despliegue ni cambios en el portfolio.
