import sys
import os

# Permite importar desde la raíz del proyecto
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from database import probar_conexion, consultar_placa, validar_y_despachar

def ejecutar_pruebas():
    print("=== 1. COMPROBANDO CONEXIÓN A MYSQL ===")
    if not probar_conexion():
        print("❌ Error: No se pudo conectar a la base de datos.")
        return
    print("✅ Conexión exitosa a MySQL.")

    print("\n=== 2. CONSULTANDO PLACA DE PRUEBA (1234ABC) ===")
    res_consulta = consultar_placa("1234ABC")
    print("Resultado consulta:", res_consulta)

    print("\n=== 3. CONSULTANDO PLACA INEXISTENTE (0000XXX) ===")
    res_inexistente = consultar_placa("0000XXX")
    print("Resultado inexistente:", res_inexistente)

    print("\n=== 4. PROBANDO DESPACHO VÁLIDO (10 Litros a 1234ABC) ===")
    res_despacho = validar_y_despachar("1234ABC", 10.0)
    print("Resultado despacho:", res_despacho)

if __name__ == "__main__":
    ejecutar_pruebas()