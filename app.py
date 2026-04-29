#!/usr/bin/env python3
"""
WesternLocate - AI Guide for Western Region Ghana (Final Strict Version)
"""

import os
import sqlite3
import uuid
from flask import Flask, render_template, request, redirect, url_for, jsonify, flash, g
from flask_login import LoginManager, UserMixin, login_user, logout_user, login_required, current_user
from werkzeug.security import generate_password_hash, check_password_hash
from groq import Groq
from dotenv import load_dotenv

load_dotenv()

app = Flask(__name__)
app.config['SECRET_KEY'] = os.getenv('SECRET_KEY', 'dev-secret-key-change-in-production')
app.config['DATABASE_PATH'] = os.getenv('DATABASE_PATH', 'instance/westernlocate.db')
os.makedirs(os.path.dirname(app.config['DATABASE_PATH']), exist_ok=True)

groq_client = Groq(api_key=os.getenv('GROQ_API_KEY'))

login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'

def get_db():
    if 'db' not in g:
        g.db = sqlite3.connect(app.config['DATABASE_PATH'])
        g.db.row_factory = sqlite3.Row
    return g.db

def close_db(e=None):
    db = g.pop('db', None)
    if db is not None:
        db.close()
app.teardown_appcontext(close_db)

def init_db():
    db = get_db()
    cursor = db.cursor()
    cursor.execute('''CREATE TABLE IF NOT EXISTS users (id INTEGER PRIMARY KEY AUTOINCREMENT, username TEXT UNIQUE NOT NULL, email TEXT UNIQUE NOT NULL, password_hash TEXT NOT NULL, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)''')
    cursor.execute('''CREATE TABLE IF NOT EXISTS conversations (id TEXT PRIMARY KEY, user_id INTEGER NOT NULL, title TEXT NOT NULL, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP, updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP, FOREIGN KEY (user_id) REFERENCES users (id))''')
    cursor.execute('''CREATE TABLE IF NOT EXISTS messages (id INTEGER PRIMARY KEY AUTOINCREMENT, conversation_id TEXT NOT NULL, role TEXT NOT NULL CHECK(role IN ('user', 'assistant')), content TEXT NOT NULL, timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP, FOREIGN KEY (conversation_id) REFERENCES conversations (id))''')
    db.commit()
    print("✅ Database initialized successfully")

with app.app_context():
    init_db()

class User(UserMixin):
    def __init__(self, id, username, email):
        self.id = id
        self.username = username
        self.email = email

@login_manager.user_loader
def load_user(user_id):
    db = get_db()
    user = db.execute('SELECT * FROM users WHERE id = ?', (user_id,)).fetchone()
    return User(user['id'], user['username'], user['email']) if user else None

# ==================== STRICT SYSTEM PROMPT ====================
SYSTEM_PROMPT = """You are WesternLocate, a professional AI Guide for the Western Region of Ghana.

STRICT RESPONSE RULES - FOLLOW EXACTLY:

1. NEVER start with "Hello", "Hi", or any greeting. Start directly with the content.
2. When giving multiple recommendations, ALWAYS use this exact format:

1. **Place Name** (Type: Beach / Fort / School / Hospital / Festival / Hotel / Restaurant)
   Short clear description.
   ⭐ Rating: X.X/5
   💬 "Realistic review quote"
   [🗺️ View on Google Maps](https://www.google.com/maps/search/?api=1&query=Place+Name+Western+Region+Ghana)

   (Leave one blank line here)

2. **Next Place Name** (Type: ...)
   ...

3. Use proper spacing. Put a blank line between each numbered item.
4. Keep responses clean, professional, and easy to read.
5. Only recommend places in Western Region Ghana.
6. End every response with exactly this sentence: "Would you like more options or help with directions?"

User's name: {username}
Current date: April 2026

Be concise and professional."""

def get_groq_response(messages, username="Traveler"):
    try:
        system_msg = {"role": "system", "content": SYSTEM_PROMPT.format(username=username)}
        full_messages = [system_msg] + messages
        chat_completion = groq_client.chat.completions.create(
            messages=full_messages,
            model="llama-3.3-70b-versatile",
            temperature=0.6,
            max_tokens=1800,
            top_p=0.9,
            stream=False
        )
        return chat_completion.choices[0].message.content.strip()
    except Exception as e:
        return "I'm having a small connection issue. Please try again! 🌍"

# ==================== ROUTES ====================
@app.route('/')
def index():
    if current_user.is_authenticated:
        return redirect(url_for('chat'))
    return redirect(url_for('login'))

@app.route('/register', methods=['GET', 'POST'])
def register():
    if current_user.is_authenticated:
        return redirect(url_for('chat'))
    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        email = request.form.get('email', '').strip().lower()
        password = request.form.get('password', '')
        confirm = request.form.get('confirm', '')
        if not username or not email or not password:
            flash('All fields are required.', 'error')
            return render_template('register.html')
        if password != confirm:
            flash('Passwords do not match.', 'error')
            return render_template('register.html')
        if len(password) < 6:
            flash('Password must be at least 6 characters.', 'error')
            return render_template('register.html')
        db = get_db()
        if db.execute('SELECT id FROM users WHERE username = ? OR email = ?', (username, email)).fetchone():
            flash('Username or email already exists.', 'error')
            return render_template('register.html')
        password_hash = generate_password_hash(password)
        db.execute('INSERT INTO users (username, email, password_hash) VALUES (?, ?, ?)', (username, email, password_hash))
        db.commit()
        flash('Account created successfully! Please log in.', 'success')
        return redirect(url_for('login'))
    return render_template('register.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated:
        return redirect(url_for('chat'))
    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '')
        db = get_db()
        user = db.execute('SELECT * FROM users WHERE username = ?', (username,)).fetchone()
        if user and check_password_hash(user['password_hash'], password):
            user_obj = User(user['id'], user['username'], user['email'])
            login_user(user_obj, remember=True)
            flash(f'Welcome back, {user["username"]}!', 'success')
            return redirect(url_for('chat'))
        else:
            flash('Invalid username or password.', 'error')
    return render_template('login.html')

@app.route('/logout')
@login_required
def logout():
    logout_user()
    flash('You have been logged out.', 'info')
    return redirect(url_for('login'))

@app.route('/chat')
@login_required
def chat():
    return render_template('chat.html', username=current_user.username)

@app.route('/api/chat', methods=['POST'])
@login_required
def api_chat():
    data = request.get_json()
    user_message = data.get('message', '').strip()
    conversation_id = data.get('conversation_id')
    if not user_message:
        return jsonify({'error': 'Message cannot be empty'}), 400
    db = get_db()
    if not conversation_id:
        conversation_id = str(uuid.uuid4())
        title = user_message[:50] + "..." if len(user_message) > 50 else user_message
        db.execute('INSERT INTO conversations (id, user_id, title) VALUES (?, ?, ?)', (conversation_id, current_user.id, title))
        db.commit()
        is_new = True
    else:
        is_new = False
    db.execute('INSERT INTO messages (conversation_id, role, content) VALUES (?, ?, ?)', (conversation_id, 'user', user_message))
    db.commit()
    history = db.execute('SELECT role, content FROM messages WHERE conversation_id = ? ORDER BY timestamp DESC LIMIT 12', (conversation_id,)).fetchall()
    history = list(reversed(history))
    messages_for_llm = [{"role": m['role'], "content": m['content']} for m in history]
    ai_response = get_groq_response(messages_for_llm, current_user.username)
    db.execute('INSERT INTO messages (conversation_id, role, content) VALUES (?, ?, ?)', (conversation_id, 'assistant', ai_response))
    db.execute('UPDATE conversations SET updated_at = CURRENT_TIMESTAMP WHERE id = ?', (conversation_id,))
    db.commit()
    return jsonify({'response': ai_response, 'conversation_id': conversation_id, 'is_new': is_new})

@app.route('/api/conversations', methods=['GET'])
@login_required
def api_conversations():
    db = get_db()
    convos = db.execute('SELECT id, title, created_at, updated_at FROM conversations WHERE user_id = ? ORDER BY updated_at DESC', (current_user.id,)).fetchall()
    return jsonify([{'id': c['id'], 'title': c['title'], 'created_at': c['created_at'], 'updated_at': c['updated_at']} for c in convos])

@app.route('/api/conversation/<conv_id>', methods=['GET'])
@login_required
def api_conversation(conv_id):
    db = get_db()
    conv = db.execute('SELECT * FROM conversations WHERE id = ? AND user_id = ?', (conv_id, current_user.id)).fetchone()
    if not conv:
        return jsonify({'error': 'Conversation not found'}), 404
    messages = db.execute('SELECT role, content, timestamp FROM messages WHERE conversation_id = ? ORDER BY timestamp ASC', (conv_id,)).fetchall()
    return jsonify({'id': conv_id, 'title': conv['title'], 'messages': [{'role': m['role'], 'content': m['content'], 'timestamp': m['timestamp']} for m in messages]})

if __name__ == '__main__':
    print("🚀 Starting WesternLocate- Western Region Ghana Edition")
    print("📍 Access at: http://127.0.0.1:5000")
    app.run(debug=True, host='0.0.0.0', port=5000)