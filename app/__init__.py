from flask import Flask
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager
from flask_mail import Mail
from flask_apscheduler import APScheduler
import os

db = SQLAlchemy()
login_manager = LoginManager()
mail = Mail()
scheduler = APScheduler()

def create_app():
    app = Flask(__name__)

    app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'change-me-in-production')
    app.config['SQLALCHEMY_DATABASE_URI'] = os.environ.get(
        'DATABASE_URL',
        'mysql+pymysql://taskuser:taskpass@db:3306/taskmanager'
    )
    app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
    app.config['MAX_CONTENT_LENGTH'] = 10 * 1024 * 1024 * 10  # 10 files × 10 MB headroom

    # Mail config
    app.config['MAIL_SERVER']   = os.environ.get('MAIL_SERVER', 'smtp.gmail.com')
    app.config['MAIL_PORT']     = int(os.environ.get('MAIL_PORT', 587))
    app.config['MAIL_USE_TLS']  = os.environ.get('MAIL_USE_TLS', 'true').lower() == 'true'
    app.config['MAIL_USERNAME'] = os.environ.get('MAIL_USERNAME', '')
    app.config['MAIL_PASSWORD'] = os.environ.get('MAIL_PASSWORD', '')
    app.config['MAIL_DEFAULT_SENDER'] = os.environ.get('MAIL_DEFAULT_SENDER', '')

    # Scheduler
    app.config['SCHEDULER_API_ENABLED'] = False

    db.init_app(app)
    login_manager.init_app(app)
    mail.init_app(app)

    login_manager.login_view = 'auth.login'
    login_manager.login_message = 'Будь ласка, увійдіть для доступу до системи.'

    from .models import User
    @login_manager.user_loader
    def load_user(user_id):
        return User.query.get(int(user_id))

    from .routes.auth import auth_bp
    from .routes.tasks import tasks_bp
    from .routes.calendar import calendar_bp
    from .routes.admin import admin_bp
    from .routes.analytics import analytics_bp

    app.register_blueprint(auth_bp)
    app.register_blueprint(tasks_bp)
    app.register_blueprint(calendar_bp)
    app.register_blueprint(admin_bp)
    app.register_blueprint(analytics_bp)

    from .routes.tasks import register_template_helpers
    register_template_helpers(app)

    with app.app_context():
        db.create_all()
        _seed_defaults()

    # Scheduler for reminders
    # Час вказується за Київським часовим поясом (Europe/Kiev)
    # Змініть REMINDER_HOUR і REMINDER_MINUTE за потребою
    REMINDER_HOUR   = int(os.environ.get('REMINDER_HOUR', 8))
    REMINDER_MINUTE = int(os.environ.get('REMINDER_MINUTE', 0))

    if not scheduler.running:
        scheduler.init_app(app)
        from .tasks_scheduler import send_reminders
        scheduler.add_job(
            id='reminders',
            func=send_reminders,
            args=[app],
            trigger='cron',
            hour=REMINDER_HOUR,
            minute=REMINDER_MINUTE,
            timezone='Europe/Kyiv'   # ← Київський час, не UTC
        )
        scheduler.start()

    return app


def _seed_defaults():
    from .models import Group, User
    from werkzeug.security import generate_password_hash
    if not Group.query.first():
        for name in ['Управління', 'Кадри', 'Бухгалтерія']:
            db.session.add(Group(name=name))
        db.session.commit()
    if not User.query.filter_by(username='admin').first():
        g = Group.query.first()
        u = User(username='admin', email='admin@localhost',
                 full_name='Адміністратор', role='admin', group_id=g.id,
                 password_hash=generate_password_hash('admin123'))
        db.session.add(u)
        db.session.commit()
