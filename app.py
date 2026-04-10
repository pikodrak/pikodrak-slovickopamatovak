import os
import json
import secrets
import configparser
import urllib.request
import urllib.error
from functools import wraps
from flask import Flask, render_template, request, redirect, url_for, flash, jsonify
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager, UserMixin, login_user, logout_user, login_required, current_user
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import datetime

# --- Load config ---
cfg = configparser.ConfigParser()
cfg.read(os.path.join(os.path.dirname(os.path.abspath(__file__)), 'config.ini'), encoding='utf-8')

APP_NAME = cfg.get('app', 'name', fallback='SlovíčkoPamatovák')
APP_VERSION = cfg.get('app', 'version', fallback='0.0.0')
SECRET_KEY = cfg.get('app', 'secret_key', fallback='') or os.environ.get('SECRET_KEY', '') or secrets.token_hex(32)
DEBUG = cfg.getboolean('app', 'debug', fallback=True)
HOST = cfg.get('app', 'host', fallback='0.0.0.0')
PORT = cfg.getint('app', 'port', fallback=5001)
DB_URI = cfg.get('database', 'uri', fallback='sqlite:///slovickopamatovak.db')
DEFAULT_LANG_A = cfg.get('defaults', 'lang_a', fallback='cs')
DEFAULT_LANG_B = cfg.get('defaults', 'lang_b', fallback='es')
MIN_PASSWORD_LENGTH = cfg.getint('defaults', 'min_password_length', fallback=4)
OPENAI_API_KEY = cfg.get('openai', 'api_key', fallback='')
OPENAI_MODEL = cfg.get('openai', 'model', fallback='gpt-4o-mini')

LANGUAGES = []
if cfg.has_section('languages'):
    for code in cfg.options('languages'):
        LANGUAGES.append((code, cfg.get('languages', code)))
if not LANGUAGES:
    LANGUAGES = [('cs', 'Čeština'), ('es', 'Španělština'), ('en', 'Angličtina')]
LANG_MAP = dict(LANGUAGES)

app = Flask(__name__)
app.config['SECRET_KEY'] = SECRET_KEY
app.config['SQLALCHEMY_DATABASE_URI'] = DB_URI
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db = SQLAlchemy(app)
login_manager = LoginManager(app)
login_manager.login_view = 'login'
login_manager.login_message = 'Pro přístup se musíte přihlásit.'


# --- Models ---

class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    password_hash = db.Column(db.String(256), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    sets = db.relationship('WordSet', backref='owner', lazy=True, cascade='all, delete-orphan')


class WordSet(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(200), nullable=False)
    lang_a = db.Column(db.String(10), nullable=False, default='cs')
    lang_b = db.Column(db.String(10), nullable=False, default='es')
    share_token = db.Column(db.String(32), unique=True, nullable=True, index=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    words = db.relationship('Word', backref='word_set', lazy=True, cascade='all, delete-orphan')

    @property
    def lang_a_name(self):
        return LANG_MAP.get(self.lang_a, self.lang_a)

    @property
    def lang_b_name(self):
        return LANG_MAP.get(self.lang_b, self.lang_b)


class Word(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    word_a = db.Column(db.String(300), nullable=False)
    word_b = db.Column(db.String(300), nullable=False)
    set_id = db.Column(db.Integer, db.ForeignKey('word_set.id'), nullable=False)


class PracticeResult(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    word_id = db.Column(db.Integer, db.ForeignKey('word.id'), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    correct = db.Column(db.Boolean, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    word = db.relationship('Word', backref=db.backref('results', lazy=True, cascade='all, delete-orphan'))


class WordExplanation(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    word = db.Column(db.String(300), nullable=False)
    lang = db.Column(db.String(100), nullable=False)
    explanation = db.Column(db.Text, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    __table_args__ = (db.UniqueConstraint('word', 'lang', name='uq_word_lang'),)


class ApiToken(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    token = db.Column(db.String(64), unique=True, nullable=False, index=True)
    name = db.Column(db.String(200), nullable=False)
    permission = db.Column(db.String(10), nullable=False, default='read')
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    user = db.relationship('User', backref=db.backref('api_tokens', lazy=True, cascade='all, delete-orphan'))


def api_auth(write=False):
    def decorator(f):
        @wraps(f)
        def decorated(*args, **kwargs):
            auth = request.headers.get('Authorization', '')
            if not auth.startswith('Bearer '):
                return jsonify({'error': 'Missing or invalid Authorization header. Use: Bearer <token>'}), 401
            token_str = auth[7:]
            tok = ApiToken.query.filter_by(token=token_str).first()
            if not tok:
                return jsonify({'error': 'Invalid token'}), 401
            if write and tok.permission != 'rw':
                return jsonify({'error': 'Token does not have write permission'}), 403
            request.api_user = tok.user
            request.api_token = tok
            return f(*args, **kwargs)
        return decorated
    return decorator


@login_manager.user_loader
def load_user(user_id):
    return db.session.get(User, int(user_id))


@app.context_processor
def inject_globals():
    return {'APP_NAME': APP_NAME, 'APP_VERSION': APP_VERSION,
            'LANGUAGES': LANGUAGES, 'LANG_MAP': LANG_MAP,
            'DEFAULT_LANG_A': DEFAULT_LANG_A, 'DEFAULT_LANG_B': DEFAULT_LANG_B,
            'AI_ENABLED': bool(OPENAI_API_KEY)}


# --- Auth routes ---

@app.route('/')
def index():
    if current_user.is_authenticated:
        return redirect(url_for('dashboard'))
    return redirect(url_for('login'))


@app.route('/register', methods=['GET', 'POST'])
def register():
    if current_user.is_authenticated:
        return redirect(url_for('dashboard'))
    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '')
        password2 = request.form.get('password2', '')
        if not username or not password:
            flash('Vyplňte všechna pole.', 'error')
        elif len(password) < MIN_PASSWORD_LENGTH:
            flash(f'Heslo musí mít alespoň {MIN_PASSWORD_LENGTH} znaky.', 'error')
        elif password != password2:
            flash('Hesla se neshodují.', 'error')
        elif User.query.filter_by(username=username).first():
            flash('Toto uživatelské jméno je již obsazené.', 'error')
        else:
            user = User(username=username, password_hash=generate_password_hash(password))
            db.session.add(user)
            db.session.commit()
            login_user(user)
            flash('Registrace proběhla úspěšně!', 'success')
            return redirect(url_for('dashboard'))
    return render_template('register.html')


@app.route('/login', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated:
        return redirect(url_for('dashboard'))
    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '')
        user = User.query.filter_by(username=username).first()
        if user and check_password_hash(user.password_hash, password):
            login_user(user)
            return redirect(url_for('dashboard'))
        else:
            flash('Nesprávné jméno nebo heslo.', 'error')
    return render_template('login.html')


@app.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('login'))


# --- Dashboard ---

@app.route('/dashboard')
@login_required
def dashboard():
    sets = WordSet.query.filter_by(user_id=current_user.id).order_by(WordSet.created_at.desc()).all()
    return render_template('dashboard.html', sets=sets)


# --- Word Set CRUD ---

@app.route('/set/new', methods=['GET', 'POST'])
@login_required
def new_set():
    if request.method == 'POST':
        name = request.form.get('name', '').strip()
        lang_a = request.form.get('lang_a', DEFAULT_LANG_A)
        lang_b = request.form.get('lang_b', DEFAULT_LANG_B)
        if not name:
            flash('Zadejte název sady.', 'error')
            return render_template('set_form.html', edit=False)
        ws = WordSet(name=name, lang_a=lang_a, lang_b=lang_b, user_id=current_user.id)
        db.session.add(ws)
        db.session.commit()
        return redirect(url_for('view_set', set_id=ws.id))
    return render_template('set_form.html', edit=False)


@app.route('/set/<int:set_id>')
@login_required
def view_set(set_id):
    ws = WordSet.query.get_or_404(set_id)
    if ws.user_id != current_user.id:
        flash('Nemáte přístup k této sadě.', 'error')
        return redirect(url_for('dashboard'))
    # Get per-word stats
    word_ids = [w.id for w in ws.words]
    word_stats = {}
    if word_ids:
        rows = db.session.execute(db.text("""
            SELECT word_id,
                   COUNT(*) as total,
                   SUM(CASE WHEN correct = 0 THEN 1 ELSE 0 END) as wrong
            FROM practice_result
            WHERE user_id = :uid AND word_id IN ({})
            GROUP BY word_id
        """.format(','.join(str(i) for i in word_ids))),
            {'uid': current_user.id}).fetchall()
        for r in rows:
            word_stats[r.word_id] = {'total': r.total, 'wrong': r.wrong,
                                      'pct': round(100 * r.wrong / r.total) if r.total else 0}
    return render_template('view_set.html', ws=ws, word_stats=word_stats)


@app.route('/set/<int:set_id>/edit', methods=['GET', 'POST'])
@login_required
def edit_set(set_id):
    ws = WordSet.query.get_or_404(set_id)
    if ws.user_id != current_user.id:
        flash('Nemáte přístup k této sadě.', 'error')
        return redirect(url_for('dashboard'))
    if request.method == 'POST':
        name = request.form.get('name', '').strip()
        lang_a = request.form.get('lang_a', ws.lang_a)
        lang_b = request.form.get('lang_b', ws.lang_b)
        if name:
            ws.name = name
            ws.lang_a = lang_a
            ws.lang_b = lang_b
            db.session.commit()
            flash('Sada byla uložena.', 'success')
        return redirect(url_for('view_set', set_id=ws.id))
    return render_template('set_form.html', edit=True, ws=ws)


@app.route('/set/<int:set_id>/import', methods=['GET', 'POST'])
@login_required
def import_words(set_id):
    ws = WordSet.query.get_or_404(set_id)
    if ws.user_id != current_user.id:
        flash('Nemáte přístup k této sadě.', 'error')
        return redirect(url_for('dashboard'))
    if request.method == 'POST':
        text = ''
        f = request.files.get('file')
        if f and f.filename:
            text = f.read().decode('utf-8', errors='ignore')
        else:
            text = request.form.get('text', '')
        count = 0
        for line in text.splitlines():
            line = line.strip()
            if not line:
                continue
            sep = ';' if ';' in line else '\t' if '\t' in line else None
            if not sep:
                continue
            parts = line.split(sep, 1)
            if len(parts) != 2:
                continue
            a = parts[0].strip()
            b = parts[1].strip()
            if a and b:
                db.session.add(Word(word_a=a, word_b=b, set_id=ws.id))
                count += 1
        db.session.commit()
        flash(f'Importováno {count} slovíček.', 'success')
        return redirect(url_for('view_set', set_id=ws.id))
    return render_template('import.html', ws=ws)


@app.route('/set/<int:set_id>/delete', methods=['POST'])
@login_required
def delete_set(set_id):
    ws = WordSet.query.get_or_404(set_id)
    if ws.user_id != current_user.id:
        flash('Nemáte přístup k této sadě.', 'error')
        return redirect(url_for('dashboard'))
    db.session.delete(ws)
    db.session.commit()
    flash('Sada byla smazána.', 'success')
    return redirect(url_for('dashboard'))


# --- Sharing ---

@app.route('/set/<int:set_id>/share', methods=['POST'])
@login_required
def toggle_share(set_id):
    ws = WordSet.query.get_or_404(set_id)
    if ws.user_id != current_user.id:
        flash('Nemáte přístup.', 'error')
        return redirect(url_for('dashboard'))
    if ws.share_token:
        ws.share_token = None
        flash('Sdílení vypnuto.', 'success')
    else:
        ws.share_token = secrets.token_urlsafe(16)
        flash('Sdílení zapnuto.', 'success')
    db.session.commit()
    return redirect(url_for('view_set', set_id=ws.id))


@app.route('/shared/<token>')
def shared_set(token):
    ws = WordSet.query.filter_by(share_token=token).first_or_404()
    return render_template('shared.html', ws=ws)


@app.route('/shared/<token>/practice')
def shared_practice(token):
    ws = WordSet.query.filter_by(share_token=token).first_or_404()
    if not ws.words:
        flash('Sada neobsahuje žádná slovíčka.', 'error')
        return redirect(url_for('shared_set', token=token))
    words = [{'id': w.id, 'word_a': w.word_a, 'word_b': w.word_b} for w in ws.words]
    return render_template('practice.html', ws=ws, words=words, shared_token=token)


@app.route('/shared/<token>/import', methods=['POST'])
@login_required
def import_shared(token):
    source = WordSet.query.filter_by(share_token=token).first_or_404()
    new_ws = WordSet(
        name=source.name, lang_a=source.lang_a, lang_b=source.lang_b,
        user_id=current_user.id
    )
    db.session.add(new_ws)
    db.session.flush()
    for w in source.words:
        db.session.add(Word(word_a=w.word_a, word_b=w.word_b, set_id=new_ws.id))
    db.session.commit()
    flash(f'Sada "{source.name}" importována ({len(source.words)} slovíček).', 'success')
    return redirect(url_for('view_set', set_id=new_ws.id))


# --- Word CRUD ---

@app.route('/set/<int:set_id>/word/add', methods=['POST'])
@login_required
def add_word(set_id):
    ws = WordSet.query.get_or_404(set_id)
    if ws.user_id != current_user.id:
        return jsonify({'error': 'forbidden'}), 403
    word_a = request.form.get('word_a', '').strip()
    word_b = request.form.get('word_b', '').strip()
    if not word_a or not word_b:
        flash('Vyplňte oba výrazy.', 'error')
        return redirect(url_for('view_set', set_id=set_id))
    word = Word(word_a=word_a, word_b=word_b, set_id=ws.id)
    db.session.add(word)
    db.session.commit()
    return redirect(url_for('view_set', set_id=set_id))


@app.route('/word/<int:word_id>/delete', methods=['POST'])
@login_required
def delete_word(word_id):
    word = Word.query.get_or_404(word_id)
    ws = word.word_set
    if ws.user_id != current_user.id:
        return jsonify({'error': 'forbidden'}), 403
    set_id = ws.id
    db.session.delete(word)
    db.session.commit()
    return redirect(url_for('view_set', set_id=set_id))


@app.route('/word/<int:word_id>/edit', methods=['POST'])
@login_required
def edit_word(word_id):
    word = Word.query.get_or_404(word_id)
    ws = word.word_set
    if ws.user_id != current_user.id:
        return jsonify({'error': 'forbidden'}), 403
    word_a = request.form.get('word_a', '').strip()
    word_b = request.form.get('word_b', '').strip()
    if word_a and word_b:
        word.word_a = word_a
        word.word_b = word_b
        db.session.commit()
    return redirect(url_for('view_set', set_id=ws.id))


# --- API Token management (web UI) ---

@app.route('/tokens')
@login_required
def tokens():
    user_tokens = ApiToken.query.filter_by(user_id=current_user.id).order_by(ApiToken.created_at.desc()).all()
    return render_template('tokens.html', tokens=user_tokens)


@app.route('/tokens/new', methods=['POST'])
@login_required
def create_token():
    name = request.form.get('name', '').strip()
    permission = request.form.get('permission', 'read')
    if permission not in ('read', 'rw'):
        permission = 'read'
    if not name:
        flash('Zadejte popis tokenu.', 'error')
        return redirect(url_for('tokens'))
    raw_token = secrets.token_hex(32)
    t = ApiToken(token=raw_token, name=name, permission=permission, user_id=current_user.id)
    db.session.add(t)
    db.session.commit()
    flash(f'Token vytvořen: {raw_token}', 'token')
    return redirect(url_for('tokens'))


@app.route('/tokens/<int:token_id>/delete', methods=['POST'])
@login_required
def delete_token(token_id):
    t = ApiToken.query.get_or_404(token_id)
    if t.user_id != current_user.id:
        flash('Nemáte přístup.', 'error')
        return redirect(url_for('tokens'))
    db.session.delete(t)
    db.session.commit()
    flash('Token smazán.', 'success')
    return redirect(url_for('tokens'))


# --- REST API ---

def set_to_dict(ws, include_words=False):
    d = {
        'id': ws.id, 'name': ws.name, 'lang_a': ws.lang_a, 'lang_b': ws.lang_b,
        'word_count': len(ws.words), 'created_at': ws.created_at.isoformat(),
        'share_url': url_for('shared_set', token=ws.share_token, _external=True) if ws.share_token else None,
    }
    if include_words:
        d['words'] = [{'id': w.id, 'word_a': w.word_a, 'word_b': w.word_b} for w in ws.words]
    return d


@app.route('/api/sets', methods=['GET'])
@api_auth(write=False)
def api_list_sets():
    sets = WordSet.query.filter_by(user_id=request.api_user.id).order_by(WordSet.created_at.desc()).all()
    return jsonify([set_to_dict(s) for s in sets])


@app.route('/api/sets', methods=['POST'])
@api_auth(write=True)
def api_create_set():
    data = request.get_json(silent=True) or {}
    name = data.get('name', '').strip()
    if not name:
        return jsonify({'error': 'name is required'}), 400
    lang_a = data.get('lang_a', 'cs')
    lang_b = data.get('lang_b', 'es')
    ws = WordSet(name=name, lang_a=lang_a, lang_b=lang_b, user_id=request.api_user.id)
    db.session.add(ws)
    db.session.commit()
    return jsonify(set_to_dict(ws)), 201


@app.route('/api/sets/<int:set_id>', methods=['GET'])
@api_auth(write=False)
def api_get_set(set_id):
    ws = WordSet.query.get_or_404(set_id)
    if ws.user_id != request.api_user.id:
        return jsonify({'error': 'forbidden'}), 403
    return jsonify(set_to_dict(ws, include_words=True))


@app.route('/api/sets/<int:set_id>', methods=['PUT'])
@api_auth(write=True)
def api_update_set(set_id):
    ws = WordSet.query.get_or_404(set_id)
    if ws.user_id != request.api_user.id:
        return jsonify({'error': 'forbidden'}), 403
    data = request.get_json(silent=True) or {}
    name = data.get('name', '').strip()
    if name:
        ws.name = name
    if 'lang_a' in data:
        ws.lang_a = data['lang_a']
    if 'lang_b' in data:
        ws.lang_b = data['lang_b']
    db.session.commit()
    return jsonify(set_to_dict(ws))


@app.route('/api/sets/<int:set_id>', methods=['DELETE'])
@api_auth(write=True)
def api_delete_set(set_id):
    ws = WordSet.query.get_or_404(set_id)
    if ws.user_id != request.api_user.id:
        return jsonify({'error': 'forbidden'}), 403
    db.session.delete(ws)
    db.session.commit()
    return jsonify({'ok': True})


@app.route('/api/sets/<int:set_id>/share', methods=['POST'])
@api_auth(write=True)
def api_toggle_share(set_id):
    ws = WordSet.query.get_or_404(set_id)
    if ws.user_id != request.api_user.id:
        return jsonify({'error': 'forbidden'}), 403
    if ws.share_token:
        ws.share_token = None
    else:
        ws.share_token = secrets.token_urlsafe(16)
    db.session.commit()
    return jsonify(set_to_dict(ws))


@app.route('/api/sets/<int:set_id>/words', methods=['GET'])
@api_auth(write=False)
def api_list_words(set_id):
    ws = WordSet.query.get_or_404(set_id)
    if ws.user_id != request.api_user.id:
        return jsonify({'error': 'forbidden'}), 403
    return jsonify([{'id': w.id, 'word_a': w.word_a, 'word_b': w.word_b} for w in ws.words])


@app.route('/api/sets/<int:set_id>/words', methods=['POST'])
@api_auth(write=True)
def api_add_word(set_id):
    ws = WordSet.query.get_or_404(set_id)
    if ws.user_id != request.api_user.id:
        return jsonify({'error': 'forbidden'}), 403
    data = request.get_json(silent=True) or {}
    word_a = data.get('word_a', '').strip()
    word_b = data.get('word_b', '').strip()
    if not word_a or not word_b:
        return jsonify({'error': 'word_a and word_b are required'}), 400
    word = Word(word_a=word_a, word_b=word_b, set_id=ws.id)
    db.session.add(word)
    db.session.commit()
    return jsonify({'id': word.id, 'word_a': word.word_a, 'word_b': word.word_b}), 201


@app.route('/api/words/<int:word_id>', methods=['PUT'])
@api_auth(write=True)
def api_update_word(word_id):
    word = Word.query.get_or_404(word_id)
    if word.word_set.user_id != request.api_user.id:
        return jsonify({'error': 'forbidden'}), 403
    data = request.get_json(silent=True) or {}
    word_a = data.get('word_a', '').strip()
    word_b = data.get('word_b', '').strip()
    if not word_a or not word_b:
        return jsonify({'error': 'word_a and word_b are required'}), 400
    word.word_a = word_a
    word.word_b = word_b
    db.session.commit()
    return jsonify({'id': word.id, 'word_a': word.word_a, 'word_b': word.word_b})


@app.route('/api/words/<int:word_id>', methods=['DELETE'])
@api_auth(write=True)
def api_delete_word(word_id):
    word = Word.query.get_or_404(word_id)
    if word.word_set.user_id != request.api_user.id:
        return jsonify({'error': 'forbidden'}), 403
    db.session.delete(word)
    db.session.commit()
    return jsonify({'ok': True})


@app.route('/api/sets/<int:set_id>/import', methods=['POST'])
@api_auth(write=True)
def api_import_words(set_id):
    ws = WordSet.query.get_or_404(set_id)
    if ws.user_id != request.api_user.id:
        return jsonify({'error': 'forbidden'}), 403
    data = request.get_json(silent=True) or {}
    words_list = data.get('words')
    text = data.get('text', '')
    count = 0
    if words_list and isinstance(words_list, list):
        for w in words_list:
            a = w.get('word_a', '').strip()
            b = w.get('word_b', '').strip()
            if a and b:
                db.session.add(Word(word_a=a, word_b=b, set_id=ws.id))
                count += 1
    elif text:
        for line in text.splitlines():
            line = line.strip()
            if not line:
                continue
            sep = ';' if ';' in line else '\t' if '\t' in line else None
            if not sep:
                continue
            parts = line.split(sep, 1)
            if len(parts) != 2:
                continue
            a = parts[0].strip()
            b = parts[1].strip()
            if a and b:
                db.session.add(Word(word_a=a, word_b=b, set_id=ws.id))
                count += 1
    else:
        return jsonify({'error': 'Provide "words" array or "text" field'}), 400
    db.session.commit()
    return jsonify({'imported': count}), 201


# --- API docs page ---

@app.route('/api/docs')
def api_docs():
    return render_template('api_docs.html')


# --- Offline sync endpoint ---

@app.route('/api/my-data')
@login_required
def my_data():
    """Download all user data for offline use."""
    sets = WordSet.query.filter_by(user_id=current_user.id).all()
    return jsonify({
        'sets': [{
            'id': s.id, 'name': s.name, 'lang_a': s.lang_a, 'lang_b': s.lang_b,
            'lang_a_name': s.lang_a_name, 'lang_b_name': s.lang_b_name,
            'words': [{'id': w.id, 'word_a': w.word_a, 'word_b': w.word_b} for w in s.words]
        } for s in sets],
        'timestamp': datetime.utcnow().isoformat()
    })


# --- Practice mode ---

@app.route('/set/<int:set_id>/practice')
@login_required
def practice(set_id):
    ws = WordSet.query.get_or_404(set_id)
    if ws.user_id != current_user.id:
        flash('Nemáte přístup k této sadě.', 'error')
        return redirect(url_for('dashboard'))
    if not ws.words:
        flash('Sada neobsahuje žádná slovíčka.', 'error')
        return redirect(url_for('view_set', set_id=set_id))
    all_words = [{'id': w.id, 'word_a': w.word_a, 'word_b': w.word_b} for w in ws.words]
    # Optional range or random filter
    import random as rnd
    rand_count = request.args.get('random', type=int)
    wfrom = request.args.get('from', type=int)
    wto = request.args.get('to', type=int)
    if rand_count and rand_count < len(all_words):
        words = rnd.sample(all_words, rand_count)
        range_label = f'{rand_count} náhodných'
    elif wfrom is not None and wto is not None:
        words = all_words[wfrom-1:wto]
        range_label = f'{wfrom}–{wto}'
    else:
        words = all_words
        range_label = None
    if not words:
        flash('Žádná slovíčka v tomto rozsahu.', 'error')
        return redirect(url_for('view_set', set_id=set_id))
    return render_template('practice.html', ws=ws, words=words, shared_token=None, range_label=range_label)


# --- Practice stats ---

@app.route('/practice/log', methods=['POST'])
def log_practice_result():
    """Log a practice result. Works for both logged-in users and shared practice."""
    if not current_user.is_authenticated:
        return jsonify({'ok': True})  # silently skip for anonymous
    data = request.get_json(silent=True) or {}
    word_id = data.get('word_id')
    correct = data.get('correct', False)
    if not word_id:
        return jsonify({'error': 'missing word_id'}), 400
    word = db.session.get(Word, word_id)
    if not word:
        return jsonify({'error': 'word not found'}), 404
    pr = PracticeResult(word_id=word_id, user_id=current_user.id, correct=bool(correct))
    db.session.add(pr)
    db.session.commit()
    return jsonify({'ok': True})


def get_difficult_words(user_id, min_attempts=2, limit=50):
    """Get words with highest error rate for a user."""
    results = db.session.execute(db.text("""
        SELECT w.id, w.word_a, w.word_b, w.set_id, ws.name as set_name,
               ws.lang_a, ws.lang_b,
               COUNT(*) as total,
               SUM(CASE WHEN pr.correct = 0 THEN 1 ELSE 0 END) as wrong,
               ROUND(100.0 * SUM(CASE WHEN pr.correct = 0 THEN 1 ELSE 0 END) / COUNT(*), 0) as error_pct
        FROM practice_result pr
        JOIN word w ON pr.word_id = w.id
        JOIN word_set ws ON w.set_id = ws.id
        WHERE pr.user_id = :uid
        GROUP BY w.id
        HAVING total >= :min_att AND wrong > 0
        ORDER BY error_pct DESC, wrong DESC
        LIMIT :lim
    """), {'uid': user_id, 'min_att': min_attempts, 'lim': limit}).fetchall()
    return results


@app.route('/difficult')
@login_required
def difficult_words():
    words = get_difficult_words(current_user.id)
    return render_template('difficult.html', words=words)


@app.route('/difficult/practice')
@login_required
def practice_difficult():
    rows = get_difficult_words(current_user.id, min_attempts=1, limit=100)
    if not rows:
        flash('Zatím nemáte žádná slovíčka k opakování.', 'error')
        return redirect(url_for('difficult_words'))
    all_words = [{'id': r.id, 'word_a': r.word_a, 'word_b': r.word_b} for r in rows]
    # Optional range
    wfrom = request.args.get('from', type=int)
    wto = request.args.get('to', type=int)
    if wfrom is not None and wto is not None:
        words = all_words[wfrom-1:wto]
        range_label = f'{wfrom}–{wto}'
    else:
        words = all_words
        range_label = None
    if not words:
        flash('Žádná slovíčka v tomto rozsahu.', 'error')
        return redirect(url_for('difficult_words'))
    lang_a = rows[0].lang_a
    lang_b = rows[0].lang_b
    ws_data = type('WS', (), {
        'id': 0, 'name': 'Opakování',
        'lang_a': lang_a, 'lang_b': lang_b,
        'lang_a_name': LANG_MAP.get(lang_a, lang_a),
        'lang_b_name': LANG_MAP.get(lang_b, lang_b),
        'share_token': None,
    })()
    return render_template('practice.html', ws=ws_data, words=words, shared_token=None, is_difficult=True, range_label=range_label)


# --- Changelog ---

@app.route('/changelog')
def changelog():
    changelog_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'CHANGELOG.md')
    with open(changelog_path, 'r', encoding='utf-8') as f:
        raw = f.read()
    return render_template('changelog.html', raw=raw)


# --- AI features ---

def openai_chat(system_prompt, user_prompt):
    """Call OpenAI chat API. Returns the response text or raises an exception."""
    req = urllib.request.Request(
        'https://api.openai.com/v1/chat/completions',
        data=json.dumps({
            'model': OPENAI_MODEL,
            'messages': [
                {'role': 'system', 'content': system_prompt},
                {'role': 'user', 'content': user_prompt},
            ],
            'temperature': 0.7,
        }).encode(),
        headers={
            'Authorization': f'Bearer {OPENAI_API_KEY}',
            'Content-Type': 'application/json',
        },
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        data = json.loads(resp.read())
    return data['choices'][0]['message']['content']


@app.route('/set/<int:set_id>/ai-generate', methods=['GET', 'POST'])
@login_required
def ai_generate(set_id):
    ws = WordSet.query.get_or_404(set_id)
    if ws.user_id != current_user.id:
        flash('Nemáte přístup.', 'error')
        return redirect(url_for('dashboard'))
    if not OPENAI_API_KEY:
        flash('OpenAI API klíč není nastaven v config.ini.', 'error')
        return redirect(url_for('view_set', set_id=set_id))

    if request.method == 'POST':
        topic = request.form.get('topic', '').strip()
        count = min(int(request.form.get('count', 20)), 100)
        if not topic:
            flash('Zadejte téma.', 'error')
            return render_template('ai_generate.html', ws=ws)

        system_prompt = (
            f"You are a vocabulary generator. Generate exactly {count} vocabulary word pairs "
            f"for learning languages. Source language: {ws.lang_a_name}. Target language: {ws.lang_b_name}.\n"
            f"Return ONLY lines in format: word_in_{ws.lang_a_name};word_in_{ws.lang_b_name}\n"
            f"One pair per line. No numbering, no headers, no explanation. Just the word pairs."
        )
        user_prompt = f"Topic: {topic}"

        try:
            result = openai_chat(system_prompt, user_prompt)
            # Collect all existing words across user's sets
            all_user_sets = WordSet.query.filter_by(user_id=current_user.id).all()
            existing = set()
            for s in all_user_sets:
                for w in s.words:
                    existing.add((w.word_a.lower(), w.word_b.lower()))
            added = 0
            skipped = 0
            for line in result.splitlines():
                line = line.strip()
                if not line or ';' not in line:
                    continue
                parts = line.split(';', 1)
                if len(parts) == 2:
                    a, b = parts[0].strip(), parts[1].strip()
                    if a and b:
                        if (a.lower(), b.lower()) in existing:
                            skipped += 1
                        else:
                            db.session.add(Word(word_a=a, word_b=b, set_id=ws.id))
                            existing.add((a.lower(), b.lower()))
                            added += 1
            db.session.commit()
            msg = f'AI vygenerovalo {added} slovíček na téma "{topic}".'
            if skipped:
                msg += f' ({skipped} přeskočeno — už existují v jiné sadě)'
            flash(msg, 'success')
        except urllib.error.HTTPError as e:
            flash(f'Chyba OpenAI API: {e.code}', 'error')
        except Exception as e:
            flash(f'Chyba: {e}', 'error')
        return redirect(url_for('view_set', set_id=set_id))

    return render_template('ai_generate.html', ws=ws)


@app.route('/ai/translate', methods=['POST'])
@login_required
def ai_translate():
    if not OPENAI_API_KEY:
        return jsonify({'error': 'OpenAI API klíč není nastaven'}), 400
    data = request.get_json(silent=True) or {}
    word = data.get('word', '').strip()
    from_lang = data.get('from_lang', '')
    to_lang = data.get('to_lang', '')
    if not word or not from_lang or not to_lang:
        return jsonify({'error': 'missing fields'}), 400

    system_prompt = (
        f"You are a translator. Translate the given word or short phrase from {from_lang} to {to_lang}. "
        f"Return ONLY the translation, nothing else. No explanation, no alternatives."
    )
    try:
        result = openai_chat(system_prompt, word)
        return jsonify({'translation': result.strip()})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/ai/evaluate', methods=['POST'])
def ai_evaluate():
    if not OPENAI_API_KEY:
        return jsonify({'error': 'AI není dostupné'}), 400
    data = request.get_json(silent=True) or {}
    correct_answer = data.get('correct', '').strip()
    user_answer = data.get('answer', '').strip()
    lang = data.get('lang', '')
    if not correct_answer or not user_answer:
        return jsonify({'error': 'missing fields'}), 400

    system_prompt = (
        f"You are a vocabulary quiz evaluator for {lang}. "
        f"The correct answer is: \"{correct_answer}\"\n"
        f"The student answered: \"{user_answer}\"\n\n"
        f"Evaluate if the answer is correct. Accept synonyms, minor typos, "
        f"missing/extra accents, and alternative valid translations.\n"
        f"Respond with EXACTLY one JSON object (no markdown, no explanation):\n"
        f'{{"result": "correct"|"almost"|"wrong", "note": "short feedback in Czech, max 10 words"}}\n'
        f"- correct = the answer is right or a valid synonym\n"
        f"- almost = very close but has a meaningful error (e.g. wrong gender, tense)\n"
        f"- wrong = completely different meaning"
    )
    try:
        raw = openai_chat(system_prompt, user_answer)
        # Parse JSON from response
        raw = raw.strip()
        if raw.startswith('```'):
            raw = raw.split('\n', 1)[-1].rsplit('```', 1)[0].strip()
        result = json.loads(raw)
        result['correct_answer'] = correct_answer
        return jsonify(result)
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/ai/hint', methods=['POST'])
def ai_hint():
    if not OPENAI_API_KEY:
        return jsonify({'error': 'AI není dostupné'}), 400
    data = request.get_json(silent=True) or {}
    word = data.get('word', '').strip()
    lang = data.get('lang', '')
    if not word or not lang:
        return jsonify({'error': 'missing fields'}), 400

    system_prompt = (
        f"You are a vocabulary learning helper. The student is trying to remember "
        f"the translation of a word. Give a SHORT hint in Czech (max 15 words) "
        f"that helps them remember without revealing the exact word. "
        f"You can mention: first letter, number of syllables, a related context, "
        f"or a mnemonic. Do NOT say the word itself."
    )
    user_prompt = f"The word in {lang} is: \"{word}\""
    try:
        result = openai_chat(system_prompt, user_prompt)
        return jsonify({'hint': result.strip()})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/ai/explain', methods=['POST'])
def ai_explain():
    data = request.get_json(silent=True) or {}
    word = data.get('word', '').strip()
    lang = data.get('lang', '')
    if not word or not lang:
        return jsonify({'error': 'missing fields'}), 400

    # Check cache first
    cached = WordExplanation.query.filter_by(word=word, lang=lang).first()
    if cached:
        return jsonify({'explanation': cached.explanation, 'cached': True})

    if not OPENAI_API_KEY:
        return jsonify({'error': 'AI není dostupné'}), 400

    system_prompt = (
        f"You are a language teacher. A student is learning {lang}. "
        f"Explain the given word/phrase in Czech. Include:\n"
        f"1. All meanings the word can have in {lang} (numbered)\n"
        f"2. For each meaning, give a short example sentence in {lang} with Czech translation\n"
        f"3. If relevant, mention irregular forms, common collocations, or usage notes\n"
        f"4. If the word is a VERB, add at the end a full conjugation table:\n"
        f"   - First the PRESENT tense (yo, tú, él/ella, nosotros, vosotros, ellos/ellas)\n"
        f"   - Then PAST tenses (pretérito, imperfecto) in the same format\n"
        f"   - Mark irregular forms with *\n"
        f"Keep it concise but thorough. Answer in Czech (examples and conjugation in {lang})."
    )
    try:
        result = openai_chat(system_prompt, word)
        explanation = result.strip()
        # Save to cache
        entry = WordExplanation(word=word, lang=lang, explanation=explanation)
        db.session.add(entry)
        db.session.commit()
        return jsonify({'explanation': explanation, 'cached': False})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


# --- AI Chat ---

@app.route('/chat')
@login_required
def chat_page():
    return render_template('chat.html')


@app.route('/ai/chat', methods=['POST'])
@login_required
def ai_chat_endpoint():
    if not OPENAI_API_KEY:
        return jsonify({'error': 'AI není dostupné'}), 400
    data = request.get_json(silent=True) or {}
    messages = data.get('messages', [])
    if not messages:
        return jsonify({'error': 'no messages'}), 400

    # Build context about user's sets
    sets = WordSet.query.filter_by(user_id=current_user.id).all()
    sets_info = ', '.join([f'"{s.name}" ({s.lang_a_name}→{s.lang_b_name}, {len(s.words)} slov)' for s in sets])

    system_prompt = (
        f"Jsi jazykový asistent v aplikaci SlovíčkoPamatovák. Uživatel: {current_user.username}.\n"
        f"Uživatelovy slovníky: {sets_info or 'žádné'}.\n\n"
        f"Tvoje schopnosti:\n"
        f"- Konverzace v jakémkoli jazyce, přizpůsobená úrovni uživatele\n"
        f"- Vysvětlování gramatiky, slovíček, frází\n"
        f"- Když uživatel nerozumí, vysvětli česky\n"
        f"- Můžeš navrhnout slovíčka k přidání do slovníku\n"
        f"- Opravuj chyby uživatele jemně a vysvětli proč\n\n"
        f"Pokud uživatel chce vytvořit slovník nebo přidat slovíčka, vrať na konci zprávy speciální blok:\n"
        f"[ACTION:CREATE_SET|název|lang_a|lang_b]\n"
        f"[ACTION:ADD_WORDS|set_id|slovo1;překlad1\\nslovo2;překlad2]\n"
        f"[ACTION:EXPLAIN_ALL|set_id] — vygeneruje popisy všech slov v sadě\n"
        f"Tyto akce se provedou automaticky. Odpovídej stručně a přátelsky."
    )

    api_messages = [{'role': 'system', 'content': system_prompt}] + messages[-20:]

    try:
        req = urllib.request.Request(
            'https://api.openai.com/v1/chat/completions',
            data=json.dumps({
                'model': OPENAI_MODEL,
                'messages': api_messages,
                'temperature': 0.8,
            }).encode(),
            headers={
                'Authorization': f'Bearer {OPENAI_API_KEY}',
                'Content-Type': 'application/json',
            },
        )
        with urllib.request.urlopen(req, timeout=60) as resp:
            result = json.loads(resp.read())
        reply = result['choices'][0]['message']['content']

        # Process actions
        actions_done = []
        import re
        for match in re.finditer(r'\[ACTION:CREATE_SET\|(.+?)\|(.+?)\|(.+?)\]', reply):
            name, lang_a, lang_b = match.group(1), match.group(2), match.group(3)
            ws = WordSet(name=name, lang_a=lang_a, lang_b=lang_b, user_id=current_user.id)
            db.session.add(ws)
            db.session.commit()
            actions_done.append(f'Slovník "{name}" vytvořen (ID: {ws.id})')

        for match in re.finditer(r'\[ACTION:ADD_WORDS\|(\d+)\|(.+?)\]', reply, re.DOTALL):
            set_id = int(match.group(1))
            ws = db.session.get(WordSet, set_id)
            if ws and ws.user_id == current_user.id:
                count = 0
                for line in match.group(2).split('\\n'):
                    line = line.strip()
                    if ';' in line:
                        parts = line.split(';', 1)
                        if len(parts) == 2 and parts[0].strip() and parts[1].strip():
                            db.session.add(Word(word_a=parts[0].strip(), word_b=parts[1].strip(), set_id=set_id))
                            count += 1
                db.session.commit()
                if count:
                    actions_done.append(f'Přidáno {count} slovíček do "{ws.name}"')

        # Clean action tags from reply
        clean_reply = re.sub(r'\[ACTION:.+?\]', '', reply).strip()

        return jsonify({'reply': clean_reply, 'actions': actions_done})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


# --- Offline page + SW ---

@app.route('/offline')
def offline_page():
    return render_template('offline.html')


@app.route('/sw.js')
def service_worker():
    return app.send_static_file('sw.js'), 200, {
        'Content-Type': 'application/javascript',
        'Service-Worker-Allowed': '/',
    }


# --- Error handlers ---

@app.errorhandler(404)
def not_found(e):
    return render_template('error.html', code=404, message='Stránka nenalezena'), 404


@app.errorhandler(403)
def forbidden(e):
    return render_template('error.html', code=403, message='Přístup odepřen'), 403


@app.errorhandler(500)
def server_error(e):
    return render_template('error.html', code=500, message='Chyba serveru'), 500


# --- Init ---

with app.app_context():
    db.create_all()


if __name__ == '__main__':
    app.run(debug=DEBUG, host=HOST, port=PORT)
