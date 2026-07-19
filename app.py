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

# --- ACCUEIL TEMPORAIRE (ÉTAPE 1) ---

@app.route('/')
@login_required
def index():
    # Cet index temporaire nous sert uniquement à tester que l'authentification fonctionne
    return f"<h1>Bienvenue {current_user.username} !</h1><p>L'étape 1 fonctionne parfaitement. <a href='/logout'>Se déconnecter</a></p>"

if __name__ == '__main__':
    app.run(debug=True)