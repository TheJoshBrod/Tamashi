import json
import sqlite3
from datetime import datetime

# --- The actual subagent tools (Notice NO @tool decorator) ---

DB_PATH = "nutrition.db"

def init_db():
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute('''
            CREATE TABLE IF NOT EXISTS meals (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT NOT NULL,
                log_text TEXT NOT NULL,
                calories INTEGER,
                protein_g INTEGER,
                carbs_g INTEGER,
                fat_g INTEGER,
                summary TEXT
            )
        ''')
        conn.commit()

init_db()

def log_meal_data(calories: int, protein_g: int, carbs_g: int, fat_g: int, summary: str, original_description: str) -> str:
    """Saves the fully parsed nutritional macro data to the database."""
    try:
        timestamp = datetime.now().isoformat()
        with sqlite3.connect(DB_PATH) as conn:
            conn.execute('''
                INSERT INTO meals (timestamp, log_text, calories, protein_g, carbs_g, fat_g, summary)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            ''', (timestamp, original_description, calories, protein_g, carbs_g, fat_g, summary))
        return f"Logged meal successfully: {calories} kcal | {protein_g}g P | {carbs_g}g C | {fat_g}g F"
    except Exception as e:
        return f"Error logging data: {e}"

def query_nutrition_db(sql_query: str) -> str:
    """Executes a RAW SQLite SELECT query on the `meals` table.
    Schema: meals(id INTEGER, timestamp TEXT, log_text TEXT, calories INTEGER, protein_g INTEGER, carbs_g INTEGER, fat_g INTEGER, summary TEXT).
    Use this to execute precise lookups, aggregations, averages, or searches to answer the user's questions.
    """
    if not sql_query.strip().upper().startswith("SELECT"):
        return "Error: For safety, only SELECT queries are permitted."
    
    try:
        with sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(sql_query).fetchall()
            
        if not rows:
            return "Query returned 0 results."
            
        results = []
        for r in rows:
            results.append(str(dict(r)))
            
        return '\n'.join(results)
    except Exception as e:
        return f"SQL Error: {e}"

def update_meal_data(meal_id: int, calories: int, protein_g: int, carbs_g: int, fat_g: int, summary: str) -> str:
    """Updates an existing meal with new macro information."""
    try:
        with sqlite3.connect(DB_PATH) as conn:
            cur = conn.cursor()
            cur.execute('''
                UPDATE meals 
                SET calories=?, protein_g=?, carbs_g=?, fat_g=?, summary=?
                WHERE id=?
            ''', (calories, protein_g, carbs_g, fat_g, summary, meal_id))
            conn.commit()
            if cur.rowcount == 0:
                return f"No meal found with id {meal_id}"
        return f"Updated meal {meal_id} successfully: {calories} kcal | {protein_g}g P | {carbs_g}g C | {fat_g}g F"
    except Exception as e:
        return f"Error updating data: {e}"

def delete_meal_data(meal_id: int) -> str:
    """Deletes a meal from history."""
    try:
        with sqlite3.connect(DB_PATH) as conn:
            cur = conn.cursor()
            cur.execute("DELETE FROM meals WHERE id=?", (meal_id,))
            conn.commit()
            if cur.rowcount == 0:
                return f"No meal found with id {meal_id}"
        return f"Deleted meal {meal_id} successfully."
    except Exception as e:
        return f"Error deleting data: {e}"

# --- The Subagent Registration ---
from subagents.registry import define_subagent
from tools.web_search import web_search
from tools.time import get_current_time

define_subagent(
    name="nutrition",
    tools=[log_meal_data, query_nutrition_db, update_meal_data, delete_meal_data, web_search, get_current_time]
)
