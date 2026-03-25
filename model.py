from flask_sqlalchemy import SQLAlchemy
from datetime import datetime
from werkzeug.security import generate_password_hash, check_password_hash

db = SQLAlchemy()


# ================= USER MODEL =================

class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False)
    password_hash = db.Column(db.String(256), nullable=False)
    role = db.Column(db.String(20), nullable=False)  # 'admin', 'marketing', 'director', 'web'
    display_name = db.Column(db.String(100))
    is_active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

    def __repr__(self):
        return f'<User {self.username} ({self.role})>'


# ================= PRODUCT MODEL =================

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
    
    # Stores pending AI revisions & Director section comments
    revision_data = db.Column(db.JSON)
    
    image_path = db.Column(db.String(200))
    seo_keywords = db.Column(db.String(255))
    
    # Approval & Feedback
    director_pis_comments = db.Column(db.Text)
    director_spec_comments = db.Column(db.Text)
    additional_images = db.Column(db.JSON, default=list)


# ================= PRODUCT HISTORY (EVENT LOG) =================

class ProductHistory(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    product_id = db.Column(db.Integer, db.ForeignKey('product.id'), nullable=False)
    
    actor = db.Column(db.String(50))
    action_title = db.Column(db.String(100))
    description = db.Column(db.Text)
    action_type = db.Column(db.String(20), default='neutral') 
    
    timestamp = db.Column(db.DateTime, default=datetime.utcnow)

    product = db.relationship('Product', backref=db.backref('history', lazy=True, cascade="all, delete"))


# ================= VERSION SNAPSHOTS =================

class ProductVersion(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    product_id = db.Column(db.Integer, db.ForeignKey('product.id'), nullable=False)
    version_num = db.Column(db.Integer, nullable=False)
    
    # Full data snapshots
    pis_data = db.Column(db.JSON)
    spec_data = db.Column(db.JSON)
    revision_data = db.Column(db.JSON)
    workflow_stage = db.Column(db.String(50))
    
    # Metadata
    created_by_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    label = db.Column(db.String(100))  # e.g. "Before Director Review"
    
    product = db.relationship('Product', backref=db.backref('versions', lazy=True, cascade="all, delete"))
    created_by = db.relationship('User', backref='versions')


# ================= FIELD-LEVEL CHANGE LOG =================

class FieldChangeLog(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    product_id = db.Column(db.Integer, db.ForeignKey('product.id'), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True)
    
    field_name = db.Column(db.String(150))   # e.g. "pis_data.header_info.brand"
    old_value = db.Column(db.Text)           # JSON-serialized
    new_value = db.Column(db.Text)           # JSON-serialized
    
    timestamp = db.Column(db.DateTime, default=datetime.utcnow)
    
    product = db.relationship('Product', backref=db.backref('field_changes', lazy=True, cascade="all, delete"))
    user = db.relationship('User', backref='field_changes')