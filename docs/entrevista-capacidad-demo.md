# Guion de entrevista · aproximadamente dos minutos

«Para el ensayo planteé el escenario de un taller de veinte personas que abrieran Data Crime Scene por enlace, sin instalar nada ni crear cuentas, y lanzaran un experimento. Cada participante debía poder descargar su resultado en JSON.

Antes de elegir infraestructura revisé el recorrido real: qué botón entrena, qué reutilizan los reruns y qué estado pertenece a cada sesión. Encontré un límite de un cálculo activo y doce admisiones por minuto por proceso, además de una caché compartida.

Preparé un benchmark local con Chrome y contextos independientes. Coordiné los clics una vez listas las sesiones, separé el consumo del servidor del navegador y registré cuándo se admitía una solicitud y cuándo se llamaba realmente al motor. También contrasté las descargas con la configuración y las predicciones.

Con uno, cinco y diez participantes hice tres repeticiones. Con diez clics coordinados, en cada tanda una persona recibió un resultado y nueve recibieron el aviso de cálculo activo. El resultado correcto tardó entre 1,31 y 1,93 segundos. No hubo timeouts del experimento. Cambiar las semillas no eliminó el rechazo.

Abrí veinte sesiones, pero detuve la prueba antes de sus clics porque el navegador superó mi umbral conservador de memoria. No afirmo haber probado veinte entrenamientos. La caché devolvió resultados sin volver a entrenar y comprobé dos sesiones con configuraciones distintas y sus JSON.

Con esa evidencia no compraría más servidor todavía: trasladar el mismo código a AWS conservaría el límite. Mantendría el acceso por enlace y organizaría turnos si se aceptan en ese escenario. Si fuera obligatorio aceptar las veinte solicitudes a la vez, propondría una cola acotada, espera visible y descarga individual, y mediría ese prototipo antes de dimensionarlo.

El siguiente ensayo separaría los clientes de carga del servidor y usaría los pins vigentes. Lo importante fue distinguir un rechazo de admisión de un fallo de CPU y reconocer qué parte todavía no había medido».

Los tiempos corresponden a **Guiado/future con configuración fija** en el equipo y entorno descritos en [capacidad-demo.md](capacidad-demo.md), no al alojamiento público. Historial compartido, cuentas y persistencia se acordarían aparte con el cliente.
