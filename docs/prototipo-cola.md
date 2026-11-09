# Comparación local: rechazo y cola FIFO

Ensayo del **9 de noviembre de 2026**, sobre `c3986cb2ab6fee58992536c1821bc3c4f1094e99`.
Fuentes de partida: [capacidad de la demo](capacidad-demo.md) y
[benchmark publicado](../scripts/benchmark_demo.py), leídos sin modificarlos.

**Recomendación: integrar una cola acotada en una iteración posterior de la
demo si se quiere que las 20 personas puedan solicitar su experimento sin
reintentar.** El prototipo entrega los 20 resultados, conserva un solo motor
activo y no necesita ampliar recursos para estas tandas locales. La espera
máxima observada con `future` y semillas distintas fue **60,284 s hasta empezar,
60,345 s hasta disponer del JSON en el servidor y 62,028 s hasta recuperarlo con
el cliente**. El cupo de 12/minuto sigue vigente: la cola evita perder el intento,
no elimina la espera ni aumenta la capacidad de cálculo.

Para el taller con la demo que existe hoy, siguen siendo necesarios los turnos
manuales hasta implementar y verificar la integración en navegador. Este
prototipo no cambia ese despliegue. La recomendación elige la cola como siguiente
cambio de producto, sin presentar la API experimental como una integración ya
terminada o una capacidad remota acreditada.

## Entrega y reproducción

El código aislado está en [prototypes/fifo](../prototypes/fifo/README.md): servicio
HTTP de biblioteca estándar, cliente de carga, análisis y pruebas. No añade
dependencias ni se importa desde la aplicación. Cada sesión puede consultar
su estado y recuperar su JSON. El mismo caso y semilla en la misma sesión
reutiliza su trabajo, incluso si se repite mientras está en cola o calculándose.
La cola llena devuelve **HTTP 429 con `queue_full`**. La pertenencia se comprueba
con un token aleatorio por sesión, sin cuentas ni historial compartido.

Comandos reproducibles desde la raíz; las carpetas de salida deben ser nuevas:

```bash
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m prototypes.fifo.benchmark \
  --budget-seconds 600 --output-dir artifacts/fifo-repeticion-principal

PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m prototypes.fifo.benchmark \
  --cases groups selection --seed-policies distinct --repetitions 1 \
  --budget-seconds 480 --output-dir artifacts/fifo-repeticion-complemento

PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m prototypes.fifo.analyze \
  artifacts/fifo-repeticion-principal artifacts/fifo-repeticion-complemento

PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest -q \
  prototypes/fifo/test_scheduler.py tests/test_benchmark_demo.py \
  tests/test_public_limits.py tests/test_public_demo.py tests/test_engine.py
```

El README incluye cómo arrancar la API y un cliente breve para consultar dos
sesiones y guardar sus resultados. Las campañas crean y detienen sus propios
servidores en puertos elegidos por el sistema, exclusivamente en `127.0.0.1`.
No se ejecutan contra un servidor ajeno. No hay navegador, despliegue, commit,
push ni PR.

## Comparación y límites conservados

Se usan los mismos experimentos reales de Guiado, sin entrenamiento sintético
de sustitución ni retrasos artificiales. La campaña principal compara `future`
con semilla fija 42 y con semillas distintas 42…61 según el tamaño de tanda.
Hay tres repeticiones por combinación de política, semilla y nivel 1/5/10/20:
**48 procesos/tandas**. El complemento compara `groups` y `selection` con
semillas distintas y una repetición por nivel/política: **16 tandas**.
No se ejecuta el estudio de Laboratorio ni se acredita Detective.

Las dos políticas comparten el adaptador HTTP, estado por sesión, exportación,
deduplicación y caché. `reject` usa el **`PublicBudget.action` original** al
admitir, mantiene su contexto durante el trabajo y rechaza si está ocupado.
`fifo` tiene **19 puestos de espera y un turno reservado de ejecución**. Acepta
sin consumir todavía una entrada del presupuesto; al llegar su turno, entra
en ese mismo `PublicBudget.action`. Si se agotaron las 12 entradas de los últimos
60 s, el primer trabajo espera en `waiting_budget`; nadie lo adelanta.
Se conservan también los 3 s por sesión, tanto al aceptar solicitudes nuevas
como al ejecutar. Los duplicados no son solicitudes nuevas.

Esta separación cambia expresamente **cuándo** se carga el cupo: en FIFO limita
inicios, en rechazo limita admisiones inmediatas. Mantener 12 aceptaciones/minuto
también en la entrada impediría aceptar las 20 de la tanda. No se ha aumentado
el límite de ejecuciones para obtener el resultado.

La caché del adaptador conserva hasta 24 JSON inmutables por caso/semilla/huella
del motor; se reutiliza entre sesiones. Replica la intención de la caché de
Guiado, pero no ejecuta `st.cache_data` ni los reruns de Streamlit. **Se compara
la política de admisión original mediante HTTP, no la interfaz pública completa.**
Una llamada al motor es un experimento con sus procedimientos y baselines,
no necesariamente un único `fit` ni un único hilo nativo.

Cada tanda usa un proceso nuevo, presupuesto vacío y caché fría. Los dos lados
reciben las mismas configuraciones y se alterna el orden entre repeticiones.
El cliente prepara sus hilos y libera una barrera; se registra la dispersión
de envío y de recepción. No se retiene al motor para forzar un único ganador.
Esto aísla tandas y **no representa un taller continuo**.

## Medición principal: future con semillas distintas

Cada fila suma tres tandas. Admisiones y resultados coinciden; los rechazos
quedan fuera de las latencias de éxito. No hubo errores del motor, timeouts ni
resultados perdidos en las tandas completadas.

| Solicitudes/tanda | Política | Solicitudes totales | Admitidas/resultados | Rechazadas | Cálculos reales |
| --- | --- | --- | --- | --- | --- |
| 1 | Rechazo | 3 | 3 | 0 | 3 |
| 1 | FIFO | 3 | 3 | 0 | 3 |
| 5 | Rechazo | 15 | 3 | 12 | 3 |
| 5 | FIFO | 15 | 15 | 0 | 15 |
| 10 | Rechazo | 30 | 3 | 27 | 3 |
| 10 | FIFO | 30 | 30 | 0 | 30 |
| 20 | Rechazo | 60 | 10 | 50 | 10 |
| 20 | FIFO | 60 | 60 | 0 | 60 |

En 20, rechazo admitió **3, 4 y 3** solicitudes, sin reintentar ninguna de las
rechazadas. En el conjunto de niveles: **19/108 resultados frente a 108/108**.
Con semillas distintas no hubo cache hits: cada resultado corresponde a una
llamada real al motor.

Tiempos en segundos, **mediana / máximo de todos los resultados correctos**
del nivel; no son medianas de medianas ni percentiles:

| Solicitudes/tanda | Política | Espera aceptación→inicio | Aceptación→JSON disponible | Envío→JSON recibido por cliente |
| --- | --- | --- | --- | --- |
| 1 | Rechazo | <0,001 / <0,001 | 0,153 / 0,165 | 0,248 / 0,257 |
| 1 | FIFO | <0,001 / <0,001 | 0,140 / 0,143 | 0,230 / 0,246 |
| 5 | Rechazo | <0,001 / 0,002 | 0,145 / 0,150 | 0,343 / 0,365 |
| 5 | FIFO | 0,195 / 0,319 | 0,258 / 0,383 | 0,712 / 1,098 |
| 10 | Rechazo | <0,001 / <0,001 | 0,153 / 0,170 | 0,450 / 0,461 |
| 10 | FIFO | 0,325 / 0,573 | 0,386 / 0,635 | 1,499 / 2,290 |
| 20 | Rechazo | <0,001 / 0,001 | 0,089 / 0,275 | 1,037 / 1,340 |
| 20 | FIFO | 0,490 / 60,284 | 0,552 / 60,345 | 3,047 / 62,028 |

La mediana de 20 oculta la espera de la parte final de la cola: **8 de 20 trabajos
por tanda esperan la renovación del cupo**. Se muestra el máximo por ese motivo.
La latencia del cliente incluye sondeo, validación y descarga secuenciales,
además de las sondas de deduplicación. El JSON ya podía estar disponible antes
de que ese cliente lo recogiera; los dos relojes se registran por separado.
El rechazo HTTP en las tandas de 20 distintas tardó mediana **0,687 s**, máximo
**0,766 s** desde el envío; no se presenta como latencia de un experimento.

## Medición principal: future con semilla compartida

Cada fila suma también tres tandas, inicialmente frías:

| Solicitudes/tanda | Política | Admitidas/resultados | Rechazadas | Cálculos reales | Cache hits | Máximo envío→JSON recibido, s |
| --- | --- | --- | --- | --- | --- | --- |
| 1 | Rechazo | 3 | 0 | 3 | 0 | 0,193 |
| 1 | FIFO | 3 | 0 | 3 | 0 | 0,194 |
| 5 | Rechazo | 3 | 12 | 3 | 0 | 0,235 |
| 5 | FIFO | 15 | 0 | 3 | 12 | 0,748 |
| 10 | Rechazo | 3 | 27 | 3 | 0 | 0,297 |
| 10 | FIFO | 30 | 0 | 3 | 27 | 1,588 |
| 20 | Rechazo | 36 | 24 | 3 | 33 | 2,977 |
| 20 | FIFO | 60 | 0 | 3 | 57 | 61,795 |

En FIFO/20 iguales, la espera máxima hasta inicio fue **59,941 s** y hasta JSON
disponible **59,942 s**. Un cache hit consume cupo igual que en la demo; solo
evita el cálculo. En rechazo/20 hubo **12 admisiones por tanda**, no doce motores.

Esto no contradice el benchmark de navegador, donde solo se admitió una acción
por tanda: las llegadas HTTP no son atómicas. En 20, los envíos del cliente se
dispersaron hasta **25 ms** con semillas distintas, mientras las entradas al
gestor se dispersaron hasta **416 ms** en FIFO y **397 ms** en rechazo. Con semilla
fija fueron hasta **423 ms / 369 ms**. Parte de las peticiones alcanzó el gestor
después de acabar el primer motor y encontró caché. Se comparan ambas políticas
con el mismo generador, sin extrapolar esos conteos a clics en Streamlit.

## Complemento: groups y selection

Una tanda por nivel y política, semillas distintas, sin cache hits. En esta
tabla cada admisión es un resultado y un cálculo real. Las dos políticas
recibieron exactamente las mismas configuraciones:

| Caso | Solicitudes | Rechazo: resultados / rechazos | FIFO: resultados / rechazos | FIFO: espera mediana / máxima, s | FIFO: JSON disponible mediana / máxima, s | FIFO: JSON recibido mediana / máxima, s |
| --- | --- | --- | --- | --- | --- | --- |
| groups | 1 | 1 / 0 | 1 / 0 | <0,001 / <0,001 | 0,156 / 0,156 | 0,248 / 0,248 |
| groups | 5 | 1 / 4 | 5 / 0 | 0,136 / 0,258 | 0,197 / 0,318 | 0,853 / 1,134 |
| groups | 10 | 1 / 9 | 10 / 0 | 0,292 / 0,542 | 0,353 / 0,602 | 1,509 / 2,203 |
| groups | 20 | 4 / 16 | 20 / 0 | 0,456 / 60,217 | 0,519 / 60,278 | 3,032 / 61,840 |
| selection | 1 | 1 / 0 | 1 / 0 | <0,001 / <0,001 | 0,212 / 0,212 | 0,275 / 0,275 |
| selection | 5 | 1 / 4 | 5 / 0 | 0,341 / 0,601 | 0,475 / 0,743 | 0,955 / 1,258 |
| selection | 10 | 1 / 9 | 10 / 0 | 0,676 / 1,203 | 0,811 / 1,343 | 1,853 / 2,552 |
| selection | 20 | 2 / 18 | 20 / 0 | 1,150 / 60,715 | 1,282 / 60,846 | 3,265 / 62,234 |

Los JSON recibidos por los éxitos de rechazo en 20 tardaron hasta **1,381 s**
en groups y **1,078 s** en selection; son solo 4 y 2 participantes, respectivamente.
El complemento aporta **84 resultados y cálculos reales** entre ambas políticas.
Su sonda de cola de tamaño 1 produjo **4 admisiones y 16 rechazos `queue_full`**.
Una repetición es un control de alcance; no demuestra estabilidad estadística
de estos otros casos.

## Verificaciones y límites de la evidencia

Las trazas comprueban orden de inicio igual al de aceptación, **como máximo un
motor activo** y como máximo 12 entradas al presupuesto original en cualquier
ventana de 60 s. Se comprueban todos los JSON correctos: caso/semilla, métricas
recalculadas desde predicciones, mismo hash para la misma configuración entre
políticas/repeticiones, recuperación repetida sin cambios y rechazo 404 a otra
sesión tanto del estado como del resultado. Las sondas se hacen después de
enviar toda la tanda primaria y no cuentan como nuevas admisiones.

En la campaña principal se verificaron **280 trabajos/resultados** y se
ejecutaron **151 experimentos reales** entre ambas políticas. Esos conteos no
incluyen la sonda de saturación, que usa semillas distintas y una cola de tamaño
1: **5 admitidas y 15 rechazos `queue_full`**. Puede admitir más de dos a lo largo
de la ráfaga porque el motor va liberando puestos. Las pruebas controladas sí
mantienen ocupado al ejecutor para comprobar exactamente 19 esperando más un
turno reservado y el rechazo del intento 21.

Las **14 pruebas nuevas** usan motores controlados para verificar duplicados
concurrentes, FIFO, capacidad exacta 0/19, pertenencia, consulta antes de terminar,
fallo y liberación del ejecutor, caducidad y recuperación de cupos con reloj
simulado. No son medidas de rendimiento. Pasaron además las **17 pruebas del
benchmark publicado y 99 pruebas existentes** de límites, demo y motor: **130**
en total, sin ejecutar una prueba de navegador. Se probaron fallos por inyección;
no se observó un fallo real del motor durante la carga.

Los resultados y la deduplicación duran 300 s desde terminar; las sesiones sin
trabajos expiran tras 900 s sin uso. Hay límites de 64 sesiones, 128 trabajos
retenidos y 4 por sesión. Los trabajos pendientes no caducan. Reiniciar pierde
trabajos, tokens y resultados; no se promete recuperación tras caída ni ejecución
exactamente una vez entre procesos. Un motor bloqueado necesita reiniciar el
servicio; el cliente de benchmark sí aplica un presupuesto externo y lo mata.

**Pendiente de navegador/integración:** conservar el token y la identidad del
trabajo en `st.session_state`; mostrar posición y espera por cupo con sondeo;
reruns, doble clic real, cambio de caso/semilla mientras hay trabajo, desconexión
y reconexión; revelado y descarga desde el mismo resultado; comportamiento real
de `st.cache_data`; expiración/fallo visibles y acceso con varias sesiones.
Falta también un taller continuo con varias acciones por persona y las versiones
y recursos del alojamiento objetivo. Estos puntos no se dan por probados por
una prueba HTTP. Chrome no participó en esta campaña y no limita estas medidas;
el cliente ligero sí añade su propia dispersión y coste de sondeo.

## Entorno y conservación

Python 3.12.3, Ubuntu 24.04.5, i7-14650HX, 24 CPU lógicas visibles, 31,04 GiB de
memoria; 20,98 GiB disponibles al empezar la principal. Se reutilizó `.venv`:
Streamlit 1.66.1, NumPy 2.5.4, pandas 3.1.0, scikit-learn 1.9.1 y SciPy 1.18.1.
No se fijaron hilos nativos. Persisten las diferencias ya documentadas con los
pins de producción: dateutil 3.0.0, multipart 0.0.32 y websockets 17.3.
No se actualizó el entorno y no se acredita una instalación limpia de esos pins.

En la campaña principal, pico RSS sumado del servidor **236,2 MiB** y del
controlador/cliente **85,5 MiB**, frente a los GiB del generador Chrome anterior.
Es muestreo `/proc` cada 250 ms, con posible doble conteo de páginas compartidas
y pérdida de picos breves. No implica dimensionamiento de producción ni permite
atribuir toda la diferencia a retirar Chrome: el protocolo y la presentación
también son diferentes.

El complemento alcanzó **252,3 MiB** de servidor y **81,4 MiB** de controlador;
no se activaron las paradas de presión de memoria. La principal consumió
**492,405 s** y el complemento **171,429 s** incluyendo arranques, comprobaciones
y sus sondas: **663,834 s** en total, más el smoke local breve. Se mantuvo el
presupuesto conjunto por debajo de 20 minutos; los comandos fijan máximos de
600 y 480 s, respectivamente, y no se ejecutaron en paralelo.

La evidencia local, excluida de Git, se guarda en
`artifacts/fifo-capacidad-20261109/` y `artifacts/fifo-complemento-20261109/`.
Cada tanda conserva solicitudes, rechazos, admisiones, eventos del motor, tiempos,
recursos, log y todos los JSON correctos. `summary.json` y `trials.csv` resumen
las tandas; el analizador recalcula agregados sin lanzar carga.
No hay enlaces públicos a estos datos.

La primera comprobación no pudo crear un socket dentro del sandbox y no lanzó
ningún experimento; queda en `artifacts/fifo-smoke-20261109/`. Se repitió con
permiso local y pasó en `artifacts/fifo-smoke-local-20261109/`. Esto no se cuenta
como fallo de capacidad. No se modificó el benchmark anterior para habilitarlo.
Se registró un manifiesto SHA-256 de **223 archivos** del motor, UI, entrada
pública, benchmark, documentación de capacidad y evidencia histórica para
comprobar su conservación byte por byte al cerrar el trabajo. La comprobación
final confirmó que los 223 permanecen idénticos, y que no quedan procesos propios
del servicio vivos. Los hashes y el acta de comprobación se conservan en la
carpeta de la campaña principal.
