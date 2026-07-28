import os
from flask import Flask, render_template, redirect, url_for, request, flash
from flask_login import LoginManager, UserMixin, login_user, login_required, logout_user, current_user
from werkzeug.security import check_password_hash
import database as db
import random

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "un_secret_tres_bien_garde_12345")

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
@login_required
def logout():
    logout_user()
    return redirect(url_for('login'))

# --- LOGIQUE DE L'ARBORESCENCE (SÉCURISÉE) ---

@app.route('/', methods=['GET', 'POST'])
@login_required
def index():
    if request.method == 'POST':
        action = request.form.get('action')
        
        if action == 'add_category':
            category_name = request.form.get('category_name')
            if category_name:
                db.create_category(current_user.id, category_name)
                flash(f"Catégorie '{category_name}' ajoutée !", "success")
                
        elif action == 'add_collection':
            category_id = request.form.get('category_id')
            collection_name = request.form.get('collection_name')
            
            if collection_name:
                # Si 'aucune' est sélectionné, category_id devient None
                if category_id == 'aucune':
                    db.create_collection(current_user.id, None, collection_name)
                    flash(f"Collection '{collection_name}' ajoutée à la racine !", "success")
                else:
                    # Sécurité : on vérifie que la catégorie appartient à l'utilisateur
                    user_categories = [str(c['id']) for c in db.get_categories_by_user(current_user.id)]
                    if category_id in user_categories:
                        db.create_collection(current_user.id, int(category_id), collection_name)
                        flash(f"Collection '{collection_name}' ajoutée !", "success")
                    else:
                        flash("Action non autorisée.", "danger")
                    
        return redirect(url_for('index'))

    # Récupération des catégories et des collections à la racine
    user_categories = db.get_categories_by_user(current_user.id)
    root_collections = db.get_root_collections_by_user(current_user.id)
    
    tree_data = []
    for cat in user_categories:
        collections = db.get_collections_by_category(cat['id'])
        tree_data.append({
            'id': cat['id'],
            'name': cat['name'],
            'collections': collections
        })
        
    return render_template('index.html', tree=tree_data, root_collections=root_collections)
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
        flash("🎉 Session de révision terminée !", "success")
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

if __name__ == '__main__':
    app.run(debug=True)