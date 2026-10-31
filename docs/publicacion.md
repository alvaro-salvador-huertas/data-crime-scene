# Publicación del código

El 31 de octubre de 2026 se autorizó la primera publicación pública del código en [alvaro-salvador-huertas/data-crime-scene](https://github.com/alvaro-salvador-huertas/data-crime-scene). El alcance incluye licencia, primer commit y publicación de `main`; no incluye despliegue, portfolio, tags ni releases. La preparación de CI no equivale a una ejecución remota correcta; no se incluye un badge de éxito.

Revisión del 30 de octubre de 2026: [corrección y evidencia nueva](correccion-baseline-cohorte.md). La [lista exacta de archivos propuestos](archivos-publicacion.txt) enumera el contenido completo del checkout publicable, incluidos los cambios anteriores. El diff de esta intervención se conserva aparte en `artifacts/cohort-baseline-20261030/intervention.patch`, respecto de la instantánea previa; no se ha inventado un commit base.

**Licencia autorizada:** [MIT](../LICENSE), Copyright (c) 2026 Álvaro Salvador Huertas, con el texto de la [Open Source Initiative](https://opensource.org/license/mit). Los [avisos de terceros](../THIRD_PARTY_NOTICES.md) explican la procedencia revisada y las licencias que conserva cada componente. No se modifican las dependencias ni sus avisos.

Los 90 archivos anteriores coinciden byte a byte con el manifiesto del cierre de la corrección, incluidos fuentes, pruebas, dependencias y workflow. Se conservan las 122 evidencias locales y las identidades de los 21 históricos. Se reutiliza la validación de **226 pruebas en 33,36 s**, AppTest, `pip check` y arranque; no se repite la suite local por añadir licencia y documentación. La revisión del índice detectó además líneas vacías sobrantes al final de `ui/plotly_theme.py`: se eliminaron y se comprobó que su AST permanece idéntico. No cambia el comportamiento, las pruebas, las dependencias ni la huella del motor. El conjunto final revisado contiene **92 archivos**, enumerados en la lista explícita. Las evidencias nuevas se guardan en `artifacts/publication-20261031/`, excluido de Git.

## Qué revisar y compartir

| Contenido publicable | Motivo |
| --- | --- |
| `app.py`, `data_crime_scene/`, `ui/` | Aplicación y lógica local; datos sintéticos sin cuentas ni servicios externos. |
| `tests/`, `scripts/` | Pruebas y comprobaciones de navegador reproducibles. El navegador es opcional y no se descarga desde CI. |
| `requirements.txt`, `requirements-browser.txt`, `pyproject.toml` | Entorno fijado y extra opcional de revisión visual. Para reproducir las versiones comprobadas se usa `requirements.txt`; instalar solo el proyecto deja resolver versiones sin ese bloqueo. |
| `.streamlit/config.toml`, `.gitignore`, `.github/workflows/ci.yml` | Tema, servidor en loopback, telemetría desactivada, exclusiones y CI. No se comparte `secrets.toml`. |
| `LICENSE`, `THIRD_PARTY_NOTICES.md` | Licencia propia y procedencia/avisos de dependencias y recursos. |
| `README.md`, `docs/` y sus capturas seleccionadas | Presentación, metodología, protocolo, límites y evidencia histórica diferenciada de las comprobaciones actuales. |

Los informes locales de `artifacts/` se regeneran mediante comandos explícitos. Se conservan para revisión, pero se excluyen del repositorio: el estudio y las descargas pueden ser voluminosos y contener notas personales de una sesión Detective. Las capturas seleccionadas muestran datos sintéticos y se mantienen dentro de `docs/screenshots/`.

Se excluyen entornos virtuales habituales y auxiliares, cachés, bytecode, artefactos de empaquetado, `.env`, secretos de Streamlit y directorios de configuración del entorno como `.aws/`, `.codex/` o `.agents/`. No es necesario borrar los archivos locales para excluirlos.

La inspección de publicación buscó rutas personales y patrones comunes de credenciales en archivos de código y documentación, sin imprimir posibles secretos ni examinar configuraciones ajenas al proyecto. No encontró coincidencias de credenciales en ese alcance. Una búsqueda por patrones no constituye una garantía universal. El README público usa comandos relativos; las evidencias históricas se interpretan en su entorno original.

La revisión actual sustituye únicamente la ruta personal del comando de arranque en `integracion-visual.md` por `cd data-crime-scene`. No modifica las capturas ni el diseño. Las reglas exactas de exclusión permanecen en [`.gitignore`](../.gitignore):

```gitignore
.venv/
.venv-*/
.tmp/
.agents/
.codex/
.aws/
.DS_Store
Thumbs.db
*.log
__pycache__/
*.py[cod]
.pytest_cache/
.ruff_cache/
.coverage
htmlcov/
*.egg-info/
build/
dist/
.env
.env.*
!.env.example
.streamlit/secrets.toml
artifacts/
!artifacts/.gitkeep
```

No hay actualmente `artifacts/.gitkeep`; la negación no reabre el directorio padre ignorado. Todo `artifacts/`, incluidas las evidencias nuevas y las instantáneas anteriores, queda local. No se ha borrado ningún archivo. Los metadatos `.git/` tampoco forman parte del contenido publicable.

## Instalación y comprobación local

Desde la raíz del checkout:

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python -m pip check
.venv/bin/python -m pytest -q
.venv/bin/python -m streamlit run app.py --server.address 127.0.0.1
```

La instalación necesita conexión para descargar paquetes. Después, los datos y entrenamientos son locales; no se requieren credenciales ni recursos externos durante el uso. La comprobación de instalación limpia se realiza en un entorno auxiliar separado, sin alterar `.venv`; su resultado efectivo se recoge en el README. El extra `requirements-browser.txt` solo es necesario para repetir la navegación real con Chrome/Chromium instalado en el equipo.

En esta corrección se utiliza el entorno existente: Python 3.12.3 y los 45 pins de `requirements.txt` coinciden con lo instalado; `pip check` es correcto. No se repite la instalación limpia histórica ni se afirma haber probado una descarga nueva de dependencias. Los comandos de estudio se revisan, pero no se ejecuta el estudio de 90 combinaciones.

## CI preparada

El [workflow](../.github/workflows/ci.yml) usa eventos `push` y `pull_request`, un único job en Ubuntu 24.04 y Python 3.12. Instala `requirements.txt`, ejecuta `pip check` y lanza pytest. Sus permisos se limitan a `contents: read`, desactiva la persistencia de credenciales del checkout y no incorpora secretos, publicación, despliegue ni descarga de navegadores.

Se consultaron las fuentes oficiales el 28 de octubre de 2026: [sintaxis de workflows](https://docs.github.com/en/actions/reference/workflows-and-actions/workflow-syntax), [pruebas de Python](https://docs.github.com/en/actions/tutorials/build-and-test-code/python), [actions/checkout](https://github.com/actions/checkout) y [actions/setup-python](https://github.com/actions/setup-python). Los README oficiales documentaban `@v7` para ambas acciones. La caché de pip usa la huella de `requirements.txt`; los paquetes siguen instalándose con las versiones fijadas.

La publicación de `main` debe disparar ese workflow. Su estado efectivo, SHA evaluado, pasos y logs se consultan en [GitHub Actions](https://github.com/alvaro-salvador-huertas/data-crime-scene/actions). No se presenta la batería local como CI remota: solo una ejecución terminada acredita su resultado. El cierre de publicación conserva la respuesta y los logs remotos en `artifacts/publication-20261031/`.

El 30 de octubre se han vuelto a consultar los README oficiales de [checkout](https://github.com/actions/checkout) y [setup-python](https://github.com/actions/setup-python): ambos documentan `@v7`. El workflow existente no necesita cambios para esta corrección; sus comandos de comprobación se ejecutan localmente. Esto no acredita la instalación ni la ejecución en un runner remoto.

## Revisión del contenido

Al iniciar la revisión del 31 de octubre, el repositorio local seguía en `main`, sin commits, remotos ni archivos en staging. La cuenta autenticada y el destino remoto se comprueban antes de publicar; no se sustituye un `origin` existente ni se sobrescribe historial. El índice se prepara exclusivamente con la lista revisada y se contrasta antes del commit. Estos comandos son de lectura:

```bash
git status --short
git remote -v
git diff --stat
git ls-files --others --exclude-standard
git check-ignore .venv/ artifacts/ .aws/ .codex/ .agents/
```

En un repositorio recién inicializado sin commits, `git diff` no muestra los archivos nuevos: hay que revisar también el listado de archivos sin seguimiento y su contenido. El estado real de Git y cualquier limitación del entorno se recoge en la entrega; no se presupone un historial que no exista.

Los informes y capturas anteriores se conservan con su atribución histórica. Añadir el modo Detective no transforma las 90 combinaciones del Laboratorio en una validación del modo nuevo ni exige repetirlas si no cambia el motor histórico.
