# Система управління завданнями — Інструкція встановлення

## Технічний стек
- **Backend:** Python 3.11 / Flask
- **БД:** MariaDB (окремий контейнер, або ваша існуюча)
- **Розгортання:** Docker + Docker Compose
- **Проксі:** Nginx → Cloudflare Tunnel

---

## Крок 1 — Підготовка файлів на сервері

```bash
# Створіть директорію
mkdir ~/taskmanager
cd ~/taskmanager

# Скопіюйте всі файли проєкту в цю директорію
# (через scp, sftp або git clone)
```

---

## Крок 2 — Налаштування docker-compose.yml

Відкрийте `docker-compose.yml` і замініть:

| Змінна | Що замінити |
|--------|-------------|
| `SECRET_KEY` | Будь-який довгий випадковий рядок (мінімум 32 символи) |
| `TASKPASS` | Пароль для БД (в обох місцях — однаковий!) |
| `ROOT_PASS_ЗАМІНИТИ` | Пароль root для MariaDB |
| `MAIL_PASSWORD` | App Password від Gmail (не звичайний пароль!) |

### Отримання Gmail App Password:
1. Google Account → Безпека → Двоетапна перевірка (увімкніть якщо вимкнена)
2. Google Account → Безпека → Паролі застосунків
3. Виберіть "Пошта" → "Інший пристрій" → Введіть "TaskManager"
4. Скопіюйте згенерований 16-символьний пароль

### Якщо хочете використати існуючу MariaDB на сервері:
Видаліть сервіс `taskmanager-db` з docker-compose.yml і змініть DATABASE_URL:
```
DATABASE_URL: "mysql+pymysql://taskuser:TASKPASS@host.docker.internal:3306/taskmanager"
```
Потім створіть БД і користувача вручну:
```sql
CREATE DATABASE taskmanager CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
CREATE USER 'taskuser'@'%' IDENTIFIED BY 'TASKPASS';
GRANT ALL PRIVILEGES ON taskmanager.* TO 'taskuser'@'%';
FLUSH PRIVILEGES;
```

---

## Крок 3 — Запуск

```bash
cd ~/taskmanager

# Зібрати та запустити
docker compose up -d --build

# Перевірити статус
docker compose ps

# Перегляд логів (якщо щось не так)
docker compose logs -f taskmanager
```

Додаток запуститься на порту **5050** (можна змінити в docker-compose.yml).

Перевірте що працює:
```bash
curl -I http://127.0.0.1:5050/
# Має відповісти 200 OK або 302 (redirect на /login)
```

---

## Крок 4 — Налаштування Nginx

```bash
sudo nano /etc/nginx/sites-available/tasks.tmo2lviv.pp.ua
```

Вставте вміст файлу `nginx.conf.example` (відредагувавши домен).

```bash
sudo ln -s /etc/nginx/sites-available/tasks.tmo2lviv.pp.ua \
           /etc/nginx/sites-enabled/

sudo nginx -t && sudo systemctl reload nginx
```

---

## Крок 5 — Cloudflare Tunnel

У панелі Cloudflare Tunnel додайте новий публічний hostname:
- **Subdomain:** tasks (або інший)
- **Domain:** tmo2lviv.pp.ua
- **Service:** HTTP → localhost:80

---

## Перший вхід

Після запуску відкрийте додаток у браузері.

**Стандартні дані для входу:**
- Логін: `admin`
- Пароль: `admin123`

**⚠️ Одразу змініть пароль адміністратора!**
Адмін-панель → Користувачі → admin → Редагувати → Новий пароль

---

## Структура ролей

| Роль | Можливості |
|------|-----------|
| **Адміністратор** | Створення/редагування/видалення завдань, керування користувачами та групами, аналітика |
| **Виконавець** | Перегляд призначених завдань, підтвердження ознайомлення, зміна статусу |

---

## Оновлення додатку

```bash
cd ~/taskmanager

# Зупинити
docker compose down

# Відновити з новим кодом
docker compose up -d --build

# БД зберігається в named volume — дані не втрачаються
```

---

## Резервне копіювання БД

```bash
# Якщо використовуєте контейнер з MariaDB
docker exec taskmanager-db \
  mysqldump -u taskuser -pTASKPASS taskmanager > backup_$(date +%Y%m%d).sql

# Відновлення
docker exec -i taskmanager-db \
  mysql -u taskuser -pTASKPASS taskmanager < backup_20260101.sql
```

---

## Нагадування електронною поштою

Нагадування про прострочені завдання відправляються щодня о **08:00** (за UTC).
Щоб змінити час — відредагуйте `app/tasks_scheduler.py`:
```python
trigger='cron', hour=6, minute=0   # ← змініть год/хвилину
```

---

## Діагностика

```bash
# Логи додатку
docker compose logs -f taskmanager

# Логи БД
docker compose logs -f taskmanager-db

# Увійти в контейнер
docker exec -it taskmanager-app bash

# Перезапуск
docker compose restart taskmanager
```
