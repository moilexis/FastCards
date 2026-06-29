import os
from flask import Flask, render_template, redirect, url_for, request, flash
from flask_login import LoginManager, UserMixin, login_user, login_required, logout_user, current_user
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
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        
        if db.create_user(username, password):
            flash("Compte créé avec succès ! Connectez-vous.", "success")
            return redirect(url_for('login'))
        else:
            flash("Ce nom d'utilisateur est déjà pris.", "danger")
            
    return render_template('register.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        
        user_row = db.get_user_by_username(username)
        if user_row and db.check_password_hash(user_row['password_hash'], password):
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

# --- ROUTES DE L'APPLICATION ---

@app.route('/', methods=['GET', 'POST'])
@login_required
def index():
    if request.method == 'POST':
        bulk_text = request.form.get('bulk_data')
        # Étape 2 : Le Parser de masse
        lines = bulk_text.strip().split('\n')
        cards_added = 0
        
        for line in lines:
            if ';' in line:
                question, answer = line.split(';', 1)
                db.insert_card(current_user.id, question, answer)
                cards_added += 1
                
        flash(f"{cards_added} cartes ont été ajoutées à votre paquet !", "success")
        return redirect(url_for('index'))
        
    return render_template('index.html')

@app.route('/reviser', methods=['GET', 'POST'])
@login_required
def reviser():
    # Étape 3 : Isolation des révisions
    cards = db.get_cards_to_review(current_user.id)
    
    if request.method == 'POST':
        card_id = request.form.get('card_id')
        status = request.form.get('status') # 'success' ou 'fail'
        
        db.update_card_review(card_id, current_user.id, success=(status == 'success'))
        return redirect(url_for('reviser'))

    # On passe uniquement la première carte à réviser
    current_card = cards[0] if cards else None
    return render_template('reviser.html', card=current_card, remaining=len(cards))

if __name__ == '__main__':
    app.run(debug=True)