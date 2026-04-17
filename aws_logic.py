import boto3
import json
from datetime import datetime
from cryptography.fernet import Fernet
from database import accounts_collection, costs_collection
from botocore.exceptions import ClientError
import os
import logging

# Mapeo de regiones clave de AWS a nombres amigables
REGION_NAMES = {
    "us-east-1": "US East (N. Virginia)",
    "us-east-2": "US East (Ohio)",
    "us-west-1": "US West (N. California)",
    "us-west-2": "US West (Oregon)",
    "ca-central-1": "Canada (Central)",
    "sa-east-1": "South America (São Paulo)",
    "eu-west-1": "Europe (Ireland)",
    "eu-central-1": "Europe (Frankfurt)",
    "eu-west-2": "Europe (London)",
    "eu-west-3": "Europe (Paris)",
    "eu-north-1": "Europe (Stockholm)",
    "ap-southeast-1": "Asia Pacific (Singapore)",
    "ap-southeast-2": "Asia Pacific (Sydney)",
    "ap-northeast-1": "Asia Pacific (Tokyo)",
    "Global": "Global"
}

logging.basicConfig(level=logging.INFO)

# Generamos o leemos una clave de encriptación persistente en disco
KEY_FILE = "encryption.key"
if not os.path.exists(KEY_FILE):
    with open(KEY_FILE, "wb") as f:
        f.write(Fernet.generate_key())

with open(KEY_FILE, "rb") as f:
    FERNET_KEY = f.read()

cipher_suite = Fernet(FERNET_KEY)

def encrypt_secret(secret_key: str) -> str:
    return cipher_suite.encrypt(secret_key.encode('utf-8')).decode('utf-8')

def decrypt_secret(encrypted_secret: str) -> str:
    return cipher_suite.decrypt(encrypted_secret.encode('utf-8')).decode('utf-8')

def get_boto3_client(alias_cuenta: str, service='ce'):
    account = accounts_collection.find_one({"alias_cuenta": alias_cuenta})
    if not account:
        raise ValueError(f"No se encontró la cuenta con el alias: {alias_cuenta}")
        
    access_key = account['access_key']
    encrypted_secret = account['secret_key']
    region = account['region']
    
    decrypted_secret = decrypt_secret(encrypted_secret)
    
    return boto3.client(
        service,
        aws_access_key_id=access_key,
        aws_secret_access_key=decrypted_secret,
        region_name=region
    )

class AWSResourceMapper:
    """Capa de mapeo para resolver nombres reales de recursos AWS por ID."""
    def __init__(self):
        self.cache = {} # {account_alias: {resource_id: friendly_name}}
        self.clients = {} # {(alias_cuenta, service_name): boto3_client}

    def _get_client(self, alias_cuenta, service_name):
        key = (alias_cuenta, service_name)
        if key not in self.clients:
            try:
                self.clients[key] = get_boto3_client(alias_cuenta, service=service_name)
            except Exception as e:
                logging.error(f"Error creando cliente {service_name}: {str(e)}")
                return None
        return self.clients[key]

    def resolve_name(self, resource_id, service_label, alias_cuenta):
        if not resource_id or resource_id == "NoResourceId": return "Recurso no identificado"
        
        # 1. Verificar Cache
        if alias_cuenta not in self.cache: self.cache[alias_cuenta] = {}
        if resource_id in self.cache[alias_cuenta]:
            return self.cache[alias_cuenta][resource_id]

        friendly_name = None
        
        try:
            # 2. Lógica por servicio
            if "EC2" in service_label or "Elastic Compute Cloud" in service_label:
                if resource_id.startswith("i-"):
                    client = self._get_client(alias_cuenta, 'ec2')
                    if client:
                        resp = client.describe_instances(InstanceIds=[resource_id])
                        for resv in resp.get('Reservations', []):
                            for inst in resv.get('Instances', []):
                                tags = {t['Key']: t['Value'] for t in inst.get('Tags', [])}
                                friendly_name = tags.get('Name')
            
            elif "RDS" in service_label or "Relational Database Service" in service_label:
                client = self._get_client(alias_cuenta, 'rds')
                if client:
                    # RDS IDs suelen ser el mismo nombre, pero buscamos tags si es necesario
                    resp = client.describe_db_instances(DBInstanceIdentifier=resource_id)
                    for db in resp.get('DBInstances', []):
                        friendly_name = db.get('DBInstanceIdentifier')

            elif "Lambda" in service_label:
                client = self._get_client(alias_cuenta, 'lambda')
                if client:
                    resp = client.get_function(FunctionName=resource_id)
                    tags = resp.get('Tags', {})
                    friendly_name = tags.get('Name') or resource_id.split(":")[-1]

            elif "S3" in service_label or "Simple Storage Service" in service_label:
                # El ResourceID de S3 es el nombre del bucket
                friendly_name = resource_id

        except Exception as e:
            logging.debug(f"Mapeo saltado para {resource_id}: {str(e)}")

        # 3. Fallback: Si no se pudo resolver por API, usamos el ID acortado
        if not friendly_name:
            if "/" in resource_id:
                friendly_name = resource_id.split("/")[-1]
            else:
                friendly_name = resource_id[:22] + "..." if len(resource_id) > 28 else resource_id

        # 4. Guardar en Cache
        self.cache[alias_cuenta][resource_id] = friendly_name
        return friendly_name

resource_mapper = AWSResourceMapper()

def fetch_aws_costs(alias_cuenta: str, start_date: str, end_date: str):
    cache_query = {
        "account_alias": alias_cuenta,
        "start_date": start_date,
        "end_date": end_date,
        "level": "FULL_DETAIL"
    }
    
    cached_result = costs_collection.find_one(cache_query)
    if cached_result:
        cached_result['_id'] = str(cached_result['_id'])
        return cached_result['data']
        
    try:
        ce_client = get_boto3_client(alias_cuenta, service='ce')
        
        # 1. Query principal: SERVICE & TAG Name en su lugar para evitar API pagada
        res_main = ce_client.get_cost_and_usage(
            TimePeriod={'Start': start_date, 'End': end_date}, Granularity='DAILY', Metrics=['UnblendedCost'],
            GroupBy=[{'Type': 'DIMENSION', 'Key': 'SERVICE'}, {'Type': 'TAG', 'Key': 'Name'}]
        )
        results_over_time = res_main.get('ResultsByTime', [])
        
        # 2. Mapeo y formateo de datos para el frontend
        for res_time in results_over_time:
            for g in res_time.get('Groups', []):
                service = g['Keys'][0]
                tag_key = g.get('Keys', [service, "Name$"])[1] if len(g.get('Keys', [])) > 1 else "Name$"
                
                # Extraemos el valor real de la etiqueta o asignamos un fallback genérico
                if tag_key == "Name$":
                    # Si no tiene nombre definido en los AWS Tags
                    final_name = f"Recurso {service.split(' -')[0]} (Sin Nombre/Sin Tag)"
                    original_name = "(Múltiples/Sin ID)"
                else:
                    final_name = tag_key.replace("Name$", "", 1)
                    original_name = final_name
                
                # Inyectamos metadatos estandarizados para que los dashboards no se rompan
                g['Service'] = service
                g['Operation'] = "N/A"
                g['Region'] = "Global" # Cost explorer sin filtros de región reporta a nivel Global
                
                # El Dashboard espera el nombre semántico en la posición 1
                g['Keys'][1] = final_name
                # Guardamos como ResourceId por compatibilidad
                g['ResourceId'] = original_name
        
        # Guardamos en Mongo
        costs_collection.insert_one({
            "account_alias": alias_cuenta,
            "start_date": start_date,
            "end_date": end_date,
            "level": "FULL_DETAIL",
            "data": results_over_time,
            "fetched_at": datetime.utcnow()
        })
        
        return results_over_time
        
    except ClientError as e:
        raise Exception(f"Boto3 ClientError: {str(e)}")
    except Exception as e:
        raise Exception(f"Error general procesando datos: {str(e)}")
