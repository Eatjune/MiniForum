# -*- coding: utf-8 -*-
"""MiniForum - 轻量级论坛 (Supabase PostgreSQL)"""
import os
import re
import secrets
from datetime import datetime
from functools import wraps

from flask import (
    Flask, render_template, request, redirect, url_for,
    session, flash, g, abort, Response
)
from werkzeug.security import generate_password_hash, check_password_hash
import psycopg2
from psycopg2.extras import RealDictCursor
import mistune

app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', secrets.token_hex(32))

# Supabase PostgreSQL connection
DATABASE_URL = os.environ.get('DATABASE_URL')

def get_db():
    """获取数据库连接"""
    if 'db' not in g:
        g.db = psycopg2.connect(DATABASE_URL, cursor_factory=RealDictCursor)
    return g.db

@app.teardown_appcontext
def close_db(e=None):
    db = g.pop('db', None)
    if db:
        db.close()

# Markdown 渲染器
md = mistune.create_markdown(escape=False, plugins=['strikethrough', 'footnotes', 'table'])

# ─── 数据库工具 ────────────────────────────────────────────

def query_one(sql, args=()):
    cur = get_db().cursor()
    cur.execute(sql, args)
    return cur.fetchone()

def query_all(sql, args=()):
    cur = get_db().cursor()
    cur.execute(sql, args)
    return cur.fetchall()

def execute(sql, args=()):
    db = get_db()
    cur = db.cursor()
    cur.execute(sql, args)
    db.commit()

# ─── 初始化 ────────────────────────────────────────────────

def init_db():
    """初始化数据库表"""
    try:
        execute('''
        CREATE TABLE IF NOT EXISTS users (
            id         SERIAL PRIMARY KEY,
            username   TEXT    UNIQUE NOT NULL,
            email      TEXT    UNIQUE,
            qq         TEXT    UNIQUE,
            password_hash TEXT  NOT NULL,
            is_admin   INTEGER DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        ''')
        
        execute('''
        CREATE TABLE IF NOT EXISTS posts (
            id         SERIAL PRIMARY KEY,
            user_id    INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            title      TEXT    NOT NULL,
            content    TEXT    NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        ''')
        
        execute('''
        CREATE TABLE IF NOT EXISTS replies (
            id         SERIAL PRIMARY KEY,
            post_id    INTEGER NOT NULL REFERENCES posts(id) ON DELETE CASCADE,
            user_id    INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            content    TEXT    NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        ''')
        
        execute('CREATE INDEX IF NOT EXISTS idx_posts_user ON posts(user_id)')
        execute('CREATE INDEX IF NOT EXISTS idx_posts_time ON posts(created_at DESC)')
        execute('CREATE INDEX IF NOT EXISTS idx_replies_post ON replies(post_id)')
        
        # 创建默认管理员
        existing = query_one('SELECT id FROM users WHERE username=%s', ('admin',))
        if not existing:
            execute(
                'INSERT INTO users (username, password_hash, is_admin) VALUES (%s, %s, 1)',
                ('admin', generate_password_hash('admin123'))
            )
    except Exception as e:
        print(f"初始化数据库: {e}")

with app.app_context():
    init_db()

# ─── 认证装饰器 ────────────────────────────────────────────

def login_required(f):
    @wraps(f)
    def decorated(*a, **kw):
        if 'user_id' not in session:
            return redirect(url_for('login', next=request.full_path))
        return f(*a, **kw)
    return decorated

def admin_required(f):
    @wraps(f)
    def decorated(*a, **kw):
        if 'user_id' not in session:
            return redirect(url_for('login', next=request.full_path))
        user = query_one('SELECT is_admin FROM users WHERE id=%s', (session['user_id'],))
        if not user or not user['is_admin']:
            abort(403)
        return f(*a, **kw)
    return decorated

# ─── 模板工具 ──────────────────────────────────────────────

@app.template_filter('markdown')
def markdown_filter(text):
    if not text:
        return ''
    return md(text)

@app.template_filter('date')
def date_filter(dt_str):
    if not dt_str:
        return ''
    try:
        if isinstance(dt_str, str):
            dt = datetime.strptime(dt_str.split('.')[0], '%Y-%m-%d %H:%M:%S')
        else:
            dt = dt_str
        return dt.strftime('%m-%d %H:%M')
    except:
        return str(dt_str)

@app.template_filter('truncate')
def truncate_filter(s, n=100):
    s = str(s)
    return s[:n] + ('…' if len(s) > n else '')

@app.context_processor
def inject_user():
    user = None
    if 'user_id' in session:
        user = query_one('SELECT * FROM users WHERE id=%s', (session['user_id'],))
    return dict(current_user=user, now_year=datetime.now().year)

# ─── 路由 ──────────────────────────────────────────────────

@app.route('/')
def index():
    page = max(1, int(request.args.get('page', 1)))
    per_page = 20
    offset = (page - 1) * per_page
    total = query_one('SELECT COUNT(*) FROM posts')[0]
    
    posts = query_all(
        '''SELECT p.*, u.username,
                  (SELECT COUNT(*) FROM replies r WHERE r.post_id=p.id) AS reply_count
           FROM posts p JOIN users u ON p.user_id=u.id
           ORDER BY p.created_at DESC
           LIMIT %s OFFSET %s''',
        (per_page, offset)
    )
    total_pages = (total + per_page - 1) // per_page
    return render_template('index.html',
        posts=posts, page=page, total_pages=total_pages
    )

@app.route('/post/<int:post_id>', methods=['GET', 'POST'])
def view_post(post_id):
    post = query_one(
        '''SELECT p.*, u.username
           FROM posts p JOIN users u ON p.user_id=u.id
           WHERE p.id=%s''', (post_id,)
    )
    if not post:
        abort(404)

    if request.method == 'POST':
        if 'user_id' not in session:
            return redirect(url_for('login'))
        content = request.form.get('content', '').strip()
        if content:
            execute(
                'INSERT INTO replies (post_id, user_id, content) VALUES (%s, %s, %s)',
                (post_id, session['user_id'], content)
            )
            flash('回复成功', 'success')
        return redirect(url_for('view_post', post_id=post_id))

    replies = query_all(
        '''SELECT r.*, u.username
           FROM replies r JOIN users u ON r.user_id=u.id
           WHERE r.post_id=%s ORDER BY r.created_at''',
        (post_id,)
    )
    return render_template('post.html', post=post, replies=replies)

@app.route('/new', methods=['GET', 'POST'])
@login_required
def new_post():
    if request.method == 'POST':
        title = request.form.get('title', '').strip()
        content = request.form.get('content', '').strip()
        if title and content:
            execute(
                'INSERT INTO posts (user_id, title, content) VALUES (%s, %s, %s)',
                (session['user_id'], title, content)
            )
            flash('发帖成功', 'success')
            return redirect(url_for('index'))
        flash('标题和内容不能为空', 'error')
    return render_template('new_post.html')

# ─── 认证 ──────────────────────────────────────────────────

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '')
        password2 = request.form.get('password2', '')
        email = request.form.get('email', '').strip()
        qq = request.form.get('qq', '').strip()

        if not username or not password:
            flash('用户名和密码不能为空', 'error')
        elif password != password2:
            flash('两次密码不一致', 'error')
        elif not email and not qq:
            flash('请填写 QQ号 或 邮箱（至少一个）', 'error')
        elif query_one('SELECT id FROM users WHERE username=%s', (username,)):
            flash('用户名已存在', 'error')
        elif email and query_one('SELECT id FROM users WHERE email=%s', (email,)):
            flash('邮箱已被注册', 'error')
        elif qq and query_one('SELECT id FROM users WHERE qq=%s', (qq,)):
            flash('QQ号已被注册', 'error')
        else:
            execute(
                '''INSERT INTO users (username, email, qq, password_hash)
                   VALUES (%s, %s, %s, %s)''',
                (username, email or None, qq or None,
                 generate_password_hash(password))
            )
            flash('注册成功，请登录', 'success')
            return redirect(url_for('login'))
    return render_template('register.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        identifier = request.form.get('identifier', '').strip()
        password = request.form.get('password', '')

        user = None
        if '@' in identifier:
            user = query_one('SELECT * FROM users WHERE email=%s', (identifier,))
        elif identifier.isdigit():
            user = query_one('SELECT * FROM users WHERE qq=%s', (identifier,))

        if not user:
            user = query_one('SELECT * FROM users WHERE username=%s', (identifier,))

        if user and check_password_hash(user['password_hash'], password):
            session['user_id'] = user['id']
            session['username'] = user['username']
            flash(f'欢迎回来，{user["username"]}', 'success')
            next_url = request.form.get('next') or request.args.get('next') or url_for('index')
            return redirect(next_url)
        flash('登录失败，请检查账号密码', 'error')
    return render_template('login.html')

@app.route('/logout')
def logout():
    session.clear()
    flash('已退出登录', 'info')
    return redirect(url_for('index'))

# ─── 管理后台 ──────────────────────────────────────────────

@app.route('/admin')
@admin_required
def admin():
    users = query_all('SELECT * FROM users ORDER BY created_at DESC')
    posts = query_all(
        '''SELECT p.*, u.username
           FROM posts p JOIN users u ON p.user_id=u.id
           ORDER BY p.created_at DESC LIMIT 50'''
    )
    replies = query_all(
        '''SELECT r.*, u.username, p.title AS post_title
           FROM replies r
           JOIN users u ON r.user_id=u.id
           JOIN posts p ON r.post_id=p.id
           ORDER BY r.created_at DESC LIMIT 50'''
    )
    return render_template('admin.html',
        users=users, posts=posts, replies=replies
    )

@app.route('/admin/delete/user/<int:uid>', methods=['POST'])
@admin_required
def admin_delete_user(uid):
    if uid == session['user_id']:
        flash('不能删除自己', 'error')
    else:
        execute('DELETE FROM replies WHERE user_id=%s', (uid,))
        execute('DELETE FROM posts WHERE user_id=%s', (uid,))
        execute('DELETE FROM users WHERE id=%s', (uid,))
        flash('用户已删除', 'success')
    return redirect(url_for('admin'))

@app.route('/admin/delete/post/<int:pid>', methods=['POST'])
@admin_required
def admin_delete_post(pid):
    execute('DELETE FROM replies WHERE post_id=%s', (pid,))
    execute('DELETE FROM posts WHERE id=%s', (pid,))
    flash('帖子已删除', 'success')
    return redirect(url_for('admin'))

@app.route('/admin/delete/reply/<int:rid>', methods=['POST'])
@admin_required
def admin_delete_reply(rid):
    execute('DELETE FROM replies WHERE id=%s', (rid,))
    flash('回复已删除', 'success')
    return redirect(url_for('admin'))

@app.route('/admin/toggle_admin/<int:uid>', methods=['POST'])
@admin_required
def admin_toggle_admin(uid):
    if uid == session['user_id']:
        flash('不能修改自己的权限', 'error')
    else:
        current = query_one('SELECT is_admin FROM users WHERE id=%s', (uid,))
        if current:
            execute('UPDATE users SET is_admin=%s WHERE id=%s',
                    (0 if current['is_admin'] else 1, uid))
            flash('权限已更新', 'success')
    return redirect(url_for('admin'))

# Vercel serverless function handler
def handler(environ, start_response):
    return app(environ, start_response)
