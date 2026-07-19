import os
from flask import Flask, render_template, redirect, url_for, request, flash
from flask_login import LoginManager, UserMixin, login_user, login_required, logout_user, current_user
from werkzeug.security import check_password_hash
import database as db

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

@app.route('/collection/<int:collection_id>')
@login_required
def view_collection(collection_id):
    # Route pour inspecter une collection (Sert de transition vers l'Étape 3 et 4)
    collection = db.get_collection_details(collection_id, current_user.id)
    if not collection:
        flash("Collection introuvable ou accès refusé.", "danger")
        return redirect(url_for('index'))
        
    return render_template('collection.html', collection=collection)

@app.route('/reviser')
@login_required
def reviser():
    # Route vers la page dee revision
    return "<h3>La révision n'est pas encore disponible oupsi 😶‍🌫️</h3><p><a href='/'>Retour</a></p>" 

if __name__ == '__main__':
    app.run(debug=True)