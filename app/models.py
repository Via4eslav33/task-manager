from . import db
from flask_login import UserMixin
from datetime import datetime, date, timedelta
import pytz

KYIV_TZ = pytz.timezone('Europe/Kiev')


def kyiv_now():
    return datetime.now(KYIV_TZ).replace(tzinfo=None)


class Group(db.Model):
    __tablename__ = 'groups'
    id    = db.Column(db.Integer, primary_key=True)
    name  = db.Column(db.String(100), nullable=False, unique=True)
    users = db.relationship('User', backref='group', lazy=True)

    def __repr__(self):
        return self.name


class User(UserMixin, db.Model):
    __tablename__ = 'users'
    id            = db.Column(db.Integer, primary_key=True)
    username      = db.Column(db.String(80), unique=True, nullable=False)
    email         = db.Column(db.String(120), unique=True, nullable=False)
    full_name     = db.Column(db.String(150), nullable=False)
    password_hash = db.Column(db.String(255), nullable=False)
    role          = db.Column(db.Enum('admin', 'manager', 'executor'), default='executor', nullable=False)
    group_id      = db.Column(db.Integer, db.ForeignKey('groups.id'), nullable=True)
    is_active     = db.Column(db.Boolean, default=True)
    sort_order    = db.Column(db.Integer, default=100, nullable=False)
    created_at    = db.Column(db.DateTime, default=kyiv_now)

    calendar_token = db.Column(db.String(64), unique=True, nullable=True)
    assigned_tasks = db.relationship('TaskAssignment', backref='user', lazy=True)

    def is_admin(self):         return self.role == 'admin'
    def is_manager(self):       return self.role == 'manager'
    def can_create_tasks(self): return self.role in ('admin', 'manager')

    def role_label(self):
        return {'admin': 'Адміністратор', 'manager': 'Керівник завдань',
                'executor': 'Виконавець'}.get(self.role, self.role)


class TaskAssignment(db.Model):
    __tablename__ = 'task_assignments'
    id              = db.Column(db.Integer, primary_key=True)
    task_id         = db.Column(db.Integer, db.ForeignKey('tasks.id', ondelete='CASCADE'), nullable=False)
    user_id         = db.Column(db.Integer, db.ForeignKey('users.id', ondelete='CASCADE'), nullable=False)
    acknowledged    = db.Column(db.Boolean, default=False)
    acknowledged_at = db.Column(db.DateTime, nullable=True)
    user_rel        = db.relationship('User', foreign_keys=[user_id])


class TaskAttachment(db.Model):
    """File attached to a task."""
    __tablename__ = 'task_attachments'
    id           = db.Column(db.Integer, primary_key=True)
    task_id      = db.Column(db.Integer, db.ForeignKey('tasks.id', ondelete='CASCADE'), nullable=False)
    filename     = db.Column(db.String(255), nullable=False)   # original name shown to user
    stored_name  = db.Column(db.String(255), nullable=False)   # uuid-based name on disk
    size_bytes   = db.Column(db.Integer, nullable=False)
    uploaded_by  = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    uploaded_at  = db.Column(db.DateTime, default=kyiv_now)

    uploader = db.relationship('User', foreign_keys=[uploaded_by])

    def size_human(self):
        b = self.size_bytes
        for unit in ('Б', 'КБ', 'МБ'):
            if b < 1024:
                return f"{b:.0f} {unit}"
            b /= 1024
        return f"{b:.1f} МБ"


class Task(db.Model):
    __tablename__ = 'tasks'
    id          = db.Column(db.Integer, primary_key=True)
    title       = db.Column(db.String(255), nullable=False)
    description = db.Column(db.Text, nullable=True)
    status      = db.Column(db.Enum('new', 'in_progress', 'done', 'cancelled'),
                            default='new', nullable=False)
    priority    = db.Column(db.Enum('low', 'medium', 'high'), default='medium', nullable=False)
    date_start  = db.Column(db.Date, nullable=True)
    date_end    = db.Column(db.Date, nullable=True)
    time_start  = db.Column(db.Time, nullable=True)
    time_end    = db.Column(db.Time, nullable=True)
    recurrence  = db.Column(db.Enum('none', 'daily', 'weekly', 'monthly', 'yearly'),
                            default='none', nullable=False)
    created_by  = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    group_id    = db.Column(db.Integer, db.ForeignKey('groups.id'), nullable=True)
    created_at  = db.Column(db.DateTime, default=kyiv_now)
    updated_at  = db.Column(db.DateTime, default=kyiv_now, onupdate=kyiv_now)

    creator     = db.relationship('User', foreign_keys=[created_by])
    group       = db.relationship('Group', foreign_keys=[group_id])
    assignments = db.relationship('TaskAssignment', backref='task',
                                  lazy=True, cascade='all, delete-orphan')
    attachments = db.relationship('TaskAttachment', backref='task',
                                  lazy=True, cascade='all, delete-orphan')

    STATUS_LABELS     = {'new': 'Нове', 'in_progress': 'Виконується',
                         'done': 'Виконано', 'cancelled': 'Скасовано'}
    PRIORITY_LABELS   = {'low': 'Низький', 'medium': 'Середній', 'high': 'Високий'}
    RECURRENCE_LABELS = {'none': 'Один раз', 'daily': 'Щодня', 'weekly': 'Щотижня',
                         'monthly': 'Щомісяця', 'yearly': 'Щорічно'}

    def status_label(self):     return self.STATUS_LABELS.get(self.status, self.status)
    def priority_label(self):   return self.PRIORITY_LABELS.get(self.priority, self.priority)
    def recurrence_label(self): return self.RECURRENCE_LABELS.get(self.recurrence, self.recurrence)
    def assigned_users(self):   return [a.user_rel for a in self.assignments]
    def ack_count(self):        return sum(1 for a in self.assignments if a.acknowledged)
    def total_assignees(self):  return len(self.assignments)

    def calendar_start(self):
        d = self.date_start or self.created_at.date()
        if self.time_start:
            return f"{d.isoformat()}T{self.time_start.strftime('%H:%M:%S')}"
        return d.isoformat()

    def calendar_end(self):
        d = self.date_start or self.created_at.date()
        if self.time_end:
            return f"{d.isoformat()}T{self.time_end.strftime('%H:%M:%S')}"
        if self.time_start:
            from datetime import datetime as dt
            end_t = (dt.combine(d, self.time_start) + timedelta(hours=1)).time()
            return f"{d.isoformat()}T{end_t.strftime('%H:%M:%S')}"
        return d.isoformat()

    def rrule(self):
        if self.recurrence == 'none':
            return None
        return {'freq': {'daily': 'DAILY', 'weekly': 'WEEKLY',
                         'monthly': 'MONTHLY', 'yearly': 'YEARLY'}[self.recurrence]}
