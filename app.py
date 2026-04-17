# -*- coding: utf-8 -*-
"""MiniForum - 轻量级论坛 (Supabase PostgreSQL)"""
import os
import sys
import urllib.parse
import traceback
from datetime import datetime
from functools import wraps

from flask import (
    Flask, render_template, request, redirect, url_for,
    session, flash, g, abort, Response, jsonify
)
from werkzeug.security import generate_password_hash, check_password_hash
import psycopg2
from psycopg2.extras import RealDictCursor
from psycopg2 import pool
import mistune

app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', 'miniforum-default-secret')

# Supabase PostgreSQL connection (SSL required)
DATABASE_URL = os.environ.get('DATABASE_URL', '').encode().decode('utf-8-sig')  # 移除 BOM
db_config = urllib.parse.urlparse(DATABASE_URL)

# ─── 数据库工具 ────────────────────────────────────────────

def get_db_connection():
    """获取新的数据库连接（每次请求创建，适合 serverless）"""
    if not DATABASE_URL:
        raise Exception("DATABASE_URL not set")
    try:
        # 使用解析后的配置，显式设置 sslmode
        conn = psycopg2.connect(
            host=db_config.hostname,
            port=db_config.port or 5432,
            database=db_config.path.lstrip('/') or 'postgres',
            user=db_config.username,
            password=db_config.password,
            sslmode='require',
            connect_timeout=10
        )
        return conn
    except Exception as e:
        print(f"连接错误: {e}", file=sys.stderr)
        raise

def get_db():
    """获取数据库连接"""
    if 'db' not in g:
        g.db = get_db_connection()
    return g.db

@app.teardown_appcontext
def close_db(e=None):
    db = g.pop('db', None)
    if db:
        try:
            db.close()
        except:
            pass

# Markdown 渲染器
md = mistune.create_markdown(escape=False, plugins=['strikethrough', 'footnotes', 'table'])

# ─── 数据库工具 ────────────────────────────────────────────

def query_one(sql, args=()):
    cur = get_db().cursor(cursor_factory=RealDictCursor)
    cur.execute(sql, args)
    return cur.fetchone()

def query_all(sql, args=()):
    cur = get_db().cursor(cursor_factory=RealDictCursor)
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
            parent_id  INTEGER REFERENCES replies(id) ON DELETE CASCADE,
            content    TEXT    NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        ''')
        
        execute('''
        CREATE TABLE IF NOT EXISTS notifications (
            id          SERIAL PRIMARY KEY,
            user_id     INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            type        TEXT    NOT NULL,
            from_user_id INTEGER REFERENCES users(id) ON DELETE CASCADE,
            post_id     INTEGER REFERENCES posts(id) ON DELETE CASCADE,
            reply_id    INTEGER REFERENCES replies(id) ON DELETE CASCADE,
            is_read     INTEGER DEFAULT 0,
            created_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        ''')
        
        execute('CREATE INDEX IF NOT EXISTS idx_posts_user ON posts(user_id)')
        execute('CREATE INDEX IF NOT EXISTS idx_posts_time ON posts(created_at DESC)')
        execute('CREATE INDEX IF NOT EXISTS idx_replies_post ON replies(post_id)')
        execute('CREATE INDEX IF NOT EXISTS idx_replies_parent ON replies(parent_id)')
        execute('CREATE INDEX IF NOT EXISTS idx_notifs_user ON notifications(user_id)')
        execute('CREATE INDEX IF NOT EXISTS idx_notifs_read ON notifications(user_id, is_read)')
        
        # 创建默认管理员
        existing = query_one('SELECT id FROM users WHERE username=%s', ('admin',))
        if not existing:
            execute(
                'INSERT INTO users (username, password_hash, is_admin) VALUES (%s, %s, 1)',
                ('admin', generate_password_hash('admin123'))
            )
    except Exception as e:
        print(f"初始化数据库错误: {e}", file=sys.stderr)
        traceback.print_exc(file=sys.stderr)

# 初始化数据库表（启动时执行）
with app.app_context():
    try:
        init_db()
    except Exception as e:
        print(f"数据库初始化警告: {e}", file=sys.stderr)

# ─── 错误处理 ──────────────────────────────────────────────

@app.errorhandler(500)
def internal_error(e):
    print(f"500 Error: {e}", file=sys.stderr)
    traceback.print_exc(file=sys.stderr)
    return f"Server Error: {e}", 500

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
def date_filter(dt_str, fmt=None):
    if not dt_str:
        return ''
    try:
        if isinstance(dt_str, str):
            dt = datetime.strptime(dt_str.split('.')[0], '%Y-%m-%d %H:%M:%S')
        else:
            dt = dt_str
        if fmt:
            return dt.strftime(fmt)
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
        try:
            user = query_one('SELECT * FROM users WHERE id=%s', (session['user_id'],))
        except:
            pass
    return dict(current_user=user, now_year=datetime.now().year)

# ─── 路由 ──────────────────────────────────────────────────

@app.route('/')
def index():
    try:
        page = max(1, int(request.args.get('page', 1)))
        per_page = 20
        offset = (page - 1) * per_page
        total = query_one('SELECT COUNT(*) FROM posts')['count']
        
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
    except Exception as e:
        print(f"Index error: {e}", file=sys.stderr)
        traceback.print_exc(file=sys.stderr)
        return f"Error loading posts: {e}", 500

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
            parent_id = request.form.get('parent_id')
            parent_id = int(parent_id) if parent_id else None
            execute(
                'INSERT INTO replies (post_id, user_id, parent_id, content) VALUES (%s, %s, %s, %s)',
                (post_id, session['user_id'], parent_id, content)
            )
            # 通知：回复帖子 或 回复别人的回复
            reply_author = post['user_id']
            notif_type = 'reply_post'
            if parent_id:
                parent = query_one('SELECT user_id FROM replies WHERE id=%s', (parent_id,))
                if parent:
                    reply_author = parent['user_id']
                    notif_type = 'reply_reply'
            if reply_author != session['user_id']:
                execute(
                    'INSERT INTO notifications (user_id, type, from_user_id, post_id, reply_id) VALUES (%s, %s, %s, %s, %s)',
                    (reply_author, notif_type, session['user_id'], post_id, None)
                )
            flash('回复成功', 'success')
        return redirect(url_for('view_post', post_id=post_id) + '#reply-' + str(parent_id or ''))

    replies = query_all(
        '''SELECT r.*, u.username
           FROM replies r JOIN users u ON r.user_id=u.id
           WHERE r.post_id=%s ORDER BY r.created_at''',
        (post_id,)
    )
    # 构建嵌套树结构
    top_replies = []
    children_map = {}
    for r in replies:
        r['children'] = []
        children_map[r['id']] = r
    for r in replies:
        if r['parent_id']:
            parent = children_map.get(r['parent_id'])
            if parent:
                parent['children'].append(r)
        else:
            top_replies.append(r)
    return render_template('post.html', post=post, replies=replies, top_replies=top_replies)

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

# ─── 我的页面 ──────────────────────────────────────────────

@app.route('/my')
@login_required
def my_page():
    my_posts = query_all(
        '''SELECT p.*, u.username,
                  (SELECT COUNT(*) FROM replies r WHERE r.post_id=p.id) AS reply_count
           FROM posts p JOIN users u ON p.user_id=u.id
           WHERE p.user_id=%s
           ORDER BY p.created_at DESC''',
        (session['user_id'],)
    )
    my_replies = query_all(
        '''SELECT r.*, p.title AS post_title, p.id AS post_id,
                  u.username AS replier_username
           FROM replies r
           JOIN posts p ON r.post_id=p.id
           JOIN users u ON r.user_id=u.id
           WHERE r.user_id=%s
           ORDER BY r.created_at DESC
           LIMIT 100''',
        (session['user_id'],)
    )
    return render_template('my.html', my_posts=my_posts, my_replies=my_replies)

@app.route('/edit/<int:pid>', methods=['GET', 'POST'])
@login_required
def edit_post(pid):
    post = query_one('SELECT * FROM posts WHERE id=%s', (pid,))
    if not post:
        abort(404)
    if post['user_id'] != session['user_id']:
        abort(403)
    if request.method == 'POST':
        title = request.form.get('title', '').strip()
        content = request.form.get('content', '').strip()
        if not title or not content:
            flash('标题和内容不能为空', 'error')
        else:
            execute('UPDATE posts SET title=%s, content=%s WHERE id=%s',
                    (title, content, pid))
            flash('帖子已更新', 'success')
            return redirect(url_for('view_post', post_id=pid))
    return render_template('edit_post.html', post=post)

@app.route('/delete_post/<int:pid>', methods=['POST'])
@login_required
def delete_post(pid):
    post = query_one('SELECT user_id FROM posts WHERE id=%s', (pid,))
    if post and post['user_id'] == session['user_id']:
        execute('DELETE FROM posts WHERE id=%s', (pid,))
        flash('帖子已删除', 'success')
    return redirect(url_for('my_page'))

@app.route('/api/notifications/count')
@login_required
def notifications_count():
    count = query_one(
        'SELECT COUNT(*) FROM notifications WHERE user_id=%s AND is_read=0',
        (session['user_id'],)
    )
    return jsonify({'count': count['count'] if count else 0})

# ─── 个人中心 ──────────────────────────────────────────────

@app.route('/profile', methods=['GET', 'POST'])
@login_required
def profile():
    user = query_one('SELECT id, username, email, qq, is_admin, created_at FROM users WHERE id=%s', (session['user_id'],))
    if request.method == 'POST':
        action = request.form.get('action')
        if action == 'change_password':
            old_pw = request.form.get('old_password', '')
            new_pw = request.form.get('new_password', '')
            new_pw2 = request.form.get('new_password2', '')
            if not check_password_hash(user['password_hash'], old_pw):
                flash('原密码错误', 'error')
            elif len(new_pw) < 6:
                flash('新密码至少6位', 'error')
            elif new_pw != new_pw2:
                flash('两次密码不一致', 'error')
            else:
                execute('UPDATE users SET password_hash=%s WHERE id=%s',
                        (generate_password_hash(new_pw), session['user_id']))
                flash('密码修改成功', 'success')
        elif action == 'update_info':
            email = request.form.get('email', '').strip()
            qq = request.form.get('qq', '').strip()
            existing_email = query_one('SELECT id FROM users WHERE email=%s AND id!=%s', (email, session['user_id']))
            existing_qq = query_one('SELECT id FROM users WHERE qq=%s AND id!=%s', (qq, session['user_id']))
            if email and existing_email:
                flash('邮箱已被使用', 'error')
            elif qq and existing_qq:
                flash('QQ号已被使用', 'error')
            else:
                execute('UPDATE users SET email=%s, qq=%s WHERE id=%s',
                        (email or None, qq or None, session['user_id']))
                flash('个人信息更新成功', 'success')
        return redirect(url_for('profile'))
    return render_template('profile.html', user=user)

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

@app.route('/admin/change_password/<int:uid>', methods=['GET', 'POST'])
@admin_required
def admin_change_password(uid):
    target = query_one('SELECT id, username FROM users WHERE id=%s', (uid,))
    if not target:
        abort(404)
    if request.method == 'POST':
        new_pw = request.form.get('new_password', '')
        new_pw2 = request.form.get('new_password2', '')
        if not new_pw or len(new_pw) < 6:
            flash('密码至少6位', 'error')
        elif new_pw != new_pw2:
            flash('两次密码不一致', 'error')
        else:
            execute('UPDATE users SET password_hash=%s WHERE id=%s',
                    (generate_password_hash(new_pw), uid))
            flash(f'用户【{target["username"]}】密码已修改', 'success')
            return redirect(url_for('admin'))
    return render_template('admin_change_password.html', target=target)

# ─── 安装路由 ──────────────────────────────────────────────

@app.route('/setup')
def setup():
    """初始化数据库并创建管理员账号"""
    try:
        init_db()
        admin = query_one('SELECT id FROM users WHERE username=%s', ('admin',))
        if not admin:
            execute(
                'INSERT INTO users (username, password_hash, is_admin) VALUES (%s, %s, 1)',
                ('admin', generate_password_hash('admin123'))
            )
            return '管理员创建成功！用户名: admin 密码: admin123'
        return f'管理员已存在 (id={admin["id"]})，数据库初始化完成'
    except Exception as e:
        return f'错误: {e}', 500

# ─── 调试路由 ──────────────────────────────────────────────

@app.route('/debug')
def debug():
    """调试端点 - 检查环境变量和数据库连接"""
    import json
    # 解析连接字符串
    db_info = {}
    if DATABASE_URL:
        try:
            # 尝试解析 URL
            import urllib.parse
            parsed = urllib.parse.urlparse(DATABASE_URL)
            db_info = {
                'scheme': parsed.scheme,
                'host': parsed.hostname,
                'port': parsed.port,
                'database': parsed.path.lstrip('/') if parsed.path else None,
                'user': parsed.username,
                # 不显示完整密码
                'password_set': bool(parsed.password),
            }
        except Exception as e:
            db_info = {'parse_error': str(e)}
    
    info = {
        'DATABASE_URL': db_info,
        'SECRET_KEY': '***' if app.secret_key else 'NOT SET',
    }
    return json.dumps(info, indent=2)

@app.route('/test')
def test_db():
    """测试数据库连接"""
    try:
        result = query_one('SELECT NOW() as now')
        return f"数据库连接成功: {result['now']}"
    except Exception as e:
        import traceback
        return f"数据库错误: {e}\n\n{traceback.format_exc()}", 500

# Vercel serverless function handler
def handler(environ, start_response):
    return app(environ, start_response)
