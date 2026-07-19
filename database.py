import sqlite3
from werkzeug.security import generate_password_hash, check_password_hash

DB_NAME = "flashcards.db"

def get_db_connection():
    """Crée une connexion active à la base de données avec support des clés étrangères."""
    conn = sqlite3.connect(DB_NAME)
    conn.execute("PRAGMA foreign_keys = ON;")  # Permet d'activer les suppressions en cascade
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    """
    Initialise la base de données et crée les tables si elles n'existent pas.
    Pour rénitialiser la base, simplement supprimer le fichier 'flashcards.db'
    """
    with get_db_connection() as conn:
        cursor = conn.cursor()
        
        # 1. Table des utilisateurs
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT UNIQUE NOT NULL,
                password_hash TEXT NOT NULL
            )
        ''')
        
        # 2. Table des catégories 
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS categories (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                name TEXT NOT NULL,
                FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
            )
        ''')

        # 3. Table des collections 
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS collections (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                category_id INTEGER NOT NULL,
                name TEXT NOT NULL,
                FOREIGN KEY (category_id) REFERENCES categories(id) ON DELETE CASCADE
            )
        ''')
        
        # 4. Table des cartes 
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS cards (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                collection_id INTEGER NOT NULL,
                question TEXT NOT NULL,
                answer TEXT NOT NULL,
                is_known INTEGER DEFAULT 0,
                is_difficult INTEGER DEFAULT 0,
                FOREIGN KEY (collection_id) REFERENCES collections(id) ON DELETE CASCADE
            )
        ''')
        conn.commit()

# --- GESTION DES UTILISATEURS ---

def create_user(username, password):
    """Hache le mot de passe et enregistre un utilisateur."""
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
        return False  # Nom d'utilisateur déjà pris

def get_user_by_id(user_id):
    """Récupère un utilisateur par son ID."""
    with get_db_connection() as conn:
        return conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()

def get_user_by_username(username):
    """Récupère un utilisateur par son nom d'utilisateur."""
    with get_db_connection() as conn:
        return conn.execute("SELECT * FROM users WHERE username = ?", (username,)).fetchone()