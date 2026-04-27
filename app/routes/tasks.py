import os
import re
import uuid
from flask import (Blueprint, render_template, redirect, url_for,
                   request, flash, jsonify, current_app, send_from_directory, abort)
from flask_login import login_required, current_user
from datetime import datetime, date, time as dtime
from .. import db
from ..models import Task, TaskAssignment, TaskAttachment, User, Group, kyiv_now
from .auth import effective_role
from ..email_utils import send_task_assigned

tasks_bp = Blueprint('tasks', __name__, url_prefix='/tasks')

# ── File upload config ────────────────────────────────────────────
MAX_FILES        = 10
MAX_FILE_BYTES   = 10 * 1024 * 1024          # 10 MB per file
ALLOWED_EXTENSIONS = {
    'pdf', 'doc', 'docx', 'xls', 'xlsx', 'ppt', 'pptx',
    'txt', 'csv', 'odt', 'ods', 'odp',
    'png', 'jpg', 'jpeg', 'gif', 'webp', 'svg',
    'zip', 'rar', '7z',
}

def _upload_dir():
    d = os.path.join(current_app.root_path, '..', 'uploads')
    os.makedirs(d, exist_ok=True)
    return os.path.abspath(d)

def _allowed(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

def _ext_icon(filename):
    ext = filename.rsplit('.', 1)[-1].lower() if '.' in filename else ''
    icons = {
        'pdf': '📄', 'doc': '📝', 'docx': '📝', 'xls': '📊', 'xlsx': '📊',
        'ppt': '📋', 'pptx': '📋', 'txt': '📃', 'csv': '📊',
        'png': '🖼', 'jpg': '🖼', 'jpeg': '🖼', 'gif': '🖼', 'webp': '🖼',
        'zip': '📦', 'rar': '📦', '7z': '📦',
    }
    return icons.get(ext, '📎')

def _safe_filename(raw: str) -> str:
    """
    Keep original filename (including Cyrillic/spaces) but strip dangerous chars.
    Only removes: / \ : * ? " < > | and control chars.
    """
    # take only the basename
    name = os.path.basename(raw)
    # strip shell-dangerous characters but keep Unicode letters, digits, spaces, dots, dashes
    name = re.sub(r'[/\\:*?"<>|\x00-\x1f]', '_', name)
    name = name.strip('. ')   # no leading/trailing dots or spaces
    return name or 'file'

# Register icon helper so templates can use it
def register_template_helpers(app):
    app.jinja_env.globals['ext_icon'] = _ext_icon

# ── Helpers ───────────────────────────────────────────────────────
def _parse_date(s): return datetime.strptime(s, '%Y-%m-%d').date() if s else None
def _parse_time(s):
    if not s: return None
    try:
        h, m = s.split(':'); return dtime(int(h), int(m))
    except Exception: return None

def _save_uploads(task_id, files):
    """Save uploaded files and create TaskAttachment records. Returns error string or None."""
    saved = 0
    for f in files:
        if not f or not f.filename:
            continue
        if saved >= MAX_FILES:
            return f'Максимум {MAX_FILES} вкладень'
        if not _allowed(f.filename):
            return f'Файл «{f.filename}» — недозволений тип'
        # read to check size
        data = f.read()
        if len(data) > MAX_FILE_BYTES:
            return f'Файл «{f.filename}» перевищує 10 МБ'
        # unique stored name
        ext         = f.filename.rsplit('.', 1)[-1].lower()
        stored_name = f"{uuid.uuid4().hex}.{ext}"
        dest        = os.path.join(_upload_dir(), stored_name)
        with open(dest, 'wb') as fp:
            fp.write(data)
        db.session.add(TaskAttachment(
            task_id     = task_id,
            filename    = _safe_filename(f.filename),
            stored_name = stored_name,
            size_bytes  = len(data),
            uploaded_by = current_user.id,
        ))
        saved += 1
    return None

def _task_from_form():
    return dict(
        title        = request.form.get('title', '').strip(),
        description  = request.form.get('description', '').strip(),
        status       = request.form.get('status', 'new'),
        priority     = request.form.get('priority', 'medium'),
        group_id     = request.form.get('group_id') or None,
        date_start   = _parse_date(request.form.get('date_start') or None),
        date_end     = _parse_date(request.form.get('date_end') or None),
        time_start   = _parse_time(request.form.get('time_start') or None),
        time_end     = _parse_time(request.form.get('time_end') or None),
        recurrence   = request.form.get('recurrence', 'none'),
        assignee_ids = request.form.getlist('assignees'),
    )

# ── Routes ────────────────────────────────────────────────────────
@tasks_bp.route('/')
@login_required
def list_tasks():
    status   = request.args.get('status', '')
    group_id = request.args.get('group_id', '')
    priority = request.args.get('priority', '')

    role = effective_role()
    if role == 'admin':
        q = Task.query
    elif role == 'manager':
        aids = [a.task_id for a in current_user.assigned_tasks]
        q = Task.query.filter(db.or_(Task.created_by == current_user.id, Task.id.in_(aids)))
    else:
        aids = [a.task_id for a in current_user.assigned_tasks]
        q = Task.query.filter(Task.id.in_(aids))

    if status:   q = q.filter(Task.status == status)
    if group_id: q = q.filter(Task.group_id == group_id)
    if priority: q = q.filter(Task.priority == priority)

    return render_template('tasks/list.html',
        tasks=q.order_by(Task.created_at.desc()).all(),
        groups=Group.query.all(),
        status=status, group_id=group_id, priority=priority,
        today_date=date.today())


@tasks_bp.route('/create', methods=['GET', 'POST'])
@login_required
def new_task():
    if not current_user.can_create_tasks():
        flash('Недостатньо прав', 'error')
        return redirect(url_for('tasks.list_tasks'))

    users  = User.query.filter_by(is_active=True).order_by(User.sort_order, User.full_name).all()
    groups = Group.query.all()

    if request.method == 'POST':
        f = _task_from_form()
        if not f['title']:
            flash("Назва завдання обов'язкова", 'error')
            return render_template('tasks/form.html', users=users, groups=groups)

        # Check file count before saving
        files = request.files.getlist('attachments')
        real_files = [x for x in files if x and x.filename]
        if len(real_files) > MAX_FILES:
            flash(f'Максимум {MAX_FILES} вкладень', 'error')
            return render_template('tasks/form.html', users=users, groups=groups)

        task = Task(
            title=f['title'], description=f['description'],
            status=f['status'], priority=f['priority'], group_id=f['group_id'],
            date_start=f['date_start'], date_end=f['date_end'],
            time_start=f['time_start'], time_end=f['time_end'],
            recurrence=f['recurrence'], created_by=current_user.id
        )
        db.session.add(task)
        db.session.flush()

        # Attachments
        err = _save_uploads(task.id, real_files)
        if err:
            db.session.rollback()
            flash(err, 'error')
            return render_template('tasks/form.html', users=users, groups=groups)

        # Assignees
        new_users = []
        for uid in f['assignee_ids']:
            u = User.query.get(int(uid))
            if u:
                db.session.add(TaskAssignment(task_id=task.id, user_id=u.id))
                new_users.append(u)

        db.session.commit()
        if new_users:
            send_task_assigned(task, new_users)
        flash('Завдання створено', 'success')
        return redirect(url_for('tasks.list_tasks'))

    return render_template('tasks/form.html', users=users, groups=groups, task=None)


@tasks_bp.route('/<int:task_id>', methods=['GET'])
@login_required
def view_task(task_id):
    task = Task.query.get_or_404(task_id)
    role = effective_role()
    if role != 'admin':
        if role == 'manager' or current_user.is_manager():
            aids = [a.task_id for a in current_user.assigned_tasks]
            if task.created_by != current_user.id and task_id not in aids:
                flash('Немає доступу', 'error'); return redirect(url_for('tasks.list_tasks'))
        else:
            if task_id not in [a.task_id for a in current_user.assigned_tasks]:
                flash('Немає доступу', 'error'); return redirect(url_for('tasks.list_tasks'))
    my_assignment = TaskAssignment.query.filter_by(task_id=task_id, user_id=current_user.id).first()
    return render_template('tasks/view.html', task=task, my_assignment=my_assignment)


@tasks_bp.route('/<int:task_id>/edit', methods=['GET', 'POST'])
@login_required
def edit_task(task_id):
    task = Task.query.get_or_404(task_id)
    if not current_user.is_admin() and not (current_user.is_manager() and task.created_by == current_user.id):
        flash('Недостатньо прав', 'error'); return redirect(url_for('tasks.list_tasks'))

    users  = User.query.filter_by(is_active=True).order_by(User.sort_order, User.full_name).all()
    groups = Group.query.all()

    if request.method == 'POST':
        f = _task_from_form()
        task.title=f['title']; task.description=f['description']
        task.status=f['status']; task.priority=f['priority']; task.group_id=f['group_id']
        task.date_start=f['date_start']; task.date_end=f['date_end']
        task.time_start=f['time_start']; task.time_end=f['time_end']
        task.recurrence=f['recurrence']

        # New file uploads
        files      = request.files.getlist('attachments')
        real_files = [x for x in files if x and x.filename]
        existing   = len(task.attachments)
        if existing + len(real_files) > MAX_FILES:
            flash(f'Максимум {MAX_FILES} вкладень (зараз {existing})', 'error')
            return render_template('tasks/form.html', task=task, users=users, groups=groups)
        if real_files:
            err = _save_uploads(task.id, real_files)
            if err:
                flash(err, 'error')
                return render_template('tasks/form.html', task=task, users=users, groups=groups)

        # Assignees
        existing_ids = {a.user_id for a in task.assignments}
        new_ids      = {int(uid) for uid in f['assignee_ids']}
        for a in task.assignments:
            if a.user_id not in new_ids: db.session.delete(a)
        newly = []
        for uid in new_ids:
            if uid not in existing_ids:
                u = User.query.get(uid)
                if u:
                    db.session.add(TaskAssignment(task_id=task.id, user_id=uid))
                    newly.append(u)

        db.session.commit()
        if newly: send_task_assigned(task, newly)
        flash('Завдання оновлено', 'success')
        return redirect(url_for('tasks.view_task', task_id=task.id))

    return render_template('tasks/form.html', task=task, users=users, groups=groups)


@tasks_bp.route('/<int:task_id>/delete', methods=['POST'])
@login_required
def delete_task(task_id):
    task = Task.query.get_or_404(task_id)
    if not current_user.is_admin() and not (current_user.is_manager() and task.created_by == current_user.id):
        return jsonify({'error': 'forbidden'}), 403
    # Delete stored files
    for att in task.attachments:
        try:
            os.remove(os.path.join(_upload_dir(), att.stored_name))
        except OSError:
            pass
    db.session.delete(task)
    db.session.commit()
    flash('Завдання видалено', 'success')
    return redirect(url_for('tasks.list_tasks'))


@tasks_bp.route('/<int:task_id>/attachments/<int:att_id>/delete', methods=['POST'])
@login_required
def delete_attachment(task_id, att_id):
    task = Task.query.get_or_404(task_id)
    if not current_user.is_admin() and not (current_user.is_manager() and task.created_by == current_user.id):
        abort(403)
    att = TaskAttachment.query.filter_by(id=att_id, task_id=task_id).first_or_404()
    try:
        os.remove(os.path.join(_upload_dir(), att.stored_name))
    except OSError:
        pass
    db.session.delete(att)
    db.session.commit()
    flash('Вкладення видалено', 'success')
    return redirect(url_for('tasks.view_task', task_id=task_id))


def _check_att_access(task):
    """Return True if current user can access attachments of this task."""
    if current_user.is_admin():
        return True
    if current_user.is_manager():
        aids = [a.task_id for a in current_user.assigned_tasks]
        return task.created_by == current_user.id or task.id in aids
    return task.id in [a.task_id for a in current_user.assigned_tasks]


def _make_content_disposition(disposition, filename):
    """
    Build a Content-Disposition header that correctly encodes Unicode filenames.
    Uses RFC 5987 encoding: filename*=UTF-8''encoded
    All major browsers (Chrome, Firefox, Edge, Safari) support this.
    """
    from urllib.parse import quote
    encoded = quote(filename, safe='')
    # Provide both ASCII fallback and UTF-8 encoded version
    ascii_name = filename.encode('ascii', 'replace').decode('ascii')
    return f'{disposition}; filename="{ascii_name}"; filename*=UTF-8''{encoded}'


@tasks_bp.route('/<int:task_id>/attachments/<int:att_id>/download')
@login_required
def download_attachment(task_id, att_id):
    task = Task.query.get_or_404(task_id)
    if not _check_att_access(task):
        abort(403)
    att  = TaskAttachment.query.filter_by(id=att_id, task_id=task_id).first_or_404()
    path = os.path.join(_upload_dir(), att.stored_name)

    from flask import send_file
    resp = send_file(path, as_attachment=False)
    resp.headers['Content-Disposition'] = _make_content_disposition('attachment', att.filename)
    return resp


@tasks_bp.route('/<int:task_id>/attachments/<int:att_id>/preview')
@login_required
def preview_attachment(task_id, att_id):
    """Serve file inline so the browser can display it without downloading."""
    task = Task.query.get_or_404(task_id)
    if not _check_att_access(task):
        abort(403)
    att = TaskAttachment.query.filter_by(id=att_id, task_id=task_id).first_or_404()
    ext = att.stored_name.rsplit('.', 1)[-1].lower()

    MIME_MAP = {
        'pdf':  'application/pdf',
        'png':  'image/png',
        'jpg':  'image/jpeg',
        'jpeg': 'image/jpeg',
        'gif':  'image/gif',
        'webp': 'image/webp',
        'svg':  'image/svg+xml',
        'txt':  'text/plain; charset=utf-8',
        'csv':  'text/plain; charset=utf-8',
    }
    mime = MIME_MAP.get(ext)
    path = os.path.join(_upload_dir(), att.stored_name)

    from flask import send_file
    if not mime:
        # Not previewable — force download with correct filename
        resp = send_file(path, as_attachment=False)
        resp.headers['Content-Disposition'] = _make_content_disposition('attachment', att.filename)
        return resp

    # Serve inline — browser will display PDF/image/text directly
    resp = send_file(path, mimetype=mime.split(';')[0].strip(), as_attachment=False)
    # inline disposition with proper Unicode filename
    resp.headers['Content-Disposition'] = _make_content_disposition('inline', att.filename)
    # Important: allow iframe embedding (needed for PDF in modal)
    resp.headers.pop('X-Frame-Options', None)
    resp.headers['X-Content-Type-Options'] = 'nosniff'
    return resp


@tasks_bp.route('/<int:task_id>/acknowledge', methods=['POST'])
@login_required
def acknowledge(task_id):
    a = TaskAssignment.query.filter_by(task_id=task_id, user_id=current_user.id).first_or_404()
    a.acknowledged = True; a.acknowledged_at = kyiv_now()
    db.session.commit()
    flash('Ознайомлення підтверджено', 'success')
    return redirect(url_for('tasks.view_task', task_id=task_id))


@tasks_bp.route('/<int:task_id>/status', methods=['POST'])
@login_required
def update_status(task_id):
    task = Task.query.get_or_404(task_id)
    s = request.form.get('status')
    if s in ('new', 'in_progress', 'done', 'cancelled'):
        task.status = s; db.session.commit(); flash('Статус оновлено', 'success')
    return redirect(url_for('tasks.view_task', task_id=task_id))
