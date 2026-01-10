import os
import json
import re
import time
import requests
from bs4 import BeautifulSoup
from flask import Flask, render_template, request, redirect, url_for, Response, stream_with_context, session, flash
from werkzeug.utils import secure_filename
from dotenv import load_dotenv
import google.generativeai as genai
from model import db, Product, ProductHistory
from io import BytesIO
import io
from xhtml2pdf import pisa
from datetime import datetime, timedelta
import fitz  
from PIL import Image
import itertools
import random
import shutil 
from duckduckgo_search import DDGS
from bs4 import BeautifulSoup
from playwright.sync_api import sync_playwright
import base64
from urllib.parse import urlparse

load_dotenv()

app = Flask(__name__)
app.config['SECRET_KEY'] = os.getenv('FLASK_SECRET_KEY', 'default_secret_key')

# --- SINGLE KEY SETUP ---
api_key = os.getenv('GOOGLE_API_KEY')
if not api_key:
    print("Error: GOOGLE_API_KEY not found in .env")
else:
    genai.configure(api_key=api_key)

# Database Config
basedir = os.path.abspath(os.path.dirname(__file__))
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///' + os.path.join(basedir, 'instance', 'pis_system.db')
app.config['UPLOAD_FOLDER'] = 'static/uploads'

db.init_app(app)


# Import utility functions from utils package
from utils.image_processing import (
    extract_domain,
    search_google_api,
    clean_search_query,
    ai_validate_image,
    download_image_bytes,
    find_best_image,
    find_and_validate_image,
    download_web_image
)
from utils.web_scraping import scrape_url_data
from utils.ai_generation import (
    generate_pis_data,
    generate_comprehensive_spec_data,
    generate_bulk_pis_data,
    generate_specsheet_optimization,
    generate_ai_revision
)
from utils.pdf_processing import extract_specific_image
from utils.history import log_event


# ================= ROUTES =================

@app.route('/')
def login():
    return render_template('login.html')

@app.route('/set_role/<role>')
def set_role(role):
    session['role'] = role
    if role == 'marketing': return redirect(url_for('dashboard_marketing'))
    elif role == 'director': return redirect(url_for('dashboard_director'))
    elif role == 'web': return redirect(url_for('dashboard_web'))
    return redirect(url_for('login'))

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))

# --- DASHBOARDS ---

@app.route('/dashboard/marketing')
def dashboard_marketing():
    if session.get('role') != 'marketing': return redirect(url_for('login'))
    
    # 1. Fetch all products (needed for metrics calculation)
    all_products = Product.query.order_by(Product.created_at.desc()).all()
    
    # 2. Filter for Active Pipeline (Not finalized)
    active_pipeline = [p for p in all_products if p.workflow_stage != 'finalized']
    
    # 3. Calculate Real-Time Metrics
    metrics = {
        'total_active': len(active_pipeline),
        'drafts': sum(1 for p in all_products if 'draft' in p.workflow_stage or 'changes_requested' in p.workflow_stage),
        'pending_review': sum(1 for p in all_products if 'pending' in p.workflow_stage),
        'completed': sum(1 for p in all_products if p.workflow_stage == 'finalized')
    }
    
    return render_template('dashboard_marketing.html', 
                         products=active_pipeline, 
                         metrics=metrics)

@app.route('/dashboard/marketing/history')
def history_marketing():
    if session.get('role') != 'marketing': return redirect(url_for('login'))
    
    # Fetch all products ordered by newest first
    all_products = Product.query.order_by(Product.created_at.desc()).all()
    
    # --- SIMULATION BLOCK: GENERATE DEMO PIS TIMELINE DATA ---
    # In a real app, you would query a 'ProductHistory' table here.
    # We are generating this on the fly so the frontend template works.
    products_with_history = []
    
    for p in all_products:
        timeline = []
        
        # 1. Creation Event (Always exists)
        timeline.append({
            'date': p.created_at.strftime('%Y-%m-%d'),
            'time': p.created_at.strftime('%H:%M'),
            'title': 'PIS Draft Created',
            'description': 'Initial product data imported and draft started.',
            'actor': 'Marketing Team',
            'status': 'neutral', # neutral, waiting, action, success
            'icon': 'M11 5H6a2 2 0 00-2 2v11a2 2 0 002 2h11a2 2 0 002-2v-5m-1.414-9.414a2 2 0 112.828 2.828L11.828 15H9v-2.828l8.586-8.586z'
        })

        # 2. Simulate intermediate steps based on current stage
        stage = p.workflow_stage

        if 'pending_director' in stage or 'requested' in stage or 'finalized' in stage:
             timeline.append({
                'date': p.created_at.strftime('%Y-%m-%d'), # Using same date for demo
                'time': (p.created_at + timedelta(hours=2)).strftime('%H:%M'),
                'title': 'Submitted to Director',
                'description': 'PIS draft sent for approval.',
                'actor': 'Marketing Team',
                'status': 'waiting',
                'icon': 'M12 19l9 2-9-18-9 18 9-2zm0 0v-8'
            })

        if 'changes_requested' in stage and p.director_pis_comments:
             timeline.append({
                'date': p.created_at.strftime('%Y-%m-%d'),
                'time': (p.created_at + timedelta(hours=4)).strftime('%H:%M'),
                'title': 'Changes Requested by Director',
                'description': f'Feedback: "{p.director_pis_comments}"',
                'actor': 'Director',
                'status': 'action',
                'icon': 'M12 8v4m0 4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z'
            })

        # 3. Final PIS Approval State
        # We check if it passed the PIS stage. 'finalized', 'ready_for_web', 'specsheet_draft' etc mean PIS is done.
        pis_approved_stages = ['ready_for_web', 'specsheet_draft', 'pending_director_spec', 'web_changes_requested', 'finalized']
        if any(s in stage for s in pis_approved_stages):
             timeline.append({
                'date': p.created_at.strftime('%Y-%m-%d'),
                'time': (p.created_at + timedelta(days=1)).strftime('%H:%M'),
                'title': 'PIS Approved',
                'description': 'Director approved the product information sheet.',
                'actor': 'Director',
                'status': 'success',
                'icon': 'M9 12l2 2 4-4m6 2a9 9 0 11-18 0 9 9 0 0118 0z'
            })

        # Determine current PIS status label for the main table
        current_pis_status = 'Draft'
        if 'pending_director_pis' in stage: current_pis_status = 'Pending Review'
        elif 'marketing_changes_requested' in stage: current_pis_status = 'Changes Requested'
        elif any(s in stage for s in pis_approved_stages): current_pis_status = 'Approved'

        products_with_history.append({
            'product': p,
            'pis_status': current_pis_status,
            # Reverse timeline so newest event is at top
            'timeline': timeline[::-1] 
        })

    # In production, you would pass the ID and fetch timeline via AJAX call instead of dumping it all here.
    # We dump it here for the demo to work without extra API routes.
    import json
    def default_converter(o):
        if isinstance(o, datetime): return o.strftime("%Y-%m-%d %H:%M:%S")
        return o.__dict__

    # We need to serialize this data so Alpine.js can use it
    products_json = json.dumps([{
        'id': item['product'].id,
        'model_name': item['product'].model_name,
        'brand': item['product'].pis_data.get('header_info', {}).get('brand', 'Unknown') if item['product'].pis_data else 'Unknown',
        'image_path': url_for('static', filename=item['product'].image_path) if item['product'].image_path else None,
        'pis_status': item['pis_status'],
        'created_date': item['product'].created_at.strftime('%Y-%m-%d'),
        'timeline': item['timeline']
    } for item in products_with_history])
    
    return render_template('history_marketing.html', products_json=products_json)


@app.route('/dashboard/director')
def dashboard_director():
    if session.get('role') != 'director': return redirect(url_for('login'))
    
    # 1. Fetch Action Items
    pending_pis = Product.query.filter_by(workflow_stage='pending_director_pis').all()
    pending_spec = Product.query.filter_by(workflow_stage='pending_director_spec').all()
    
    # 2. Fetch All Products for Metrics (keep complete list for dashboard stats)
    all_products = Product.query.order_by(Product.created_at.desc()).all()
    
    # 3. Calculate Metrics
    metrics = {
        'total_products': len(all_products),
        'pending_reviews': len(pending_pis) + len(pending_spec),
        'finalized': sum(1 for p in all_products if p.workflow_stage == 'finalized'),
        'in_progress': sum(1 for p in all_products if p.workflow_stage not in ['finalized', 'ready_for_web'])
    }
    
    return render_template('dashboard_director.html', 
                         pending_pis=pending_pis, 
                         pending_spec=pending_spec,
                         all_products=all_products,
                         metrics=metrics)

@app.route('/dashboard/director/archive')
def director_archive():
    if session.get('role') != 'director': return redirect(url_for('login'))
    
    # Fetch only finalized/approved products for the archive
    # Stages: 'finalized' (Spec approved) or 'ready_for_web' (PIS approved but Spec pending, technically has PIS PDF)
    # Adjust list based on strictness. Here we show anything that has at least passed PIS approval.
    approved_stages = ['finalized', 'ready_for_web', 'specsheet_draft', 'pending_director_spec', 'web_changes_requested']
    archived_products = Product.query.filter(Product.workflow_stage.in_(approved_stages)).order_by(Product.created_at.desc()).all()
    
    return render_template('archive_director.html', products=archived_products)

@app.route('/dashboard/web')
def dashboard_web():
    # ---- ACCESS CONTROL ----
    if session.get('role') != 'web':
        return redirect(url_for('login'))

    # ---- FETCH TASKS FOR WEB TEAM ----
    tasks = (
        Product.query
        .filter(Product.workflow_stage.in_([
            'ready_for_web',
            'web_changes_requested',
            'specsheet_draft'
        ]))
        .order_by(Product.created_at.desc())
        .all()
    )

    # ---- BUILD JSON-SAFE PRODUCT PAYLOAD (CRITICAL FIX) ----
    products_json = []
    for p in tasks:
        products_json.append({
            "id": p.id,
            "model_name": p.model_name or "",
            "brand": (
                p.pis_data.get("header_info", {}).get("brand", "Unknown")
                if p.pis_data else "Unknown"
            ),
            "image": (
                url_for("static", filename=p.image_path)
                if p.image_path else ""
            ),
            "date": p.created_at.strftime("%d %b"),
            "stage": p.workflow_stage,
            "action_url": url_for("create_specsheet", product_id=p.id)
        })

    # ---- METRICS (SERVER-SIDE, TRUSTED) ----
    metrics = {
        "total_tasks": len(tasks),
        "new_pis": sum(1 for p in tasks if p.workflow_stage == "ready_for_web"),
        "changes_requested": sum(1 for p in tasks if p.workflow_stage == "web_changes_requested"),
        "drafts": sum(1 for p in tasks if p.workflow_stage == "specsheet_draft"),
    }

    # ---- RENDER DASHBOARD ----
    return render_template(
        "dashboard_web.html",
        tasks=tasks,                 # used only for metrics/debug
        products_json=products_json, # used by Alpine (IMPORTANT)
        metrics=metrics
    )



@app.route('/dashboard/web/archive')
def web_archive():
    if session.get('role') != 'web': return redirect(url_for('login'))
    
    # Fetch finalized products that have completed the full SpecSheet cycle
    finalized_products = Product.query.filter_by(workflow_stage='finalized').order_by(Product.created_at.desc()).all()
    
    return render_template('archive_web.html', products=finalized_products)


@app.route('/create', methods=['GET', 'POST'])
def create_pis():
    if request.method == 'GET':
        return render_template('create.html')
    
    if request.method == 'POST':
        model_name = request.form.get('model_name')
        supplier_url = request.form.get('supplier_url')
        ai_file = request.files.get('ai_document')
        
        # --- NEW: Capture toggle value ---
        # Toggle is 'on' if checked, otherwise None
        contains_images = request.form.get('contains_images') == 'on'
        
        ai_filepath = None
        if ai_file:
            filename = secure_filename(ai_file.filename)
            ai_filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
            ai_file.save(ai_filepath)

        def generate_updates():
            yield json.dumps({"progress": 10, "message": "Initializing Analysis..."}) + "\n"
            
            site_data = {"text": "", "html": ""}
            if supplier_url:
                yield json.dumps({"progress": 20, "message": "Reading Website Text..."}) + "\n"
                site_data = scrape_url_data(supplier_url)

            yield json.dumps({"progress": 40, "message": "Generating PIS Content..."}) + "\n"
            try:
                ai_data = generate_pis_data(ai_filepath, model_name, site_data)
                
                extracted_image_path = None
                
                yield json.dumps({"progress": 60, "message": "Searching Google Images..."}) + "\n"
                
                header = ai_data.get('header_info', {})
                brand = header.get('brand', '')
                m_num = header.get('model_number', '')
                p_name = header.get('product_name', '')
                
                q_parts = []
                if brand: q_parts.append(brand)
                if p_name: q_parts.append(p_name)
                
                if m_num and (any(c.isalpha() for c in m_num) or '-' in m_num):
                    if m_num not in (p_name or ''):
                        q_parts.append(m_num)
                        
                full_str = " ".join(q_parts)
                unique_words = []
                [unique_words.append(x) for x in full_str.split() if x.lower() not in [y.lower() for y in unique_words]]
                rich_query = " ".join(unique_words)
                
                if not rich_query: rich_query = model_name

                # Execute Google Search
                public_url = find_and_validate_image(rich_query, supplier_url)

                
                if public_url:
                    yield json.dumps({"progress": 70, "message": "Downloading Image..."}) + "\n"
                    extracted_image_path = download_web_image(public_url, model_name, app.config['UPLOAD_FOLDER'])

                # --- UPDATED Fallback: PDF Scan based on Toggle ---
                if not extracted_image_path and ai_filepath and contains_images:
                    yield json.dumps({"progress": 80, "message": "Google failed. Scanning PDF..."}) + "\n"
                    extracted_image_path = extract_specific_image(ai_filepath, model_name, app.config['UPLOAD_FOLDER'])

                if extracted_image_path:
                    yield json.dumps({"progress": 90, "message": "Visual Acquired."}) + "\n"
                else:
                    yield json.dumps({"progress": 90, "message": "No visual found."}) + "\n"

                with app.app_context():
                    new_product = Product(
                        model_name=model_name, 
                        pis_data=ai_data,
                        image_path=extracted_image_path,
                        seo_keywords=ai_data.get('seo_data', {}).get('generated_keywords', ''),
                        workflow_stage='marketing_draft'
                    )
                    db.session.add(new_product)
                    db.session.commit()
                    log_event(new_product.id, 'Marketing Team', 'PIS Draft Created', 'Created via Single Import.', 'neutral')
                    
                    yield json.dumps({"progress": 100, "message": "Done!", "redirect": url_for('review_pis_marketing', product_id=new_product.id)}) + "\n"

            except Exception as e:
                yield json.dumps({"error": str(e)}) + "\n"

        return Response(stream_with_context(generate_updates()), mimetype='application/x-ndjson')
    



@app.route('/create_bulk', methods=['GET', 'POST'])
def create_bulk():
    if request.method == 'GET':
        return render_template('create_bulk.html')

    if request.method == 'POST':
        supplier_url = request.form.get('supplier_url')
        ai_file = request.files.get('ai_document')
        
        # --- NEW: Capture toggle value ---
        contains_images = request.form.get('contains_images') == 'on'
        
        if not ai_file: return "No file uploaded", 400

        filename = secure_filename(ai_file.filename)
        ai_filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
        ai_file.save(ai_filepath)

        def generate_bulk_updates():
            yield json.dumps({"progress": 10, "message": "Analyzing Invoice..."}) + "\n"
            
            site_data = {"text": "", "html": ""}
            if supplier_url:
                site_data = scrape_url_data(supplier_url)
            
            try:
                products_list = generate_bulk_pis_data(ai_filepath, site_data)
                total_items = len(products_list)
                yield json.dumps({"progress": 20, "message": f"Found {total_items} items. Starting Google Search..."}) + "\n"

                with app.app_context():
                    processed_count = 0
                    for idx, p_data in enumerate(products_list):
                        header = p_data.get('header_info', {})
                        brand = header.get('brand', '')
                        model_id = header.get('model_number', '') 
                        prod_name = header.get('product_name', '')
                        
                        display_name = prod_name if prod_name else (model_id if model_id else f"Item_{idx+1}")
                        
                        processed_count += 1
                        current_progress = 20 + int((processed_count / total_items) * 75) 
                        
                        query_parts = []
                        if brand: query_parts.append(brand)
                        if prod_name: query_parts.append(prod_name)
                        
                        is_real_model = model_id and (any(c.isalpha() for c in model_id) or '-' in model_id)
                        if is_real_model and (model_id not in (prod_name or '')):
                            query_parts.append(model_id)

                        seen_words = set()
                        unique_words = []
                        for w in " ".join(query_parts).split():
                            if w.lower() not in seen_words:
                                unique_words.append(w)
                                seen_words.add(w.lower())
                        
                        search_query = " ".join(unique_words) if unique_words else display_name
                        
                        yield json.dumps({"progress": current_progress, "message": f"Searching: {search_query}"}) + "\n"

                        # Primary Search: Google
                        image_url = find_and_validate_image(search_query, supplier_url)

                        extracted_image_path = None
                        if image_url:
                            extracted_image_path = download_web_image(image_url, display_name, app.config['UPLOAD_FOLDER'])

                        # --- UPDATED Fallback: PDF Scan based on Toggle ---
                        if not extracted_image_path and contains_images:
                             extracted_image_path = extract_specific_image(ai_filepath, model_id, app.config['UPLOAD_FOLDER'])

                        new_product = Product(
                            model_name=display_name,
                            pis_data=p_data,
                            image_path=extracted_image_path, 
                            seo_keywords=p_data.get('seo_data', {}).get('generated_keywords', ''),
                            workflow_stage='marketing_draft'
                        )
                        db.session.add(new_product)
                        db.session.commit()
                        log_event(new_product.id, 'Marketing Team', 'PIS Draft Created', 'Imported via Bulk Tool.', 'neutral')

                yield json.dumps({"progress": 100, "message": "Bulk Import Complete!", "redirect": url_for('dashboard_marketing')}) + "\n"
            
            except Exception as e:
                yield json.dumps({"error": str(e)}) + "\n"

        return Response(stream_with_context(generate_bulk_updates()), mimetype='application/x-ndjson')

# --- Compatibility Route ---
@app.route('/verify/<int:product_id>')
def old_verify_redirect(product_id):
    return redirect(url_for('review_pis_marketing', product_id=product_id))

# --- REVIEW ROUTES ---
@app.route('/review/marketing/<int:product_id>', methods=['GET', 'POST'])
def review_pis_marketing(product_id):
    product = Product.query.get_or_404(product_id)
    
    if request.method == 'POST':
        updated_data = product.pis_data or {}
        
        if 'header_info' not in updated_data: updated_data['header_info'] = {}
        updated_data['header_info']['product_name'] = request.form.get('product_name')
        updated_data['header_info']['model_number'] = request.form.get('model_number')
        updated_data['header_info']['brand'] = request.form.get('brand')
        updated_data['header_info']['price_estimate'] = request.form.get('price_estimate')
        
        updated_data['range_overview'] = request.form.get('range_overview')
        updated_data['sales_arguments'] = request.form.getlist('sales_arguments')
        
        spec_names = request.form.getlist('spec_name')
        spec_values = request.form.getlist('spec_value')
        updated_data['technical_specifications'] = dict(zip(spec_names, spec_values))
        
        if 'warranty_service' not in updated_data: updated_data['warranty_service'] = {}
        updated_data['warranty_service']['period'] = request.form.get('warranty_period')
        updated_data['warranty_service']['coverage'] = request.form.get('warranty_coverage')
        
        product.pis_data = updated_data
        
        # CRITICAL: Flag the JSON field as modified so SQLAlchemy saves it
        from sqlalchemy.orm.attributes import flag_modified
        flag_modified(product, 'pis_data')
        
        if request.form.get('action') == 'submit_director':
            product.workflow_stage = 'pending_director_pis'
            log_event(product.id, 'Marketing Team', 'Submitted to Director', 'PIS draft submitted for review.', 'waiting')
            flash("Submitted to Director")
        else:
            log_event(product.id, 'Marketing Team', 'Draft Updated', 'Marketing team saved changes.', 'neutral')
            flash("Draft Saved")
            
        db.session.commit()
        return redirect(url_for('dashboard_marketing'))
        
    return render_template('verify_marketing.html', product=product, data=product.pis_data)


@app.route('/review/director_pis/<int:product_id>', methods=['GET', 'POST'])
def review_director_pis(product_id):
    product = Product.query.get_or_404(product_id)
    if request.method == 'POST':
        action = request.form.get('director_action')
        
        # --- NEW: Handle director field edits before approval/review ---
        updated_data = product.pis_data or {}
        
        # Update Header Info if edited
        if request.form.get('product_name'):
            if 'header_info' not in updated_data: updated_data['header_info'] = {}
            updated_data['header_info']['product_name'] = request.form.get('product_name')
            updated_data['header_info']['model_number'] = request.form.get('model_number')
            updated_data['header_info']['brand'] = request.form.get('brand')
            updated_data['header_info']['price_estimate'] = request.form.get('price_estimate')
        
        # Update Range Overview if edited
        if request.form.get('range_overview'):
            updated_data['range_overview'] = request.form.get('range_overview')
        
        # Update Sales Arguments if edited
        sales_args = request.form.getlist('sales_argument')
        if sales_args and any(arg.strip() for arg in sales_args):
            updated_data['sales_arguments'] = [arg.strip() for arg in sales_args if arg.strip()]
        
        # Update Technical Specifications if edited
        tech_spec_keys = request.form.getlist('tech_spec_key')
        tech_spec_values = request.form.getlist('tech_spec_value')
        if tech_spec_keys and tech_spec_values:
            updated_data['technical_specifications'] = dict(zip(tech_spec_keys, tech_spec_values))
        
        # Update Warranty if edited
        if request.form.get('warranty_period'):
            if 'warranty_service' not in updated_data: updated_data['warranty_service'] = {}
            updated_data['warranty_service']['period'] = request.form.get('warranty_period')
            updated_data['warranty_service']['coverage'] = request.form.get('warranty_coverage')
        
        # Save updated data
        product.pis_data = updated_data
        
        # CRITICAL: Flag the JSON field as modified so SQLAlchemy saves it
        from sqlalchemy.orm.attributes import flag_modified
        flag_modified(product, 'pis_data')
        
        if action == 'review':
            # Updated Map with ALL sections
            comments_map = {
                'header_info': request.form.get('comment_header_info'),
                'range_overview': request.form.get('comment_range_overview'),
                'sales_arguments': request.form.get('comment_sales_arguments'),
                'technical_specifications': request.form.get('comment_technical_specifications'),
                'warranty_service': request.form.get('comment_warranty_service')
            }
            
            new_revisions = {}
            
            for section, comment in comments_map.items():
                if comment and comment.strip():
                    # Get Original Content
                    original = product.pis_data.get(section)
                    
                    # Call AI
                    ai_suggestion = generate_ai_revision(section, original, comment)
                    
                    # Store
                    new_revisions[section] = {
                        'comment': comment,
                        'original': original,
                        'ai_suggestion': ai_suggestion,
                        'status': 'pending'
                    }
            
            product.revision_data = new_revisions
            product.director_pis_comments = request.form.get('director_general_comments')
            product.workflow_stage = 'marketing_changes_requested'
            
            log_desc = f"Director requested changes on {len(new_revisions)} sections."
            log_event(product.id, 'Director', 'Changes Requested', log_desc, 'action')

        elif action == 'approve':
            print("\n" + "="*80)
            print("📋 DIRECTOR APPROVED PIS - GENERATING SPECSHEET")
            print("="*80)
            
            # --- Generate comprehensive specsheet data with AI (includes categories) ---
            try:
                print("🤖 Calling generate_comprehensive_spec_data()...")
                spec_data_generated = generate_comprehensive_spec_data(product.pis_data)
                
                # Add technical specifications from PIS
                spec_data_generated['technical_specifications'] = product.pis_data.get('technical_specifications', {})
                
                product.spec_data = spec_data_generated
                print(f"✅ SpecSheet data generated successfully")
                print(f"   - Has categories: {'categories' in spec_data_generated}")
                if 'categories' in spec_data_generated:
                    print(f"   - Categories: {spec_data_generated['categories']}")
                
            except Exception as e:
                print(f"❌ ERROR generating specsheet data: {e}")
                import traceback
                traceback.print_exc()
                
                # Fallback to basic spec_data
                print("⚠️ Using fallback spec_data creation...")
                initial_spec_data = {
                    'customer_friendly_description': product.pis_data.get('seo_data', {}).get('seo_long_description', ''),
                    'refined_description': product.pis_data.get('seo_data', {}).get('seo_long_description', ''),
                    'key_features': product.pis_data.get('sales_arguments', []),
                    'long_tail_keywords': '',
                    'seo': {
                        'meta_title': product.pis_data.get('seo_data', {}).get('meta_title', ''),
                        'meta_description': product.pis_data.get('seo_data', {}).get('meta_description', ''),
                        'keywords': product.pis_data.get('seo_data', {}).get('generated_keywords', '')
                    },
                    'categories': {
                        'category_1': 'Home & Garden',
                        'category_2': 'Home Deco',
                        'category_3': 'Lighting'
                    }
                }
                product.spec_data = initial_spec_data
            
            print("="*80 + "\n")
            
            product.workflow_stage = 'ready_for_web'
            product.revision_data = None
            log_event(product.id, 'Director', 'PIS Approved', 'Director approved the PIS content and initialized Specsheet.', 'success')
            
        db.session.commit()
        return redirect(url_for('dashboard_director'))
        
    return render_template('verify_director_pis.html', product=product, data=product.pis_data)


@app.route('/create_specsheet/<int:product_id>', methods=['GET', 'POST'])
def create_specsheet(product_id):
    product = Product.query.get_or_404(product_id)
    
    # Initialize spec_data if it doesn't exist (first time viewing)
    if not product.spec_data or not product.spec_data.get('key_features'):
        # Use PIS sales_arguments as initial key_features
        initial_spec_data = {
            'customer_friendly_description': product.pis_data.get('seo_data', {}).get('seo_long_description', ''),
            'key_features': product.pis_data.get('sales_arguments', []),
            'seo': {
                'meta_title': product.pis_data.get('seo_data', {}).get('meta_title', ''),
                'meta_description': product.pis_data.get('seo_data', {}).get('meta_description', ''),
                'keywords': product.pis_data.get('seo_data', {}).get('generated_keywords', '')
            }
        }
        product.spec_data = initial_spec_data
        db.session.commit()
    
    # HARD GUARANTEE: Validate key_features is always a valid list
    if (
        not product.spec_data.get("key_features")
        or not isinstance(product.spec_data["key_features"], list)
        or len(product.spec_data["key_features"]) == 0
    ):
        product.spec_data["key_features"] = product.pis_data.get("sales_arguments", [])
        db.session.commit()
    
    if request.method == 'POST':
        if request.form.get('action') == 'submit_director':
            product.workflow_stage = 'pending_director_spec'
            log_event(product.id, 'Web Team', 'Submitted SpecSheet', 'SpecSheet submitted to Director.', 'waiting')
        
        # Save edits to spec data
        spec_data = product.spec_data or {}
        
        # Save New Fields
        spec_data['customer_friendly_description'] = request.form.get('customer_friendly_description')
        
        # Save Key Features (handle as list)
        features_raw = request.form.getlist('key_features')
        spec_data['key_features'] = [f.strip() for f in features_raw if f.strip()]
        
        # Save SEO Data
        if 'seo' not in spec_data: spec_data['seo'] = {}
        spec_data['seo']['meta_title'] = request.form.get('seo_meta_title')
        spec_data['seo']['meta_description'] = request.form.get('seo_meta_description')
        spec_data['seo']['keywords'] = request.form.get('seo_keywords')
        
        # Save Categories
        if request.form.get('category_1'):
            if 'categories' not in spec_data:
                spec_data['categories'] = {}
            spec_data['categories']['category_1'] = request.form.get('category_1')
            spec_data['categories']['category_2'] = request.form.get('category_2')
            spec_data['categories']['category_3'] = request.form.get('category_3')
        
        # Save Technical Specifications (from JSON)
        tech_specs_json = request.form.get('technical_specifications')
        if tech_specs_json:
            try:
                spec_data['technical_specifications'] = json.loads(tech_specs_json)
            except:
                # Fallback to PIS data if JSON parse fails
                spec_data['technical_specifications'] = product.pis_data.get('technical_specifications', {})

        product.spec_data = spec_data
        
        # CRITICAL: Flag the JSON field as modified so SQLAlchemy saves it
        from sqlalchemy.orm.attributes import flag_modified
        flag_modified(product, 'spec_data')
        
        db.session.commit()
        return redirect(url_for('dashboard_web'))
        
    return render_template('edit_specsheet.html', product=product, spec_data=product.spec_data or {})



@app.route('/review/director_spec/<int:product_id>', methods=['GET', 'POST'])
def review_director_spec(product_id):
    product = Product.query.get_or_404(product_id)
    
    if request.method == 'POST':
        action = request.form.get('director_action')
        
        # --- NEW: Handle director field edits before approval/review ---
        updated_pis_data = product.pis_data or {}
        updated_spec_data = product.spec_data or {}
        
        # Update Header Info if edited (from PIS data)
        if request.form.get('product_name'):
            if 'header_info' not in updated_pis_data: updated_pis_data['header_info'] = {}
            updated_pis_data['header_info']['product_name'] = request.form.get('product_name')
            updated_pis_data['header_info']['model_number'] = request.form.get('model_number')
            updated_pis_data['header_info']['brand'] = request.form.get('brand')
            updated_pis_data['header_info']['price_estimate'] = request.form.get('price_estimate')
        
        # Update Range Overview if edited
        if request.form.get('range_overview'):
            updated_pis_data['range_overview'] = request.form.get('range_overview')
        
        # Update Sales Arguments if edited
        sales_args = request.form.getlist('sales_argument')
        if sales_args and any(arg.strip() for arg in sales_args):
            updated_pis_data['sales_arguments'] = [arg.strip() for arg in sales_args if arg.strip()]
        
        # Update Technical Specifications if edited
        tech_spec_keys = request.form.getlist('tech_spec_key')
        tech_spec_values = request.form.getlist('tech_spec_value')
        if tech_spec_keys and tech_spec_values:
            updated_pis_data['technical_specifications'] = dict(zip(tech_spec_keys, tech_spec_values))
        
        # Update Warranty if edited
        if request.form.get('warranty_period'):
            if 'warranty_service' not in updated_pis_data: updated_pis_data['warranty_service'] = {}
            updated_pis_data['warranty_service']['period'] = request.form.get('warranty_period')
            updated_pis_data['warranty_service']['coverage'] = request.form.get('warranty_coverage')
        
        # Update SpecSheet-specific fields
        if request.form.get('refined_description'):
            updated_spec_data['refined_description'] = request.form.get('refined_description')
            updated_spec_data['customer_friendly_description'] = request.form.get('refined_description')
        
        # Update SEO Keywords if edited
        if request.form.get('seo_keywords'):
            product.seo_keywords = request.form.get('seo_keywords')
        
        # Update Categories if edited
        if request.form.get('category_1'):
            if 'categories' not in updated_spec_data:
                updated_spec_data['categories'] = {}
            updated_spec_data['categories']['category_1'] = request.form.get('category_1')
            updated_spec_data['categories']['category_2'] = request.form.get('category_2')
            updated_spec_data['categories']['category_3'] = request.form.get('category_3')
        
        # Save updated data
        product.pis_data = updated_pis_data
        product.spec_data = updated_spec_data
        
        # CRITICAL: Flag the JSON fields as modified so SQLAlchemy saves them
        from sqlalchemy.orm.attributes import flag_modified
        flag_modified(product, 'pis_data')
        flag_modified(product, 'spec_data')
        
        if action == 'review':
            # Section-specific comments map
            comments_map = {
                'seo_optimization': request.form.get('comment_seo_optimization'),
                'header_info': request.form.get('comment_header_info'),
                'range_overview': request.form.get('comment_range_overview'),
                'sales_arguments': request.form.get('comment_sales_arguments'),
                'technical_specifications': request.form.get('comment_technical_specifications'),
                'warranty_service': request.form.get('comment_warranty_service')
            }
            
            new_revisions = {}
            
            for section, comment in comments_map.items():
                if comment and comment.strip():
                    # Get original content based on section
                    if section == 'seo_optimization':
                        # For SEO, we use spec_data content
                        original = product.spec_data.get('customer_friendly_description') if product.spec_data else ''
                    else:
                        # For other sections, use PIS data
                        original = product.pis_data.get(section)
                    
                    # Generate AI suggestion
                    ai_suggestion = generate_ai_revision(section, original, comment)
                    
                    # Store revision
                    new_revisions[section] = {
                        'comment': comment,
                        'original': original,
                        'ai_suggestion': ai_suggestion,
                        'status': 'pending'
                    }
            
            # Store in spec_revision_data (reusing revision_data field)
            product.revision_data = new_revisions
            
            # Store general comments
            general_comments = request.form.get('director_general_comments')
            product.director_spec_comments = general_comments
            
            product.workflow_stage = 'web_changes_requested'
            
            log_desc = f"Director requested SpecSheet changes on {len(new_revisions)} sections."
            log_event(product.id, 'Director', 'SpecSheet Changes Requested', log_desc, 'action')
            
        elif action == 'approve':
            product.workflow_stage = 'finalized'
            product.revision_data = None
            log_event(
                product.id, 
                'Director', 
                'SpecSheet Finalized', 
                'Final PDF design and SEO keywords approved. Workflow complete.', 
                'success'
            )
            
        db.session.commit()
        return redirect(url_for('dashboard_director'))
        
    return render_template('verify_specsheet.html', product=product, spec_data=product.spec_data)

# --- NEW ROUTE: Marketing PIS PDF Download ---
@app.route('/download_pis_pdf/<int:product_id>')
def download_pis_pdf(product_id):
    product = Product.query.get_or_404(product_id)
    
    # 1. Process Image to Base64 (Best for Playwright rendering)
    image_b64 = None
    if product.image_path:
        try:
            # Construct absolute path
            img_abs_path = os.path.join(app.root_path, 'static', product.image_path.replace('/', os.sep))
            
            if os.path.exists(img_abs_path):
                with open(img_abs_path, "rb") as img_file:
                    # Determine extension
                    ext = os.path.splitext(img_abs_path)[1].lower().replace('.', '')
                    if ext == 'jpg': ext = 'jpeg'
                    
                    # Encode
                    b64_data = base64.b64encode(img_file.read()).decode('utf-8')
                    image_b64 = f"data:image/{ext};base64,{b64_data}"
        except Exception as e:
            print(f"Image processing error: {e}")
            image_b64 = None

    # 2. Render HTML Template
    html = render_template('pdf_print.html', 
                           data=product.pis_data, 
                           product=product, 
                           image_b64=image_b64, # Pass Base64 string instead of path
                           date_generated=datetime.now().strftime("%Y-%m-%d"))
    
    # 3. Generate PDF using Playwright
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page()
            
            # Load HTML content
            page.set_content(html)
            
            # Generate PDF (A4, print background graphics)
            pdf_bytes = page.pdf(
                format="A4",
                print_background=True,
                margin={"top": "15mm", "right": "15mm", "bottom": "15mm", "left": "15mm"}
            )
            browser.close()
            
        return Response(pdf_bytes, mimetype='application/pdf', 
                        headers={"Content-Disposition": f"attachment;filename=PIS_{secure_filename(product.model_name)}.pdf"})
                        
    except Exception as e:
        return f"Error generating PDF with Playwright: {str(e)}"
    
@app.route('/download_specsheet/<int:product_id>')
def download_specsheet(product_id):
    product = Product.query.get_or_404(product_id)
    
    # 1. Process Image to Base64 (Same logic as PIS for consistency)
    image_b64 = None
    if product.image_path:
        try:
            img_abs_path = os.path.join(app.root_path, 'static', product.image_path.replace('/', os.sep))
            if os.path.exists(img_abs_path):
                with open(img_abs_path, "rb") as img_file:
                    ext = os.path.splitext(img_abs_path)[1].lower().replace('.', '')
                    if ext == 'jpg': ext = 'jpeg'
                    b64_data = base64.b64encode(img_file.read()).decode('utf-8')
                    image_b64 = f"data:image/{ext};base64,{b64_data}"
        except Exception as e:
            print(f"Image error: {e}")

    # 2. Render Template
    html = render_template('specsheet_pdf.html', 
                           data=product.pis_data, 
                           spec_data=product.spec_data or {}, 
                           product=product, 
                           image_b64=image_b64, 
                           date_generated=datetime.now().strftime("%Y-%m-%d"))

    # 3. Generate with Playwright
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page()
            page.set_content(html)
            pdf_bytes = page.pdf(
                format="A4", 
                print_background=True, 
                margin={"top": "15mm", "right": "15mm", "bottom": "15mm", "left": "15mm"}
            )
            browser.close()
        return Response(pdf_bytes, mimetype='application/pdf', headers={"Content-Disposition": f"attachment;filename=SpecSheet_{secure_filename(product.model_name)}.pdf"})
    except Exception as e:
        print(f"SpecSheet PDF Error: {e}")
        return f"Error generating PDF: {e}"


@app.route('/retry_revision/<int:product_id>/<section>', methods=['POST'])
def retry_revision(product_id, section):
    product = Product.query.get_or_404(product_id)

    if not product.revision_data or section not in product.revision_data:
        return {"error": "No revision data"}, 400

    revision = product.revision_data[section]

    original_content = revision.get("original")
    director_comment = revision.get("comment")

    new_ai_suggestion = generate_ai_revision(
        section_name=section,
        original_content=original_content,
        director_comment=director_comment
    )

    # Update only the AI suggestion
    product.revision_data[section]["ai_suggestion"] = new_ai_suggestion

    db.session.commit()

    return {
        "ai_suggestion": new_ai_suggestion
    }


@app.route('/api/product/<int:product_id>/images/upload', methods=['POST'])
def api_upload_image(product_id):
    product = Product.query.get_or_404(product_id)
    if 'file' not in request.files:
        return {"error": "No file provided"}, 400
    
    file = request.files['file']
    if file.filename == '':
        return {"error": "No file selected"}, 400
        
    try:
        filename = secure_filename(f"extra_{product.id}_{int(time.time())}_{file.filename}")
        save_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
        file.save(save_path)
        db_path = f"uploads/{filename}"
        
        # Logic: If main image is empty, fill it. Otherwise, add to additional_images.
        if not product.image_path:
            product.image_path = db_path
            is_main = True
        else:
            imgs = list(product.additional_images) if product.additional_images else []
            imgs.append(db_path)
            product.additional_images = imgs
            is_main = False
            
        db.session.commit()
        return {"status": "success", "path": db_path, "is_main": is_main}
        
    except Exception as e:
        return {"error": str(e)}, 500

@app.route('/api/product/<int:product_id>/images/delete', methods=['POST'])
def api_delete_image(product_id):
    product = Product.query.get_or_404(product_id)
    data = request.get_json()
    path_to_delete = data.get('path')
    
    if not path_to_delete:
        return {"error": "No path provided"}, 400

    try:
        # Check if it's the main image
        if product.image_path == path_to_delete:
            product.image_path = None
            # Optional: Promote the first additional image to main if exists
            imgs = list(product.additional_images) if product.additional_images else []
            if imgs:
                product.image_path = imgs.pop(0)
                product.additional_images = imgs
        else:
            # Check additional images
            imgs = list(product.additional_images) if product.additional_images else []
            if path_to_delete in imgs:
                imgs.remove(path_to_delete)
                product.additional_images = imgs
        
        db.session.commit()
        return {"status": "success"}
        
    except Exception as e:
        return {"error": str(e)}, 500



# --- NEW: SpecSheet AI Generation API ---
@app.route('/api/generate_specsheet/<int:product_id>', methods=['POST'])
def api_generate_specsheet(product_id):
    product = Product.query.get_or_404(product_id)
    
    def generate():
        yield json.dumps({"progress": 20, "message": "Analyzing PIS Data..."}) + "\n"
        time.sleep(0.5) # UI visual pacing
        
        yield json.dumps({"progress": 50, "message": "Rewriting Customer Content..."}) + "\n"
        
        try:
            # Generate comprehensive content
            spec_data = generate_comprehensive_spec_data(product.pis_data)
            
            yield json.dumps({"progress": 80, "message": "Optimizing SEO Metadata..."}) + "\n"
            
            with app.app_context():
                # Re-fetch to ensure session context
                p = Product.query.get(product_id)
                p.spec_data = spec_data
                p.workflow_stage = 'specsheet_draft'
                db.session.commit()
                log_event(p.id, 'Web Team', 'SpecSheet Generated', 'AI generated customer-facing content and SEO data.', 'neutral')
            
            yield json.dumps({"progress": 100, "message": "Generation Complete!", "redirect": url_for('create_specsheet', product_id=product.id)}) + "\n"
            
        except Exception as e:
            print(f"Error: {e}")
            yield json.dumps({"error": "AI Generation Failed. Please try again."}) + "\n"

    return Response(stream_with_context(generate()), mimetype='application/x-ndjson')


if __name__ == '__main__':
    with app.app_context():
        if not os.path.exists('instance'): os.makedirs('instance')
        db.create_all()
        if not os.path.exists(app.config['UPLOAD_FOLDER']): os.makedirs(app.config['UPLOAD_FOLDER'])
    app.run(debug=False)