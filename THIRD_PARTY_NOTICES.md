# Componentes y recursos de terceros

La [licencia MIT del proyecto](LICENSE) cubre sus aportaciones propias. No sustituye las licencias de dependencias, herramientas, fuentes u otros componentes de sus respectivos autores.

## Dependencias instaladas por separado

Este repositorio declara dependencias; no incorpora sus distribuciones, código fuente, fuentes tipográficas o binarios. Se conservan sus avisos en los paquetes instalados. Las versiones fijadas figuran en `requirements.txt` y `requirements-browser.txt`; las dependencias de construcción y los extras se declaran en `pyproject.toml`.

Licencias declaradas por los metadatos de las dependencias directas del entorno revisado el 31 de octubre de 2026:

| Componente | Licencia declarada |
| --- | --- |
| NumPy | `BSD-3-Clause AND 0BSD AND MIT AND Zlib AND CC0-1.0` |
| pandas | `BSD-3-Clause` |
| scikit-learn | `BSD-3-Clause` |
| Streamlit | `Apache-2.0` |
| Plotly | `MIT` |
| pytest | `MIT` |
| Playwright, opcional para navegador | `Apache-2.0` |

Estas expresiones no reemplazan los textos completos ni los avisos adicionales de cada distribución. NumPy, pandas, scikit-learn, Plotly y Playwright incluyen además avisos de componentes incorporados en sus propios paquetes. No se han eliminado ni trasladado al copyright del proyecto. Las dependencias transitivas mantienen igualmente sus licencias. El entorno virtual queda excluido de Git.

El backend de construcción setuptools se obtiene por separado cuando se construye el paquete; no está instalado en el entorno local revisado y no se ha construido una distribución en esta publicación. Las acciones [checkout](https://github.com/actions/checkout) y [setup-python](https://github.com/actions/setup-python) se ejecutan desde sus repositorios y conservan su licencia MIT; su código tampoco se incorpora aquí.

## Procedencia de los recursos incluidos

- El código de presentación y CSS procede de la integración local documentada en [integración visual](docs/integracion-visual.md). No se han encontrado bibliotecas vendorizadas, iconos descargados, archivos de fuentes ni fotografías externas en el conjunto publicable.
- `tests/test_visual_charts.py` conserva la atribución y SHA-256 de las funciones de gráficos extraídas de la versión previa del propio proyecto; no se atribuyen a un tercero ni se sustituyen sus referencias.
- Las imágenes de `docs/screenshots/` son capturas históricas de la aplicación y sus datos sintéticos. Muestran también elementos renderizados por Streamlit y Plotly, cuyos componentes siguen perteneciendo a sus respectivos autores.
- Las referencias CSS a Arial, Helvetica y familias genéricas no redistribuyen esas fuentes. Los recursos que sirve Streamlit pertenecen a su distribución.
- Los enlaces metodológicos y técnicos citan sus fuentes; no se incorpora el contenido completo de esos documentos como obra del proyecto.

La revisión cubre los archivos publicados y los metadatos disponibles, no constituye una auditoría jurídica independiente de todas las dependencias transitivas. Si se redistribuyen paquetes o binarios en el futuro, deben acompañarse de los textos y avisos exigidos por sus propias licencias.
