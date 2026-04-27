import uuid
from datetime import date, datetime, timedelta
from flask import Blueprint, render_template, request, jsonify, Response, abort, url_for, flash, redirect
from flask_login import login_required, current_user
from ..models import Task, TaskAssignment, User, db
from .auth import effective_role, is_admin_mode

calendar_bp = Blueprint('calendar', __name__, url_prefix='/calendar')


# ── Helpers ───────────────────────────────────────────────────────

def _user_tasks(user):
    """Return queryset of tasks visible to the given user.
    Respects admin mode: in manager mode admin sees only own tasks.
    """
    from .auth import effective_role
    role = effective_role()          # uses current_user + session
    if role == 'admin':
        return Task.query
    if role == 'manager' or user.is_manager():
        aids = [a.task_id for a in user.assigned_tasks]
        return Task.query.filter(
            db.or_(Task.created_by == user.id, Task.id.in_(aids))
        )
    aids = [a.task_id for a in user.assigned_tasks]
    return Task.query.filter(Task.id.in_(aids))


def _ical_escape(text):
    """Escape special characters for iCalendar format."""
    if not text:
        return ''
    return (text.replace('\\', '\\\\')
                .replace(';', '\\;')
                .replace(',', '\\,')
                .replace('\n', '\\n')
                .replace('\r', ''))


def _fold(line):
    """
    iCalendar line folding: lines > 75 octets must be wrapped.
    Continuation lines start with a single space.
    """
    encoded = line.encode('utf-8')
    if len(encoded) <= 75:
        return line
    chunks = []
    current = b''
    for char in line:
        c = char.encode('utf-8')
        if len(current) + len(c) > 75:
            chunks.append(current.decode('utf-8'))
            current = b' ' + c
        else:
            current += c
    if current:
        chunks.append(current.decode('utf-8'))
    return '\r\n'.join(chunks)


def _build_ical(tasks, owner_name, base_url):
    """Generate iCalendar (.ics) content for a list of tasks."""
    now_stamp = datetime.utcnow().strftime('%Y%m%dT%H%M%SZ')

    lines = [
        'BEGIN:VCALENDAR',
        'VERSION:2.0',
        'PRODID:-//TMO2 Task Manager//UA',
        'CALSCALE:GREGORIAN',
        'METHOD:PUBLISH',
        f'X-WR-CALNAME:Завдання ТМО2 — {owner_name}',
        'X-WR-TIMEZONE:Europe/Kiev',
        'X-WR-CALDESC:Завдання з системи управління ТМО2',
    ]

    FREQ_MAP = {
        'daily':   'DAILY',
        'weekly':  'WEEKLY',
        'monthly': 'MONTHLY',
        'yearly':  'YEARLY',
    }

    STATUS_MAP = {
        'new':         'NEEDS-ACTION',
        'in_progress': 'IN-PROCESS',
        'done':        'COMPLETED',
        'cancelled':   'CANCELLED',
    }

    for t in tasks:
        # Determine event date/time
        ev_date = t.date_start or t.created_at.date()
        has_time = t.time_start is not None

        if has_time:
            # VEVENT with specific time
            start_str = f"{ev_date.strftime('%Y%m%d')}T{t.time_start.strftime('%H%M%S')}"
            if t.time_end:
                end_str = f"{ev_date.strftime('%Y%m%d')}T{t.time_end.strftime('%H%M%S')}"
            else:
                # Default 1 hour
                from datetime import datetime as dt
                end_t = (dt.combine(ev_date, t.time_start) + timedelta(hours=1)).time()
                end_str = f"{ev_date.strftime('%Y%m%d')}T{end_t.strftime('%H%M%S')}"
            dtstart = f'DTSTART;TZID=Europe/Kiev:{start_str}'
            dtend   = f'DTEND;TZID=Europe/Kiev:{end_str}'
        else:
            # All-day event
            dtstart = f'DTSTART;VALUE=DATE:{ev_date.strftime("%Y%m%d")}'
            # All-day end is exclusive in iCal — next day
            end_date = (t.date_end + timedelta(days=1)) if t.date_end else (ev_date + timedelta(days=1))
            dtend   = f'DTEND;VALUE=DATE:{end_date.strftime("%Y%m%d")}'

        # Description with metadata
        assignees = ', '.join(u.full_name for u in t.assigned_users())
        desc_parts = []
        if t.description:
            desc_parts.append(t.description)
        desc_parts.append(f'Статус: {t.status_label()}')
        desc_parts.append(f'Пріоритет: {t.priority_label()}')
        if assignees:
            desc_parts.append(f'Виконавці: {assignees}')
        if t.recurrence != 'none':
            desc_parts.append(f'Повторення: {t.recurrence_label()}')
        description = _ical_escape('\n'.join(desc_parts))

        task_url = f"{base_url}/tasks/{t.id}"
        uid = f"task-{t.id}@tmo2-taskmanager"

        lines += [
            'BEGIN:VEVENT',
            f'UID:{uid}',
            f'DTSTAMP:{now_stamp}',
            dtstart,
            dtend,
            f'SUMMARY:{_ical_escape(t.title)}',
            f'DESCRIPTION:{description}',
            f'URL:{task_url}',
            f'STATUS:{STATUS_MAP.get(t.status, "NEEDS-ACTION")}',
            f'PRIORITY:{"1" if t.priority=="high" else "5" if t.priority=="medium" else "9"}',
        ]

        # Categories from group
        if t.group:
            lines.append(f'CATEGORIES:{_ical_escape(t.group.name)}')

        # Recurrence rule
        if t.recurrence in FREQ_MAP:
            lines.append(f'RRULE:FREQ={FREQ_MAP[t.recurrence]}')

        # Last modified
        updated = t.updated_at or t.created_at
        lines.append(f'LAST-MODIFIED:{updated.strftime("%Y%m%dT%H%M%SZ")}')

        lines.append('END:VEVENT')

    lines.append('END:VCALENDAR')

    # Fold long lines and join with CRLF (required by RFC 5545)
    return '\r\n'.join(_fold(l) for l in lines) + '\r\n'


# ── Routes ────────────────────────────────────────────────────────

@calendar_bp.route('/')
@login_required
def view():
    today = date.today()
    return render_template('calendar/calendar.html', today=today)


@calendar_bp.route('/events')
@login_required
def events():
    tasks = _user_tasks(current_user).all()

    STATUS_COLORS = {
        'new':         '#11353F',
        'in_progress': '#E8B7A6',
        'done':        '#81BDA7',
        'cancelled':   '#9ca3af',
    }
    PRIORITY_BORDER = {
        'low':    '#81BDA7',
        'medium': '#E8B7A6',
        'high':   '#F05F5F',
    }

    result = []
    for t in tasks:
        ev_start = t.calendar_start()
        ev_end   = t.calendar_end()
        has_time = t.time_start is not None

        event = {
            'id':          t.id,
            'title':       t.title,
            'start':       ev_start,
            'end':         ev_end,
            'allDay':      not has_time,
            'color':       STATUS_COLORS.get(t.status, '#11353F'),
            'borderColor': PRIORITY_BORDER.get(t.priority, '#81BDA7'),
            'url':         f'/tasks/{t.id}',
            'extendedProps': {
                'status':      t.status_label(),
                'priority':    t.priority_label(),
                'recurrence':  t.recurrence_label(),
                'description': (t.description or '').strip(),
                'assignees':   ', '.join(u.full_name for u in t.assigned_users()) or '',
                'timeRange': (
                    t.time_start.strftime('%H:%M') +
                    (' — ' + t.time_end.strftime('%H:%M') if t.time_end else '')
                ) if t.time_start else '',
            }
        }
        rrule = t.rrule()
        if rrule:
            event['rrule'] = {**rrule, 'dtstart': ev_start}
            event.pop('end', None)
            if has_time and t.time_end:
                from datetime import datetime as dt
                ts, te = t.time_start, t.time_end
                diff = (dt.combine(date.today(), te) - dt.combine(date.today(), ts))
                h, rem = divmod(int(diff.total_seconds()), 3600)
                event['duration'] = f"{h:02d}:{rem//60:02d}"
        result.append(event)

    return jsonify(result)


@calendar_bp.route('/subscribe')
@login_required
def subscribe():
    """Show subscription page with iCal URL for the current user."""
    # Generate token if user doesn't have one
    if not current_user.calendar_token:
        current_user.calendar_token = uuid.uuid4().hex
        db.session.commit()

    # Build webcal:// and https:// URLs
    host = request.host  # e.g. tasks.tmo2lviv.pp.ua
    token = current_user.calendar_token
    https_url  = f"https://{host}/calendar/feed/{token}.ics"
    webcal_url = f"webcal://{host}/calendar/feed/{token}.ics"

    google_url = (
        "https://calendar.google.com/calendar/r?cid="
        + https_url.replace('https://', 'https%3A%2F%2F').replace('/', '%2F')
    )

    return render_template('calendar/subscribe.html',
        https_url=https_url,
        webcal_url=webcal_url,
        google_url=google_url,
        token=token,
    )


@calendar_bp.route('/subscribe/reset', methods=['POST'])
@login_required
def reset_token():
    """Generate a new token — invalidates old subscription URL."""
    current_user.calendar_token = uuid.uuid4().hex
    db.session.commit()
    flash('Посилання для підписки оновлено. Попереднє посилання більше не працює.', 'success')
    return redirect(url_for('calendar.subscribe'))


@calendar_bp.route('/feed/<token>.ics')
def ical_feed(token):
    """
    Public iCal feed endpoint — no login required, token is the auth.
    Compatible with Google Calendar, Apple Calendar, Outlook.
    """
    user = User.query.filter_by(calendar_token=token, is_active=True).first()
    if not user:
        abort(404)

    tasks  = _user_tasks(user).all()
    # Use request host to build task URLs
    base   = f"https://{request.host}"
    ical   = _build_ical(tasks, user.full_name, base)

    return Response(
        ical,
        mimetype='text/calendar; charset=utf-8',
        headers={
            'Content-Disposition': f'inline; filename="tmo2-tasks.ics"',
            'Cache-Control':       'no-cache, no-store, must-revalidate',
            'Pragma':              'no-cache',
        }
    )
