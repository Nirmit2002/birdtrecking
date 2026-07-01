"""
Database models for White Stork Migration Visualiser.
Uses SQLAlchemy ORM with MySQL backend (PyMySQL driver).
Connection: mysql+pymysql://stork_user:stork_pass2024@localhost/stork_db
"""

from flask_sqlalchemy import SQLAlchemy
from flask_bcrypt import Bcrypt
from flask_login import UserMixin
from datetime import datetime

db = SQLAlchemy()
bcrypt = Bcrypt()


class User(UserMixin, db.Model):
    """Registered system user — either admin or researcher role."""
    __tablename__ = 'users'

    id         = db.Column(db.Integer, primary_key=True)
    username   = db.Column(db.String(80), unique=True, nullable=False)
    email      = db.Column(db.String(120), unique=True, nullable=False)
    password   = db.Column(db.String(255), nullable=False)
    role       = db.Column(db.String(20), default='researcher')   # 'admin' | 'researcher'
    full_name  = db.Column(db.String(120), default='')
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    last_login = db.Column(db.DateTime, nullable=True)

    uploads = db.relationship('UploadedFile', backref='uploader', lazy=True)

    def set_password(self, raw_password):
        self.password = bcrypt.generate_password_hash(raw_password).decode('utf-8')

    def check_password(self, raw_password):
        return bcrypt.check_password_hash(self.password, raw_password)

    @property
    def is_admin(self):
        return self.role == 'admin'

    def __repr__(self):
        return f'<User {self.username} [{self.role}]>'


class UploadedFile(db.Model):
    """Record of every GPS data file uploaded to the system."""
    __tablename__ = 'uploaded_files'

    id             = db.Column(db.Integer, primary_key=True)
    filename       = db.Column(db.String(255), nullable=False)
    uploaded_by    = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    upload_date    = db.Column(db.DateTime, default=datetime.utcnow)
    status         = db.Column(db.String(50), default='processed')   # 'processed' | 'error'
    rows_processed = db.Column(db.Integer, default=0)
    file_size      = db.Column(db.Integer, default=0)   # bytes

    def __repr__(self):
        return f'<UploadedFile {self.filename}>'


def init_db(app):
    """
    Create all MySQL tables and seed default admin + researcher accounts.
    Called once on application startup.
    """
    with app.app_context():
        db.create_all()

        # ── Default admin ──────────────────────────────────────────────
        if not User.query.filter_by(username='admin').first():
            admin = User(
                username='admin',
                email='admin@stork.ac.uk',
                role='admin',
                full_name='System Administrator',
            )
            admin.set_password('admin123')
            db.session.add(admin)

        # ── Default researcher ─────────────────────────────────────────
        if not User.query.filter_by(username='fenil').first():
            researcher = User(
                username='fenil',
                email='fenil@stork.ac.uk',
                role='researcher',
                full_name='Fenil Kachhadiya',
            )
            researcher.set_password('fenil123')
            db.session.add(researcher)

        db.session.commit()
        print('[DB] MySQL tables initialised with default users.')
