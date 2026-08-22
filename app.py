import os
import json
import random
from flask import Flask, render_template, redirect, url_for, request, flash, jsonify, session
from flask_login import LoginManager, UserMixin, login_user, login_required, logout_user, current_user
from werkzeug.security import check_password_hash
import database as db
from database import (
    get_root_categories_by_user,
    get_subcategories,
    get_categories_by_user,
    get_collections_by_category,
    get_root_collections_by_user,
    create_category,
    create_collection,
    delete_collection,
    move_collection,
    delete_category,
    merge_collections,
    invert_cards_in_collection,
    get_db_connection
)

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

@login_manager.user_loader
def load_user(user_id):
    user_row = db.get_user_by_id(user_id)
    if user_row:
        return User(user_row)
    return None

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

def build_category_tree(category_id, user_id):
    sub_cats = get_subcategories(category_id, user_id)
    sub_tree = []
    
    for sub in sub_cats:
        sub_dict = dict(sub)
        sub_dict['collections'] = get_collections_by_category(sub['id'])
        sub_dict['subcategories'] = build_category_tree(sub['id'], user_id)
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
    user_id = current_user.id

    root_categories = get_root_categories_by_user(user_id)
    tree = []
    for cat in root_categories:
        cat_dict = dict(cat)
        cat_dict['collections'] = [dict(c) for c in get_collections_by_category(cat['id'])]
        cat_dict['subcategories'] = build_category_tree(cat['id'], user_id)
        tree.append(cat_dict)

    raw_root_cols = get_root_collections_by_user(user_id)
    root_collections = [dict(c) for c in raw_root_cols]

    raw_categories = get_categories_by_user(user_id)
    formatted_categories = []
    for cat in raw_categories:
        formatted_categories.append({
            'id': cat['id'],
            'full_path': get_category_full_path(cat['id'], user_id)
        })

    formatted_categories.sort(key=lambda x: x['full_path'])

    with db.get_db_connection() as conn:
        all_user_collections = conn.execute(
            "SELECT id, name FROM collections WHERE user_id = ?",
            (current_user.id,)
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
def handle_create_category():
    user_id = current_user.id
    name = request.form.get('name')
    parent_id = request.form.get('parent_id')
    
    if name and name.strip():
        create_category(user_id, name, parent_id)
        
    return redirect(url_for('index'))

@app.route('/create_collection', methods=['POST'])
@login_required
def create_collection_route():
    user_id = current_user.id
    name = request.form.get('name')
    category_id = request.form.get('category_id')
    
    if name and name.strip():
        create_collection(user_id, category_id, name)
        
    return redirect(url_for('index'))

@app.route('/collection/<int:collection_id>', methods=['GET', 'POST'])
@login_required
def view_collection(collection_id):
    collection = db.get_collection_details(collection_id, current_user.id)
    if not collection:
        flash("Collection introuvable ou accès refusé.", "danger")
        return redirect(url_for('index'))
        
    if request.method == 'POST':
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
            db.toggle_card_difficulty(int(card_id), current_user.id)
            return redirect(url_for('view_collection', collection_id=collection_id))
            
        elif action == 'delete_card':
            card_id = request.form.get('card_id')
            db.delete_card(int(card_id), current_user.id)
            flash("Carte supprimée.", "success")
            return redirect(url_for('view_collection', collection_id=collection_id))

    cards = db.get_cards_by_collection(collection_id)
    stats = get_collection_stats(collection_id)

    with db.get_db_connection() as conn:
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

        user_row = conn.execute('SELECT favorite_modes FROM users WHERE id = ?', (current_user.id,)).fetchone()

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
def reset_collection_progress(collection_id):
    db.reset_collection_progress(collection_id)
    flash("Progression réinitialisée avec succès.", "info")
    return redirect(url_for('view_collection', collection_id=collection_id))

@app.route('/collection/<int:collection_id>/review/<mode>')
@login_required
def start_review(collection_id, mode):
    collection = db.get_collection_details(collection_id, current_user.id)
    if not collection:
        flash("Collection introuvable ou accès refusé.", "danger")
        return redirect(url_for('index'))

    # Redirection vers la route dédiée au mode difficile
    if mode == 'difficult':
        return redirect(url_for('review_difficult_mode', collection_id=collection_id))
    if mode == 'write':
        return redirect(url_for('review_write_mode', collection_id=collection_id))
    all_cards = db.get_cards_by_collection(collection_id)

    # Filtrage selon le mode
    if mode == 'not_validated':
        cards_to_review = [c for c in all_cards if c['is_known'] == 0]
    else:  # Mode 'all' par défaut
        cards_to_review = list(all_cards)

    if not cards_to_review:
        flash("Aucune carte à réviser dans ce mode !", "warning")
        return redirect(url_for('view_collection', collection_id=collection_id))

    cards_list = [dict(c) for c in cards_to_review]
    random.shuffle(cards_list)

    session['review_cards'] = [c['id'] for c in cards_list]
    session['review_index'] = 0

    return redirect(url_for('render_review_card', collection_id=collection_id))


@app.route('/collection/<int:collection_id>/review/difficult')
@login_required
def review_difficult_mode(collection_id):
    collection = db.get_collection_details(collection_id, current_user.id)
    if not collection:
        flash("Collection introuvable.", "danger")
        return redirect(url_for('index'))

    # Vérification rapide s'il y a des cartes difficiles
    all_cards = db.get_cards_by_collection(collection_id)
    difficult_cards = [c for c in all_cards if c['is_difficult'] == 1]

    if not difficult_cards:
        flash("Aucune carte marquée comme difficile dans cette collection !", "warning")
        return redirect(url_for('view_collection', collection_id=collection_id))

    return render_template('review_difficult.html', collection=collection)

@app.route('/collection/<int:collection_id>/review/write')
@login_required
def review_write_mode(collection_id):
    collection = db.get_collection_details(collection_id, current_user.id)
    if not collection:
        flash("Collection introuvable.", "danger")
        return redirect(url_for('index'))

    return render_template('review_write.html', collection=collection)


@app.route('/collection/<int:collection_id>/data')
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
def toggle_card_difficult(card_id):
    with db.get_db_connection() as conn:
        conn.execute('UPDATE cards SET is_difficult = CASE WHEN is_difficult = 1 THEN 0 ELSE 1 END WHERE id = ?', (card_id,))
        conn.commit()
    return jsonify({'status': 'ok'})

@app.route('/card/<int:card_id>/answer', methods=['POST'])
def answer_card(card_id):
    data = request.get_json() or {}
    knows = data.get('knows', 0)
    
    with db.get_db_connection() as conn:
        conn.execute('UPDATE cards SET is_known = ? WHERE id = ?', (knows, card_id))
        conn.commit()
    return jsonify({'status': 'ok'})

@app.route('/collection/<int:collection_id>/invert', methods=['POST'])
def invert_collection(collection_id):
    invert_cards_in_collection(collection_id)
    return redirect(url_for('view_collection', collection_id=collection_id))

@app.route('/collection/<int:collection_id>/review/card', methods=['GET', 'POST'])
@login_required
def render_review_card(collection_id):
    collection = db.get_collection_details(collection_id, current_user.id)
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
        
        if action == 'toggle_difficult_review':
            db.toggle_card_difficulty(current_card_id, current_user.id)
            return redirect(url_for('render_review_card', collection_id=collection_id))
            
        if user_knows is not None:
            db.update_card_knowledge(current_card_id, int(user_knows))
            session['review_index'] = index + 1
            return redirect(url_for('render_review_card', collection_id=collection_id))

    with db.get_db_connection() as conn:
        card = conn.execute("SELECT * FROM cards WHERE id = ?", (current_card_id,)).fetchone()
        
    return render_template('review_flashcards.html', collection=collection, card=card, progress=(index+1, len(card_ids)))

@app.route('/delete_category/<int:category_id>', methods=['POST'])
@login_required
def handle_delete_category(category_id):
    user_id = current_user.id
    success = delete_category(category_id, user_id)
    
    if success:
        flash("Dossier supprimé avec succès.", "success")
    else:
        flash("Impossible de supprimer ce dossier : il contient des sous-dossiers ou des collections !", "danger")
        
    return redirect(url_for('index'))

@app.route('/delete_collection/<int:collection_id>', methods=['POST'])
@login_required
def handle_delete_collection(collection_id):
    user_id = current_user.id
    delete_collection(collection_id, user_id)
    flash("Collection supprimée.", "success")
    return redirect(url_for('index'))

@app.route('/move_collection/<int:collection_id>', methods=['POST'])
@login_required
def handle_move_collection(collection_id):
    user_id = current_user.id
    new_category_id = request.form.get('category_id')
    
    move_collection(collection_id, new_category_id, user_id)
    flash("Collection déplacée avec succès.", "success")
    return redirect(url_for('index'))

@app.route('/merge_collections/<int:collection_id>', methods=['POST'])
@login_required
def handle_merge_collections(collection_id):
    user_id = current_user.id
    target_col_id = request.form.get('target_collection_id')
    new_name = request.form.get('new_name')
    
    if target_col_id and new_name and new_name.strip():
        new_col_id = merge_collections(user_id, collection_id, int(target_col_id), new_name)
        if new_col_id:
            flash("Collections fusionnées avec succès !", "success")
        else:
            flash("Erreur lors de la fusion.", "danger")
    else:
        flash("Veuillez remplir tous les champs pour la fusion.", "warning")
        
    return redirect(url_for('index'))

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
        conn.execute('UPDATE users SET favorite_modes = ? WHERE id = ?', (favs_json, current_user.id))
        conn.commit()

    return jsonify({'status': 'ok'}), 200

# ROUTE DEBUG / RESET
@app.route('/reset_my_favorites')
@login_required
def reset_my_favorites():
    default_favs = json.dumps(['fc_not_validated', 'fc_difficult'])
    
    with db.get_db_connection() as conn:
        conn.execute('UPDATE users SET favorite_modes = ? WHERE id = ?', (default_favs, current_user.id))
        conn.commit()
    
    flash("Favoris réinitialisés avec succès !", "success")
    return redirect(url_for('index'))


if __name__ == '__main__':
    app.run(debug=True)