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
    Pour réinitialiser la base, simplement supprimer le fichier 'flashcards.db'
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
        
        # 2. Table des catégories (avec parent_id pour gérer les sous-catégories)
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS categories (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                parent_id INTEGER DEFAULT NULL,
                name TEXT NOT NULL,
                FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
                FOREIGN KEY (parent_id) REFERENCES categories(id) ON DELETE CASCADE
            )
        ''')

        # 3. Table des collections 
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS collections (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                category_id INTEGER, -- Peut être NULL (racine)
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
    
# --- GESTION DES CATÉGORIES & COLLECTIONS ---

def create_category(user_id, name, parent_id=None):
    """Crée une catégorie ou sous-catégorie pour un utilisateur."""
    if parent_id in (None, '', 'None', 'aucune'):
        parent_id = None
    else:
        parent_id = int(parent_id)

    with get_db_connection() as conn:
        conn.execute(
            "INSERT INTO categories (user_id, parent_id, name) VALUES (?, ?, ?)",
            (user_id, parent_id, name.strip())
        )
        conn.commit()

def get_categories_by_user(user_id):
    """Récupère TOUTES les catégories créées par l'utilisateur."""
    with get_db_connection() as conn:
        return conn.execute(
            "SELECT * FROM categories WHERE user_id = ? ORDER BY name ASC",
            (user_id,)
        ).fetchall()

def get_root_categories_by_user(user_id):
    """Récupère uniquement les catégories principales (sans parent)."""
    with get_db_connection() as conn:
        return conn.execute(
            "SELECT * FROM categories WHERE user_id = ? AND parent_id IS NULL ORDER BY name ASC",
            (user_id,)
        ).fetchall()

def get_subcategories(parent_id, user_id):
    """Récupère les sous-catégories associées à une catégorie donnée."""
    with get_db_connection() as conn:
        return conn.execute(
            "SELECT * FROM categories WHERE parent_id = ? AND user_id = ? ORDER BY name ASC",
            (parent_id, user_id)
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
    """Récupère uniquement les collections à la racine d'un utilisateur, celles sans catégorie."""
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
    
# --- GESTION DES CARTES ---

def insert_cards_bulk(collection_id, cards_list):
    """Prend une liste de tuples (question, answer) et les insère en bloc."""
    with get_db_connection() as conn:
        conn.executemany(
            "INSERT INTO cards (collection_id, question, answer) VALUES (?, ?, ?)",
            [(collection_id, q, a) for q, a in cards_list]
        )
        conn.commit()

def get_cards_by_collection(collection_id):
    """Récupère toutes les cartes associées à une collection donnée."""
    with get_db_connection() as conn:
        return conn.execute(
            "SELECT * FROM cards WHERE collection_id = ?",
            (collection_id,)
        ).fetchall()
    
def delete_card(card_id, user_id):
    """Supprime une carte après vérification de l'utilisateur."""
    with get_db_connection() as conn:
        conn.execute('''
            DELETE FROM cards 
            WHERE id = ? AND collection_id IN (
                SELECT id FROM collections WHERE user_id = ?
            )
        ''', (card_id, user_id))
        conn.commit()

def toggle_card_difficulty(card_id, user_id):
    """Inverse l'état difficile d'une carte."""
    with get_db_connection() as conn:
        conn.execute('''
            UPDATE cards 
            SET is_difficult = NOT is_difficult
            WHERE id = ? AND collection_id IN (
                SELECT id FROM collections WHERE user_id = ?
            )
        ''', (card_id, user_id))
        conn.commit()

def reset_collection_progress(collection_id):
    """Remet toutes les cartes d'une collection à is_known = 0."""
    with get_db_connection() as conn:
        conn.execute("UPDATE cards SET is_known = 0 WHERE collection_id = ?", (collection_id,))
        conn.commit()

def update_card_knowledge(card_id, is_known):
    """Met à jour le statut de révision d'une carte."""
    with get_db_connection() as conn:
        conn.execute("UPDATE cards SET is_known = ? WHERE id = ?", (int(is_known), card_id))
        conn.commit()


#GESTION DES MISES A JOUR DES DONNES DE L'USER


def delete_collection(collection_id, user_id):
    """Supprime une collection et toutes ses cartes associées."""
    with get_db_connection() as conn:
        # Les cartes liées sont supprimées automatiquement si ON DELETE CASCADE est actif,
        # sinon on les supprime explicitement par sécurité :
        conn.execute("DELETE FROM cards WHERE collection_id = ?", (collection_id,))
        conn.execute("DELETE FROM collections WHERE id = ? AND user_id = ?", (collection_id, user_id))
        conn.commit()

def move_collection(collection_id, new_category_id, user_id):
    """Déplace une collection vers une autre catégorie (ou à la racine si new_category_id est None)."""
    if new_category_id in (None, '', 'None'):
        new_category_id = None
    else:
        new_category_id = int(new_category_id)

    with get_db_connection() as conn:
        conn.execute(
            "UPDATE collections SET category_id = ? WHERE id = ? AND user_id = ?",
            (new_category_id, collection_id, user_id)
        )
        conn.commit()

def is_category_empty(category_id, user_id):
    """Vérifie si une catégorie contient des sous-catégories ou des collections."""
    with get_db_connection() as conn:
        has_subcats = conn.execute(
            "SELECT 1 FROM categories WHERE parent_id = ? AND user_id = ?", 
            (category_id, user_id)
        ).fetchone()
        
        has_cols = conn.execute(
            "SELECT 1 FROM collections WHERE category_id = ?", 
            (category_id,)
        ).fetchone()

        # Retourne True si aucun enfant trouvé
        return not (has_subcats or has_cols)

def delete_category(category_id, user_id):
    """Supprime une catégorie si et seulement si elle est vide."""
    if not is_category_empty(category_id, user_id):
        return False # Échec : le dossier n'est pas vide
        
    with get_db_connection() as conn:
        conn.execute("DELETE FROM categories WHERE id = ? AND user_id = ?", (category_id, user_id))
        conn.commit()
    return True # Succès

def merge_collections(user_id, source_col_id_1, source_col_id_2, new_name):
    """
    Fusionne deux collections (source 1 et source 2) dans une nouvelle collection.
    La nouvelle collection hérite de la catégorie/emplacement de la source 1.
    """
    with get_db_connection() as conn:
        # 1. Récupère la catégorie de la 1ère collection pour placer la nouvelle au même endroit
        col1 = conn.execute(
            "SELECT category_id FROM collections WHERE id = ? AND user_id = ?", 
            (source_col_id_1, user_id)
        ).fetchone()
        
        if not col1:
            return None
            
        category_id = col1['category_id']

        # 2. Crée la nouvelle collection
        cursor = conn.execute(
            "INSERT INTO collections (user_id, category_id, name) VALUES (?, ?, ?)",
            (user_id, category_id, new_name.strip())
        )
        new_col_id = cursor.lastrowid

        # 3. Récupère toutes les cartes de la 1ère collection et les insère dans la nouvelle
        cards_1 = conn.execute(
            "SELECT question, answer, is_difficult, is_known FROM cards WHERE collection_id = ?", 
            (source_col_id_1,)
        ).fetchall()
        
        for c in cards_1:
            conn.execute(
                "INSERT INTO cards (collection_id, question, answer, is_difficult, is_known) VALUES (?, ?, ?, ?, ?)",
                (new_col_id, c['question'], c['answer'], c['is_difficult'], c['is_known'])
            )

        # 4. Récupère toutes les cartes de la 2nde collection et les insère dans la nouvelle
        cards_2 = conn.execute(
            "SELECT question, answer, is_difficult, is_known FROM cards WHERE collection_id = ?", 
            (source_col_id_2,)
        ).fetchall()
        
        for c in cards_2:
            conn.execute(
                "INSERT INTO cards (collection_id, question, answer, is_difficult, is_known) VALUES (?, ?, ?, ?, ?)",
                (new_col_id, c['question'], c['answer'], c['is_difficult'], c['is_known'])
            )

        conn.commit()
        return new_col_id