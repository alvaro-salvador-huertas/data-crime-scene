# Controles de seguridad de la demo pública

La aplicación y el repositorio son públicos. Un crawler puede leer su contenido,
y las soluciones didácticas pueden inspeccionarse en el código. `robots.txt` no
es un control de acceso ni protege credenciales. No se añade una prohibición de
indexación como sustituto de seguridad.

## Alcance de los límites

La entrada `demo/streamlit_app.py` aplica controles en el servidor antes de
admitir las siguientes acciones: ejecutar Guiado, ejecutar Laboratorio, abrir
un expediente nuevo, aplicar una intervención nueva y cargar el estudio fijo
opcional de la demo. El estudio no se distribuye actualmente.

| Control | Comportamiento |
| --- | --- |
| Concurrencia | Un cálculo admitido por proceso; los demás se rechazan, sin cola ni reintento automático. |
| Presupuesto global | Hasta 12 admisiones en una ventana móvil de 60 segundos, compartidas por los tres modos y todas las sesiones del proceso. |
| Intervalo por sesión | Al menos 3 segundos entre admisiones; cambiar de modo, semilla o reiniciar Detective no lo borra. |
| Notas públicas | Hasta 2.000 caracteres Unicode; límite del widget y comprobación del servidor antes de guardar borrador o confirmar. Se rechaza el exceso, sin truncamiento silencioso. |
| Errores no controlados | La configuración de la entrada pública oculta el detalle de excepciones en el navegador; los logs del servidor siguen disponibles al operador. |

Se cuentan solicitudes admitidas, aunque una caché evite entrenar o el cálculo
falle. Un expediente ya abierto y una intervención ya registrada reutilizan
su resultado sin nueva admisión. Una negativa por presupuesto no elimina el
resultado actual ni modifica las respuestas. Cambiar parámetros conserva el
comportamiento previo de retirar resultados incompatibles.

El recurso compartido usa reloj monotónico y bloqueo entre hilos. Guarda como
máximo 12 marcas temporales, sin direcciones IP ni identificadores de visitante.
Las notas no se califican, no se ejecutan y no se envían a modelos. No escribas
secretos ni datos personales en ellas: aparecen en tus descargas.

La entrada local `app.py` y la CLI conservan su funcionamiento sin estas cuotas
públicas. No se modifican generadores, entrenamiento, métricas, validadores,
protocolos ni huellas del motor.

## Límites de la protección

Los presupuestos viven en memoria **por proceso**, se reinician con él y no se
coordinan entre réplicas. Una sesión nueva evita el intervalo individual, pero
comparte el presupuesto global. No hay autenticación ni reparto justo entre
personas: un visitante puede consumir el presupuesto y retrasar a otros.

Las validaciones de resultados, renderizado, conexiones, reruns, descargas y
costes propios de Streamlit no quedan todos dentro del cupo. Los límites no
protegen contra tráfico volumétrico, demasiadas conexiones, consumo distribuido
ni todo agotamiento de memoria. Para esos riesgos se necesitan controles del
proveedor o de infraestructura; no se ha realizado una prueba de carga remota.
El límite de notas no es un límite del tamaño de los mensajes WebSocket.

CORS y XSRF no se desactivan. No se añaden servicios externos, cuentas,
credenciales, telemetría propia ni dependencias a la aplicación.

## Comprobaciones de CI

El workflow mantiene `contents: read` y checkout sin persistir credenciales.
Las acciones checkout y setup-python quedan fijadas a commits completos.
Dependabot propone actualizaciones semanales de pip y GitHub Actions, sin
fusión automática.

- **pytest y pip check:** funcionamiento y consistencia del entorno.
- **pip-audit 2.10.1:** las versiones fijadas de aplicación y navegador,
  incluidas mediante `requirements-browser.txt`, sin instalar esos paquetes en
  el job de seguridad. Un paquete no auditable o una vulnerabilidad conocida
  impiden que el job termine correctamente. No se ignoran avisos de CVE.
- **Bandit 1.9.4:** código de `app.py`, `demo/`, `ui/` y
  `data_crime_scene/`, con todas sus reglas. Una única advertencia B311 revisada
  corresponde a `random.Random(seed).shuffle(order)`, usado para ordenar casos
  reproduciblemente, sin finalidad criptográfica. La excepción exige archivo,
  línea, fragmento y SHA-256 exactos; cualquier cambio exige revisión. No se
  suprimen todas las advertencias B311. El control está en
  `scripts/check_static_security.py` y sus pruebas adversariales.
- **Gitleaks 8.30.1:** historial completo disponible en el checkout y archivos
  actuales. El binario oficial se verifica por SHA-256 antes de ejecutarlo;
  los resultados se redactan para no imprimir posibles secretos. No se usa un
  baseline que ignore filtraciones previas.

Estos análisis son complementarios, no certifican ausencia de vulnerabilidades.
pip-audit depende de los avisos conocidos en su fecha de ejecución; las versiones
instaladas por el alojamiento deben cotejarse aparte. Gitleaks no hace OCR de
capturas ni asegura encontrar cualquier credencial. La publicación de este
workflow tampoco acredita que GitHub Secret Scanning o Push Protection estén
activados: son ajustes independientes de la cuenta/repositorio.

Para reproducir los controles de Python en un entorno auxiliar:

```bash
python3 -m venv .venv-security
.venv-security/bin/python -m pip install pip-audit==2.10.1 bandit==1.9.4
.venv-security/bin/python -m pip_audit --no-deps --disable-pip --strict -r requirements-browser.txt
.venv-security/bin/python scripts/check_static_security.py
.venv/bin/python -m pytest -q
```

El [workflow](../.github/workflows/ci.yml) conserva los comandos y la identidad
del binario de Gitleaks. No subas sus posibles hallazgos sin revisarlos y redactarlos.
Si aparece una credencial real, revócala/rotála primero; borrarla del último
commit no elimina copias ni historial.

## Protección de main: configuración separada

La inspección inicial del 3 de noviembre de 2026 encontró `main` sin protección
y sin rulesets. El archivo [main-protection.json](../.github/main-protection.json)
es una propuesta revisable; **su presencia no activa ninguna regla**.

Exige PR, checks `tests` y `security` correctos sobre una rama actualizada,
conversaciones resueltas y prohíbe borrado y force-push, también para
administradores. No exige aprobación de otra persona: este proyecto tiene
un único mantenedor. La revisión humana y el merge siguen siendo explícitos.

La conexión usada para preparar el cambio no permite administrar protecciones.
Después de comprobar la PR y los nombres de los checks, el propietario puede
aplicar la propuesta desde una terminal autenticada con permiso de administración:

```bash
gh api --method PUT repos/alvaro-salvador-huertas/data-crime-scene/branches/main/protection \
  --input .github/main-protection.json
gh api repos/alvaro-salvador-huertas/data-crime-scene/branches/main/protection
```

El PUT sustituye la configuración de protección de esa rama. Si se ha añadido
otra política desde la inspección, hay que compararla primero y conservarla;
no ejecutar el comando a ciegas. La activación efectiva se comprueba en GitHub,
no se infiere del archivo. La integración y el despliegue de esta propuesta
siguen siendo pasos posteriores a su revisión.

## Validación de esta propuesta — 3 de noviembre de 2026

- Python 3.12.14: **276 pruebas correctas en 55,64 s**, una suite completa final;
  35 pruebas nuevas. Incluyen ocho hilos simultáneos, recuperación de cuotas,
  varias sesiones/modos, idempotencia, conservación tras rechazos, notas Unicode
  y rechazo del exceso en el servidor. Las 50 enfocadas pasaron previamente.
- Los tests funcionales públicos anteriores usan un reloj que avanza entre
  acciones sobre el limitador real. Los tests nuevos mantienen el tiempo fijo
  para verificar los rechazos y los límites exactos; no esperan segundos reales
  ni eliminan aserciones funcionales.
- `pip check` correcto. pip-audit consultó las 48 versiones fijadas: ninguna
  vulnerabilidad conocida encontrada en esa ejecución. No se cambiaron pins.
- Bandit: ninguna advertencia sin revisar; una B311 justificada como se describe
  arriba. Gitleaks: sin hallazgos en el historial disponible ni en una copia de
  los archivos publicables. Un token sintético no funcional produjo rechazo y
  un informe redactado, verificando el control negativo.
- Arranque local: HTTP 200 en raíz y health; servidor propio detenido al acabar.
  **Navegador pendiente en esta versión**: la descarga de Chromium devolvió un
  archivo inválido. AppTest verifica las interacciones del servidor, pero no
  sustituye esa comprobación visual. El script de navegador respeta ahora el
  intervalo real entre cálculos, sin desactivar los límites.
- Los bytes versionados de `data_crime_scene/` permanecen idénticos a la base
  `2f861bb12b20a425809bcd4d8d4d9f25aeb7c1bf`. No se regeneró ningún estudio.
  Esta copia de trabajo no contiene los 21 históricos privados del equipo del
  propietario; no se afirma haberlos vuelto a cotejar.

Los logs locales de esta intervención están en `artifacts/security-hardening/`,
excluido de Git. La CI de cada commit, su revisión humana, la activación de
protecciones y el despliegue deben comprobarse por separado en sus servicios.
