# from mbientlab.metawear import MetaWear
# from mbientlab.metawear.cbindings import *
# import time

# # 1. Direccion de la MAC de tu sensor
# MAC_ADDRESS = "E7:D7:CE:C3:E0:25" 

# print(f"Buscando y conectando al sensor {MAC_ADDRESS}...")
# device = MetaWear(MAC_ADDRESS)

# try:
#     # 2. Establecer la conexión Bluetooth
#     device.connect()
#     print("¡Conexión exitosa! El sensor MMS está enlazado al computador.")
    
#     # 3. Enviar un comando de prueba al hardware (Encender LED)
#     pattern = LedPattern(repeat_count= 5)
#     libmetawear.mbl_mw_led_load_preset_pattern(byref(pattern), LedPreset.SOLID)
#     libmetawear.mbl_mw_led_write_pattern(device.board, byref(pattern), LedColor.BLUE)
#     libmetawear.mbl_mw_led_play(device.board)
    
#     print("El LED del sensor debería estar encendido. Manteniendo conexión por 5 segundos...")
#     time.sleep(25)
    
# except Exception as e:
#     print(f"Error en la comunicación: {e}")
    
# finally:
#     # 4. Es vital desconectar al finalizar para no dejar el puerto Bluetooth ocupado
#     device.disconnect()
#     print("Sensor desconectado correctamente.")


import sys
sys.stdout.reconfigure(encoding="utf-8")

from mbientlab.metawear import MetaWear, libmetawear
from mbientlab.metawear.cbindings import *
import time

# Tu dirección MAC real sacada de la app móvil
MAC_ADDRESS = "E7:D7:CE:C3:E0:25" 

print(f"Buscando y conectando al sensor {MAC_ADDRESS}...")
device = MetaWear(MAC_ADDRESS)

try:
    # Establecer la conexión Bluetooth
    device.connect()
    print("¡Conexión exitosa! El sensor MMS está enlazado al computador.")
    
    # Enviar un comando al hardware (Encender LED Azul)
    pattern = LedPattern(repeat_count= 5)
    libmetawear.mbl_mw_led_load_preset_pattern(byref(pattern), LedPreset.SOLID)
    libmetawear.mbl_mw_led_write_pattern(device.board, byref(pattern), LedColor.BLUE)
    libmetawear.mbl_mw_led_play(device.board)
    
    print("El LED azul del sensor debería estar encendido. Manteniendo conexión por 5 segundos...")
    time.sleep(5)
    
except Exception as e:
    print(f"Error en la comunicación: {e}")
    
finally:
    # Apagar el LED y desconectar
    try:
        libmetawear.mbl_mw_led_stop_and_clear(device.board)
        device.disconnect()
        print("Sensor desconectado correctamente.")
    except:
        print("El sensor no estaba conectado, no hubo nada que desconectar.")