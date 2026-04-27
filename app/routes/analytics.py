from flask import Blueprint, render_template, redirect, url_for, flash
from flask_login import login_required, current_user
from sqlalchemy import func
from datetime import date
from ..models import Task, TaskAssignment, User, Group
from .auth import effective_role
from .. import db

analytics_bp = Blueprint('analytics', __name__, url_prefix='/analytics')


@analytics_bp.route('/')
@login_required
def dashboard():
    # Only admin and manager can see analytics
    if not current_user.can_create_tasks():  # managers and admins
        flash('Недостатньо прав', 'error')
        return redirect(url_for('tasks.list_tasks'))

    today = date.today()

    # Scope: admin sees all, manager sees only their tasks
    role = effective_role()
    if role == 'admin':
        task_q = Task.query
    else:
        assigned_ids = [a.task_id for a in current_user.assigned_tasks]
        task_q = Task.query.filter(
            db.or_(Task.created_by == current_user.id,
                   Task.id.in_(assigned_ids))
        )

    all_tasks = task_q.all()
    task_ids  = [t.id for t in all_tasks]

    total   = len(task_ids)
    new_c   = sum(1 for t in all_tasks if t.status == 'new')
    inprog  = sum(1 for t in all_tasks if t.status == 'in_progress')
    done_c  = sum(1 for t in all_tasks if t.status == 'done')
    overdue = sum(1 for t in all_tasks
                  if t.status in ('new', 'in_progress') and t.date_end and t.date_end < today)

    # By group (scoped)
    if current_user.is_admin():
        groups_data = db.session.query(
            Group.name, func.count(Task.id)
        ).outerjoin(Task, Task.group_id == Group.id).group_by(Group.id).all()
    else:
        groups_data = db.session.query(
            Group.name, func.count(Task.id)
        ).outerjoin(Task, Task.group_id == Group.id)\
         .filter(db.or_(Task.id.in_(task_ids), Task.id.is_(None)))\
         .group_by(Group.id).all()

    # By status (scoped)
    status_data = db.session.query(
        Task.status, func.count(Task.id)
    ).filter(Task.id.in_(task_ids)).group_by(Task.status).all()

    # Acknowledgment rate (scoped)
    ack_q     = TaskAssignment.query.filter(TaskAssignment.task_id.in_(task_ids))
    total_ass = ack_q.count()
    acked     = ack_q.filter_by(acknowledged=True).count()
    ack_rate  = round(acked / total_ass * 100) if total_ass else 0

    # Top executors (scoped)
    top_users = db.session.query(
        User.full_name, func.count(TaskAssignment.id).label('cnt')
    ).join(TaskAssignment, TaskAssignment.user_id == User.id)\
     .join(Task, Task.id == TaskAssignment.task_id)\
     .filter(Task.status == 'done', Task.id.in_(task_ids))\
     .group_by(User.id)\
     .order_by(func.count(TaskAssignment.id).desc())\
     .limit(5).all()

    # Recent tasks (scoped)
    recent = task_q.order_by(Task.created_at.desc()).limit(10).all()

    return render_template('analytics/dashboard.html',
        total=total, new_c=new_c, inprog=inprog, done_c=done_c,
        overdue=overdue, groups_data=groups_data, status_data=status_data,
        ack_rate=ack_rate, top_users=top_users, recent=recent, today=today
    )
