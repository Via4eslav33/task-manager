from flask import Blueprint, render_template, redirect, url_for, request, flash
from flask_login import login_required, current_user
from werkzeug.security import generate_password_hash, check_password_hash
from .. import db
from ..models import User, Group

admin_bp = Blueprint('admin', __name__, url_prefix='/admin')


def admin_required(f):
    from functools import wraps
    @wraps(f)
    def decorated(*args, **kwargs):
        if not current_user.is_authenticated or not current_user.is_admin():
            flash('Недостатньо прав', 'error')
            return redirect(url_for('tasks.list_tasks'))
        return f(*args, **kwargs)
    return decorated


@admin_bp.route('/users')
@login_required
@admin_required
def users():
    all_users  = User.query.order_by(User.sort_order, User.full_name).all()
    all_groups = Group.query.all()
    return render_template('admin/users.html', users=all_users, groups=all_groups)


@admin_bp.route('/users/create', methods=['GET', 'POST'])
@login_required
@admin_required
def new_user():
    groups = Group.query.all()
    if request.method == 'POST':
        username  = request.form.get('username', '').strip()
        email     = request.form.get('email', '').strip()
        full_name = request.form.get('full_name', '').strip()
        role      = request.form.get('role', 'executor')
        group_id  = request.form.get('group_id') or None
        password  = request.form.get('password', '')
        sort_order = int(request.form.get('sort_order') or 100)
        if not username or not email or not password:
            flash("Заповніть усі обов'язкові поля", 'error')
            return render_template('admin/user_form.html', groups=groups)
        if User.query.filter_by(username=username).first():
            flash('Такий логін вже існує', 'error')
            return render_template('admin/user_form.html', groups=groups)
        db.session.add(User(
            username=username, email=email, full_name=full_name,
            role=role, group_id=group_id, sort_order=sort_order,
            password_hash=generate_password_hash(password)
        ))
        db.session.commit()
        flash('Користувача створено', 'success')
        return redirect(url_for('admin.users'))
    return render_template('admin/user_form.html', groups=groups, user=None)


@admin_bp.route('/users/<int:user_id>/edit', methods=['GET', 'POST'])
@login_required
@admin_required
def edit_user(user_id):
    user   = User.query.get_or_404(user_id)
    groups = Group.query.all()
    if request.method == 'POST':
        user.full_name  = request.form.get('full_name', '').strip()
        user.email      = request.form.get('email', '').strip()
        user.role       = request.form.get('role', 'executor')
        user.group_id   = request.form.get('group_id') or None
        user.is_active  = 'is_active' in request.form
        user.sort_order = int(request.form.get('sort_order') or 100)
        new_pw = request.form.get('password', '').strip()
        if new_pw:
            user.password_hash = generate_password_hash(new_pw)
        db.session.commit()
        flash('Користувача оновлено', 'success')
        return redirect(url_for('admin.users'))
    return render_template('admin/user_form.html', user=user, groups=groups)


@admin_bp.route('/groups', methods=['GET', 'POST'])
@login_required
@admin_required
def groups():
    if request.method == 'POST':
        name = request.form.get('name', '').strip()
        if name and not Group.query.filter_by(name=name).first():
            db.session.add(Group(name=name))
            db.session.commit()
            flash('Групу створено', 'success')
        else:
            flash('Назва групи порожня або вже існує', 'error')
        return redirect(url_for('admin.groups'))
    all_groups = Group.query.all()
    return render_template('admin/groups.html', groups=all_groups)


@admin_bp.route('/groups/<int:group_id>/delete', methods=['POST'])
@login_required
@admin_required
def delete_group(group_id):
    g = Group.query.get_or_404(group_id)
    move_to = request.form.get('move_to_group') or None
    if g.users:
        if not move_to:
            flash('Оберіть групу для переміщення користувачів перед видаленням', 'error')
            return redirect(url_for('admin.groups'))
        target = Group.query.get(int(move_to))
        if not target or target.id == g.id:
            flash('Обрана група недійсна', 'error')
            return redirect(url_for('admin.groups'))
        for u in g.users:
            u.group_id = target.id
        db.session.flush()
    db.session.delete(g)
    db.session.commit()
    flash(f'Групу "{g.name}" видалено', 'success')
    return redirect(url_for('admin.groups'))
