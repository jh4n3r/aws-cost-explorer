# AWS Cost Explorer - Documentación Interna

Este documento detalla la arquitectura, configuración y funcionamiento interno del proyecto **AWS Cost Explorer**.

## 1. Arquitectura del Proyecto

El proyecto está diseñado como una aplicación monolítica utilizando **Flask (Python)** para el backend y **HTML/CSS/JS** vanilla (o con librerías específicas estáticas) en el frontend.

### Stack Tecnológico
- **Backend:** Python 3.x, Flask, Flask-Bcrypt (Hashing de contraseñas), PyJWT (JSON Web Tokens para Auth).
- **Base de Datos:** MongoDB (utilizando el driver `pymongo`).
- **AWS SDK:** Boto3 (para realizar llamadas a la API de Cost Explorer de AWS).
- **Generación de Reportes:** Pandas (procesamiento y exportación a CSV), ReportLab (generación de informes en PDF).
- **Criptografía:** `cryptography` (para encriptar y desencriptar de modo seguro las claves secretas de AWS en la BBDD).

### Estructura de Directorios (Asumida)
```text
aws-cost-calc/
├── app.py                  # Archivo principal de rutas de la API de Flask
├── auth.py                 # Lógica de Autenticación, JWT, y sembrado de usuarios (admin)
├── aws_logic.py            # Funciones para comunicarse con la API de Cost Explorer de AWS y encriptación
├── database.py             # Configuración y conexión con MongoDB
├── requirements.txt        # Dependencias de Python
├── encryption.key          # ⚠️ IMPORTANTE: Archivo que guarda la clave de cifrado maestro
├── static/                 # Archivos estáticos (CSS, JS, imágenes)
└── templates/              # Plantillas HTML (index.html)
```

## 2. Modelos de Base de Datos (MongoDB)

Toda la base de datos se maneja usualmente sin esquemas estrictos (NoSQL), pero el proyecto asume las siguientes colecciones:

- **Users (`users_collection`):**
  - `username` (string, unique)
  - `password` (string, hasheado con bcrypt)
  - `role` (string) - ej. `admin` o `user`
- **Accounts (`accounts_collection`):**
  - `alias_cuenta` (string, unique)
  - `access_key` (string)
  - `secret_key` (string, **encriptado en la base de datos**)
  - `region` (string) - ej. `us-east-1`
- **Costs (`costs_collection`):**
  - Almacena en "caché" por periodos de tiempo las facturaciones analizadas con `Boto3` para una rápida consulta y agregación de documentos.

## 3. Seguridad

### a. Autenticación y Autorización
Todos los endpoints protegidos bajo la API usan el decorador `@token_required` definido en `auth.py`. Éste valida que en la cabecera HTTP `Authorization` se remita un JWT válido, generado desde la ruta de Login `/api/login`, y expone los datos del usuario en la sesión al respectivo controlador.

### b. Manejo de Credenciales de AWS
Las credenciales Secret de AWS **NO se guardan en texto plano en la BBDD**. Son encriptadas usando la librería `cryptography` apoyándose en una llave maestra que reside en `encryption.key` a nivel sistema de archivos. De esta forma, si la base de datos se ve comprometida por algún evento fortuito, no se exponen de inmediato llaves de Facturación (Cost Explorer).

## 4. Endpoints Principales (`app.py`)

- `POST /api/login`: Autenticación, devuelve token JWT.
- **Manejo de Usuarios:**
  - `GET /api/users`: Lista de usuarios (Requiere admin).
  - `POST /api/users`: Creación de usuarios (Requiere admin).
  - `DELETE /api/users/<username>`: Eliminar usuario.
- **Cuentas AWS:**
  - `GET /api/accounts`: Listado de cuentas vinculadas.
  - `POST /api/accounts`: Registrar alias, Access Key, Secret Key (esta se cifra antes de insertarse en Mongo).
  - `DELETE /api/accounts/<alias>`: Elimina cuenta.
- **Cobros/Costos (Billing):**
  - `GET /api/costs`: Solicita los datos de la cuenta vinculada hacia la API de AWS y devuelve el JSON en bruto.
  - `GET /api/costs/summary`: Devuelve una vista pivotada con agrupación por servicio (`$group` en Mongo) y desglose (`breakdown`) listo para representarse en gráficas/tablas estructuradas.
- **Exportaciones:**
  - `GET /api/export/csv`: Exporta resultados transformados a `.csv`.
  - `GET /api/export/pdf`: Utiliza Reportlab para armar un sumario con estilo sobre consumos.

## 5. Consideraciones de Producción
- Ignorar archivos sensibles usando `.gitignore` (Como `encryption.key` o variables de entorno `.env` en general).
- **NO** usar `app.run(debug=True)` en producción. Utilizar WSGI tools (como Gunicorn) y un proxy reverso como Nginx.
- La variable de entorno `FLASK_SECRET_KEY` debe estar presente para la correcta firma de JWT.
- Recomendable montar una red local o restringir el Binding de la MongoDB (`bindIp=127.0.0.1` si la app y la bd residen en la misma máquina o utilizar credenciales robustas si la app se encuentra dockerizada).
