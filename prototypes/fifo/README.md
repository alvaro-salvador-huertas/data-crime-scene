# Prototipo local de admisión FIFO

Este directorio es independiente de la demo y del benchmark publicado. No se
importa desde la aplicación. Usa el motor real de Guiado (`run_experiment`),
sin cambiar datos, modelos, protocolos ni parámetros. No instala dependencias.
El informe de resultados y la recomendación están en `docs/prototipo-cola.md`.

Desde la raíz del repositorio, con la `.venv` existente:

```bash
# Campaña principal: future, semillas iguales y distintas, tres repeticiones.
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m prototypes.fifo.benchmark \
  --budget-seconds 600 --output-dir artifacts/fifo-repeticion-principal

# Complemento: mismos niveles y políticas para groups y selection, una repetición.
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m prototypes.fifo.benchmark \
  --cases groups selection --seed-policies distinct --repetitions 1 \
  --budget-seconds 480 --output-dir artifacts/fifo-repeticion-complemento

# Contratos concurrentes y regresión del benchmark original, sin carga HTTP.
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest -q \
  prototypes/fifo/test_scheduler.py tests/test_benchmark_demo.py
```

Cada salida debe ser nueva. La campaña crea un servidor propio por tanda,
escoge un puerto libre del sistema y lo detiene al terminar o fallar. Solo se
enlaza con `127.0.0.1`; el cliente ignora proxies del entorno. No abre Chrome,
consulta despliegues ni usa health checks como experimentos. Las tandas son
1, 5, 10 y 20 solicitudes primarias, con barrera en los hilos del cliente.
Las dos políticas reciben el mismo caso y las mismas semillas. Se alterna el
orden de las políticas entre repeticiones. No se retrasa artificialmente el motor.

Los presupuestos de los dos comandos suman 1.080 segundos de carga. No ejecutar
campañas paralelas; el límite de 12/minuto es **por proceso**, no global entre
campañas. Cada tanda reinicia caché y presupuesto: no representa un taller
continuo. El límite de campaña mata su proceso hijo y conserva los datos
parciales; una operación HTTP puede añadir hasta 5 s y la limpieza hasta 3 s.
Se reutiliza, sin editarlo, el monitor `/proc` del benchmark publicado y sus
paradas por memoria disponible/cgroup. Su umbral de 6 GiB para procesos
descendientes del cliente no mide los hilos HTTP: el RSS del controlador se
registra por separado. Los máximos cada 250 ms pueden perder picos cortos.

## Contrato

- `POST /sessions` crea un token aleatorio de pertenencia, sin cuentas.
- `POST /jobs`, con `Authorization: Bearer TOKEN` y JSON
  `{"case":"future","seed":42}`, devuelve **202** y un identificador.
- La misma sesión y configuración devuelve **200**, `duplicate: true` y el
  mismo identificador, incluso con el trabajo activo, fallido o la cola llena.
  No consume otra admisión, intervalo ni cálculo. Distintas sesiones conservan
  trabajos propios; la caché puede evitar cálculos idénticos entre ellas.
- `GET /jobs/ID` muestra `queued`, `waiting_budget`, `running`, `succeeded` o
  `failed`, posición actual y tiempos monotónicos del servidor. Posición 0 es
  el turno de ejecución reservado, que puede estar esperando presupuesto.
- `GET /jobs/ID/result` devuelve el JSON inmutable del motor: **409** mientras
  no haya resultado o si el trabajo falló; **404** para un identificador ajeno
  o expirado. Ambas rutas exigen el token propietario; token inválido: **401**.
- Cola llena: **429**, `{"error":"queue_full"}`. No conserva el intento ni
  lo reintenta. Otras causas tienen códigos distintos: `busy`, `rate_limit`,
  `session_interval`, `retained_job_capacity`, `session_capacity`.
- Resultados y deduplicación duran **300 s desde el estado terminal**, sin
  renovación al consultar. Después, repetir una configuración es trabajo nuevo
  y puede usar caché. Los trabajos pendientes/activos no expiran. Las sesiones
  sin trabajos expiran a los 900 s sin uso. La limpieza se hace al acceder.
- Hay como máximo 64 sesiones, 128 trabajos retenidos y 4 por sesión. Los
  límites evitan crecimiento ilimitado también cuando la cola se vacía.

La política `reject` entra en el `PublicBudget.action` **original** al admitir
y mantiene ese contexto hasta terminar; rechaza inmediatamente cuando está
ocupado. Conserva el intervalo de 3 s y las 12 admisiones/60 s. El envoltorio de
estado y deduplicación es común a ambas políticas; no forma parte de la demo
actual y no se presenta como una medición de su interfaz Streamlit.

`fifo` separa aceptación y ejecución: 19 puestos de espera más un turno de
ejecución reservado, **un solo ejecutor**, orden de aceptación bajo bloqueo.
Aplica 3 s entre nuevas solicitudes de una sesión al aceptar y entra en el mismo
`PublicBudget.action` original cuando llega el turno. Espera, sin adelantar a
otros, si no hay cupo o no ha transcurrido el intervalo de ejecución. Como los
cache hits consumen cupo, incluso 20 configuraciones iguales esperan el minuto.
No se ha elevado el presupuesto para mejorar los números de la cola.

La caché del adaptador es una LRU local de 24 JSON inmutables, con clave
caso/semilla/huella del motor. Mantiene el tamaño y la reutilización del Guiado,
pero **no usa `st.cache_data`**: comparar el comportamiento real de esa caché y
los reruns de Streamlit queda para navegador/integración. No hay coordinación
entre procesos, persistencia, notificaciones ni recuperación tras reiniciar.
Un error marca `failed`, conserva su admisión y libera el ejecutor. No hay
reintento automático. Un motor bloqueado requiere reiniciar el proceso; el
benchmark sí impone un plazo externo. El servicio independiente termina con
Ctrl+C y descarta todo el estado. No es una propuesta de despliegue tal cual.

## Probar la API con dos sesiones

```bash
mkdir -p .tmp
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m prototypes.fifo.service \
  --policy fifo --queue-size 19 --port 8877 --trace .tmp/fifo-eventos-nuevos.jsonl
```

En otra terminal, este cliente de biblioteca estándar crea dos sesiones, envía
configuraciones diferentes, consulta el estado y guarda cada resultado:

```bash
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python - <<'PY'
import time
from pathlib import Path
from prototypes.fifo.benchmark import request

url = 'http://127.0.0.1:8877'
jobs = []
for case, seed in [('future', 7), ('groups', 2026)]:
    code, session, _ = request(url, 'POST', '/sessions')
    assert code == 201
    token = session['token']
    config = {'case': case, 'seed': seed}
    code, job, _ = request(url, 'POST', '/jobs', token, config)
    assert code == 202, job
    code, duplicate, _ = request(url, 'POST', '/jobs', token, config)
    assert code == 200 and duplicate['id'] == job['id']
    jobs.append((token, job['id']))
while jobs:
    for token, jid in jobs[:]:
        _, state, _ = request(url, 'GET', '/jobs/'+jid, token)
        print(jid, state['state'], state['position'])
        if state['state'] == 'failed':
            raise RuntimeError(state)
        if state['state'] == 'succeeded':
            code, value, raw = request(url, 'GET', '/jobs/'+jid+'/result', token)
            assert code == 200
            Path('.tmp/resultado-'+jid+'.json').write_bytes(raw)
            jobs.remove((token, jid))
    time.sleep(.1)
PY
```

No se ofrece interfaz de navegador. El servicio rechaza peticiones con cabecera
`Origin` y no habilita CORS. La prueba anterior demuestra el contrato HTTP,
no la experiencia de un participante en Streamlit.

## Evidencia generada

`environment.json` recoge versiones, CPU, memoria, cgroups y hashes de fuentes;
`config.json`, parámetros; `summary.json` y `trials.csv`, resultados por tanda.
Cada subcarpeta tiene `trial.json`, `partial.json`, `events.jsonl`, recursos,
log del servidor y **todos** los JSON correctos, no solo una muestra.
No se registran tokens. Los resultados crudos quedan excluidos de Git.

Se comprueban correspondencia caso/semilla, métricas recalculadas desde
predicciones, hash idéntico entre políticas/repeticiones, relectura del mismo
resultado, duplicado durante/después del trabajo y rechazo a otra sesión.
Los eventos verifican orden FIFO, máximo de un motor activo y 12 entradas al
presupuesto original en cualquier ventana de 60 s. Las sondas de duplicación
y pertenencia se ejecutan después de enviar toda la tanda primaria y no cuentan
como nuevas solicitudes de cálculo. Cada campaña añade una sonda separada con
cola de tamaño 1 y 20 solicitudes reales para observar `queue_full`.

`wait_seconds` mide aceptación→inicio; `server_result_seconds`,
aceptación→resultado serializado; `client_result_seconds`, envío HTTP→descarga
recibida. La última incluye transporte, sondeo secuencial, validaciones anteriores
y las sondas; es un límite observado con ese cliente, no tiempo puro de motor.
Las latencias se resumen solo sobre resultados correctos; los rechazos se
cuentan aparte y tienen su tiempo de respuesta HTTP. No se estiman percentiles.
