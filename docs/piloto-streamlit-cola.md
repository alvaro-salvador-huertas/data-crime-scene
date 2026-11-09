# Piloto local de Guiado con FIFO

Verificación en Chrome del **9 de noviembre de 2026**. Se leyó
[el informe del prototipo](prototipo-cola.md) y se reutilizó
`prototypes/fifo/service.py` **sin editarlo**. La entrada nueva es
`prototypes/fifo/pilot/streamlit_app.py`; no se importa desde la demo pública.
Los archivos anteriores del motor, aplicación, benchmark y evidencias históricas
se conservan byte por byte. No se ha repetido la campaña de carga.

**Decisión: integrar la cola para Guiado en el siguiente cambio de la aplicación,
con el contrato explícito de sesión temporal de este piloto.** En Chrome se
observó el paso de cola/cupo a resultado, sin reintentar, y se descargó el JSON
de la configuración enviada en dos sesiones independientes. La interfaz resuelve
las incertidumbres de doble clic, reruns, cambio de controles, fallo y caducidad
que dejó el ensayo HTTP. No extiendo esta decisión a Laboratorio o Detective.

La limitación material es la **recarga**: pierde acceso al trabajo anterior y
el piloto lo explica, sin reenviarlo. Si se necesita recuperarlo tras recargar,
este piloto no satisface ese contrato; habría que añadir recuperación de
identidad por separado. No se introduce persistencia ni autenticación como
requisito implícito de esta entrega. La demo pública actual permanece intacta.

## Arranque y reproducción

Desde la raíz, en dos terminales, con una carpeta de evidencia nueva:

```bash
# Terminal 1: FIFO original, un ejecutor y 19 plazas de espera.
mkdir artifacts/fifo-piloto-manual
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m prototypes.fifo.service \
  --policy fifo --queue-size 19 --port 8877 \
  --trace artifacts/fifo-piloto-manual/server-events.jsonl
```

```bash
# Terminal 2: solo la entrada nueva de Guiado.
DCS_FIFO_URL=http://127.0.0.1:8877 PYTHONDONTWRITEBYTECODE=1 \
  .venv/bin/python -m streamlit run prototypes/fifo/pilot/streamlit_app.py \
  --server.address=127.0.0.1 --server.port=8503 --server.headless=true \
  --browser.gatherUsageStats=false
```

Abrir **http://127.0.0.1:8503**. Los comandos no requieren un despliegue.
La `.venv` y Chrome existentes bastan; no se instalaron dependencias.
Detener los dos procesos con Ctrl+C. Las instrucciones completas están en el
[README del piloto](../prototypes/fifo/pilot/README.md).

La comprobación reproducible siguiente crea y detiene **sus propios** servidores
en puertos efímeros; no requiere los dos comandos anteriores:

```bash
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m prototypes.fifo.pilot.check_browser \
  --output-dir artifacts/fifo-piloto-browser-repeticion

PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest -q \
  prototypes/fifo/pilot/test_client.py prototypes/fifo/test_scheduler.py
```

La salida debe ser nueva. No ejecuta `prototypes.fifo.benchmark`, tandas de carga
ni el estudio de Laboratorio. Los controles de cupo/fallo/caducidad existen solo
en `pilot/fixtures.py`, sin rutas HTTP de administración ni controles de prueba
en la interfaz normal.

## Qué se implementó

La presentación reutiliza los estilos de Guiado y sus vistas de métricas,
evidencia, explicación y comparación. Se conserva la paleta existente: fondo
`#F3F6F7`, tinta `#182A35`, acción `#126B66`, texto auxiliar `#4D6370`, borde
`#6C818C` y blanco para las pruebas. Tipografía sans del proyecto, controles
arriba y una columna de lectura alineada a la izquierda. El estado aparece
junto a la configuración enviada, antes de las métricas. No se añadieron fuentes,
imágenes remotas, animaciones ni una navegación de modos que no están incluidos.

Las solicitudes HTTP salen de **Python en el servidor Streamlit**, no de Chrome.
Un objeto por `st.session_state` conserva el token, referencia del trabajo,
caso/semilla enviados, resultado y revelado. El token solo se envía en la cabecera
`Authorization` al servicio de loopback. No se incluye en URLs, páginas,
descargas, cookies, localStorage ni logs. El identificador visible del trabajo
no permite leerlo sin el token propietario.

Se consulta el estado cada segundo mediante un fragmento. «Actualizar estado»
provoca un rerun completo. «Ejecutar experimento» puede pulsarse otra vez con
la misma configuración y recupera el mismo identificador, sin consumir otra
admisión ni ejecutar otro motor. El acceso HTTP y los cambios del estado de
una sesión se serializan con un `RLock` propio de esa sesión.

Mientras hay un trabajo pendiente, cambiar caso o semilla solo cambia el borrador
de los controles. La interfaz identifica la configuración enviada y bloquea
enviar otra hasta que termine. Las métricas y la descarga usan el caso/semilla
del trabajo, incluso si los controles ya muestran otros valores. El resultado
recibido se valida con las defensas existentes del motor; un informe incoherente
no se muestra ni descarga.

Los estados visibles son **En cola**, **Esperando cupo**, **Calculándose** y
**Terminado**. En cupo se lee:

> Esperando cupo. Tu solicitud ya está aceptada; no hace falta volver a pulsar.
> Empezará automáticamente cuando se libere el cupo de 12 cálculos o
> reutilizaciones por minuto.

También hay mensajes de fallo, resultado caducado, sesión del servicio perdida,
cola llena y conexión sin confirmar. No hay reintento automático de envío.
El servicio conserva sus límites originales: un ejecutor, 19 puestos de espera,
12 inicios/minuto, 3 s por sesión y 300 s de retención desde terminar.

## Observado en Chrome

Evidencia final en `artifacts/fifo-piloto-browser-20261109-v4/`, excluida de Git.
**Chrome 157.0.8103.38 headless**, dos BrowserContext independientes de
1440 × 1000; comprobación adicional a 390 × 844. `browser.json` terminó con
`status: passed`, sin errores de página/consola ni peticiones inesperadas.

| Comprobación | Resultado observado |
| --- | --- |
| Cálculo real por sesión | A envió `future/7`; B envió `groups/2026`. Dos trabajos propietarios distintos y dos llamadas reales al motor. |
| Doble clic real | Chrome ejecutó `dblclick`, también durante cupo y tras fallo. Los duplicados conservaron el identificador y no añadieron cálculos. |
| Reruns en espera | «Actualizar estado» en A calculándose y B en cola, y durante cupo, conservó sus trabajos. El sondeo no hizo POST de nuevos cálculos. |
| Semilla editada con trabajo pendiente | B cambió de 2026 a 2027. Se mostró el aviso y se bloqueó otro envío; no llegó al servicio una solicitud con 2027. |
| Asociación de resultado y descarga | B siguió mostrando `groups/2026`. Se descargó `data-crime-scene_groups_seed-2026.json`; A descargó `future/7`. Los bytes coincidieron con el JSON del servicio, y se recalcularon métricas desde predicciones. |
| Aislamiento | A pudo repetir su solicitud y hacer reruns sin cambiar B. Las consultas de estado y resultado con el token de la otra sesión devolvieron 404 en ambas direcciones. |
| Recuperación automática del cupo | `future/8` pasó de «Esperando cupo» a «Terminado» sin otro clic, después de liberar el presupuesto controlado. Se verificó su JSON. |
| Recarga con trabajo aceptado | Se recargó A con `future/11` esperando cupo. La sesión nueva no mostró referencia, métricas ni descarga anterior, explicó la pérdida y no reenvió el trabajo. El trabajo original terminó después en el servicio. |
| Fallo | `future/9` recibió una excepción inyectada. Se mostró fallo sin métricas ni descarga; repetir mantuvo el fallo, sin otra llamada al motor. |
| Caducidad | Al adelantar 301 s el reloj de prueba, B retiró su resultado y descarga previamente visibles. Explicó caducidad/reinicio, sin reenviar. |
| Recuperación explícita | Tras el fallo, la sesión nueva solicitó `future/10`, terminó correctamente y descargó su JSON. |
| Peticiones y token | Se bloqueó cualquier origen del navegador que no fuese Streamlit. No hubo peticiones de Chrome a FIFO; ningún token apareció en URL, DOM, mensajes WebSocket recibidos o archivos generados. |
| Pantalla estrecha | A 390 px no se observó desbordamiento horizontal; configuración enviada, estado y métricas siguieron legibles. |

El recorrido final tiene **6 admisiones**, **5 cálculos reales** (`future/7`,
`groups/2026`, `future/8`, `future/11`, `future/10`) y **1 fallo inyectado** antes
de llamar al motor (`future/9`). Se conservaron **4 descargas verificadas**; el
resultado del trabajo perdido tras recargar se confirmó en el servicio, sin
reasignarlo a la sesión nueva. No se deducen latencias ni capacidad de este
recorrido: la puerta del motor y los saltos de reloj son deliberados.

El doble clic reveló una carrera en una comprobación anterior: dos reruns podían
solaparse mientras creaban el token y abrir dos sesiones de FIFO. Se corrigió
serializando creación, envío y consulta. Una prueba concurrente reproduce ese
solapamiento y comprueba una sola sesión del servicio. Pasan **15 pruebas nuevas
del cliente/controlador y 14 del planificador FIFO existente: 29 en total**.
Incluyen también envío incierto, identidad incompatible, JSON alterado, expiración,
pérdida de sesión y transporte privado. Las pruebas unitarias no cuentan como
evidencia de comportamiento del navegador.

Las iteraciones de diagnóstico permanecen en las carpetas sin sufijo, `-v2` y
`-v3`. La evidencia de cierre es **`-v4`**. En `-v3`, un segundo clic todavía en
tránsito alcanzó el servicio después de adelantar 301 s el reloj de la prueba,
creando legítimamente un trabajo posterior al TTL. Se corrigió la sincronización
del ensayo antes de esos saltos de tiempo. No se presenta como una medición de
caducidad real en 301 segundos de reloj de pared.

## Qué significa recargar

El contrato de este piloto es una sesión efímera de Streamlit, sin recuperación
durable. No se distingue una primera visita de una recarga mediante identidad
del navegador. Ambas muestran:

> Sesión nueva. Si has recargado la página, la sesión anterior se ha perdido:
> no podemos recuperar su trabajo, que puede seguir en el servicio. No se ha
> vuelto a enviar automáticamente.

Hay además un aviso preventivo junto a los controles, visible antes de enviar.
Recargar **no cancela** lo ya aceptado ni hace público su resultado. Si se vuelve
a ejecutar desde la sesión nueva, se crea otro trabajo propietario; puede ser un
cache hit, pero consume una admisión. Los reruns normales conservan la identidad;
no equivalen a la recarga que se probó. Una desconexión breve y su reconexión
WebSocket no se han caracterizado como garantía de recuperación.

## Capturas y trazas

Capturas reales del recorrido final, guardadas localmente:

1. [Calculándose en A](../artifacts/fifo-piloto-browser-20261109-v4/01-calculandose-sesion-a.png).
2. [B en cola con la semilla editada](../artifacts/fifo-piloto-browser-20261109-v4/02-cola-seleccion-cambiada-sesion-b.png).
3. [Resultado de A](../artifacts/fifo-piloto-browser-20261109-v4/03-resultado-sesion-a.png).
4. [Resultado enviado de B: groups/2026](../artifacts/fifo-piloto-browser-20261109-v4/04-resultado-enviado-sesion-b.png).
5. [Cupo: aceptado, sin volver a pulsar](../artifacts/fifo-piloto-browser-20261109-v4/05-esperando-cupo-aceptado.png).
6. [Recarga y aviso de sesión perdida](../artifacts/fifo-piloto-browser-20261109-v4/06-recarga-sesion-perdida.png).
7. [Fallo controlado](../artifacts/fifo-piloto-browser-20261109-v4/07-fallo-controlado.png).
8. [Resultado y descarga retirados al caducar](../artifacts/fifo-piloto-browser-20261109-v4/08-resultado-caducado.png).
9. [Recuperación en pantalla estrecha](../artifacts/fifo-piloto-browser-20261109-v4/09-recuperacion-movil.png).

`browser.json` recoge comprobaciones, versión de Chrome y hashes de descargas;
`fifo-events.jsonl`, admisiones/duplicados/motor; `streamlit.log`, el servidor.
No se guardan tokens ni volcados de tráfico. El acta y el manifiesto de
conservación están en esa misma carpeta. Estos archivos son locales; los enlaces
anteriores no implican que las capturas o trazas estén publicadas en GitHub.

## Límites de la decisión

Se ha verificado el flujo local de Guiado, incluidos `future` y `groups` reales.
No se ha validado `selection` en esta interfaz, una carga simultánea de taller,
la integración con el despliegue público, ni una sesión de taller continua.
Tampoco se ha añadido recuperación tras caída/reinicio, persistencia, cuentas,
cancelación de trabajos o coordinación entre réplicas. La cola llena y sus
límites se mantienen en el servicio original y tienen pruebas del planificador;
no se llenó la cola con veinte sesiones de Chrome.

Las cifras de capacidad y espera siguen siendo las de
[prototipo-cola.md](prototipo-cola.md). Esta prueba resuelve dudas de interfaz y
propiedad de resultados, sin sustituirlas por un nuevo benchmark. No se ha
desplegado ni se ha hecho commit, push o PR. Los servidores propios de QA se
detuvieron al terminar.
