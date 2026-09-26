import time
import pandas as pd
from mbientlab.metawear import MetaWear, libmetawear, parse_value
from mbientlab.metawear.cbindings import *

# 1. Variables GLOBALES
data_buffer = []
tiempo_inicio = 0.0
callback_acelerometro = None 

def configurar_prueba_eurobench():
    print("\n" + "="*50)
    print("SISTEMA DE ADQUISICIÓN DE DATOS INERCIALES")
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
    global data_buffer, tiempo_inicio, callback_acelerometro
    
    nombre_archivo = configurar_prueba_eurobench()
    print(f"\n[OK] El archivo se guardará como: {nombre_archivo}")
    print("\nPor favor, verifica que el IMU esté correctamente posicionado en el participante.")
    input("\nPresiona ENTER cuando el paciente esté listo para iniciar la prueba...")
    
    MAC_ADDRESS = "E7:D7:CE:C3:E0:25"
    print(f"\nConectando al sensor {MAC_ADDRESS}...")
    device = MetaWear(MAC_ADDRESS)
    
    try:
        device.connect()
        print("¡Conexión exitosa! Configurando hardware...")
        
        board = device.board
        
        libmetawear.mbl_mw_acc_set_odr(board, c_float(100.0))
        libmetawear.mbl_mw_acc_set_range(board, c_float(4.0))
        libmetawear.mbl_mw_acc_write_acceleration_config(board)
        libmetawear.mbl_mw_acc_enable_acceleration_sampling(board)
        
        acc_signal = libmetawear.mbl_mw_acc_get_acceleration_data_signal(board)

        tiempo_inicio = time.time()
        data_buffer = []
        
        def on_acc(ctx, data):
            v = parse_value(data)
            tiempo_actual = time.time() - tiempo_inicio
            data_buffer.append({
                "time": round(tiempo_actual, 3), 
                "acc_x": float(v.x),
                "acc_y": float(v.y),
                "acc_z": float(v.z)
            })
            
        callback_acelerometro = FnVoid_VoidP_DataP(on_acc)
        libmetawear.mbl_mw_datasignal_subscribe(acc_signal, None, callback_acelerometro)
        
        libmetawear.mbl_mw_acc_start(board)
        print(" GRABANDO DATOS... (Presiona Ctrl+C en esta consola para detener)")
        
        while True:
            time.sleep(0.1) 
            
    except KeyboardInterrupt:
        print(f"\n Se detectó Ctrl+C. Deteniendo la prueba y GUARDANDO DATOS...")
        # 2. EL TRUCO: Guardamos el archivo ANTES de tocar la desconexión del hardware
        if data_buffer:
            df = pd.DataFrame(data_buffer)
            df.to_csv(nombre_archivo, index=False)
            print(f"¡ÉXITO! {len(df)} filas de datos inerciales guardadas en {nombre_archivo}")
        else:
            print("Alerta: El buffer está vacío.")
        
    except Exception as e:
        print(f"\nError de ejecución: {e}")
            
    finally:
        # 3. Solo después de que los datos estén en el disco duro, apagamos el sensor
        print("Desconectando hardware de forma segura...")
        try:
            libmetawear.mbl_mw_acc_stop(board)
            libmetawear.mbl_mw_datasignal_unsubscribe(acc_signal)
            libmetawear.mbl_mw_acc_disable_acceleration_sampling(board)
            device.disconnect()
        except:
            pass

if __name__ == "__main__":
    iniciar_grabacion()