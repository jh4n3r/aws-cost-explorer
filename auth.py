import jwt
import datetime
from functools import wraps
from flask import request, jsonify, current_app
from flask_bcrypt import Bcrypt
from database import users_collection

bcrypt = Bcrypt()

def init_seed_user():
    """
    Función para inicializar el administrador por defecto si la base de datos está vacía.
    Seed User: admin / admin123
    """
    if users_collection.count_documents({}) == 0:
        hashed_password = bcrypt.generate_password_hash("admin123").decode('utf-8')
        users_collection.insert_one({
            "username": "admin",
            "password": hashed_password,
            "role": "admin"
        })
        print("Usuario 'admin' creado por defecto (clave: admin123).")

def generate_token(username):
    """
    Genera un token JWT para el usuario logueado.
    """
    payload = {
        'exp': datetime.datetime.utcnow() + datetime.timedelta(days=1),
        'iat': datetime.datetime.utcnow(),
        'sub': username
    }
    return jwt.encode(payload, current_app.config.get('SECRET_KEY'), algorithm='HS256')

def token_required(f):
    """
    Decorador para proteger rutas en Flask.
    """
    @wraps(f)
    def decorated(*args, **kwargs):
        token = None
        
        # El token vendrá usualmente en la cabecera "Authorization: Bearer <token>"
        if 'Authorization' in request.headers:
            parts = request.headers['Authorization'].split()
            if len(parts) == 2 and parts[0] == 'Bearer':
                token = parts[1]
            else:
                token = request.headers['Authorization']
                
        if not token:
            return jsonify({'message': 'Falta el token de autenticación.'}), 401
            
        try:
            # Validar token
            data = jwt.decode(token, current_app.config.get('SECRET_KEY'), algorithms=['HS256'])
            current_user = users_collection.find_one({'username': data['sub']})
            if not current_user:
                raise Exception("Usuario no encontrado.")
        except jwt.ExpiredSignatureError:
            return jsonify({'message': 'El token ha expirado. Autentíquese nuevamente.'}), 401
        except Exception as e:
            return jsonify({'message': 'Token no válido.', 'error': str(e)}), 401
            
        return f(current_user, *args, **kwargs)
        
    return decorated
