# app.py
import os
from flask import Flask, render_template, request, redirect, url_for, session, flash, abort
from sqlalchemy import create_engine, Column, Integer, String, Text, select
from sqlalchemy.orm import declarative_base, Session as OrmSession
from sqlalchemy.exc import OperationalError
from dotenv import load_dotenv

load_dotenv()

DATABASE_URL = os.environ.get('DATABASE_URL')
if not DATABASE_URL:
    raise RuntimeError("Missing DATABASE_URL environment variable. Set it to your Railway Postgres URL.")

# Create engine
engine = create_engine(DATABASE_URL, echo=False, future=True)

Base = declarative_base()

# Models mapping to existing tables
class User(Base):
    __tablename__ = 'users'
    id = Column(Integer, primary_key=True)
    username = Column(String(150), unique=True, nullable=False)
    password = Column(String(255), nullable=False)  # currently plaintext in this example
    fullname = Column(String(255))
    description = Column(Text)
    role = Column(String(20))  # 'admin' or 'user'

class Notification(Base):
    __tablename__ = 'notifications'
    id = Column(Integer, primary_key=True)
    content = Column(Text)
    note = Column(Text)

# If you want to auto-create tables (only if they don't exist and you want to), uncomment:
# Base.metadata.create_all(engine)

app = Flask(__name__)
app.secret_key = os.environ.get('FLASK_SECRET', 'notifix_secret_key_12345')

# --- Helper utilities ---
def get_user_by_username(username: str):
    with OrmSession(engine) as s:
        stmt = select(User).where(User.username == username)
        return s.scalar(stmt)

def get_user_by_id(user_id: int):
    with OrmSession(engine) as s:
        stmt = select(User).where(User.id == user_id)
        return s.scalar(stmt)

def login_required(f):
    from functools import wraps
    @wraps(f)
    def wrapped(*args, **kwargs):
        if 'user_id' not in session:
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return wrapped

def admin_required(f):
    from functools import wraps
    @wraps(f)
    def wrapped(*args, **kwargs):
        if 'user_id' not in session:
            return redirect(url_for('login'))
        user = get_user_by_id(session['user_id'])
        if not user or user.role != 'admin':
            flash("Bạn không có quyền truy cập (cần admin).", "danger")
            return redirect(url_for('index'))
        return f(*args, **kwargs)
    return wrapped

# --- Auth routes ---
@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form.get('username','').strip()
        password = request.form.get('password','')
        user = get_user_by_username(username)
        if user:
            # SIMPLE CHECK: plaintext comparison
            if password == user.password:
                session['user_id'] = user.id
                session['username'] = user.username
                session['role'] = user.role
                flash("Đăng nhập thành công.", "success")
                return redirect(url_for('index'))
        flash("Sai username hoặc password.", "danger")
    return render_template('login.html')

@app.route('/logout')
def logout():
    session.clear()
    flash("Đã đăng xuất.", "info")
    return redirect(url_for('login'))

# --- Home / Notifications list ---
@app.route('/')
@login_required
def index():
    # redirect to notifications list
    return redirect(url_for('notifications'))

@app.route('/notifications')
@login_required
def notifications():
    with OrmSession(engine) as s:
        stmt = select(Notification).order_by(Notification.id.desc())
        notifications = s.scalars(stmt).all()
    return render_template('notifications.html', notifications=notifications)

@app.route('/notifications/<int:notification_id>')
@login_required
def notification_detail(notification_id):
    with OrmSession(engine) as s:
        stmt = select(Notification).where(Notification.id == notification_id)
        notif = s.scalar(stmt)
    if not notif:
        abort(404)
    return render_template('notification_detail.html', notif=notif)

# Admin: add / edit / delete notification
@app.route('/notifications/add', methods=['GET', 'POST'])
@admin_required
def notification_add():
    if request.method == 'POST':
        content = request.form.get('content','').strip()
        note = request.form.get('note','').strip()
        with OrmSession(engine) as s:
            n = Notification(content=content, note=note)
            s.add(n)
            s.commit()
        flash("Thông báo đã được thêm.", "success")
        return redirect(url_for('notifications'))
    return render_template('notification_form.html', action="Thêm", notif=None)

@app.route('/notifications/edit/<int:notification_id>', methods=['GET', 'POST'])
@admin_required
def notification_edit(notification_id):
    with OrmSession(engine) as s:
        n = s.get(Notification, notification_id)
        if not n:
            abort(404)
        if request.method == 'POST':
            n.content = request.form.get('content','').strip()
            n.note = request.form.get('note','').strip()
            s.add(n)
            s.commit()
            flash("Thông báo đã được cập nhật.", "success")
            return redirect(url_for('notifications'))
    return render_template('notification_form.html', action="Sửa", notif=n)

@app.route('/notifications/delete/<int:notification_id>', methods=['POST'])
@admin_required
def notification_delete(notification_id):
    with OrmSession(engine) as s:
        n = s.get(Notification, notification_id)
        if not n:
            abort(404)
        s.delete(n)
        s.commit()
    flash("Thông báo đã bị xóa.", "warning")
    return redirect(url_for('notifications'))

# --- Users (admin can manage) ---
@app.route('/users')
@admin_required
def users():
    with OrmSession(engine) as s:
        stmt = select(User).order_by(User.id)
        users = s.scalars(stmt).all()
    return render_template('users.html', users=users)

@app.route('/users/<int:user_id>')
@login_required
def user_detail(user_id):
    with OrmSession(engine) as s:
        u = s.get(User, user_id)
    if not u:
        abort(404)
    return render_template('user_detail.html', user=u)

@app.route('/users/add', methods=['GET', 'POST'])
@admin_required
def user_add():
    if request.method == 'POST':
        username = request.form.get('username','').strip()
        password = request.form.get('password','')
        fullname = request.form.get('fullname','').strip()
        description = request.form.get('description','').strip()
        role = request.form.get('role','user')
        with OrmSession(engine) as s:
            # check unique username
            exists = s.scalar(select(User).where(User.username==username))
            if exists:
                flash("Username đã tồn tại.", "danger")
                return render_template('user_form.html', action="Thêm", user=None)
            u = User(username=username, password=password, fullname=fullname, description=description, role=role)
            s.add(u)
            s.commit()
        flash("Người dùng đã được thêm.", "success")
        return redirect(url_for('users'))
    return render_template('user_form.html', action="Thêm", user=None)

@app.route('/users/edit/<int:user_id>', methods=['GET', 'POST'])
@admin_required
def user_edit(user_id):
    with OrmSession(engine) as s:
        u = s.get(User, user_id)
        if not u: abort(404)
        if request.method == 'POST':
            u.username = request.form.get('username','').strip()
            new_password = request.form.get('password','')
            if new_password:
                u.password = new_password
            u.fullname = request.form.get('fullname','').strip()
            u.description = request.form.get('description','').strip()
            u.role = request.form.get('role','user')
            s.add(u)
            s.commit()
            flash("Người dùng đã được cập nhật.", "success")
            return redirect(url_for('users'))
    return render_template('user_form.html', action="Sửa", user=u)

@app.route('/users/delete/<int:user_id>', methods=['POST'])
@admin_required
def user_delete(user_id):
    # prevent deleting self optionally
    if session.get('user_id') == user_id:
        flash("Bạn không thể xóa chính mình.", "danger")
        return redirect(url_for('users'))
    with OrmSession(engine) as s:
        u = s.get(User, user_id)
        if not u: abort(404)
        s.delete(u)
        s.commit()
    flash("Người dùng đã bị xóa.", "warning")
    return redirect(url_for('users'))

# --- Error handlers ---
@app.errorhandler(404)
def not_found(e):
    return render_template('404.html'), 404

if __name__ == '__main__':
    try:
        # quick DB test
        with engine.connect() as conn:
            pass
    except OperationalError as e:
        print("Kết nối DB thất bại:", e)
    app.run(debug=True)
