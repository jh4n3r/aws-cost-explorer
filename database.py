import os
from pymongo import MongoClient

# Se asume una instancia local por defecto, a menos que se defina en variables de entorno.
MONGO_URI = os.getenv("MONGO_URI", "mongodb://localhost:27017/")

client = MongoClient(MONGO_URI)
db = client["aws_cost_manager"]

# Colecciones principales
users_collection = db["users"]
accounts_collection = db["accounts"]
costs_collection = db["costs"]

def init_db():
    """
    Función de utilidad para inicializar o validar conexiones,
    y crear índices importantes para el performance.
    """
    # Índices en colección de costos para buscar rápidamente por fecha y cuenta
    costs_collection.create_index([("account_alias", 1), ("start_date", 1), ("end_date", 1)])
    
    # Índice en usuarios para asegurar la unicidad del nombre de usuario
    users_collection.create_index("username", unique=True)
    
    # Índice en las credenciales por alias
    accounts_collection.create_index("alias_cuenta", unique=True)

    print("Base de datos inicializada correctamente.")
