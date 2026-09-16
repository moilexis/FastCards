import os
import json
import random
from functools import wraps
from flask import Flask, render_template, redirect, url_for, request, flash, jsonify, session, Response
from flask_login import LoginManager, UserMixin, login_user, login_required, logout_user, current_user
from werkzeug.security import check_password_hash, generate_password_hash
import database as db

app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', 'cle_dev_temp_12345')

login_manager = LoginManager()
login_manager.login_view = 'login'
login_manager.init_app(app)

db.init_db()

class User(UserMixin):
    def __init__(self, user_row):
        self.id = user_row['id']
        self.username = user_row['username']
        self.is_guest = bool(user_row['is_guest']) if 'is_guest' in user_row.keys() and user_row['is_guest'] else False
        self.parent_user_id = user_row['parent_user_id'] if 'parent_user_id' in user_row.keys() else None

    @property
    def owner_id(self):
        return self.parent_user_id if self.is_guest else self.id

    @property
    def owner_username(self):
        if self.is_guest and self.parent_user_id:
            parent = db.get_user_by_id(self.parent_user_id)
            return parent['username'] if parent else "le propriétaire"
        return self.username

@login_manager.user_loader
def load_user(user_id):
    user_row = db.get_user_by_id(user_id)
    if user_row:
        return User(user_row)
    return None

def guest_forbidden(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if current_user.is_authenticated and current_user.is_guest:
            flash("Action non autorisée en mode invité.", "danger")
            return redirect(url_for('index'))
        return f(*args, **kwargs)
    return decorated_function

# --- ROUTES AUTHENTIFICATION ---

@app.route('/register', methods=['GET', 'POST'])
def register():
    if current_user.is_authenticated:
        return redirect(url_for('index'))
        
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        
        if not username or not password:
            flash("Tous les champs sont requis.", "danger")
        elif db.create_user(username, password):
            flash("Compte créé avec succès ! Connectez-vous.", "success")
            return redirect(url_for('login'))
        else:
            flash("Ce nom d'utilisateur est déjà pris.", "danger")
            
    return render_template('register.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated:
        return redirect(url_for('index'))
        
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        
        user_row = db.get_user_by_username(username)
        if user_row and check_password_hash(user_row['password_hash'], password):
            user_obj = User(user_row)
            login_user(user_obj)
            return redirect(url_for('index'))
        else:
            flash("Identifiants incorrects.", "danger")
            
    return render_template('login.html')

@app.route('/logout')
def logout():
    logout_user()
    return redirect(url_for('login'))

# --- LOGIQUE DE L'ARBORESCENCE ---

def build_category_tree(category_id, user_id, is_guest=False):
    sub_cats = db.get_subcategories(category_id, user_id)
    sub_tree = []
    
    for sub in sub_cats:
        if is_guest and sub['is_hidden_from_guest']:
            continue
        sub_dict = dict(sub)
        cols = db.get_collections_by_category(sub['id'])
        if is_guest:
            cols = [c for c in cols if not c['is_hidden_from_guest']]
        sub_dict['collections'] = cols
        sub_dict['subcategories'] = build_category_tree(sub['id'], user_id, is_guest)
        sub_tree.append(sub_dict)
        
    return sub_tree

def get_category_full_path(category_id, user_id):
    path = []
    current_id = category_id
    
    with db.get_db_connection() as conn:
        while current_id is not None:
            cat = conn.execute(
                "SELECT id, name, parent_id FROM categories WHERE id = ? AND user_id = ?", 
                (current_id, user_id)
            ).fetchone()
            
            if not cat:
                break
                
            path.insert(0, cat['name'])
            current_id = cat['parent_id']
            
    return " / ".join(path)

@app.route('/')
@login_required
def index():
    user_id = current_user.owner_id
    is_guest = current_user.is_guest

    root_categories = db.get_root_categories_by_user(user_id)
    tree = []
    for cat in root_categories:
        if is_guest and cat['is_hidden_from_guest']:
            continue
        cat_dict = dict(cat)
        cols = db.get_collections_by_category(cat['id'])
        if is_guest:
            cols = [c for c in cols if not c['is_hidden_from_guest']]
        cat_dict['collections'] = [dict(c) for c in cols]
        cat_dict['subcategories'] = build_category_tree(cat['id'], user_id, is_guest)
        tree.append(cat_dict)

    raw_root_cols = db.get_root_collections_by_user(user_id)
    if is_guest:
        raw_root_cols = [c for c in raw_root_cols if not c['is_hidden_from_guest']]
    root_collections = [dict(c) for c in raw_root_cols]

    raw_categories = db.get_categories_by_user(user_id)
    formatted_categories = []
    for cat in raw_categories:
        if is_guest and cat['is_hidden_from_guest']:
            continue
        formatted_categories.append({
            'id': cat['id'],
            'full_path': get_category_full_path(cat['id'], user_id)
        })

    formatted_categories.sort(key=lambda x: x['full_path'])

    with db.get_db_connection() as conn:
        all_user_collections = conn.execute(
            "SELECT id, name FROM collections WHERE user_id = ?",
            (user_id,)
        ).fetchall()

    for col in root_collections:
        col['stats'] = get_collection_stats(col['id'])

    def attach_stats_to_tree(categories):
        for cat in categories:
            cat['stats'] = get_category_stats(cat['id'])
            
            new_collections = []
            for col in cat.get('collections', []):
                col_dict = dict(col)
                col_dict['stats'] = get_collection_stats(col_dict['id'])
                new_collections.append(col_dict)
            cat['collections'] = new_collections
            
            if cat.get('subcategories'):
                attach_stats_to_tree(cat['subcategories'])

    attach_stats_to_tree(tree)

    return render_template(
        'index.html',
        tree=tree,
        root_collections=root_collections,
        all_categories=formatted_categories,
        all_user_collections=all_user_collections
    )

@app.route('/create_category', methods=['POST'])
@login_required
@guest_forbidden
def handle_create_category():
    user_id = current_user.id
    name = request.form.get('name')
    parent_id = request.form.get('parent_id')
    
    if name and name.strip():
        db.create_category(user_id, name, parent_id)
        
    return redirect(url_for('index'))

@app.route('/create_collection', methods=['POST'])
@login_required
@guest_forbidden
def create_collection_route():
    user_id = current_user.id
    name = request.form.get('name')
    category_id = request.form.get('category_id')
    
    if name and name.strip():
        db.create_collection(user_id, category_id, name)
        
    return redirect(url_for('index'))

@app.route('/collection/<int:collection_id>', methods=['GET', 'POST'])
@login_required
def view_collection(collection_id):
    user_id = current_user.owner_id
    collection = db.get_collection_details(collection_id, user_id)
    
    if not collection or (current_user.is_guest and collection['is_hidden_from_guest']):
        flash("Collection introuvable ou accès refusé.", "danger")
        return redirect(url_for('index'))
        
    if request.method == 'POST' and not current_user.is_guest:
        action = request.form.get('action')
        
        if action == 'bulk_import':
            raw_text = request.form.get('bulk_data')
            if raw_text:
                lines = raw_text.strip().split('\n')
                cards_to_insert = []
                for line in lines:
                    if ';' in line:
                        parts = line.split(';', 1)
                        q, a = parts[0].strip(), parts[1].strip()
                        if q and a: cards_to_insert.append((q, a))
                if cards_to_insert:
                    db.insert_cards_bulk(collection_id, cards_to_insert)
                    flash(f"{len(cards_to_insert)} cartes ajoutées !", "success")
            return redirect(url_for('view_collection', collection_id=collection_id))
            
        elif action == 'toggle_difficult':
            card_id = request.form.get('card_id')
            db.toggle_card_difficulty(int(card_id), user_id)
            return redirect(url_for('view_collection', collection_id=collection_id))
            
        elif action == 'delete_card':
            card_id = request.form.get('card_id')
            db.delete_card(int(card_id), user_id)
            flash("Carte supprimée.", "success")
            return redirect(url_for('view_collection', collection_id=collection_id))

    cards = db.get_cards_by_collection(collection_id)
    stats = get_collection_stats(collection_id)

    with db.get_db_connection() as conn:
        last_session = conn.execute('''
            SELECT 
                strftime('%d/%m/%Y', created_at, 'localtime') AS date_formatted,
                strftime('%H:%M', created_at, 'localtime') AS time_formatted
            FROM study_sessions 
            WHERE collection_id = ? 
            ORDER BY created_at DESC LIMIT 1
        ''', (collection_id,)).fetchone()

        last_reviewed_date = last_session['date_formatted'] if last_session else None
        last_reviewed_time = last_session['time_formatted'] if last_session else None

        user_row = conn.execute('SELECT favorite_modes FROM users WHERE id = ?', (user_id,)).fetchone()

    user_favs = ['fc_not_validated', 'fc_difficult']
    if user_row and user_row['favorite_modes']:
        try:
            user_favs = json.loads(user_row['favorite_modes'])
        except Exception:
            pass

    return render_template(
        'collection.html', 
        collection=collection, 
        cards=cards, 
        stats=stats,
        last_reviewed_date=last_reviewed_date,
        last_reviewed_time=last_reviewed_time,
        user_favs=user_favs
    )

@app.route('/collection/<int:collection_id>/reset', methods=['POST'])
@login_required
@guest_forbidden
def reset_collection_progress(collection_id):
    db.reset_collection_progress(collection_id)
    flash("Progression réinitialisée avec succès.", "info")
    return redirect(url_for('view_collection', collection_id=collection_id))
# 1. Page de sélection de la source (Filtres)
@app.route('/collection/<int:collection_id>/review/<mode>/select')
@login_required
def select_review_source(collection_id, mode):
    user_id = current_user.owner_id
    collection = db.get_collection_details(collection_id, user_id)
    if not collection:
        flash("Collection introuvable.", "danger")
        return redirect(url_for('index'))
    
    return render_template('select_source.html', collection=collection, mode=mode)

# 2. Lancement du mode de révision
@app.route('/collection/<int:collection_id>/review/<mode>/start')
@login_required
def start_review_session(collection_id, mode):
    user_id = current_user.owner_id
    collection = db.get_collection_details(collection_id, user_id)
    if not collection:
        flash("Collection introuvable.", "danger")
        return redirect(url_for('index'))
    
    # Appel de la fonction native de app.py
    stats = get_collection_stats(collection_id)
    source = request.args.get('source', 'not_validated')
    
    if mode == 'flashcards':
        return render_template('review_flashcards.html', collection=collection, source=source, progress=(1, stats['total']), hide_navbar=True)
    elif mode == 'write':
        return render_template('review_write.html', collection=collection, source=source, progress=(1, stats['total']), hide_navbar=True)
    elif mode == 'pure':
        return render_template('review_pure.html', collection=collection, source=source, progress=(1, stats['total']), hide_navbar=True)
    else:
        flash("Mode inconnu.", "warning")
        return redirect(url_for('view_collection', collection_id=collection_id))

    
@app.route('/collection/<int:collection_id>/data')
@login_required
def get_collection_cards(collection_id):
    with db.get_db_connection() as conn:
        rows = conn.execute('SELECT id, question, answer, is_known, is_difficult FROM cards WHERE collection_id = ?', (collection_id,)).fetchall()

    cards_data = []
    for row in rows:
        cards_data.append({
            'id': row['id'],
            'question': row['question'],
            'answer': row['answer'],
            'is_known': row['is_known'],
            'is_difficult': row['is_difficult']
        })

    return jsonify({'cards': cards_data})

@app.route('/card/<int:card_id>/toggle_difficult', methods=['POST'])
@login_required
def toggle_card_difficult(card_id):
    if current_user.is_guest:
        return jsonify({'status': 'ignored_guest'})
    with db.get_db_connection() as conn:
        conn.execute('UPDATE cards SET is_difficult = CASE WHEN is_difficult = 1 THEN 0 ELSE 1 END WHERE id = ?', (card_id,))
        conn.commit()
    return jsonify({'status': 'ok'})

@app.route('/card/<int:card_id>/answer', methods=['POST'])
@login_required
def answer_card(card_id):
    if current_user.is_guest:
        return jsonify({'status': 'ignored_guest'})
    data = request.get_json() or {}
    knows = data.get('knows', 0)
    
    with db.get_db_connection() as conn:
        conn.execute('UPDATE cards SET is_known = ? WHERE id = ?', (knows, card_id))
        conn.commit()
    return jsonify({'status': 'ok'})

@app.route('/collection/<int:collection_id>/invert', methods=['POST'])
@login_required
def invert_collection(collection_id):
    if current_user.is_guest:
        flash("Accès limité : L'inversion permanente en base n'est pas autorisée en mode invité.", "info")
        return redirect(url_for('view_collection', collection_id=collection_id))
    db.invert_cards_in_collection(collection_id)
    return redirect(url_for('view_collection', collection_id=collection_id))

@app.route('/collection/<int:collection_id>/review/card', methods=['GET', 'POST'])
@login_required
def render_review_card(collection_id):
    user_id = current_user.owner_id
    collection = db.get_collection_details(collection_id, user_id)
    card_ids = session.get('review_cards', [])
    index = session.get('review_index', 0)
    
    if index >= len(card_ids):
        session.pop('review_cards', None)
        flash("Session de révision terminée !", "success")
        return redirect(url_for('view_collection', collection_id=collection_id))
        
    current_card_id = card_ids[index]
    
    if request.method == 'POST':
        user_knows = request.form.get('knows')
        action = request.form.get('action')
        
        if action == 'toggle_difficult_review' and not current_user.is_guest:
            db.toggle_card_difficulty(current_card_id, user_id)
            return redirect(url_for('render_review_card', collection_id=collection_id))
            
        if user_knows is not None:
            if not current_user.is_guest:
                db.update_card_knowledge(current_card_id, int(user_knows))
            session['review_index'] = index + 1
            return redirect(url_for('render_review_card', collection_id=collection_id))

    with db.get_db_connection() as conn:
        card = conn.execute("SELECT * FROM cards WHERE id = ?", (current_card_id,)).fetchone()
        
    return render_template('review_flashcards.html', collection=collection, card=card, progress=(index+1, len(card_ids)))

@app.route('/delete_category/<int:category_id>', methods=['POST'])
@login_required
@guest_forbidden
def handle_delete_category(category_id):
    user_id = current_user.id
    success = db.delete_category(category_id, user_id)
    
    if success:
        flash("Dossier supprimé avec succès.", "success")
    else:
        flash("Impossible de supprimer ce dossier : il contient des sous-dossiers ou des collections !", "danger")
        
    return redirect(url_for('index'))

@app.route('/delete_collection/<int:collection_id>', methods=['POST'])
@login_required
@guest_forbidden
def handle_delete_collection(collection_id):
    user_id = current_user.id
    db.delete_collection(collection_id, user_id)
    flash("Collection supprimée.", "success")
    return redirect(url_for('index'))

@app.route('/move_collection/<int:collection_id>', methods=['POST'])
@login_required
@guest_forbidden
def handle_move_collection(collection_id):
    user_id = current_user.id
    new_category_id = request.form.get('category_id')
    
    db.move_collection(collection_id, new_category_id, user_id)
    flash("Collection déplacée avec succès.", "success")
    return redirect(url_for('index'))

@app.route('/merge_collections/<int:collection_id>', methods=['POST'])
@login_required
@guest_forbidden
def handle_merge_collections(collection_id):
    user_id = current_user.id
    target_col_id = request.form.get('target_collection_id')
    new_name = request.form.get('new_name')
    
    if target_col_id and new_name and new_name.strip():
        new_col_id = db.merge_collections(user_id, collection_id, int(target_col_id), new_name)
        if new_col_id:
            flash("Collections fusionnées avec succès !", "success")
        else:
            flash("Erreur lors de la fusion.", "danger")
    else:
        flash("Veuillez remplir tous les champs pour la fusion.", "warning")
        
    return redirect(url_for('index'))

@app.route('/category/<int:category_id>/toggle_guest', methods=['POST'])
@login_required
@guest_forbidden
def toggle_category_guest(category_id):
    db.toggle_category_guest_visibility(category_id, current_user.id)
    flash("Visibilité invité modifiée pour ce dossier.", "info")
    return redirect(request.referrer or url_for('index'))

@app.route('/collection/<int:collection_id>/toggle_guest', methods=['POST'])
@login_required
@guest_forbidden
def toggle_collection_guest(collection_id):
    db.toggle_collection_guest_visibility(collection_id, current_user.id)
    flash("Visibilité invité modifiée pour cette collection.", "info")
    return redirect(request.referrer or url_for('index'))

# --- STATS ---

def get_collection_stats(collection_id):
    with db.get_db_connection() as conn:
        row = conn.execute('SELECT COUNT(*) as total, SUM(CASE WHEN is_known = 1 THEN 1 ELSE 0 END) as known FROM cards WHERE collection_id = ?', (collection_id,)).fetchone()
    
    total = row['total'] if row else 0
    known = row['known'] if row and row['known'] else 0
    percent = round((known / total) * 100) if total > 0 else 0
    
    return {'known': known, 'total': total, 'percent': percent}

def get_category_stats(category_id):
    with db.get_db_connection() as conn:
        row = conn.execute('''
            WITH RECURSIVE SubCats AS (
                SELECT id FROM categories WHERE id = ?
                UNION ALL
                SELECT c.id FROM categories c JOIN SubCats s ON c.parent_id = s.id
            )
            SELECT COUNT(cards.id) as total, SUM(CASE WHEN cards.is_known = 1 THEN 1 ELSE 0 END) as known 
            FROM cards 
            JOIN collections ON cards.collection_id = collections.id
            WHERE collections.category_id IN (SELECT id FROM SubCats)
        ''', (category_id,)).fetchone()
    
    total = row['total'] if row and row['total'] else 0
    known = row['known'] if row and row['known'] else 0
    percent = round((known / total) * 100) if total > 0 else 0
    
    return {'total': total, 'known': known, 'percent': percent}

@app.route('/card/<int:card_id>/edit', methods=['POST'])
@login_required
@guest_forbidden
def edit_card_route(card_id):
    data = request.get_json() or {}
    question = data.get('question')
    answer = data.get('answer')
    
    with db.get_db_connection() as conn:
        conn.execute('UPDATE cards SET question = ?, answer = ? WHERE id = ?', (question, answer, card_id))
        conn.commit()
    
    return jsonify({'status': 'ok'})

@app.route('/api/study_session', methods=['POST'])
@login_required
def save_study_session():
    if current_user.is_guest:
        return jsonify({'status': 'success', 'message': 'Guest session ignored'}), 200

    data = request.get_json(force=True)
    if not data:
        return jsonify({'status': 'error', 'message': 'No data provided'}), 400

    collection_id = data.get('collection_id')
    mode = data.get('mode')
    duration = data.get('duration_seconds', 0)
    cards_viewed = data.get('cards_viewed', 0)
    cards_success = data.get('cards_success', 0)

    with db.get_db_connection() as conn:
        conn.execute('''
            INSERT INTO study_sessions (user_id, collection_id, mode, duration_seconds, cards_viewed, cards_success, created_at)
            VALUES (?, ?, ?, ?, ?, ?, DATETIME('now'))
        ''', (current_user.id, collection_id, mode, duration, cards_viewed, cards_success))
        conn.commit()

    return jsonify({'status': 'success'}), 200

@app.route('/api/user/favorites', methods=['POST'])
@login_required
def update_user_favorites():
    data = request.get_json() or {}
    favorites = data.get('favorites', [])
    
    if len(favorites) > 3:
        favorites = favorites[:3]

    favs_json = json.dumps(favorites)

    with db.get_db_connection() as conn:
        conn.execute('UPDATE users SET favorite_modes = ? WHERE id = ?', (favs_json, current_user.owner_id))
        conn.commit()

    return jsonify({'status': 'ok'}), 200

@app.route('/profile', methods=['GET', 'POST'])
@login_required
@guest_forbidden
def profile():
    user_row = db.get_user_by_id(current_user.id)
    guest_account = db.get_guest_account_by_parent(current_user.id)
    
    if request.method == 'POST':
        action = request.form.get('action')
        
        if action == 'update_profile':
            new_username = request.form.get('username', '').strip()
            old_password = request.form.get('old_password', '')
            new_password = request.form.get('new_password', '')
            confirm_password = request.form.get('confirm_password', '')

            if not check_password_hash(user_row['password_hash'], old_password):
                flash("Ancien mot de passe incorrect.", "danger")
            elif not new_username:
                flash("Le nom d'utilisateur ne peut pas être vide.", "danger")
            else:
                new_hash = None
                if new_password or confirm_password:
                    if new_password != confirm_password:
                        flash("Les deux nouveaux mots de passe ne correspondent pas.", "danger")
                        return redirect(url_for('profile'))
                    new_hash = generate_password_hash(new_password)

                success = db.update_user_profile(current_user.id, new_username, new_hash)
                
                if success:
                    flash("Profil mis à jour avec succès !", "success")
                    return redirect(url_for('profile'))
                else:
                    flash("Ce nom d'utilisateur est déjà utilisé.", "danger")

        elif action == 'save_guest':
            guest_user = request.form.get('guest_username', '').strip()
            guest_pass = request.form.get('guest_password', '').strip()

            if not guest_user or not guest_pass:
                flash("L'identifiant et le mot de passe invité sont requis.", "danger")
            else:
                db.create_or_update_guest_account(current_user.id, guest_user, generate_password_hash(guest_pass))
                flash("Identifiants invités mis à jour !", "success")
                return redirect(url_for('profile'))

        elif action == 'delete_guest':
            db.delete_guest_account(current_user.id)
            flash("L'accès invité a été supprimé.", "info")
            return redirect(url_for('profile'))

    stats = db.get_user_stats(current_user.id)
    
    MODE_LABELS = {
        'all': 'Tout réviser',
        'not_validated': 'Cartes non vues',
        'difficult': 'Cartes difficiles',
        'write': 'Mode Écriture',
        'flashcard_difficult': 'Cartes difficiles'
    }

    sessions_formatted = []
    for s in stats['today_sessions']:
        session_dict = dict(s)
        if session_dict['category_id']:
            cat_path = get_category_full_path(session_dict['category_id'], current_user.id)
            session_dict['full_path'] = f"{cat_path} / {session_dict['collection_name']}"
        else:
            session_dict['full_path'] = session_dict['collection_name']
            
        session_dict['mode_label'] = MODE_LABELS.get(session_dict['mode'], session_dict['mode'])
        sessions_formatted.append(session_dict)
    
    stats['today_sessions'] = sessions_formatted

    return render_template('profile.html', user=user_row, guest_account=guest_account, stats=stats)

@app.route('/category/<int:category_id>/rename', methods=['POST'])
@login_required
@guest_forbidden
def rename_category(category_id):
    new_name = request.form.get('name', '').strip()
    if new_name:
        db.update_category_name(category_id, current_user.id, new_name)
        flash("Dossier renommé avec succès.", "success")
    else:
        flash("Le nom du dossier ne peut pas être vide.", "danger")
    return redirect(request.referrer or url_for('index'))

@app.route('/collection/<int:collection_id>/rename', methods=['POST'])
@login_required
@guest_forbidden
def rename_collection(collection_id):
    new_name = request.form.get('name', '').strip()
    if new_name:
        db.update_collection_name(collection_id, current_user.id, new_name)
        flash("Collection renommée avec succès.", "success")
    else:
        flash("Le nom de la collection ne peut pas être vide.", "danger")
    return redirect(request.referrer or url_for('index'))

@app.route('/collection/<int:collection_id>/export/txt')
@login_required
def export_collection_txt(collection_id):
    user_id = current_user.owner_id
    collection = db.get_collection_details(collection_id, user_id)
    
    if not collection or (current_user.is_guest and collection['is_hidden_from_guest']):
        flash("Collection introuvable.", "danger")
        return redirect(url_for('index'))

    cards = db.get_cards_by_collection(collection_id)
    lines = [f"{card['question']} ; {card['answer']}" for card in cards]
    content = "\n".join(lines)
    
    filename = f"export_{collection['name'].lower().replace(' ', '_')}.txt"
    
    return Response(
        content,
        mimetype="text/plain",
        headers={"Content-disposition": f"attachment; filename={filename}"}
    )

@app.route('/reset_my_favorites')
@login_required
def reset_my_favorites():
    default_favs = json.dumps(['fc_not_validated', 'fc_difficult'])
    with db.get_db_connection() as conn:
        conn.execute('UPDATE users SET favorite_modes = ? WHERE id = ?', (default_favs, current_user.owner_id))
        conn.commit()
    
    flash("Favoris réinitialisés avec succès !", "success")
    return redirect(url_for('index'))

if __name__ == '__main__':
    app.run(debug=True)