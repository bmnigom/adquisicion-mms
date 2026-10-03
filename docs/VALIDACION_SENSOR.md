# Validación física del sensor y de las métricas

**Estado: pendiente de ejecución con hardware y un método externo de referencia.**
Las pruebas sintéticas comprueban comportamientos conocidos del código. El arranque
`--check` comprueba la aplicación y la carga de bibliotecas Bluetooth. Ninguna de
esas comprobaciones demuestra la exactitud de las mediciones de una persona.

Este protocolo permite decidir qué métricas pueden utilizarse en campo y con qué
límites. Los criterios numéricos siguientes son **objetivos técnicos propuestos
para este proyecto**, no umbrales clínicos ni especificaciones certificadas del
fabricante. Fijar los criterios y el análisis antes de recoger las mediciones;
registrar cualquier cambio posterior con su motivo y repetir los casos afectados.

## Preparación y registro de la configuración

1. Utilizar una instalación limpia en el computador destinado al trabajo de campo.
   Ejecutar `--check` y después verificar conexión, transmisión y reconexión reales.
2. Registrar versión de aplicación, versión del algoritmo, modelo exacto del sensor,
   firmware, dirección asignada, adaptador Bluetooth, sistema operativo, batería y
   fecha. Confirmar que el giroscopio del modelo se configura y transmite realmente.
3. Registrar frecuencia solicitada, rangos de acelerómetro y giroscopio, ubicación,
   método de fijación y referencia de orientación. El código solicita 100 Hz,
   ±16 g y ±2000 °/s; distinguir configuración solicitada de configuración confirmada.
4. Identificar instrumento externo, frecuencia de adquisición, calibración, unidades,
   versión del software y regla utilizada para detectar el inicio/final del movimiento.
5. Conservar en cada intento su `session_id`, IMU, reporte, manifiesto, archivo externo
   y anotaciones. Guardar archivos externos en una carpeta de validación separada;
   relacionarlos mediante `session_id`, sin introducirlos como datos del simulador.

Los datos simulados quedan en `data/simulacion` o en la subcarpeta equivalente del
ejecutable. No incluirlos en la estimación de exactitud con personas. Los registros
antiguos marcados `legacy-desconocido` requieren confirmar su origen antes de incluirlos.

## Comprobaciones de bancada antes del movimiento

| Comprobación | Procedimiento reproducible | Objetivo técnico propuesto | Resultado actual |
|---|---|---|---|
| Reposo y gravedad | Sensor inmóvil 30 s en seis orientaciones; registrar medianas por eje y norma | Desviación de la norma respecto a 1 g ≤0,05 g; ninguna muestra no finita | Pendiente |
| Giro en reposo | Reposo 30 s antes y después de la sesión | Mediana de cada eje ≤2 °/s en valor absoluto; documentar deriva térmica | Pendiente |
| Giro conocido | Montaje de giro controlado, con velocidad medida por referencia independiente | Diferencia ≤5 % o ≤5 °/s, usando el límite mayor; repetir ambos sentidos | Pendiente |
| Continuidad | Registro de 2 min a distancia habitual y sin obstáculos | Sin desconexión; cobertura estimada ≥98 %; guardar hueco máximo y origen del tiempo | Pendiente |
| Colocación | Retirar y volver a fijar tres veces en la misma posición | Orientación consistente; sin deslizamiento durante el movimiento | Pendiente |

Estos objetivos ayudan a detectar montaje o configuración incorrectos. Cumplirlos
no demuestra por sí solo exactitud de velocidad, desplazamiento o potencia.

## Matriz de referencia por métrica

Sincronizar el sensor y la referencia mediante un evento visible en ambas señales,
anotando el error de sincronización. Mantener las mismas definiciones de fase,
filtros y punto anatómico al comparar. Si se utilizan videos, conservar la frecuencia
real del archivo y los fotogramas seleccionados; no asumir que la frecuencia elegida
en el teléfono corresponde a la del archivo exportado.

| Prueba y métrica | Referencia externa y protocolo | Criterio técnico propuesto para el piloto | Alcance del resultado |
|---|---|---|---|
| Salto: tiempo de vuelo | Plataforma de contacto o video ≥240 fps con ambos pies visibles; sensor sobre sacro; misma postura al despegar y aterrizar | Error absoluto medio ≤20 ms y sesgo absoluto ≤10 ms | Valida detección de despegue/aterrizaje en la técnica ensayada |
| Salto: altura por vuelo | Calcular también la altura de la referencia a partir de su tiempo de vuelo; registrar flexión al aterrizar | Error absoluto medio ≤2 cm, sesgo absoluto ≤1 cm y percentil 95 del error absoluto ≤4 cm | Comparación de altura por vuelo; no equivalencia automática con altura del centro de masa |
| Salto: potencia estimada | Recalcular la ecuación implementada usando la altura y la masa efectivamente guardadas | Coincidencia aritmética dentro del redondeo mostrado: ≤0,5 W | Verifica cálculo, no potencia mecánica individual medida |
| STS: ascenso de cadera | Seguimiento óptico del mismo punto del sensor; una levantada, altura de silla y uso de brazos registrados | Error absoluto medio ≤3 cm o ≤10 % del valor de referencia, usando el límite mayor | Valida desplazamiento de la cadera en ese protocolo |
| STS: velocidad pico | Derivar velocidad de la trayectoria externa con filtrado declarado; mismo intervalo de ascenso | Error absoluto medio ≤0,10 m/s o ≤10 %, usando el límite mayor | Sensible a filtrado, posición del sensor y definición de fase |
| STS: potencia pico y media | Plataforma de fuerza sincronizada con cinemática; comparar la misma fase y definición de potencia | Error absoluto relativo medio ≤15 %; informar también error en W y límites de acuerdo | Objetivo experimental; el sacro aproxima el movimiento del centro de masa |
| Golpe: velocidad pico del punto instrumentado | Seguimiento óptico 3D de muñeca/sensor; golpe al aire, sin contacto, reposo inicial y final | Error absoluto medio ≤0,5 m/s o ≤10 %, usando el límite mayor | No valida velocidad de otro punto del puño ni fuerza del impacto |
| Golpe: aceleración y giro pico | Sensor de referencia con rango y frecuencia suficientes, montado rígidamente junto al MMS y con ejes alineados | Diferencia ≤10 % tras igualar unidades, ventana y filtrado; sin saturación | La frecuencia de la referencia debe resolver el pico observado |
| Pruebas cronometradas: duración | Video o cronómetro externo sincronizado con los mismos eventos operados | Diferencia ≤0,2 s; registrar por separado error de reloj y variación del operador | Valida el cronometraje del protocolo ensayado |

La ecuación de potencia usada en salto procede de una regresión con masa y altura
de salto. El trabajo original utilizó participantes en edad universitaria y derivó
la ecuación de datos de squat jump; una coincidencia aritmética no constituye
validación en otra población o técnica. Mantener el rótulo «potencia estimada».
[Sayers et al., 1999, publicación original](https://pubmed.ncbi.nlm.nih.gov/10211854/).

En STS, definir antes del ensayo si la referencia representa potencia del centro
de masa o del punto sobre sacro. Si las definiciones difieren, presentar ambas y
la diferencia como límite del modelo; no interpretar ese contraste como un fallo
de calibración corregible mediante una constante ajustada después de medir.

## Diseño mínimo del piloto y repetición entre días

Propuesta inicial: diez participantes de la población prevista, tres intentos por
protocolo y dos días distintos. Ajustar este tamaño al objetivo de investigación
antes de empezar; un piloto técnico no acredita resultados en toda la población.
Incluir niveles de movimiento bajos, medios y altos para comprobar que el error
no crece con la amplitud. Registrar todos los intentos, incluidos los inválidos.

Mantener altura de silla, técnica de salto, pierna de apoyo, longitud de recorrido,
calzado y consignas. Entre días, volver a colocar el sensor y registrar la referencia
usada. Repetir una parte del piloto en un segundo computador/adaptador y, si se
usarán varios modelos de sensor, analizar cada modelo por separado.

Por métrica informar número de intentos totales, válidos y rechazados; diferencia
MMS−referencia por intento; sesgo, error absoluto medio, percentil 95 y máximo;
gráfico de diferencias frente a la magnitud; y resultados separados por día,
computador, modelo y técnica. Informar límites de acuerdo junto con su incertidumbre
cuando el tamaño del estudio permita estimarlos. No sustituir acuerdo por una
correlación alta. Evitar errores relativos cuando la referencia es cercana a cero.

## Tiempo, emparejamiento IMU, latencia y pérdidas

La ruta Bluetooth actual conserva `host_time` del computador. La implementación
real no aporta identidad nativa común verificable para cada aceleración y giro;
`gyro_pairing=estimated` identifica el emparejamiento por orden de recepción.
`gyro_emparejado=1` por sí solo no demuestra sincronía nativa. `native` exige un
`device_time` o un `sequence` común confirmado para ambos canales. Dejar vacíos
los campos nativos ausentes; no convertir la hora del PC en tiempo del dispositivo.
Estas distinciones están definidas en [imu_pairing.py](../core/imu_pairing.py),
[sample_clock.py](../core/sample_clock.py) y [quality.py](../core/quality.py).

Cuando solo se dispone de horas del PC, las pérdidas y la cobertura son estimadas.
Pérdidas pequeñas y cambios permanentes de latencia pueden ser indistinguibles.
Para certificar pérdidas reales se necesita una referencia independiente, por
ejemplo un contador del dispositivo con su contrato verificado. No declarar
«100 % de datos entregados» basándose únicamente en la estimación por llegada.

| Caso | Ejecución y evidencia a conservar | Comportamiento a comprobar |
|---|---|---|
| Llegadas en ráfagas | Captura real continua, intervalos de `host_time` y señal externa sincronizada | No inventar pérdidas por una ráfaga que después se recupera; documentar incertidumbre |
| PC ocupado | Ensayar durante una carga reproducible, anotando inicio y duración; mantener referencia externa | Distinguir retraso recuperado de muestras descartadas; conservar las dos señales |
| Enlace degradado | Repetir a distancias definidas y con obstáculo documentado, sin modificar la técnica | Aumentar avisos/rechazos cuando corresponde; no seguir mostrando sensor listo tras desconexión |
| Desconexión en movimiento | Desconectar deliberadamente una vez por protocolo | Detener captura, marcar el intento inválido y conservar causa; no usarlo en comparaciones válidas |
| Reconexión | Repetir conexión/desconexión diez veces | Liberar el sensor anterior, recuperar transmisión y evitar cierres inesperados |
| Giroscopio sin pareja/saturado | Primero usar las pruebas sintéticas; después comprobar límites físicos del montaje | Identificar fallback/saturación; STS y golpe no se publican como válidos cuando fallan sus verificaciones |
| Reinicio/otro día | Repetir continuidad y colocación al día siguiente | No confundir deriva, nueva calibración o modelo distinto con cambio del participante |

Los casos físicos siguen pendientes aunque sus equivalentes sintéticos pasen.
Conservar `signal_valid`, `gyro_pairing`, saturación de acelerómetro/giroscopio,
`lost_before` y los campos temporales disponibles. Una columna vacía significa
«no registrado», no «sin problema».

## Integridad del paquete de evidencia

Crear un respaldo cuando no haya captura en curso. La publicación es atómica por
archivo; todavía no existe una transacción única para IMU, resultado y reporte.
El ZIP incluye manifiesto de tamaños y SHA-256. Restaurarlo en una carpeta nueva
y comprobar que están los mismos IDs, reportes y datos. La restauración no mezcla
automáticamente participantes de equipos diferentes ni sustituye la carpeta activa.

Si un resultado quedó pendiente porque Excel bloqueó el CSV, comprobar tras cerrar
Excel y guardar de nuevo que su `session_id` aparece una sola vez en el principal.
Los manifiestos conservan la ruta canónica de resultados y la alternativa pendiente.
Guardar también la referencia externa original: el respaldo de MMS no contiene
archivos almacenados fuera de su carpeta de datos.

## Registro de ejecución y decisión de uso

| Campo | Completar al ejecutar |
|---|---|
| Responsable, fecha y versión evaluada | Pendiente |
| Sensor/modelo/firmware y computadores | Pendiente |
| Instrumentos de referencia y calibración | Pendiente |
| Criterios fijados antes de medir | Pendiente |
| Número de participantes/intentos por día | Pendiente |
| Resultados por métrica y configuración | Pendiente |
| Casos rechazados y causa de cada rechazo | Pendiente |
| Desviaciones del protocolo | Pendiente |
| IDs y ubicación del paquete de evidencia | Pendiente |
| Métricas aceptadas, límites y firma responsable | Pendiente |

Aceptar cada métrica por separado. Un fallo en potencia STS no invalida
automáticamente el cronómetro, y un salto correcto no valida la velocidad del golpe.
Si cambia algoritmo, rango, frecuencia, modelo o montaje, repetir los casos
afectados y conservar la evaluación anterior con su versión.
