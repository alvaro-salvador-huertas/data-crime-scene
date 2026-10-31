# Integración visual · 29 de octubre de 2026

La presentación del laboratorio visual se ha adaptado a la aplicación actual de Data Crime Scene, incluido su Modo Detective. Se conserva el motor existente: los controles siguen ejecutando las operaciones reales que ya tenían asignadas. No se ha sustituido `app.py` por una versión anterior ni se han copiado datos de demostración al producto.

## Cambios

- Tema claro de laboratorio: fondo frío, tinta oscura, verde azulado para acciones y ámbar para resultados sospechosos. Los estados conservan sus etiquetas; el color no es su única señal.
- Avisos nativos con colores semánticos explícitos mediante opciones públicas del tema. Se corrigió el aviso amarillo predeterminado, cuyo contraste sobre el nuevo fondo era 4,40:1; ahora alcanza 5,90:1.
- Expediente con objetivo y momento de predicción en una lista de definiciones, dos columnas en escritorio y una en móvil. Encabezados, texto auxiliar y cifras tienen una escala compartida.
- Métricas nativas con borde, foco visible y enlace «Saltar al contenido». La barra lateral usa el comportamiento adaptable nativo de Streamlit.
- Gráficos con superficies claras y etiquetas contrastadas. Se preservan valores, orden, unidades, escalas, cuartiles lineales de pandas, bigotes mínimo–máximo, puntos individuales y reglas de emparejamiento.
- CSS limitado a clases propias y contenedores con `key` público. Sin manipulación JavaScript del documento, selectores de clases generadas ni controles nativos ocultos.
- Sin animaciones nuevas. El tema Plotly desactiva transiciones de datos y el CSS respeta `prefers-reduced-motion`.

Se mantuvieron los textos, las opciones, las claves de widgets, los callbacks, las condiciones de revelado, la puntuación, las exportaciones y las cachés. El motor, las pruebas preexistentes, las dependencias, el README, el portfolio y la galería original se conservaron.

## Archivos afectados

Modificados respecto a la copia inicial:

1. `.streamlit/config.toml`: opciones públicas del tema.
2. `app.py`: conexión con presentación compartida y tema del gráfico del recorrido guiado.
3. `ui/detective.py`: expediente, jerarquía y contenedor de solución dentro del revelado existente.
4. `ui/laboratory.py`: tema de gráficos y presentación compartida.
5. `ui/style.css`: estilos de la identidad y foco.

Nuevos:

- `ui/presentation.py`: `load_styles()`, `caption(text)`, `brief_card(objective, prediction_time)` y `skip_link()`. Escapa texto dinámico; no contiene estado ni dependencias del motor.
- `ui/plotly_theme.py`: constantes de apariencia y `apply_template(figure) -> go.Figure`, que devuelve una copia y conserva la semántica del gráfico recibido.
- `tests/test_visual_charts.py`: 23 regresiones frente a las funciones de gráficos anteriores, congeladas dentro del propio test. No necesita la carpeta de artefactos para ejecutarse.
- `scripts/check_visual_integration.py`: recorrido reproducible en navegador sobre la aplicación real; no arranca servidores ni instala paquetes.
- Este documento y `docs/screenshots/visual-integration-20261029/`.
- Evidencia local en `artifacts/visual-integration-20261029/`, ignorada por la configuración Git preexistente. Se conserva en disco; no depende de `/tmp`.

No se añadieron ni actualizaron dependencias, skills, hooks o servicios. Se utilizó el entorno existente: Python 3.12.3, Streamlit 1.66.1 y Plotly 7.1.0. Las fuentes de Streamlit se sirven localmente; no se agregó una fuente remota.

## Comprobaciones

- Suite completa: **205 pruebas aprobadas** (182 existentes y 23 nuevas).
- Sintaxis: `compileall` correcto en `app.py` y `ui/`.
- Dependencias: `pip check` sin incompatibilidades.
- Revisión estática con `web-design-guidelines`: sin regresiones concretas de lógica, texto o semántica de datos. Se contrastó con la [guía original](https://raw.githubusercontent.com/vercel-labs/web-interface-guidelines/main/command.md).
- Contraste de 11 combinaciones: texto principal 13,60:1, texto auxiliar sobre lateral 5,38:1, botón principal 6,32:1, foco 6,53:1 y bordes 3,75:1. Los pares de texto comprobados superan 4,5:1; foco y borde superan 3:1. No constituye una auditoría de todos los estados nativos.
- En navegador, el enlace de salto aparece al enfocarlo y Enter traslada el foco a `#dcs-main`.
- Colores configurados de avisos nativos: advertencia 5,90:1, éxito 6,01:1, error 6,29:1 e información 6,35:1. Se verificó que la versión instalada reconoce las opciones públicas del tema.

Comprobación final de navegador: **18 de 18 verificaciones aprobadas**, tras corregir el contraste y regenerar las capturas:

- Recorrido guiado, Laboratorio y Detective a **390, 768 y 1440 px**, sin desbordamiento de página ni de gráficos visibles.
- Navegación lateral móvil, desplegables por teclado, foco de 3 px, confirmación con Enter y notas largas conservadas en la exportación.
- Detective d01: evidencia pública sin solución, confirmación, revelación explícita e intervención real. Métricas y matrices recalculadas a partir de las predicciones exportadas.
- Gráficos del guiado contrastados con sus métricas; laboratorio contrastado con valores, orden, cuartiles, extremos, escalas y emparejamiento de la cohorte común. Estudio descargado idéntico al archivo local preexistente, sin regenerarlo.
- Estado inicial, error real al cargar un archivo inexistente, resultado y exportaciones. Movimiento reducido: contenido accesible y ninguna animación en ejecución al estabilizar la vista.
- **13 párrafos de avisos nativos** medidos sobre sus fondos efectivos; mínimo **5,898:1**.
- **178 peticiones y 1 WebSocket locales**, cero intentos externos y cero errores de página o consola.

No quedan comprobaciones bloqueadas dentro de este alcance. Los límites de cobertura se indican abajo.

## Arranque y repetición

Mañana solo hace falta arrancar la aplicación; no hay migraciones ni instalaciones pendientes:

```bash
cd data-crime-scene
.venv/bin/python -m streamlit run app.py --server.address 127.0.0.1 --server.port 8503 --server.headless true
```

Abrir <http://127.0.0.1:8503>. Si ese puerto está ocupado, elegir otro libre y pasarlo también al script de navegador.

En otra terminal, con el servidor activo:

```bash
.venv/bin/python -m pytest -q
.venv/bin/python -m compileall -q app.py ui scripts/check_visual_integration.py
.venv/bin/python -m pip check
.venv/bin/python scripts/check_visual_integration.py --url http://127.0.0.1:8503
```

El último comando requiere el Chrome y Playwright ya instalados. Usa el estudio preexistente `artifacts/laboratory-study.json` sin regenerarlo. Solicita ejecuciones reales pequeñas mediante los controles existentes; los JSON descargados son resultados de esas ejecuciones. Para conservar las capturas de esta intervención al repetirlo, proporcionar `--output-dir` y `--screenshots-dir` con directorios nuevos.

## Límites

- Streamlit requiere JavaScript y WebSocket local; no se ofrece una versión funcional sin JavaScript.
- La revisión usa Chrome de escritorio con ventanas de diferentes tamaños. No equivale a pruebas en dispositivos físicos, Safari o Firefox, ni a una revisión manual con lector de pantalla.
- Las tablas conservan su desplazamiento horizontal nativo cuando sus columnas exceden el ancho disponible. Los controles y la navegación siguen siendo widgets de Streamlit.
- No se han medido tiempos de carga comparativos, memoria o FPS; no se afirma una mejora de rendimiento.
- No se añadieron modelos, casos ni funciones de negocio. Los datos de la galería, sus estados simulados y sus transiciones permanecen únicamente en la galería. La aplicación integrada utiliza sus datos sintéticos y cálculos reales preexistentes.

## Evidencia y conservación

El repositorio todavía no tenía commits y sus archivos ya estaban sin seguimiento al comenzar. Por ello, `git diff` por sí solo no representa esta intervención. La referencia exacta está en `artifacts/visual-integration-20261029/before.json` y `before/`; incluye hashes de los 54 archivos originales y de las carpetas protegidas.

Las capturas antiguas de `docs/screenshots/` se conservan sin sobrescribirlas. La evidencia nueva se guarda en su subcarpeta fechada:

- [Inicio del recorrido guiado](screenshots/visual-integration-20261029/01-guided-initial-1440.png).
- [Detective en escritorio](screenshots/visual-integration-20261029/05-detective-public-1440.png) y [en móvil](screenshots/visual-integration-20261029/05-detective-public-390.png).
- [Comparación guiada en móvil](screenshots/visual-integration-20261029/02-guided-comparison-chart-1-390.png).
- [Distribución del laboratorio](screenshots/visual-integration-20261029/04-laboratory-chart-1-390.png), [cohorte común](screenshots/visual-integration-20261029/04-laboratory-chart-2-390.png) y [diferencias emparejadas](screenshots/visual-integration-20261029/04-laboratory-chart-3-390.png).
- [Foco de teclado](screenshots/visual-integration-20261029/07-detective-keyboard-focus-390.png) e [intervención real](screenshots/visual-integration-20261029/08-detective-intervention-390.png).

Los resultados de pytest y contraste están en `pytest.txt`, `contrast-focus.json` y `native-alert-theme.json` dentro de la carpeta de artefactos. El reporte reproducible del navegador es `browser/browser-check.json`, acompañado de `final-browser-run.log` y los JSON descargados. Hay **28 capturas nuevas**: 27 del recorrido automatizado y una del enlace de salto. Los primeros intentos conservados documentan ajustes del script de comprobación: etiqueta completa de F1, tablas dentro de desplegables cerrados y apertura de widgets nativos por teclado.

El diff de integración local (`artifacts/visual-integration-20261029/integration.diff`, excluido del repositorio público) compara los archivos de texto con la referencia inicial e incluye los nuevos. `after.json` enumera también las capturas y sus hashes. Se conservan 49 de los 54 archivos iniciales idénticos; los otros cinco son los modificados enumerados arriba. Los 21 archivos del portfolio y los 79 de la galería incluidos en la referencia permanecen idénticos, sin incorporaciones ni desapariciones; se excluyen entornos, cachés, Git y artefactos generados de ese inventario.

Git continúa sin commits y con los archivos sin seguimiento; el índice sigue vacío. El estado final está en `git-status-final.txt`. No se ha realizado staging, commit, push, PR ni despliegue.

Se detuvieron únicamente los servidores propios de esta intervención: aplicación en `127.0.0.1:8503` y galería en `127.0.0.1:58037`, además de los navegadores de prueba. Se verificó que ambos puertos quedaron libres y que el servidor ajeno de `127.0.0.1:8000` continuaba activo. Evidencia: `process-cleanup.json` y `listeners-final.txt`. Para usar la aplicación mañana hay que ejecutar el comando de arranque de esta nota.
