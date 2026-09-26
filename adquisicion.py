import time
import pandas as pd
from mbientlab.metawear import MetaWear, libmetawear, parse_value
from mbientlab.metawear.cbindings import *

# 1. Variables GLOBALES
data_buffer = []
tiempo_inicio = 0.0
callback_acelerometro = None 
callback_giroscopio = None

# Diccionario para sincronizar las lecturas (Guarda el último dato del giroscopio)
ultimo_giroscopio = {"x": 0.0, "y": 0.0, "z": 0.0}

def configurar_prueba_eurobench():
    print("\n" + "="*50)
    print("SISTEMA DE ADQUISICIÓN IMU (6 EJES)")
    print("="*50)
    
    sujeto = input("ID del Paciente (ej. 1, 2, 3...): ").zfill(2)
    sesion = input("Número de Sesión (ej. 1): ").zfill(2)
    
    print("\nSelecciona la tarea a evaluar:")
    print("1. TUG (Timed Up and Go)")
    print("2. STS (Sit to Stand)")
    print("3. Marcha 5 metros (walk)")
    print("4. Bipedestación 2 minutos (stand)")
    print("5. Apoyo monopodal (single-leg)")
    
    opcion_tarea = input("Ingresa el número de la tarea (1-5): ")
    diccionario_tareas = {
        "1": "tug", 
        "2": "sts", 
        "3": "walk", 
        "4": "stand", 
        "5": "single-leg"
    }
    tarea = diccionario_tareas.get(opcion_tarea, "unknown")
    intento = input("Número de intento (run) (ej. 1, 2...): ").zfill(2)
    
    nombre_archivo = f"sub-{sujeto}_ses-{sesion}_task-{tarea}_run-{intento}_imu.csv"
    return nombre_archivo

def iniciar_grabacion():
    global data_buffer, tiempo_inicio, callback_acelerometro, callback_giroscopio, ultimo_giroscopio
    
    nombre_archivo = configurar_prueba_eurobench()
    print(f"\n[OK] El archivo se guardará como: {nombre_archivo}")
    print("\nPor favor, verifica que el IMU esté correctamente posicionado en el participante.")
    input("\nPresiona ENTER cuando el paciente esté listo para iniciar la prueba...")
    
    MAC_ADDRESS = "E7:D7:CE:C3:E0:25"
    print(f"\nConectando al sensor {MAC_ADDRESS}...")
    device = MetaWear(MAC_ADDRESS)
    
    try:
        device.connect()
        print("¡Conexión exitosa! Configurando hardware (Acelerómetro y Giroscopio)...")
        
        board = device.board
        
        # --- 2. CONFIGURACIÓN ACELERÓMETRO (100 Hz, ±4g) ---
        libmetawear.mbl_mw_acc_set_odr(board, c_float(100.0))
        libmetawear.mbl_mw_acc_set_range(board, c_float(4.0))
        libmetawear.mbl_mw_acc_write_acceleration_config(board)
        
        # --- 3. CONFIGURACIÓN GIROSCOPIO (100 Hz, ±2000 dps) ---
        # Se utilizan las constantes de la librería cbindings para el sensor Bosch BMI160
        libmetawear.mbl_mw_gyro_bmi160_set_odr(board, GyroBoschOdr._100Hz)
        libmetawear.mbl_mw_gyro_bmi160_set_range(board, GyroBoschRange._2000dps)
        libmetawear.mbl_mw_gyro_bmi160_write_config(board)
        
        # Habilitar el muestreo en la placa
        libmetawear.mbl_mw_acc_enable_acceleration_sampling(board)
        libmetawear.mbl_mw_gyro_bmi160_enable_rotation_sampling(board)
        
        # Identificar las señales de transmisión
        acc_signal = libmetawear.mbl_mw_acc_get_acceleration_data_signal(board)
        gyro_signal = libmetawear.mbl_mw_gyro_bmi160_get_rotation_data_signal(board)

        tiempo_inicio = time.time()
        data_buffer = []
        
        # --- 4. CALLBACK GIROSCOPIO (Actualiza el estado en vivo) ---
        def on_gyro(ctx, data):
            v = parse_value(data)
            ultimo_giroscopio["x"] = float(v.x)
            ultimo_giroscopio["y"] = float(v.y)
            ultimo_giroscopio["z"] = float(v.z)
            
        # --- 5. CALLBACK ACELERÓMETRO (Empaqueta los 6 ejes) ---
        def on_acc(ctx, data):
            v = parse_value(data)
            tiempo_actual = time.time() - tiempo_inicio
            data_buffer.append({
                "time": round(tiempo_actual, 3), 
                "acc_x": float(v.x),
                "acc_y": float(v.y),
                "acc_z": float(v.z),
                "gyr_x": ultimo_giroscopio["x"],
                "gyr_y": ultimo_giroscopio["y"],
                "gyr_z": ultimo_giroscopio["z"]
            })
            
        # Suscribir y asignar las funciones
        callback_giroscopio = FnVoid_VoidP_DataP(on_gyro)
        libmetawear.mbl_mw_datasignal_subscribe(gyro_signal, None, callback_giroscopio)
        
        callback_acelerometro = FnVoid_VoidP_DataP(on_acc)
        libmetawear.mbl_mw_datasignal_subscribe(acc_signal, None, callback_acelerometro)
        
        # 6. INICIAR TRANSMISIÓN
        libmetawear.mbl_mw_gyro_bmi160_start(board)
        libmetawear.mbl_mw_acc_start(board)
        
        print("🔴 GRABANDO DATOS (6 EJES)... (Presiona Ctrl+C en esta consola para detener)")
        
        while True:
            time.sleep(0.1) 
            
    except KeyboardInterrupt:
        print(f"\n Se detectó Ctrl+C. Deteniendo la prueba y GUARDANDO DATOS...")
        if data_buffer:
            df = pd.DataFrame(data_buffer)
            df.to_csv(nombre_archivo, index=False)
            print(f"✅ ¡ÉXITO! {len(df)} filas de datos inerciales guardadas en {nombre_archivo}")
        else:
            print("⚠️ Alerta: El buffer está vacío.")
        
    except Exception as e:
        print(f"\n Error de ejecución: {e}")
            
    finally:
        print("Desconectando hardware de forma segura...")
        try:
            # Detener sensores
            libmetawear.mbl_mw_acc_stop(board)
            libmetawear.mbl_mw_gyro_bmi160_stop(board)
            
            # Desuscribir señales
            libmetawear.mbl_mw_datasignal_unsubscribe(acc_signal)
            libmetawear.mbl_mw_datasignal_unsubscribe(gyro_signal)
            
            # Deshabilitar muestreo
            libmetawear.mbl_mw_acc_disable_acceleration_sampling(board)
            libmetawear.mbl_mw_gyro_bmi160_disable_rotation_sampling(board)
            
            device.disconnect()
        except:
            pass

if __name__ == "__main__":
    iniciar_grabacion()