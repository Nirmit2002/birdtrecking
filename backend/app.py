"""
White Stork Migration Visualiser — Flask application entry point.
Run with: python /root/stork-project/backend/app.py
Accessible at: http://10.8.237.176:5000
"""

import os
import sys
import json
import shutil
from datetime import datetime
from functools import wraps

from flask import (Flask, render_template, request, jsonify,
                   redirect, url_for, flash, send_from_directory)
from flask_login import (LoginManager, login_user, logout_user,
                         login_required, current_user)

# ── Path setup ───────────────────────────────────────────────────────────────
# Ensure backend/ is on sys.path for local imports
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from models import db, bcrypt, User, UploadedFile, init_db
from preprocess import run_preprocessing, DATA_FILE, GEOJSON_DIR

# ── App factory ──────────────────────────────────────────────────────────────
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

app = Flask(
    __name__,
    template_folder=os.path.join(BASE_DIR, 'templates'),
    static_folder=os.path.join(BASE_DIR, 'static'),
)

app.config.update(
    SECRET_KEY='stork-migration-secret-key-2024-dissertation',
    SQLALCHEMY_DATABASE_URI='mysql+pymysql://stork_user:stork_pass2024@localhost/stork_db',
    SQLALCHEMY_TRACK_MODIFICATIONS=False,
    MAX_CONTENT_LENGTH=50 * 1024 * 1024,   # 50 MB upload limit
)

db.init_app(app)
bcrypt.init_app(app)

login_manager = LoginManager(app)
login_manager.login_view = 'login'
login_manager.login_message = 'Please log in to access this page.'
login_manager.login_message_category = 'warning'


@login_manager.user_loader
def load_user(user_id):
    return db.session.get(User, int(user_id))


# ── Decorators ───────────────────────────────────────────────────────────────

def admin_required(f):
    """Restrict a route to users with role='admin'."""
    @wraps(f)
    @login_required
    def decorated(*args, **kwargs):
        if not current_user.is_admin:
            flash('Admin access required.', 'danger')
            return redirect(url_for('dashboard'))
        return f(*args, **kwargs)
    return decorated


# ── Auth routes ──────────────────────────────────────────────────────────────

@app.route('/')
def index():
    if current_user.is_authenticated:
        return redirect(url_for('dashboard'))
    return redirect(url_for('login'))


@app.route('/login', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated:
        return redirect(url_for('dashboard'))

    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '')
        user = User.query.filter_by(username=username).first()

        if user and user.check_password(password):
            user.last_login = datetime.utcnow()
            db.session.commit()
            login_user(user, remember=True)
            next_page = request.args.get('next')
            flash(f'Welcome back, {user.full_name or user.username}!', 'success')
            return redirect(next_page or url_for('dashboard'))

        flash('Invalid username or password.', 'danger')

    return render_template('login.html')


@app.route('/register', methods=['GET', 'POST'])
def register():
    if current_user.is_authenticated:
        return redirect(url_for('dashboard'))

    if request.method == 'POST':
        username  = request.form.get('username', '').strip()
        email     = request.form.get('email', '').strip()
        password  = request.form.get('password', '')
        full_name = request.form.get('full_name', '').strip()
        role      = request.form.get('role', 'researcher')

        if User.query.filter_by(username=username).first():
            flash('Username already taken.', 'danger')
        elif User.query.filter_by(email=email).first():
            flash('Email already registered.', 'danger')
        elif len(password) < 6:
            flash('Password must be at least 6 characters.', 'danger')
        else:
            user = User(username=username, email=email,
                        full_name=full_name, role=role)
            user.set_password(password)
            db.session.add(user)
            db.session.commit()
            flash('Account created! Please log in.', 'success')
            return redirect(url_for('login'))

    return render_template('register.html')


@app.route('/logout')
@login_required
def logout():
    logout_user()
    flash('You have been logged out.', 'info')
    return redirect(url_for('login'))


# ── Main pages ───────────────────────────────────────────────────────────────

@app.route('/dashboard')
@login_required
def dashboard():
    # Load summary stats from pre-computed JSON
    stats_path = os.path.join(GEOJSON_DIR, 'stats.json')
    stats = {}
    if os.path.exists(stats_path):
        with open(stats_path) as f:
            stats = json.load(f)

    recent_uploads = (UploadedFile.query
                      .order_by(UploadedFile.upload_date.desc())
                      .limit(5).all())
    all_users_count = User.query.count()

    return render_template('dashboard.html',
                           stats=stats,
                           recent_uploads=recent_uploads,
                           all_users_count=all_users_count)


@app.route('/map')
@login_required
def map_view():
    return render_template('index.html')


@app.route('/admin')
@admin_required
def admin():
    users   = User.query.order_by(User.created_at.desc()).all()
    uploads = UploadedFile.query.order_by(UploadedFile.upload_date.desc()).all()

    stats_path = os.path.join(GEOJSON_DIR, 'stats.json')
    stats = {}
    if os.path.exists(stats_path):
        with open(stats_path) as f:
            stats = json.load(f)

    return render_template('admin.html', users=users, uploads=uploads, stats=stats)


# ── File upload ──────────────────────────────────────────────────────────────

@app.route('/upload', methods=['POST'])
@admin_required
def upload():
    if 'file' not in request.files:
        flash('No file selected.', 'danger')
        return redirect(url_for('admin'))

    f = request.files['file']
    if f.filename == '':
        flash('No file selected.', 'danger')
        return redirect(url_for('admin'))

    allowed = {'xlsx', 'xls', 'csv'}
    ext = f.filename.rsplit('.', 1)[-1].lower()
    if ext not in allowed:
        flash('Only Excel (.xlsx/.xls) and CSV files are accepted.', 'danger')
        return redirect(url_for('admin'))

    save_path = os.path.join(BASE_DIR, 'data', f.filename)
    f.save(save_path)
    size = os.path.getsize(save_path)

    # Preprocessing always reads data/data.xlsx — overwrite it with the new upload
    data_xlsx = os.path.join(BASE_DIR, 'data', 'data.xlsx')
    if save_path != data_xlsx:
        shutil.copy2(save_path, data_xlsx)

    # Run preprocessing on the new file
    ok = run_preprocessing(force=True)
    rows = 0
    if ok:
        tl_path = os.path.join(GEOJSON_DIR, 'timeline.json')
        if os.path.exists(tl_path):
            with open(tl_path) as fp:
                rows = len(json.load(fp))

    record = UploadedFile(
        filename=f.filename,
        uploaded_by=current_user.id,
        status='processed' if ok else 'error',
        rows_processed=rows,
        file_size=size,
    )
    db.session.add(record)
    db.session.commit()

    flash(f'File "{f.filename}" uploaded and {"processed" if ok else "failed to process"}.', 'success' if ok else 'danger')
    return redirect(url_for('admin'))


# ── API endpoints ─────────────────────────────────────────────────────────────

def _read_geojson(filename):
    path = os.path.join(GEOJSON_DIR, filename)
    if not os.path.exists(path):
        return jsonify({'error': 'Data not yet processed'}), 404
    with open(path) as f:
        return jsonify(json.load(f))


@app.route('/api/tracks')
@login_required
def api_tracks():
    return _read_geojson('tracks.geojson')


@app.route('/api/stopovers')
@login_required
def api_stopovers():
    return _read_geojson('stopovers.geojson')


@app.route('/api/stats')
@login_required
def api_stats():
    return _read_geojson('stats.json')


@app.route('/api/timeline')
@login_required
def api_timeline():
    return _read_geojson('timeline.json')


@app.route('/api/bird/<bird_name>')
@login_required
def api_bird(bird_name):
    """Return GeoJSON trajectory for a single named bird."""
    path = os.path.join(GEOJSON_DIR, 'tracks.geojson')
    if not os.path.exists(path):
        return jsonify({'error': 'Data not processed'}), 404
    with open(path) as f:
        all_tracks = json.load(f)
    features = [ft for ft in all_tracks['features']
                if ft['properties']['bird_id'] == bird_name]
    return jsonify({'type': 'FeatureCollection', 'features': features})


@app.route('/api/users')
@admin_required
def api_users():
    users = User.query.all()
    return jsonify([{
        'id':         u.id,
        'username':   u.username,
        'email':      u.email,
        'role':       u.role,
        'full_name':  u.full_name,
        'created_at': u.created_at.isoformat() if u.created_at else None,
        'last_login': u.last_login.isoformat() if u.last_login else None,
    } for u in users])


@app.route('/api/users/delete', methods=['POST'])
@admin_required
def api_delete_user():
    data    = request.get_json(force=True)
    user_id = data.get('user_id')
    user    = db.session.get(User, user_id)

    if not user:
        return jsonify({'error': 'User not found'}), 404
    if user.id == current_user.id:
        return jsonify({'error': 'Cannot delete yourself'}), 400
    if user.username == 'admin':
        return jsonify({'error': 'Cannot delete the default admin'}), 400

    db.session.delete(user)
    db.session.commit()
    return jsonify({'success': True, 'message': f'User {user.username} deleted.'})


@app.route('/api/users/role', methods=['POST'])
@admin_required
def api_change_role():
    data    = request.get_json(force=True)
    user_id = data.get('user_id')
    new_role = data.get('role')
    if new_role not in ('admin', 'researcher'):
        return jsonify({'error': 'Invalid role'}), 400
    user = db.session.get(User, user_id)
    if not user:
        return jsonify({'error': 'User not found'}), 404
    user.role = new_role
    db.session.commit()
    return jsonify({'success': True})


@app.route('/api/reprocess', methods=['POST'])
@admin_required
def api_reprocess():
    ok = run_preprocessing(force=True)
    return jsonify({'success': ok, 'message': 'Reprocessing complete.' if ok else 'Reprocessing failed.'})


# ── Startup ───────────────────────────────────────────────────────────────────

if __name__ == '__main__':
    print('=' * 60)
    print(' White Stork Migration Visualiser')
    print(' http://10.8.237.176:5000')
    print('=' * 60)

    # Initialise MySQL tables and seed users
    init_db(app)

    # Preprocess GPS data if outputs don't exist yet
    with app.app_context():
        run_preprocessing()

    app.run(host='0.0.0.0', port=5000, debug=False)
