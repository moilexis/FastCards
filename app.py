import os
from flask import Flask, render_template, redirect, url_for, request, flash,session
from flask_login import LoginManager, UserMixin, login_user, login_required, logout_user, current_user
from werkzeug.security import check_password_hash
import database as db
import random
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
    merge_collections
    )

app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', 'cle_dev_temp_12345')

# Configuration de Flask-Login
login_manager = LoginManager()
login_manager.login_view = 'login'  # Redirection si accès non autorisé
login_manager.init_app(app)
# Initialisation de la BDD au démarrage
db.init_db()

# Classe Utilisateur requise par Flask-Login
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

# --- LOGIQUE DE L'ARBORESCENCE (SÉCURISÉE) ---
def build_category_tree(category_id, user_id):
    """Fonction récursive qui construit l'arbre complet des sous-catégories et leurs collections."""
    sub_cats = get_subcategories(category_id, user_id)
    sub_tree = []
    
    for sub in sub_cats:
        sub_dict = dict(sub)
        sub_dict['collections'] = get_collections_by_category(sub['id'])
        # Appel récursif pour aller chercher les enfants du sous-dossier (niveau 3, 4, etc.)
        sub_dict['subcategories'] = build_category_tree(sub['id'], user_id)
        sub_tree.append(sub_dict)
        
    return sub_tree

def get_category_full_path(category_id, user_id):
    """Reconstruit le chemin complet d'une catégorie (ex: Allemand > situer dans le temps > verbes)."""
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
                
            path.insert(0, cat['name'])  # Ajoute au début pour garder l'ordre hiérarchique
            current_id = cat['parent_id']
            
    return " / ".join(path)


@app.route('/')
@login_required 
def index():
    user_id = current_user.id
    
    # 1. Construction récursive de l'arborescence
    root_categories = get_root_categories_by_user(user_id)
    tree = []
    for cat in root_categories:
        cat_dict = dict(cat)
        cat_dict['collections'] = get_collections_by_category(cat['id'])
        cat_dict['subcategories'] = build_category_tree(cat['id'], user_id)
        tree.append(cat_dict)

    # 2. Collections orphelines
    root_collections = get_root_collections_by_user(user_id)
    
    # 3. Récupère TOUTES les catégories et calcule leur chemin d'accès complet pour le <select>
    raw_categories = get_categories_by_user(user_id)
    formatted_categories = []
    for cat in raw_categories:
        formatted_categories.append({
            'id': cat['id'],
            'full_path': get_category_full_path(cat['id'], user_id)
        })
    
    # On trie la liste par ordre alphabétique des chemins
    formatted_categories.sort(key=lambda x: x['full_path'])

    with db.get_db_connection() as conn:
        all_user_collections = conn.execute(
            "SELECT id, name FROM collections WHERE user_id = ?", 
            (current_user.id,)
        ).fetchall()

    return render_template(
        'index.html', 
        tree=tree, 
        root_collections=root_collections,
        all_categories=formatted_categories,
        all_user_collections=all_user_collections # Passé au template
    )
# Route pour créer une catégorie ou sous-catégorie
@app.route('/create_category', methods=['POST'])
@login_required
def handle_create_category():
    user_id = current_user.id
    name = request.form.get('name')
    parent_id = request.form.get('parent_id')
    
    # name.strip() évite de créer un dossier avec juste des espaces "   "
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
        
        # Action 1 : Importation de masse (Étape 3 optimisée)
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
                    flash(f"🎉 {len(cards_to_insert)} cartes ajoutées !", "success")
            return redirect(url_for('view_collection', collection_id=collection_id))
            
        # Action 2 : Toggle Difficile depuis la liste
        elif action == 'toggle_difficult':
            card_id = request.form.get('card_id')
            db.toggle_card_difficulty(int(card_id), current_user.id)
            return redirect(url_for('view_collection', collection_id=collection_id))
            
        # Action 3 : Suppression d'une carte
        elif action == 'delete_card':
            card_id = request.form.get('card_id')
            db.delete_card(int(card_id), current_user.id)
            flash("Carte supprimée.", "success")
            return redirect(url_for('view_collection', collection_id=collection_id))

    cards = db.get_cards_by_collection(collection_id)
    return render_template('collection.html', collection=collection, cards=cards)


@app.route('/collection/<int:collection_id>/review/<mode>')
@login_required
def start_review(collection_id, mode):
    collection = db.get_collection_details(collection_id, current_user.id)
    if not collection:
        return redirect(url_for('index'))
        
    # Option : Réinitialisation globale requise par le mode "all_reset"
    if mode == 'all_reset':
        db.reset_collection_progress(collection_id)
        
    # Filtrage selon le mode choisi
    all_cards = db.get_cards_by_collection(collection_id)
    if mode == 'difficult':
        cards_to_review = [c for c in all_cards if c['is_difficult'] == 1 and c['is_known'] == 0]
    elif mode == 'not_validated':
        cards_to_review = [c for c in all_cards if c['is_known'] == 0]
    else: # mode 'all_reset'
        cards_to_review = list(all_cards)
        
    if not cards_to_review:
        flash("Aucune carte à réviser dans ce mode !", "warning")
        return redirect(url_for('view_collection', collection_id=collection_id))
        
    #  Mélange aléatoire total (différent à chaque session)
    cards_list = [dict(c) for c in cards_to_review]
    random.shuffle(cards_list)
    
    # On stocke la liste des IDs mélangés dans la session de l'utilisateur
    from flask import session
    session['review_cards'] = [c['id'] for c in cards_list]
    session['review_index'] = 0
    
    return redirect(url_for('render_review_card', collection_id=collection_id))


@app.route('/collection/<int:collection_id>/review/card', methods=['GET', 'POST'])
@login_required
def render_review_card(collection_id):
    from flask import session
    collection = db.get_collection_details(collection_id, current_user.id)
    card_ids = session.get('review_cards', [])
    index = session.get('review_index', 0)
    
    if index >= len(card_ids):
        session.pop('review_cards', None)
        flash("Session de révision terminée !", "success")
        return redirect(url_for('view_collection', collection_id=collection_id))
        
    current_card_id = card_ids[index]
    
    if request.method == 'POST':
        user_knows = request.form.get('knows') # '1' ou '0'
        action = request.form.get('action')
        
        if action == 'toggle_difficult_review':
            db.toggle_card_difficulty(current_card_id, current_user.id)
            return redirect(url_for('render_review_card', collection_id=collection_id))
            
        if user_knows is not None:
            db.update_card_knowledge(current_card_id, int(user_knows))
            session['review_index'] = index + 1
            return redirect(url_for('render_review_card', collection_id=collection_id))

    # Récupération de la carte courante avec son statut frais
    with db.get_db_connection() as conn:
        card = conn.execute("SELECT * FROM cards WHERE id = ?", (current_card_id,)).fetchone()
        
    return render_template('review.html', collection=collection, card=card, progress=(index+1, len(card_ids)))

#suppression/deplacement/fusion

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

if __name__ == '__main__':
    app.run(debug=True)