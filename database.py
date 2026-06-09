import sqlite3
import os
from datetime import datetime, timedelta

DB_PATH = os.path.join(os.path.expanduser('~'), '.filmtrack.db')

STATUS_OPTIONS = ['to-watch', 'watching', 'completed', 'on-hold', 'dropped']
TYPE_OPTIONS = ['movie', 'series', 'anime', 'documentary', 'variety', 'other']

def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_conn()
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS works (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        title TEXT NOT NULL,
        original_title TEXT,
        type TEXT NOT NULL DEFAULT 'series',
        year INTEGER,
        platform TEXT,
        total_episodes INTEGER DEFAULT 0,
        status TEXT NOT NULL DEFAULT 'to-watch',
        current_episode INTEGER DEFAULT 0,
        rating REAL,
        genre TEXT,
        added_at TEXT NOT NULL,
        last_watched_at TEXT,
        next_air_date TEXT,
        reminder_set INTEGER DEFAULT 0,
        notes TEXT DEFAULT ''
    )''')
    c.execute('''CREATE TABLE IF NOT EXISTS watch_logs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        work_id INTEGER NOT NULL,
        episode INTEGER,
        watched_at TEXT NOT NULL,
        FOREIGN KEY (work_id) REFERENCES works(id) ON DELETE CASCADE
    )''')
    c.execute('''CREATE TABLE IF NOT EXISTS ratings (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        work_id INTEGER NOT NULL,
        score REAL NOT NULL,
        rated_at TEXT NOT NULL,
        FOREIGN KEY (work_id) REFERENCES works(id) ON DELETE CASCADE
    )''')
    c.execute('''CREATE TABLE IF NOT EXISTS notes (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        work_id INTEGER NOT NULL,
        content TEXT NOT NULL,
        created_at TEXT NOT NULL,
        FOREIGN KEY (work_id) REFERENCES works(id) ON DELETE CASCADE
    )''')
    conn.commit()
    conn.close()

def add_work(title, original_title=None, work_type='series', year=None,
             platform=None, total_episodes=0, genre=None, next_air_date=None):
    conn = get_conn()
    c = conn.cursor()
    now = datetime.now().isoformat()
    c.execute('''INSERT INTO works (title, original_title, type, year, platform,
        total_episodes, status, current_episode, genre, added_at, next_air_date)
        VALUES (?, ?, ?, ?, ?, ?, 'to-watch', 0, ?, ?, ?)''',
        (title, original_title, work_type, year, platform, total_episodes,
         genre, now, next_air_date))
    work_id = c.lastrowid
    conn.commit()
    conn.close()
    return work_id

def get_work(work_id):
    conn = get_conn()
    c = conn.cursor()
    c.execute('SELECT * FROM works WHERE id = ?', (work_id,))
    row = c.fetchone()
    conn.close()
    return row

def search_works(keyword):
    conn = get_conn()
    c = conn.cursor()
    c.execute('''SELECT * FROM works WHERE title LIKE ? OR original_title LIKE ?
        ORDER BY added_at DESC''', (f'%{keyword}%', f'%{keyword}%'))
    rows = c.fetchall()
    conn.close()
    return rows

def list_works(status=None, work_type=None, platform=None):
    conn = get_conn()
    c = conn.cursor()
    query = 'SELECT * FROM works WHERE 1=1'
    params = []
    if status:
        query += ' AND status = ?'
        params.append(status)
    if work_type:
        query += ' AND type = ?'
        params.append(work_type)
    if platform:
        query += ' AND platform = ?'
        params.append(platform)
    query += ' ORDER BY last_watched_at DESC, added_at DESC'
    c.execute(query, params)
    rows = c.fetchall()
    conn.close()
    return rows

def update_status(work_id, status, current_episode=None):
    conn = get_conn()
    c = conn.cursor()
    now = datetime.now().isoformat()
    if current_episode is not None:
        c.execute('''UPDATE works SET status = ?, current_episode = ?,
            last_watched_at = ? WHERE id = ?''',
            (status, current_episode, now, work_id))
    else:
        c.execute('UPDATE works SET status = ?, last_watched_at = ? WHERE id = ?',
            (status, now, work_id))
    conn.commit()
    conn.close()

def watch_episode(work_id, episode=None):
    conn = get_conn()
    c = conn.cursor()
    c.execute('SELECT current_episode, total_episodes, status FROM works WHERE id = ?', (work_id,))
    row = c.fetchone()
    if not row:
        conn.close()
        return None
    current = row['current_episode']
    total = row['total_episodes']
    if episode is None:
        episode = current + 1
    now = datetime.now().isoformat()
    c.execute('INSERT INTO watch_logs (work_id, episode, watched_at) VALUES (?, ?, ?)',
        (work_id, episode, now))
    new_status = 'completed' if (total > 0 and episode >= total) else 'watching'
    c.execute('UPDATE works SET current_episode = ?, last_watched_at = ?, status = ? WHERE id = ?',
        (episode, now, new_status if row['status'] != 'completed' or episode < total else row['status'], work_id))
    conn.commit()
    conn.close()
    return episode

def rate_work(work_id, score):
    conn = get_conn()
    c = conn.cursor()
    now = datetime.now().isoformat()
    c.execute('INSERT INTO ratings (work_id, score, rated_at) VALUES (?, ?, ?)',
        (work_id, score, now))
    c.execute('UPDATE works SET rating = ? WHERE id = ?', (score, work_id))
    conn.commit()
    conn.close()

def add_note(work_id, content):
    conn = get_conn()
    c = conn.cursor()
    now = datetime.now().isoformat()
    c.execute('INSERT INTO notes (work_id, content, created_at) VALUES (?, ?, ?)',
        (work_id, content, now))
    c.execute('SELECT notes FROM works WHERE id = ?', (work_id,))
    row = c.fetchone()
    existing = row['notes'] or ''
    new_notes = existing + ('\n' if existing else '') + f'[{now[:10]}] {content}'
    c.execute('UPDATE works SET notes = ? WHERE id = ?', (new_notes, work_id))
    conn.commit()
    conn.close()

def get_notes(work_id):
    conn = get_conn()
    c = conn.cursor()
    c.execute('SELECT * FROM notes WHERE work_id = ? ORDER BY created_at DESC', (work_id,))
    rows = c.fetchall()
    conn.close()
    return rows

def get_watch_logs(work_id=None, start_date=None, end_date=None):
    conn = get_conn()
    c = conn.cursor()
    query = '''SELECT wl.*, w.title as work_title, w.type as work_type
        FROM watch_logs wl JOIN works w ON wl.work_id = w.id WHERE 1=1'''
    params = []
    if work_id:
        query += ' AND wl.work_id = ?'
        params.append(work_id)
    if start_date:
        query += ' AND wl.watched_at >= ?'
        params.append(start_date)
    if end_date:
        query += ' AND wl.watched_at <= ?'
        params.append(end_date)
    query += ' ORDER BY wl.watched_at DESC'
    c.execute(query, params)
    rows = c.fetchall()
    conn.close()
    return rows

def get_calendar_works():
    conn = get_conn()
    c = conn.cursor()
    today = datetime.now().date()
    week_end = today + timedelta(days=7)
    c.execute('''SELECT * FROM works WHERE next_air_date IS NOT NULL
        AND next_air_date >= ? AND next_air_date <= ?
        ORDER BY next_air_date ASC''',
        (today.isoformat(), week_end.isoformat()))
    rows = c.fetchall()
    conn.close()
    return rows

def set_reminder(work_id, enabled=True):
    conn = get_conn()
    c = conn.cursor()
    c.execute('UPDATE works SET reminder_set = ? WHERE id = ?', (1 if enabled else 0, work_id))
    conn.commit()
    conn.close()

def get_reminders():
    conn = get_conn()
    c = conn.cursor()
    today = datetime.now().date()
    tomorrow = today + timedelta(days=1)
    c.execute('''SELECT * FROM works WHERE reminder_set = 1 AND next_air_date IS NOT NULL
        AND next_air_date >= ? AND next_air_date <= ?
        ORDER BY next_air_date ASC''',
        (today.isoformat(), tomorrow.isoformat()))
    upcoming = c.fetchall()
    c.execute('''SELECT * FROM works WHERE status = 'watching'
        AND (last_watched_at IS NULL OR last_watched_at < ?)
        ORDER BY last_watched_at ASC''',
        ((today - timedelta(days=30)).isoformat(),))
    stalled = c.fetchall()
    conn.close()
    return upcoming, stalled

def get_monthly_stats(year, month):
    conn = get_conn()
    c = conn.cursor()
    start = f'{year:04d}-{month:02d}-01'
    if month == 12:
        end = f'{year+1:04d}-01-01'
    else:
        end = f'{year:04d}-{month+1:02d}-01'
    c.execute('''SELECT COUNT(DISTINCT wl.work_id) as works_watched,
        COUNT(wl.id) as episodes_watched
        FROM watch_logs wl WHERE wl.watched_at >= ? AND wl.watched_at < ?''',
        (start, end))
    totals = c.fetchone()
    c.execute('''SELECT w.type, COUNT(DISTINCT wl.work_id) as cnt
        FROM watch_logs wl JOIN works w ON wl.work_id = w.id
        WHERE wl.watched_at >= ? AND wl.watched_at < ?
        GROUP BY w.type ORDER BY cnt DESC''',
        (start, end))
    by_type = c.fetchall()
    c.execute('''SELECT w.id, w.title, w.type, COUNT(wl.id) as ep_cnt
        FROM watch_logs wl JOIN works w ON wl.work_id = w.id
        WHERE wl.watched_at >= ? AND wl.watched_at < ?
        GROUP BY w.id ORDER BY ep_cnt DESC LIMIT 10''',
        (start, end))
    top_works = c.fetchall()
    c.execute('''SELECT AVG(r.score) as avg_rating
        FROM ratings r WHERE r.rated_at >= ? AND r.rated_at < ?''',
        (start, end))
    avg_rating = c.fetchone()
    conn.close()
    return {
        'totals': totals,
        'by_type': by_type,
        'top_works': top_works,
        'avg_rating': avg_rating['avg_rating'] if avg_rating else None
    }

def delete_work(work_id):
    conn = get_conn()
    c = conn.cursor()
    c.execute('DELETE FROM works WHERE id = ?', (work_id,))
    c.execute('DELETE FROM watch_logs WHERE work_id = ?', (work_id,))
    c.execute('DELETE FROM ratings WHERE work_id = ?', (work_id,))
    c.execute('DELETE FROM notes WHERE work_id = ?', (work_id,))
    conn.commit()
    conn.close()

def update_work(work_id, **kwargs):
    conn = get_conn()
    c = conn.cursor()
    allowed = ['title', 'original_title', 'type', 'year', 'platform',
               'total_episodes', 'next_air_date', 'genre']
    updates = []
    params = []
    for k, v in kwargs.items():
        if k in allowed and v is not None:
            updates.append(f'{k} = ?')
            params.append(v)
    if updates:
        params.append(work_id)
        c.execute(f'UPDATE works SET {", ".join(updates)} WHERE id = ?', params)
        conn.commit()
    conn.close()
