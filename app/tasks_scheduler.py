from datetime import date


def send_reminders(app):
    with app.app_context():
        from .models import Task, TaskAssignment
        from .email_utils import send_overdue_reminder

        today = date.today()
        overdue = Task.query.filter(
            Task.status.in_(['new', 'in_progress']),
            Task.date_end < today
        ).all()

        for task in overdue:
            users = [a.user_rel for a in task.assignments if a.user_rel.is_active]
            if users:
                send_overdue_reminder(task, users)
