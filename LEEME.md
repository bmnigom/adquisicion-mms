# Adquisición MMS

La aplicación usa PyQt6 y puede iniciarse sin PyCharm en este equipo.

## Instalar en otro computador

Use el instalador `AdquisicionMMS-2.0.0-instalador.exe` (sección *Releases* del repositorio en GitHub, o `dist\instalador` tras construirlo con `packaging\construir.cmd`). No requiere Python ni permisos de administrador. Requiere Windows 10/11 con Bluetooth. Si SmartScreen muestra «Windows protegió su PC», elija **Más información → Ejecutar de todas formas** (el instalador no está firmado).

Tras instalar, abra **Adquisición MMS** desde el menú Inicio, encienda el sensor y use **Configurar sensor → Buscar sensores** para elegir el sensor de ese equipo (también puede escribir la dirección MAC). La elección se guarda en `%LOCALAPPDATA%\AdquisicionMMS\data\configuracion.json`. El menú Inicio incluye además el modo de simulación y un acceso a la carpeta de datos y reportes. Si ocurre un error inesperado, queda registrado en `registro_errores.log` dentro de esa carpeta.

## Abrir la aplicación desde el código fuente

- Si usa el archivo ZIP descargado, haga clic derecho sobre él y elija **Extraer todo**. Abra la carpeta extraída antes de ejecutar cualquier `.cmd`; Windows no puede iniciar la aplicación desde la vista interna del ZIP.
- Abra esta carpeta en el Explorador de Windows.
- Haga doble clic en `Simular_MMS.cmd` para comprobar la interfaz sin sensor. Verá la pantalla **Descubre tu movimiento** y, tras unos segundos, el estado **Sensor listo para comenzar**.
- Haga doble clic en `Iniciar_MMS.cmd` para usar el sensor MetaWear real. Encienda el sensor y active Bluetooth antes de abrirlo.
- Mantenga abierta la ventana negra de diagnóstico mientras usa MMS. Si la aplicación falla al iniciar, allí aparecerá el error y la ventana esperará una tecla para que pueda leerlo.

La portada es el **modo evento**. Pulse **Iniciar experiencia** para registrar 20 segundos de movimiento de brazo con el sensor en la muñeca. Verá la señal IMU en vivo, el cronómetro y un resultado simple; el registro termina automáticamente a los 20 segundos. **Ver todas las pruebas** abre el modo de evaluación con los siete protocolos. El modo evento no asigna una clasificación clínica.

Para una comprobación rápida del arranque desde una terminal en esta carpeta, ejecute `Iniciar_MMS.cmd --check`. Debe mostrar `MMS_OK`. Esta comprobación usa el sensor simulado.

Si el modo real muestra **No se pudieron leer los servicios Bluetooth del sensor (GATT)**, la ventana ya está ejecutándose; el fallo ocurre al conectar el sensor. Compruebe que está encendido y cargado, cierre otras aplicaciones que puedan usarlo y pulse **Reintentar conexión**. Si persiste, use **Configurar sensor** para comprobar que la dirección corresponde al sensor utilizado.

Los accesos directos usan el entorno `C:\Users\fx517\miniconda3\envs\adquisicion-mms`, que ya está instalado en este equipo. Si se traslada la carpeta a otro equipo, habrá que instalar Python y las dependencias de `requirements.txt`, o generar un ejecutable para ese equipo.

Los datos actuales permanecen en la carpeta `data` del proyecto. La versión fuente sigue guardando nuevas mediciones allí. Una versión empaquetada como ejecutable guardará sus datos en `%LOCALAPPDATA%\AdquisicionMMS\data` para que pueda escribirlos aunque esté instalada en una carpeta protegida.

## Pruebas disponibles

- **TUG:** cronómetro manual y registro IMU. El recorrido indicado es de 3 metros de ida y regreso.
- **STS:** una repetición detectada automáticamente. Sensor en la cadera (sobre el sacro, con cinturón). Potencia pico y media de ascenso, potencia relativa (W/kg), velocidad y ascenso de la cadera.
- **Marcha de 5 metros:** cronómetro manual y registro IMU.
- **Bipedestación de 2 minutos:** cronómetro y registro IMU, con finalización automática a los 120 segundos. También puede finalizarse antes.
- **Apoyo monopodal:** cronómetro y registro IMU; se registra la pierna de apoyo.
- **Salto vertical:** sensor en la cadera (no en el tobillo). Altura por tiempo de vuelo; potencia estimada con la ecuación de Sayers (1999).
- **Golpe rápido:** sensor en la muñeca. Velocidad pico del puño (3D), aceleración pico y velocidad angular pico.

Las pruebas cronometradas guardan un CSV de muestras IMU por intento y una fila resumen en `data/resultados_pruebas_funcionales.csv`. La acción **Cancelar** descarta el intento. No se generan diagnósticos automáticos.

## Protocolo para salto, STS y golpe

1. Fije el sensor **firme** en la ubicación indicada (un sensor suelto se mueve respecto al cuerpo y arruina la medición).
2. Pulse **Comenzar**. La persona debe quedar **quieta** hasta que la pantalla diga **«¡Ahora!»** (medio segundo de reposo: es la referencia de gravedad y de velocidad cero).
3. Realiza el movimiento y **vuelve a quedar quieta** unos 0,6 s. El resultado aparece solo.
4. Mantenga el computador a pocos metros del sensor. La línea **«Señal Bluetooth: … % de muestras recibidas»** debe decir *buena*; si dice *irregular* o *mala*, acérquelo antes de medir.

## Reporte para el personal

Tras cada intento, la pantalla muestra las cifras principales y un **reporte** con:

- **Veredicto:** ✔ *Medición válida*, ⚠ *Válida con observaciones* (lea la observación antes de comparar) o ✖ *Repetir la prueba* (con el motivo y qué hacer). Si el veredicto es *Repetir*, **no se muestran valores**: podrían ser incorrectos.
- **Resultados**, con la diferencia respecto al intento válido anterior del mismo participante.
- **Cómo interpretarlo:** qué significa cada cifra, cómo comparar y sus límites.
- **Calidad de la medición:** muestras recibidas por Bluetooth, continuidad de datos durante el movimiento, saturación del sensor y verificaciones de plausibilidad (por ejemplo, un tiempo de vuelo imposible).
- **Método** usado para el cálculo.

El reporte se guarda en `data/reportes/` y se abre en el navegador con **Abrir reporte guardado**. Los resultados de salto, STS y golpe se guardan en `data/resultados_ciclovia_v2.csv`, incluidos los intentos inválidos (columna `valido` = `no`, con el motivo). Para analizar, filtre `valido = si`.

## Comparaciones orientativas

La edad es opcional. Si se indica una edad de **65 años o más**, el resultado TUG muestra el punto de referencia de **12 segundos** de [CDC STEADI](https://www.cdc.gov/steadi/media/pdfs/steadi-assessment-tug-508.pdf). Un tiempo igual o mayor invita a ampliar la valoración del riesgo de caída; un tiempo menor no descarta ese riesgo. El cronómetro lo acciona el operador, desde la orden de inicio hasta que la persona vuelve a sentarse.

En marcha de 5 metros se muestra la velocidad media `5 / tiempo` en m/s. Para mayores de 65 años se presenta, **solo como comparación orientativa**, la referencia de **0,8 m/s** de [EWGSOP2](https://academic.oup.com/ageing/article/48/1/16/5126243): el protocolo habitual citado por ese consenso mide 4 metros. Este valor no diagnostica sarcopenia.

En STS no se aplica el umbral de cinco levantadas porque el modo actual registra una sola repetición. Bipedestación muestra el cumplimiento de los 120 segundos y apoyo monopodal muestra la duración sin un punto de corte clínico. Cuando existe un intento anterior del mismo participante y protocolo, la pantalla muestra la diferencia de tiempo, sin calificarla como mejor o peor.

Desde la pantalla de resultado, **Otra prueba** conserva el participante y su edad para registrar un protocolo distinto. **Nuevo participante** propone el siguiente identificador y borra la edad del formulario.

El archivo `resultados_pruebas_funcionales.csv` incluye la edad indicada para permitir revisar el contexto de la comparación. Estos resultados orientan una conversación o evaluación posterior; no sustituyen una valoración clínica completa.

## Cambios de la versión 2 (septiembre 2026)

La versión anterior calculaba potencia, velocidad y desplazamiento de forma no fiable (por ejemplo, un salto de 15 796 W y 4,5 m). Se corrigió:

- **Bluetooth:** acelerómetro y giroscopio empaquetados, parámetros de conexión rápidos y sin magnetómetro. Se detectan las muestras perdidas (distinguiéndolas de simples retrasos) y un intento con datos perdidos durante el movimiento se rechaza.
- **Desconexión:** si el sensor se desconecta o deja de enviar datos, la aplicación lo indica y la prueba en curso se marca para repetir (antes seguía mostrando «Sensor listo»).
- **Rango del acelerómetro:** ±16 g (antes ±4 g, que se saturaba al saltar y golpear).
- **Salto:** altura por tiempo de vuelo en lugar de doble integración.
- **Potencia STS:** fórmula corregida `m·(a+g)·v` (antes faltaba el peso corporal), solo la fase de ascenso y con corrección de deriva.
- **Golpe:** velocidad en 3D (antes solo se medía la componente vertical de un movimiento horizontal).
- **Orientación:** el acelerómetro no corrige la inclinación durante impactos, y la colocación se compara solo por inclinación (girar el cuerpo ya no cuenta como mala colocación).
- Se eliminaron los niveles «Excelente / Muy bueno / Bueno», que no tenían fuente.

`data/resultados_ciclovia.csv` se conserva como histórico del algoritmo anterior y **no debe usarse**. El script `reprocesar_datos.py` analiza de nuevo los registros antiguos con el algoritmo nuevo, sin modificarlos, y genera `data/reprocesado_datos_anteriores.csv` y `data/reportes/reprocesado_datos_anteriores.html`. Los archivos originales previos a estos cambios están en `respaldo_2026-09-25/`.

Las pruebas de los algoritmos (señales sintéticas de valor conocido) se ejecutan con `python -m tests.test_algoritmos`.

**Pendiente:** validar con el sensor real antes del próximo domingo. Grabe unos saltos junto a un método de referencia (plataforma de contacto o video a 240 fps) y compruebe que la línea de señal Bluetooth indica *buena*. Si el modelo es MetaMotionS, confirme además que el giroscopio se configura correctamente.

## Estructura

- `main.py`: inicio de la aplicación.
- `ui/`: pantallas y estilo visual.
- `core/`: conexión (`sensor_stream`), tiempos y pérdidas (`sample_clock`), orientación y procesamiento (`orientation`, `pipeline`), cálculos (`kinematics`), calidad (`quality`), reporte (`report`) y almacenamiento (`storage`).
- `tests/`: pruebas de los algoritmos.
- `reprocesar_datos.py`: reanálisis de registros anteriores.
- `data/`: mediciones y calibración, cuando se ejecuta desde el código fuente.

- `packaging/`: ejecutable (PyInstaller) e instalador (Inno Setup).

El ejecutable instalado se verificó en este equipo (arranque y carga de las bibliotecas Bluetooth nativas). La conexión con el sensor real en otro computador debe probarse antes de usarlo en campo.
