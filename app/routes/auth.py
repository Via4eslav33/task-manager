from flask import Blueprint, render_template, redirect, url_for, request, flash, session
from flask_login import login_user, logout_user, login_required, current_user
from werkzeug.security import check_password_hash
from ..models import User

auth_bp = Blueprint('auth', __name__)

ADMIN_MODE_KEY = 'admin_mode_active'


def is_admin_mode():
    """Returns True if admin user has explicitly switched to admin mode."""
    if not current_user.is_authenticated or not current_user.is_admin():
        return False
    return session.get(ADMIN_MODE_KEY, False)


def effective_role():
    """
    Returns the effective role for display/filtering purposes.
    Admin in admin_mode → 'admin'
    Admin NOT in admin_mode → behaves like 'manager' (sees only own tasks)
    Everyone else → their real role
    """
    if not current_user.is_authenticated:
        return None
    if current_user.is_admin():
        return 'admin' if is_admin_mode() else 'manager'
    return current_user.role


@auth_bp.route('/', methods=['GET'])
def index():
    if current_user.is_authenticated:
        return redirect(url_for('tasks.list_tasks'))
    return redirect(url_for('auth.login'))


@auth_bp.route('/login', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated:
        return redirect(url_for('tasks.list_tasks'))
    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '')
        user = User.query.filter_by(username=username).first()
        if user and check_password_hash(user.password_hash, password) and user.is_active:
            login_user(user, remember=True)
            # Admins start in manager mode by default (clean calendar)
            session[ADMIN_MODE_KEY] = False
            return redirect(url_for('tasks.list_tasks'))
        flash('Невірний логін або пароль', 'error')
    return render_template('login.html')


@auth_bp.route('/logout')
@login_required
def logout():
    logout_user()
    session.pop(ADMIN_MODE_KEY, None)
    return redirect(url_for('auth.login'))


@auth_bp.route('/switch-mode', methods=['POST'])
@login_required
def switch_mode():
    """Toggle admin mode on/off. Only for users with role=admin."""
    if not current_user.is_admin():
        flash('Недостатньо прав', 'error')
        return redirect(url_for('tasks.list_tasks'))
    current = session.get(ADMIN_MODE_KEY, False)
    session[ADMIN_MODE_KEY] = not current
    next_url = request.form.get('next') or url_for('tasks.list_tasks')
    return redirect(next_url)


@auth_bp.route('/profile/password', methods=['GET', 'POST'])
@login_required
def change_password():
    """Any logged-in user can change their own password."""
    if request.method == 'POST':
        current_pw  = request.form.get('current_password', '')
        new_pw      = request.form.get('new_password', '').strip()
        confirm_pw  = request.form.get('confirm_password', '').strip()

        from werkzeug.security import check_password_hash, generate_password_hash
        if not check_password_hash(current_user.password_hash, current_pw):
            flash('Поточний пароль вказано невірно', 'error')
            return render_template('profile/change_password.html')
        if len(new_pw) < 6:
            flash('Новий пароль має містити щонайменше 6 символів', 'error')
            return render_template('profile/change_password.html')
        if new_pw != confirm_pw:
            flash('Паролі не збігаються', 'error')
            return render_template('profile/change_password.html')

        from .. import db
        current_user.password_hash = generate_password_hash(new_pw)
        db.session.commit()
        flash('Пароль успішно змінено', 'success')
        return redirect(url_for('tasks.list_tasks'))

    return render_template('profile/change_password.html')
