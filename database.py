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
                user_id INTEGER NOT NULL,
                category_id INTEGER, -- Peut être NULL maintenant !
                name TEXT NOT NULL,
                FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
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
    
# --- GESTION DES CATÉGORIES & COLLECTIONS  ---

def create_category(user_id, name):
    """Crée une nouvelle catégorie pour un utilisateur spécifique."""
    with get_db_connection() as conn:
        conn.execute(
            "INSERT INTO categories (user_id, name) VALUES (?, ?)",
            (user_id, name.strip())
        )
        conn.commit()

def get_categories_by_user(user_id):
    """Récupère toutes les catégories créées par l'utilisateur."""
    with get_db_connection() as conn:
        return conn.execute(
            "SELECT * FROM categories WHERE user_id = ? ORDER BY name ASC",
            (user_id,)
        ).fetchall()

def create_collection(user_id, category_id, name):
    """Crée une collection liée à l'utilisateur (avec ou sans catégorie)."""
    with get_db_connection() as conn:
        if category_id in (None, '', 'None', 'aucune'):
            conn.execute(
                "INSERT INTO collections (user_id, category_id, name) VALUES (?, NULL, ?)",
                (user_id, name.strip())
            )
        else:
            conn.execute(
                "INSERT INTO collections (user_id, category_id, name) VALUES (?, ?, ?)",
                (user_id, int(category_id), name.strip())
            )
        conn.commit()

def get_collections_by_category(category_id):
    """Récupère toutes les collections contenues dans une catégorie."""
    with get_db_connection() as conn:
        return conn.execute(
            "SELECT * FROM collections WHERE category_id = ? ORDER BY name ASC",
            (category_id,)
        ).fetchall()
    
def get_root_collections_by_user(user_id):
    """Récupère uniquement les collections à la racine d'un utilisateur, celles sans catégorie"""
    with get_db_connection() as conn:
        return conn.execute(
            "SELECT * FROM collections WHERE user_id = ? AND category_id IS NULL ORDER BY name ASC",
            (user_id,)
        ).fetchall()
    
def get_collection_details(collection_id, user_id):
    """Récupère les détails d'une collection (racine ou non) en vérifiant la sécurité."""
    with get_db_connection() as conn:
        return conn.execute('''
            SELECT 
                collections.*, 
                categories.name AS category_name
            FROM collections
            LEFT JOIN categories ON collections.category_id = categories.id
            WHERE collections.id = ? AND collections.user_id = ?
        ''', (collection_id, user_id)).fetchone()