from flask import Flask, render_template, request, jsonify, send_file
from database import init_db, users_collection, accounts_collection
from auth import init_seed_user, generate_token, token_required, bcrypt
from aws_logic import encrypt_secret, fetch_aws_costs

import os
import io
import pandas as pd
from reportlab.lib.pagesizes import letter
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.enums import TA_CENTER, TA_RIGHT
from reportlab.lib.units import inch

app = Flask(__name__)
# Secret key fallback just in case, should be environment variable
app.config['SECRET_KEY'] = os.getenv('FLASK_SECRET_KEY', 'super-secret-key-test')

# Init DB & Seed
init_db()
init_seed_user()

@app.route('/')
def index():
    return render_template('index.html')

# ================================
# Auth Routes
# ================================

@app.route('/api/login', methods=['POST'])
def login():
    data = request.get_json()
    username = data.get('username')
    password = data.get('password')
    
    user = users_collection.find_one({'username': username})
    if user and bcrypt.check_password_hash(user['password'], password):
        token = generate_token(username)
        return jsonify({'token': token, 'role': user['role']})
    
    return jsonify({'message': 'Credenciales inválidas.'}), 401

# ================================
# User Management
# ================================

@app.route('/api/users', methods=['GET'])
@token_required
def get_users(current_user):
    if current_user['role'] != 'admin':
        return jsonify({'message': 'Acceso denegado.'}), 403
    users_cursor = users_collection.find({}, {'password': 0}) # Exclude passwords
    users = []
    for u in users_cursor:
        users.append({'username': u['username'], 'role': u.get('role', 'user')})
    return jsonify(users)

@app.route('/api/users', methods=['POST'])
@token_required
def create_user(current_user):
    if current_user['role'] != 'admin':
        return jsonify({'message': 'Acceso denegado.'}), 403
    
    data = request.get_json()
    new_username = data.get('username')
    new_password = data.get('password')
    
    if users_collection.find_one({'username': new_username}):
        return jsonify({'message': 'El usuario ya existe.'}), 400
        
    hashed_password = bcrypt.generate_password_hash(new_password).decode('utf-8')
    users_collection.insert_one({
        "username": new_username,
        "password": hashed_password,
        "role": data.get('role', 'user')
    })
    
    return jsonify({'message': 'Usuario creado existosamente.'})

@app.route('/api/users/<username>', methods=['DELETE'])
@token_required
def delete_user(current_user, username):
    if current_user['role'] != 'admin':
        return jsonify({'message': 'Acceso denegado.'}), 403
    if current_user['username'] == username:
        return jsonify({'message': 'No puedes eliminarte a ti mismo.'}), 400
        
    result = users_collection.delete_one({'username': username})
    if result.deleted_count > 0:
        return jsonify({'message': 'Usuario eliminado.'})
    return jsonify({'message': 'Usuario no encontrado.'}), 404

# ================================
# Accounts Management
# ================================

@app.route('/api/accounts', methods=['GET'])
@token_required
def get_accounts(current_user):
    accounts_cursor = accounts_collection.find({}, {'secret_key': 0}) # Do not expose secrets!
    accounts = []
    for a in accounts_cursor:
        accounts.append({'alias_cuenta': a['alias_cuenta'], 'access_key': a['access_key'], 'region': a['region']})
    return jsonify(accounts)

@app.route('/api/accounts', methods=['POST'])
@token_required
def create_account(current_user):
    data = request.get_json()
    alias = data.get('alias_cuenta')
    access_key = data.get('access_key')
    secret_key = data.get('secret_key')
    region = data.get('region', 'us-east-1')
    
    if accounts_collection.find_one({'alias_cuenta': alias}):
        return jsonify({'message': 'El alias ya existe.'}), 400
        
    encrypted_secret = encrypt_secret(secret_key)
    
    accounts_collection.insert_one({
        'alias_cuenta': alias,
        'access_key': access_key,
        'secret_key': encrypted_secret,
        'region': region
    })
    
    return jsonify({'message': 'Cuenta vinculada exitosamente.'})

@app.route('/api/accounts/<alias_cuenta>', methods=['DELETE'])
@token_required
def delete_account(current_user, alias_cuenta):
    result = accounts_collection.delete_one({'alias_cuenta': alias_cuenta})
    if result.deleted_count > 0:
        return jsonify({'message': 'Cuenta eliminada.'})
    return jsonify({'message': 'Cuenta no encontrada.'}), 404

# ================================
# Billing / Costs Logic
# ================================

@app.route('/api/costs', methods=['GET'])
@token_required
def get_costs(current_user):
    alias_cuenta = request.args.get('alias_cuenta')
    start_date = request.args.get('start_date')
    end_date = request.args.get('end_date')
    
    if not all([alias_cuenta, start_date, end_date]):
        return jsonify({'message': 'Faltan parámetros requeridos: alias_cuenta, start_date, end_date'}), 400
        
    try:
        data = fetch_aws_costs(alias_cuenta, start_date, end_date)
        return jsonify({'results': data})
    except Exception as e:
        return jsonify({'message': str(e)}), 500

@app.route('/api/costs/summary', methods=['GET'])
@token_required
def get_costs_summary(current_user):
    alias_cuenta = request.args.get('alias_cuenta')
    start_date = request.args.get('start_date')
    end_date = request.args.get('end_date')
    
    if not all([alias_cuenta, start_date, end_date]):
        return jsonify({'message': 'Faltan parámetros requeridos: alias_cuenta, start_date, end_date'}), 400
        
    try:
        # Aseguramos que los datos estén cacheados primero llamando a fetch
        fetch_aws_costs(alias_cuenta, start_date, end_date)
        
        pipeline = [
            {"$match": {
                "account_alias": alias_cuenta,
                "start_date": start_date,
                "end_date": end_date,
                "level": "FULL_DETAIL"
            }},
            {"$unwind": "$data"},
            {"$unwind": "$data.Groups"},
            {"$project": {
                "date": "$data.TimePeriod.Start",
                "usage_type": {"$arrayElemAt": ["$data.Groups.Keys", 0]},
                "raw_name": {"$arrayElemAt": ["$data.Groups.Keys", 1]},
                "service": "$data.Groups.Service",
                "operation": "$data.Groups.Operation",
                "region": "$data.Groups.Region",
                "amount": {"$toDouble": "$data.Groups.Metrics.UnblendedCost.Amount"}
            }},
            {"$match": {"amount": {"$gt": 0}}},
            {"$group": {
                "_id": {
                    "date": "$date",
                    "service": "$service"
                },
                "total_cost": {"$sum": "$amount"},
                "breakdown": {
                    "$push": {
                        "usage_type": "$usage_type",
                        "operation": "$operation",
                        "resource_name": {
                            "$let": {
                                "vars": {
                                    "cleaned": {"$replaceAll": {"input": "$raw_name", "find": "Name$", "replacement": ""}}
                                },
                                "in": {
                                    "$cond": [
                                        {"$or": [
                                            {"$eq": ["$$cleaned", ""]},
                                            {"$eq": [{"$type": "$$cleaned"}, "missing"]}
                                        ]},
                                        "$usage_type",
                                        "$$cleaned"
                                    ]
                                }
                            }
                        },
                        "region": "$region",
                        "cost": "$amount"
                    }
                }
            }},
            {"$sort": {"_id.date": -1, "total_cost": -1}},
            {"$project": {
                "_id": 0,
                "fecha": "$_id.date",
                "servicio": "$_id.service",
                "total_cost": "$total_cost",
                "breakdown": "$breakdown"
            }}
        ]
        
        from database import costs_collection
        summary = list(costs_collection.aggregate(pipeline))
        return jsonify({'summary': summary})
    except Exception as e:
        return jsonify({'message': str(e)}), 500

# ================================
# Exporting (CSV & PDF)
# ================================

@app.route('/api/export/csv', methods=['GET'])
@token_required
def export_csv(current_user):
    alias_cuenta = request.args.get('alias_cuenta')
    start_date = request.args.get('start_date')
    end_date = request.args.get('end_date')
    service_filter = request.args.get('service', 'ALL')
    region_filter = request.args.get('region', 'ALL')
    search_filter = request.args.get('search', '').lower()
    
    try:
        from database import costs_collection
        pipeline = [
            {"$match": {"account_alias": alias_cuenta, "start_date": start_date, "end_date": end_date, "level": "FULL_DETAIL"}},
            {"$unwind": "$data"},
            {"$unwind": "$data.Groups"},
            {"$project": {
                "date": "$data.TimePeriod.Start",
                "usage_type": {"$arrayElemAt": ["$data.Groups.Keys", 0]},
                "raw_name": {"$arrayElemAt": ["$data.Groups.Keys", 1]},
                "service": "$data.Groups.Service",
                "operation": "$data.Groups.Operation",
                "region": "$data.Groups.Region",
                "amount": {"$toDouble": "$data.Groups.Metrics.UnblendedCost.Amount"}
            }},
            {"$match": {"amount": {"$gt": 0}}}
        ]
        
        match_filters = {}
        if service_filter != 'ALL':
            match_filters["service"] = service_filter
        if region_filter != 'ALL':
            match_filters["region"] = region_filter
        if search_filter:
            match_filters["$or"] = [
                {"raw_name": {"$regex": search_filter, "$options": "i"}},
                {"usage_type": {"$regex": search_filter, "$options": "i"}}
            ]
            
        if match_filters:
            pipeline.append({"$match": match_filters})
            
        pipeline.append({"$sort": {"date": 1, "service": 1}})
        raw_data = list(costs_collection.aggregate(pipeline))
        
        data_flat = []
        for d in raw_data:
            data_flat.append({
                'Fecha (Start)': d['date'],
                'Cuenta AWS': alias_cuenta,
                'Servicio': d['service'],
                'Nombre Recurso': d['raw_name'].replace('Name$', '') or d['usage_type'],
                'Tipo de Uso': d['usage_type'],
                'Operación': d['operation'],
                'Región': d['region'],
                'Costo Real (USD)': round(d['amount'], 6)
            })
        
        df = pd.DataFrame(data_flat)
        output = io.StringIO()
        df.to_csv(output, index=False)
        output.seek(0)
        
        return send_file(
            io.BytesIO(output.getvalue().encode()),
            mimetype="text/csv",
            as_attachment=True,
            download_name=f"AUDIT_{alias_cuenta}_{start_date}_{end_date}.csv"
        )
    except Exception as e:
        return jsonify({'message': str(e)}), 500

@app.route('/api/export/pdf', methods=['GET'])
@token_required
def export_pdf(current_user):
    alias_cuenta = request.args.get('alias_cuenta')
    start_date = request.args.get('start_date')
    end_date = request.args.get('end_date')
    service_filter = request.args.get('service', 'ALL')
    region_filter = request.args.get('region', 'ALL')
    search_filter = request.args.get('search', '').lower()
    
    try:
        from database import costs_collection
        # Pipeline optimizado para resumen y detalle
        pipeline = [
            {"$match": {"account_alias": alias_cuenta, "start_date": start_date, "end_date": end_date, "level": "FULL_DETAIL"}},
            {"$unwind": "$data"},
            {"$unwind": "$data.Groups"},
            {"$project": {
                "service": "$data.Groups.Service",
                "resource_name": {"$arrayElemAt": ["$data.Groups.Keys", 1]},
                "usage_type": {"$arrayElemAt": ["$data.Groups.Keys", 0]},
                "operation": "$data.Groups.Operation",
                "region": "$data.Groups.Region",
                "cost": {"$toDouble": "$data.Groups.Metrics.UnblendedCost.Amount"}
            }},
            {"$match": {"cost": {"$gt": 0}}}
        ]
        
        match_filters = {}
        if service_filter != 'ALL':
            match_filters["service"] = service_filter
        if region_filter != 'ALL':
            match_filters["region"] = region_filter
        if search_filter:
            match_filters["$or"] = [
                {"resource_name": {"$regex": search_filter, "$options": "i"}},
                {"usage_type": {"$regex": search_filter, "$options": "i"}}
            ]
            
        if match_filters:
            pipeline.append({"$match": match_filters})
            
        pipeline.extend([
            {"$group": {
                "_id": {
                    "resource": "$resource_name",
                    "service": "$service",
                },
                "total_cost": {"$sum": "$cost"},
                "regions": {"$addToSet": "$region"}
            }},
            {"$sort": {"total_cost": -1}}
        ])
        agg_data = list(costs_collection.aggregate(pipeline))
        
        buffer = io.BytesIO()
        doc = SimpleDocTemplate(buffer, pagesize=letter, leftMargin=0.5*inch, rightMargin=0.5*inch, topMargin=0.5*inch)
        elements = []
        styles = getSampleStyleSheet()
        
        # Styles
        title_style = ParagraphStyle('TitleCustom', parent=styles['Title'], textColor=colors.HexColor('#232f3e'), fontSize=18, spaceAfter=20)
        header_style = ParagraphStyle('HeaderCustom', parent=styles['Heading2'], textColor=colors.HexColor('#ff9900'), fontSize=14, spaceBefore=10, spaceAfter=10)
        body_style = ParagraphStyle('BodyCustom', parent=styles['Normal'], fontSize=9, leading=12)
        body_bold_style = ParagraphStyle('BodyBold', parent=body_style, fontName='Helvetica-Bold')
        
        # Header
        elements.append(Paragraph(f"AWS Cost Intelligence Report", title_style))
        elements.append(Paragraph(f"Cuenta: {alias_cuenta} | Periodo: {start_date} a {end_date}", styles['Normal']))
        elements.append(Spacer(1, 0.3 * inch))
        
        # Executive Summary (TOP 5)
        elements.append(Paragraph("Resumen Ejecutivo (Top 5 Recursos por Gasto)", header_style))
        top_data = [['Servicio', 'Recurso/Concepto', 'Región', 'Costo Total (USD)']]
        total_period = 0
        for item in agg_data:
            total_period += item['total_cost']
            
        for item in agg_data[:5]:
            _id = item.get('_id', {})
            name = (_id.get('resource', '').replace('Name$', '') or 'N/A')
            regions = ", ".join(_id.get('regions', ['N/A']))
            top_data.append([
                Paragraph(_id.get('service', 'N/A'), body_style),
                Paragraph(name, body_style),
                Paragraph(regions, body_style),
                Paragraph(f"${item['total_cost']:.2f}", body_style)
            ])
            
        top_table = Table(top_data, colWidths=[1.5*inch, 3.5*inch, 1.2*inch, 1.3*inch])
        top_table.setStyle(TableStyle([
            ('BACKGROUND', (0,0), (-1,0), colors.HexColor('#232f3e')),
            ('TEXTCOLOR', (0,0), (-1,0), colors.white),
            ('ALIGN', (0,0), (-1,-1), 'LEFT'),
            ('ALIGN', (-1, 0), (-1, -1), 'RIGHT'),
            ('VALIGN', (0,0), (-1,-1), 'TOP'),
            ('FONTNAME', (0,0), (-1,0), 'Helvetica-Bold'),
            ('FONTSIZE', (0,0), (-1,-1), 10),
            ('BOTTOMPADDING', (0,0), (-1,0), 10),
            ('TOPPADDING', (0,0), (-1,0), 10),
            ('GRID', (0,0), (-1,-1), 0.5, colors.grey),
            ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, colors.HexColor('#f2f3f3')])
        ]))
        elements.append(top_table)
        elements.append(Spacer(1, 0.4 * inch))
        
        # Detailed Breakdown - Consolidated by Resource
        elements.append(Paragraph("Resumen Consolidado de Gastos por Recurso", header_style))
        detail_data = [['Servicio', 'Recurso / Instancia', 'Regiones', 'Costo Total USD']]
        
        for item in agg_data:
            _id = item.get('_id', {})
            name = (_id.get('resource', '').replace('Name$', '') or 'N/A')
            regions_list = item.get('regions', ['N/A'])
            regions_str = ", ".join(regions_list) if isinstance(regions_list, list) else str(regions_list)
            
            detail_data.append([
                Paragraph(_id.get('service', 'N/A'), body_style),
                Paragraph(name, body_style),
                Paragraph(regions_str, body_style),
                Paragraph(f"${item['total_cost']:.2f}", body_bold_style)
            ])
            
        det_table = Table(detail_data, colWidths=[1.8*inch, 3.0*inch, 1.4*inch, 1.3*inch], repeatRows=1)
        det_table.setStyle(TableStyle([
            ('BACKGROUND', (0,0), (-1,0), colors.HexColor('#232f3e')),
            ('TEXTCOLOR', (0,0), (-1,0), colors.white),
            ('ALIGN', (0,0), (-1,0), 'CENTER'),
            ('ALIGN', (-1, 1), (-1, -1), 'RIGHT'),
            ('VALIGN', (0,0), (-1,-1), 'TOP'),
            ('FONTNAME', (0,0), (-1,0), 'Helvetica-Bold'),
            ('FONTSIZE', (0,0), (-1,-1), 9),
            ('BOTTOMPADDING', (0,0), (-1,-1), 8),
            ('TOPPADDING', (0,0), (-1,-1), 8),
            ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, colors.HexColor('#f9f9f9')]),
            ('GRID', (0,0), (-1,-1), 0.2, colors.lightgrey),
        ]))
        elements.append(det_table)
        
        elements.append(Spacer(1, 0.5 * inch))
        elements.append(Paragraph(f"<b>Costo Total Acumulado en el Periodo:</b> ${total_period:.2f} USD", styles['Normal']))
        elements.append(Paragraph("<font size='8' color='grey'>Este reporte representa costos reales aproximados (Unblended) obtenidos de AWS Cost Explorer API.</font>", styles['Normal']))

        doc.build(elements)
        buffer.seek(0)
        
        return send_file(
            buffer,
            mimetype="application/pdf",
            as_attachment=True,
            download_name=f"Reporte_AWS_{alias_cuenta}_{start_date}.pdf"
        )
        
    except Exception as e:
        return jsonify({'message': str(e)}), 500

if __name__ == '__main__':
    app.run(debug=True, port=5000)
