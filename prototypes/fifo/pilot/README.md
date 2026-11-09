# Piloto local de Streamlit: Guiado con FIFO

Entrada independiente de la demo pública. Reutiliza `prototypes.fifo.service`
sin modificarlo y las funciones de presentación existentes de `app.py`.
No incorpora Laboratorio ni Detective, ni instala dependencias.

## Arrancar

Desde la raíz del repositorio, en una terminal (carpeta y trace nuevos):

```bash
mkdir artifacts/fifo-piloto-manual
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m prototypes.fifo.service \
  --policy fifo --queue-size 19 --port 8877 \
  --trace artifacts/fifo-piloto-manual/server-events.jsonl
```

En otra terminal:

```bash
DCS_FIFO_URL=http://127.0.0.1:8877 PYTHONDONTWRITEBYTECODE=1 \
  .venv/bin/python -m streamlit run prototypes/fifo/pilot/streamlit_app.py \
  --server.address=127.0.0.1 --server.port=8503 --server.headless=true \
  --browser.gatherUsageStats=false
```

Abrir **http://127.0.0.1:8503**. Para dos sesiones, usar ventanas/perfiles
independientes; en QA se usan dos BrowserContext de Chrome. Detener ambos
procesos con Ctrl+C. No apunta a la demo pública ni a otro alojamiento.
Si un puerto está ocupado, elegir otro en su comando y ajustar `DCS_FIFO_URL`.

## Verificar sin repetir la campaña de carga

Requiere la `.venv` de navegador y Chrome ya instalados. No instala nada:

```bash
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m prototypes.fifo.pilot.check_browser \
  --output-dir artifacts/fifo-piloto-browser-repeticion

PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest -q \
  prototypes/fifo/pilot/test_client.py prototypes/fifo/test_scheduler.py
```

La carpeta de salida debe ser nueva. El primer comando **crea y detiene sus
propios** Streamlit y FIFO en puertos efímeros; no necesita los dos servidores
manuales. Chrome funciona en modo headless, con dos contextos independientes.
Solo permite al navegador solicitudes al origen de Streamlit; un acceso del
navegador al puerto de FIFO hace fallar la prueba. Comprueba que no se envía
el token al DOM, URL, mensajes WebSocket recibidos ni archivos generados.

La QA tiene seis trabajos admitidos: cinco experimentos reales y un fallo
inyectado. No es una tanda de capacidad ni da nuevas cifras de rendimiento.
Los primeros son `future/7` en A y `groups/2026` en B. Se mantiene una puerta
de prueba antes del primer motor para observar `running` y `queued`, sin
alterar sus argumentos ni resultados. `future/8` comprueba recuperación de cupo;
`future/11`, la pérdida de acceso tras recargar; `future/9`, fallo inyectado;
`future/10`, recuperación explícita después del fallo.

`fixtures.py` es exclusivo de la QA. Inserta doce marcas recientes en el
presupuesto **sin lanzar doce cálculos** y adelanta un reloj monotónico para
recuperar cupo y caducar resultados. No añade rutas de control HTTP ni opciones
en la interfaz. Ni el piloto ni el servicio normal importan estas pruebas.
Sus tiempos de eventos incluyen saltos de reloj: **no son latencias medidas**.

Antes de saltar minutos en ese reloj, la QA deja terminar los manejadores de
clic de Chrome. Así un segundo clic aún en tránsito no se convierte en una
solicitud posterior a los 300 segundos de deduplicación.

## Estado e identidad

`Session` vive únicamente en `st.session_state`: contiene token, configuración
enviada, referencia del trabajo, resultado y revelado. No se usa un recurso
cacheado compartido para el estado del visitante. Un `RLock` por sesión
serializa creación del token, envío y consulta: los fast reruns de Streamlit
pueden solaparse mientras un script anterior espera HTTP. Ese bloqueo evita
crear dos sesiones del servicio ante un doble clic inicial.

El cliente `urllib` ejecuta las peticiones **en Python, en el servidor**. El token
solo viaja en `Authorization: Bearer …` hacia `127.0.0.1`; no se guarda en URL,
cookies, localStorage ni archivos. Los errores se traducen a mensajes fijos,
sin volcar cabeceras, respuestas arbitrarias ni objetos de sesión a logs.
La referencia del trabajo se puede mostrar: sin el token propietario, consultar
su estado o resultado devuelve 404. La configuración del servicio admite solo
una URL HTTP limpia en `127.0.0.1`, y no usa proxies del entorno.

La configuración de los controles es un borrador. Un trabajo pendiente conserva
su caso y semilla aunque se cambien los controles; el piloto bloquea enviar
otra configuración hasta que termine. Repetir la misma petición consulta el
mismo trabajo idempotente del servicio. Un envío sin confirmar conserva su
configuración para reconciliarlo, sin reenviarlo automáticamente.

Un fragmento consulta el estado cada segundo; también hay «Actualizar estado»
para un rerun completo. Muestra:

- **En cola**, con posición.
- **Esperando cupo**, indicando que ya está aceptado, no hace falta volver a
  pulsar y empezará automáticamente al liberarse el presupuesto.
- **Calculándose**, sin lanzar cálculo desde Streamlit.
- **Terminado**, con el informe correspondiente a lo enviado, aunque los
  controles muestren otro borrador. Se conservan evidencia, hipótesis, revelado
  y descarga de Guiado usando su presentación existente.
- **Fallo**, **caducidad**, **sesión perdida**, **cola llena** o falta de conexión
  con mensajes explícitos. No se reenvía automáticamente ninguna petición.

El JSON recibido se reconstruye en los tipos existentes y se valida contra la
configuración enviada. No se sirve un informe que no coincida. La descarga de
Guiado se reconstruye de ese mismo resultado; Chrome verifica identidad byte
por byte con el JSON del servicio, nombre de archivo, métricas y predicciones.
Al caducar, se retiran tanto el informe local como el botón de descarga.

## Recargar

**No hay recuperación del trabajo al recargar.** Se pierde `st.session_state`,
incluido el token del servicio. La página muestra:

> Sesión nueva. Si has recargado la página, la sesión anterior se ha perdido:
> no podemos recuperar su trabajo, que puede seguir en el servicio. No se ha
> vuelto a enviar automáticamente.

El aviso aparece en toda sesión nueva: no se usa un identificador del navegador
para distinguir una primera visita de una recarga. Los controles vuelven a sus
valores iniciales y no hay métricas ni descarga anteriores. El trabajo aceptado
puede terminar en el servicio; no se cancela ni se reasigna a otra sesión.
Solicitarlo desde la sesión nueva es una **acción nueva**, que puede reutilizar
la caché del motor pero consume otra admisión. El aviso preventivo está visible
también antes de recargar. No se promete conservación tras reiniciar servicios,
cerrar pestañas o recuperar una conexión WebSocket.

Siguen vigentes la cola de 19 + un turno, 12 inicios/minuto, intervalo de 3 s,
retención de 300 s y límites de memoria por trabajos/sesiones del prototipo
original. Este piloto usa el `session_state` en memoria predeterminado, sin
`enforceSerializableSessionState`: el bloqueo es un objeto Python del servidor.

El [informe del piloto](../../../docs/piloto-streamlit-cola.md) reúne la evidencia,
capturas y decisión de integración. Los datos de capacidad siguen siendo los del
[informe anterior](../../../docs/prototipo-cola.md), que no se ha reejecutado.
