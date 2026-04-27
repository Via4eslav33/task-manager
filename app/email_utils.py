from flask_mail import Message
from . import mail
from flask import current_app


def send_task_assigned(task, users):
    """Send email to newly assigned users."""
    for user in users:
        if not user.email:
            continue
        try:
            msg = Message(
                subject=f'Нове завдання: {task.title}',
                recipients=[user.email]
            )
            msg.body = f"""Вітаємо, {user.full_name}!

Вам призначено нове завдання.

Назва: {task.title}
{'Опис: ' + task.description if task.description else ''}
{'Дата початку: ' + task.date_start.strftime('%d.%m.%Y') if task.date_start else ''}
{'Дата завершення: ' + task.date_end.strftime('%d.%m.%Y') if task.date_end else ''}
Пріоритет: {task.priority_label()}

Будь ласка, ознайомтесь із завданням та підтвердьте ознайомлення в системі.

https://tasks.tmo2lviv.pp.ua/
"""
            mail.send(msg)
        except Exception as e:
            current_app.logger.error(f'Mail error for {user.email}: {e}')


def send_overdue_reminder(task, users):
    """Send reminder for overdue tasks."""
    for user in users:
        if not user.email:
            continue
        try:
            msg = Message(
                subject=f'Нагадування: невиконане завдання "{task.title}"',
                recipients=[user.email]
            )
            msg.body = f"""Вітаємо, {user.full_name}!

Нагадуємо, що завдання ще не виконано.

Назва: {task.title}
{'Термін завершення: ' + task.date_end.strftime('%d.%m.%Y') if task.date_end else ''}
Статус: {task.status_label()}

Будь ласка, оновіть статус завдання або зверніться до керівника.

https://tasks.tmo2lviv.pp.ua/
"""
            mail.send(msg)
        except Exception as e:
            current_app.logger.error(f'Reminder mail error for {user.email}: {e}')
