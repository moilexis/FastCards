import sqlite3
from datetime import datetime, timedelta
from werkzeug.security import generate_password_hash, check_password_hash

DB_NAME = "flashcards.db"

def get_db_connection():
    """Crée une connexion active à la base de données avec gestion des lignes par nom."""
    conn = sqlite3.connect(DB_NAME)
    conn.row_factory = sqlite3.Row  # Permet d'accéder aux colonnes par leur nom : row['username']
    return conn

def init_db():
    """Initialise la base de données et crée les tables si elles n'existent pas."""
    with get_db_connection() as conn:
        cursor = conn.cursor()
        
        # Table des utilisateurs
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT UNIQUE NOT NULL,
                password_hash TEXT NOT NULL
            )
        ''')
        
        # Table des cartes (liée à l'utilisateur)
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS cards (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                question TEXT NOT NULL,
                answer TEXT NOT NULL,
                next_review_date TEXT,
                box_level INTEGER DEFAULT 1,
                FOREIGN KEY (user_id) REFERENCES users(id)
            )
        ''')
        conn.commit()

# --- GESTION DES UTILISATEURS ---

def create_user(username, password):
    """Hache le mot de passe et crée un utilisateur. Retourne False si le pseudo existe déjà."""
    hashed_password = generate_password_hash(password)
    try:
        with get_db_connection() as conn:
            conn.execute(
                "INSERT INTO users (username, password_hash) VALUES (?, ?)",
                (username, hashed_password)
            )
            conn.commit()
        return True
    except sqlite3.IntegrityError:
        return False  # Le nom d'utilisateur existe déjà

def get_user_by_id(user_id):
    """Récupère un utilisateur via son ID (requis pour Flask-Login)."""
    with get_db_connection() as conn:
        return conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()

def get_user_by_username(username):
    """Récupère un utilisateur via son pseudo (pour la connexion)."""
    with get_db_connection() as conn:
        return conn.execute("SELECT * FROM users WHERE username = ?", (username,)).fetchone()

# --- GESTION DES CARTES (ISOLATION PAR USER_ID) ---

def insert_card(user_id, question, answer):
    """Insère une nouvelle carte pour un utilisateur spécifique."""
    today_str = datetime.now().strftime('%Y-%m-%d')
    with get_db_connection() as conn:
        conn.execute(
            "INSERT INTO cards (user_id, question, answer, next_review_date) VALUES (?, ?, ?, ?)",
            (user_id, question.strip(), answer.strip(), today_str)
        )
        conn.commit()

def get_cards_to_review(user_id):
    """Récupère uniquement les cartes de l'utilisateur qui sont dues aujourd'hui ou en retard."""
    today_str = datetime.now().strftime('%Y-%m-%d')
    with get_db_connection() as conn:
        return conn.execute(
            "SELECT * FROM cards WHERE user_id = ? AND next_review_date <= ?",
            (user_id, today_str)
        ).fetchall()

def update_card_review(card_id, user_id, success):
    """
    Système Leitner : Si succès, augmente le niveau de la boîte (+ de jours d'attente).
    Si échec, retour à la boîte 1 (révision le lendemain).
    """
    with get_db_connection() as conn:
        # Sécurité : On vérifie que la carte appartient bien à l'utilisateur
        card = conn.execute("SELECT * FROM cards WHERE id = ? AND user_id = ?", (card_id, user_id)).fetchone()
        if not card:
            return

        current_level = card['box_level']
        
        if success:
            new_level = current_level + 1
            # Jours à ajouter selon le niveau (Ex: Niveau 1 = 1j, Niveau 2 = 2j, Niveau 3 = 4j...)
            days_to_add = 2 ** (new_level - 1)
        else:
            new_level = 1
            days_to_add = 1

        next_date = (datetime.now() + timedelta(days=days_to_add)).strftime('%Y-%m-%d')
        
        conn.execute(
            "UPDATE cards SET box_level = ?, next_review_date = ? WHERE id = ?",
            (new_level, next_date, card_id)
        )
        conn.commit()