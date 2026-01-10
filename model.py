from flask_sqlalchemy import SQLAlchemy
from datetime import datetime

db = SQLAlchemy()

class Product(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    model_name = db.Column(db.String(100), nullable=False)
    
    # Workflow Stage: 
    # 'marketing_draft', 'pending_director_pis', 'marketing_changes_requested',
    # 'ready_for_web', 'specsheet_draft', 'pending_director_spec', 'web_changes_requested', 'finalized'
    workflow_stage = db.Column(db.String(50), default='marketing_draft')
    
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    # Data Fields
    pis_data = db.Column(db.JSON)       # Stores the PIS structure
    spec_data = db.Column(db.JSON)      # Stores specific SpecSheet styling/SEO data
    
    # --- NEW: Stores pending AI revisions & Director section comments ---
    # Structure: { 'range_overview': {'comment': '...', 'ai_suggestion': '...', 'original': '...'}, ... }
    revision_data = db.Column(db.JSON)
    
    image_path = db.Column(db.String(200))
    seo_keywords = db.Column(db.String(255))
    
    # Approval & Feedback
    director_pis_comments = db.Column(db.Text)      # General Global Comments
    director_spec_comments = db.Column(db.Text)     # Comments on final SpecSheet/SEO
    additional_images = db.Column(db.JSON, default=list)

class ProductHistory(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    product_id = db.Column(db.Integer, db.ForeignKey('product.id'), nullable=False)
    
    actor = db.Column(db.String(50))
    action_title = db.Column(db.String(100))
    description = db.Column(db.Text)
    action_type = db.Column(db.String(20), default='neutral') 
    
    timestamp = db.Column(db.DateTime, default=datetime.utcnow)

    product = db.relationship('Product', backref=db.backref('history', lazy=True, cascade="all, delete"))