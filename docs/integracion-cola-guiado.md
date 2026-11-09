# Cola de Guiado en la demo pública: opción de arranque

Integración local del **9 de noviembre de 2026**. Se leyó
[el informe del piloto](piloto-streamlit-cola.md); su código y evidencia se
conservaron. La cola está **desactivada por defecto**. No se desplegó ni se hizo
commit, push o PR. No se repitió la campaña de carga.

## Activar y desactivar

Desde la raíz, con la `.venv` existente, detener primero el proceso anterior.

```bash
# Activar: solo Guiado de la entrada pública usa FIFO.
DCS_GUIDED_FIFO=1 PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m streamlit run \
  demo/streamlit_app.py --server.address=127.0.0.1 --server.port=8503 \
  --server.headless=true --browser.gatherUsageStats=false

# Desactivar: rechazo original, sin crear cola ni ejecutor FIFO.
DCS_GUIDED_FIFO=0 PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m streamlit run \
  demo/streamlit_app.py --server.address=127.0.0.1 --server.port=8503 \
  --server.headless=true --browser.gatherUsageStats=false
```

Abrir **http://127.0.0.1:8503**. Omitir `DCS_GUIDED_FIFO` equivale a `0`; solo el
valor exacto `1` activa la opción. Se elige al arrancar, sin interruptor para
visitantes. Cambiarla requiere reiniciar: no migra trabajos de un proceso previo.
La entrada local `app.py` conserva su funcionamiento incluso con la variable a 1.

**No hay que arrancar `prototypes.fifo.service`.** No se abre un segundo puerto,
no se usa `DCS_FIFO_URL` y no hay cliente HTTP en el recorrido integrado. Solo
escucha el servidor normal de Streamlit. Token y trabajos permanecen en memoria
del mismo proceso; no se exponen en URLs, logs ni descargas.

## Diff y arquitectura

El [diff de esta intervención](../artifacts/guiado-integracion-20261109/revision/integracion.diff)
contiene siete archivos:

| Archivo | Cambio |
| --- | --- |
| `app.py` | Importación condicional de la cola solo en Guiado público y enlace del presupuesto de sesión al activar la opción. El camino apagado conserva el código original. |
| `ui/public_limits.py` | Permite que la UI y su ejecutor usen el mismo diccionario de intervalo individual. Sin ese diccionario adjunto, conserva la ruta anterior. No cambia límites, reloj ni orden de comprobación. |
| `ui/guided_fifo.py` | Adaptador dentro del proceso: singleton por `st.cache_resource`, mismo `PublicBudget` global y llamadas directas al planificador. |
| `ui/guided_fifo_view.py` | Controles de Guiado, estado/turno, espera por cupo, configuración enviada, revelado y descarga. |
| `tests/test_guided_fifo.py` | Pruebas del interruptor, singleton, ausencia de HTTP y presupuesto compartido. |
| `scripts/check_guided_fifo.py` | QA local reproducible de la entrada pública, con la opción apagada/activada y dos contextos de Chrome. |
| `docs/integracion-cola-guiado.md` | Instrucciones, evidencia y límites de esta entrega. |

El diff se aplica sobre el estado inicial de esta tarea, **que ya contenía los
prototipos e informes anteriores sin versionar**. No los introduce como si se
hubiesen escrito de nuevo. La aplicación integrada depende de las clases
existentes `Scheduler` de `prototypes/fifo/service.py` y `Session` del cliente del
piloto; esas fuentes deben acompañar cualquier copia futura del proyecto.
Importar el módulo del planificador no arranca su servidor HTTP: ni `make_server`
ni su `main` se invocan desde la integración.

No se bifurcó el algoritmo FIFO. `SharedScheduler` conserva el algoritmo probado
y reemplaza su presupuesto privado, todavía sin trabajos al construirlo, por
**el objeto devuelto por `get_public_budget()`**. La cola es única por proceso,
con 19 plazas de espera y un turno reservado; cada sesión solo conserva su
controlador/identidad. La caché JSON LRU de 24 entradas, deduplicación por sesión
y configuración, retención de 300 s, límites de trabajos y liberación tras fallo
siguen siendo los del prototipo. El motor no se modificó.

El trabajador entra en ese `PublicBudget.action` antes de calcular o reutilizar
un resultado. Laboratorio y Detective siguen entrando por `public_action`, sin
cambios en sus módulos ni sus reglas de rechazo. Si cualquiera ocupa el turno,
los demás no pueden abrir otro cálculo. Si un modo anterior está activo, Guiado
queda en cola y lo explica; si falta cupo, muestra «Esperando cupo».

Se conservan **un cálculo activo por proceso, 12 entradas por ventana móvil de
60 s y 3 s por sesión**. El diccionario individual se adjunta a `st.session_state`
al activar la opción, pero es un objeto Python normal utilizable desde el
trabajador. Cambiar de modo no reinicia el intervalo. El planificador limita
inicios, incluidos cache hits: aceptar en cola no consume aún una entrada del
presupuesto, igual que en el prototipo. Los duplicados no consumen otra entrada.

La FIFO ordena los trabajos aceptados de Guiado. Laboratorio y Detective no se
añaden a esa cola ni reservan plazas: conservan sus acciones inmediatas y
compiten por el mismo presupuesto. No se promete orden FIFO global entre modos
ni ausencia de espera prolongada bajo peticiones continuas de otros modos.

## Comportamiento del participante

Se muestran **En cola**, posición o turno reservado, **Esperando cupo**,
**Calculándose** y **Terminado**. La espera por cupo explica que la solicitud ya
está aceptada, no hace falta volver a pulsar y empezará automáticamente. El sondeo
cada segundo y «Actualizar estado» consultan el trabajo; no lo reenvían.

El controlador probado conserva su `RLock` por sesión para serializar fast reruns
y doble clic. Cambiar controles solo cambia el borrador: un trabajo pendiente
mantiene caso/semilla y bloquea otro envío distinto hasta terminar. Las métricas,
evidencia, explicación y descarga usan el resultado validado contra la
configuración enviada, independientemente de los controles actuales.

Recargar pierde `st.session_state` y el acceso al trabajo anterior. Con la opción
activada, la página nueva indica esa pérdida, que el trabajo puede continuar y
que **no se ha reenviado automáticamente**. La advertencia también está visible
antes de recargar. No se asigna el resultado anterior a otra sesión ni se cancela
el cálculo aceptado. Con la opción apagada se conserva la presentación original:
recargar vuelve al expediente inicial, sin cálculo ni resultado automático.

## Verificación realizada

**Suite completa ejecutada una sola vez: 334 pruebas aprobadas en 85,03 s.**
Incluye pruebas anteriores, 12 pruebas nuevas de integración y todas las del
planificador y cliente del piloto conservados. Antes hubo comprobaciones
enfocadas durante el desarrollo; no se volvió a lanzar la suite completa.
`git diff --check` pasó. El log se conserva en
`artifacts/guiado-integracion-20261109/revision/pytest-completa.txt`.

```bash
# Repetir la suite completa, incluida la de los prototipos conservados.
DCS_GUIDED_FIFO=0 PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest -q \
  tests prototypes/fifo

# Repetir solo la QA funcional; su carpeta debe ser nueva.
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m scripts.check_guided_fifo \
  --output-dir artifacts/guiado-integracion-repeticion
```

La QA crea y detiene sus propios procesos, apunta solo a loopback y prueba
**la entrada pública real** `demo/streamlit_app.py`, no la entrada del piloto.
Usó Chrome 157.0.8103.38 headless, con dos BrowserContext independientes de
1440 × 1000. La instrumentación está solo en el hijo de QA: observa el presupuesto
y motores, retiene temporalmente una llamada real para ver concurrencia, y
admite controles de cupo/reloj por **stdin**, sin rutas HTTP de prueba.
La inserción de doce marcas y los saltos de reloj son casos controlados, sin
lanzar doce experimentos ni obtener medidas de rendimiento de esas esperas.

| Comprobación | Resultado |
| --- | --- |
| Variable ausente y valor 0 | Las pruebas de UI confirman rechazo original y ninguna inicialización de la cola. |
| Chrome, opción apagada | A calcula `future/7`; B recibe rechazo mientras A está activo. Tras reintentar explícitamente, B calcula `groups/2026`. Ambos descargan su JSON. Cero admisiones FIFO. |
| Chrome, opción activada | A y B aceptados en una cola compartida. Doble clic y reruns conservan trabajo. B cambia a 2027 mientras espera, pero no se envía 2027 y el resultado/JSON sigue siendo `groups/2026`. |
| Identidad y aislamiento | Las consultas de estado y resultado con la identidad de la otra sesión dan 404 en ambas direcciones. Las métricas exportadas se recalculan desde predicciones. |
| Guiado activo → otros modos | Desde B se intentan Laboratorio y Detective. Ambos muestran el rechazo original por cálculo activo y no entran en sus motores. |
| Cupo común | Con el presupuesto controlado lleno, Guiado acepta y espera; Laboratorio y Detective rechazan por presupuesto compartido. Liberar el cupo permite el resultado automático de Guiado. |
| Laboratorio activo → Guiado | Una llamada real a Laboratorio con semilla 321 ocupa el turno. Guiado queda en cola, sin comenzar otro motor, y termina al liberarlo. |
| Intervalo individual | Las pruebas comprueban los 3 s en ambos sentidos entre la acción anterior y Guiado, incluso cambiando de modo. |
| Recarga | En FIFO se recarga con un trabajo aceptado pendiente: muestra el aviso de acceso perdido y no reenvía. Se comprueba también recarga sin cálculo automático con la opción apagada. |
| Transporte y privacidad | El adaptador pasa pruebas que prohíben abrir HTTP. Chrome solo accede al origen de Streamlit. Los tokens de pertenencia no aparecen en URL, DOM, mensajes WebSocket ni archivos generados. El identificador público del trabajo sí es visible y no permite leerlo sin pertenencia. |

Ambas ejecuciones de Chrome terminaron con `status: passed`, sin errores de
página ni peticiones inesperadas. Con FIFO hubo **5 trabajos de Guiado y 1
experimento de Laboratorio**, todos reales; sin FIFO, **2 experimentos de
Guiado**. En las dos configuraciones se observó **máximo de un motor activo** y
**todas las admisiones usaron el mismo objeto de presupuesto**. Se guardaron
**6 JSON de Guiado verificados**: dos con la opción apagada y cuatro activada.
El trabajo que perdió acceso al recargar terminó en el proceso, sin entregarse
a la sesión nueva. No son tandas ni cifras nuevas de capacidad.

## Capturas y conservación

La evidencia nueva está en `artifacts/guiado-integracion-20261109/`, excluida de
Git. `summary.json` resume ambas configuraciones; cada `fifo-0/` y `fifo-1/`
conserva `browser.json`, eventos, log, descargas y capturas. Selección:

- [Rechazo con la opción apagada](../artifacts/guiado-integracion-20261109/fifo-0/01-rechazo-original.png).
- [Trabajo en cola y configuración enviada](../artifacts/guiado-integracion-20261109/fifo-1/01-cola-configuracion-enviada.png).
- [Rechazo de Laboratorio](../artifacts/guiado-integracion-20261109/fifo-1/02-bloqueo-lab.png) y [de Detective](../artifacts/guiado-integracion-20261109/fifo-1/02-bloqueo-detective.png) mientras calcula Guiado.
- [Resultado propio de B](../artifacts/guiado-integracion-20261109/fifo-1/03-resultado-b.png).
- [Aceptado esperando cupo](../artifacts/guiado-integracion-20261109/fifo-1/04-esperando-cupo.png).
- [Recarga sin reenvío](../artifacts/guiado-integracion-20261109/fifo-1/05-recarga-sin-reenvio.png).
- [Guiado esperando a Laboratorio](../artifacts/guiado-integracion-20261109/fifo-1/06-guiado-espera-laboratorio.png).

El acta y los hashes en `revision/verification.json` comprueban la conservación
de motor, entrada pública, módulos de Laboratorio/Detective, prototipos,
documentación anterior e históricos. Solo `app.py` y `ui/public_limits.py`
cambian entre los archivos que ya existían al empezar. No se regeneraron
históricos ni estudios, se alteró `.venv` o se instalaron dependencias.
Los servidores propios de la QA se detuvieron. Los enlaces de evidencia son
locales y no implican publicación de datos o capturas.

## Pendiente en el alojamiento real

Esta entrega acredita el flujo local y sus límites compartidos, no el despliegue
real. Antes de activar allí la opción falta comprobar que las fuentes del
planificador/controlador acompañan a la aplicación, los pins/recursos efectivos,
el funcionamiento de los hilos y del sondeo bajo el proxy/WebSocket del
alojamiento, las descargas y qué sucede al suspender o reiniciar el proceso.
También falta una sesión continua de taller y el comportamiento ante varias
réplicas: el presupuesto y la cola son por proceso, sin coordinación externa.

No hay recuperación durable tras recargar o reiniciar, persistencia, cuentas,
cancelación ni garantía de ejecución exactamente una vez entre procesos.
`selection` no se recorrió en Chrome en esta integración; los otros modos se
ejercitaron para presupuesto, no como una nueva auditoría funcional completa.
Los casos de fallo, caducidad y cola llena mantienen las pruebas del planificador
y piloto; no se llenó la cola con veinte navegadores. La campaña de capacidad
previa se conserva como evidencia separada y no se ha repetido.
