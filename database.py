import sqlite3
import os
from datetime import datetime, timedelta, date

DB_PATH = os.path.join(os.path.expanduser('~'), '.filmtrack.db')

STATUS_OPTIONS = ['to-watch', 'watching', 'completed', 'on-hold', 'dropped']
TYPE_OPTIONS = ['movie', 'series', 'anime', 'documentary', 'variety', 'other']
WEEKDAYS = ['mon', 'tue', 'wed', 'thu', 'fri', 'sat', 'sun']
WEEKDAY_CN = {'mon': '一', 'tue': '二', 'wed': '三', 'thu': '四', 'fri': '五', 'sat': '六', 'sun': '日'}

def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute('PRAGMA foreign_keys = ON')
    return conn

def _migrate(conn):
    c = conn.cursor()
    existing_cols = [row[1] for row in c.execute("PRAGMA table_info(works)").fetchall()]
    new_cols = {
        'air_weekday': 'TEXT',
        'episodes_per_air': 'INTEGER DEFAULT 1',
        'remind_days_before': 'INTEGER DEFAULT 1',
    }
    for col, col_type in new_cols.items():
        if col not in existing_cols:
            c.execute(f'ALTER TABLE works ADD COLUMN {col} {col_type}')
    conn.commit()

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
        air_weekday TEXT,
        episodes_per_air INTEGER DEFAULT 1,
        reminder_set INTEGER DEFAULT 0,
        remind_days_before INTEGER DEFAULT 1,
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
    _migrate(conn)
    conn.close()

def add_work(title, original_title=None, work_type='series', year=None,
             platform=None, total_episodes=0, genre=None, next_air_date=None,
             air_weekday=None, episodes_per_air=1, remind_days_before=1):
    conn = get_conn()
    c = conn.cursor()
    now = datetime.now().isoformat()
    c.execute('''INSERT INTO works (title, original_title, type, year, platform,
        total_episodes, status, current_episode, genre, added_at, next_air_date,
        air_weekday, episodes_per_air, remind_days_before)
        VALUES (?, ?, ?, ?, ?, ?, 'to-watch', 0, ?, ?, ?, ?, ?, ?)''',
        (title, original_title, work_type, year, platform, total_episodes,
         genre, now, next_air_date, air_weekday, episodes_per_air, remind_days_before))
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

def validate_episode(work, episode):
    if episode is None:
        return None, '集数不能为空'
    if not isinstance(episode, int) or episode <= 0:
        return None, '集数必须是大于 0 的整数'
    if work['total_episodes'] and work['total_episodes'] > 0:
        if episode > work['total_episodes']:
            return None, f'集数不能超过总集数 {work["total_episodes"]}（当前输入 {episode}）'
    return episode, None

def update_status(work_id, status, current_episode=None):
    conn = get_conn()
    c = conn.cursor()
    c.execute('SELECT * FROM works WHERE id = ?', (work_id,))
    work = c.fetchone()
    if not work:
        conn.close()
        return False, '作品不存在'
    now = datetime.now().isoformat()
    if current_episode is not None:
        ep, err = validate_episode(work, current_episode)
        if err:
            conn.close()
            return False, err
        c.execute('''UPDATE works SET status = ?, current_episode = ?,
            last_watched_at = ? WHERE id = ?''',
            (status, ep, now, work_id))
    else:
        c.execute('UPDATE works SET status = ?, last_watched_at = ? WHERE id = ?',
            (status, now, work_id))
    conn.commit()
    conn.close()
    return True, None

def watch_episodes(work_id, start_episode=None, count=1, watched_at=None, movie=False):
    conn = get_conn()
    c = conn.cursor()
    c.execute('SELECT * FROM works WHERE id = ?', (work_id,))
    work = c.fetchone()
    if not work:
        conn.close()
        return False, '作品不存在', []
    is_movie = work['type'] == 'movie' or movie
    total = work['total_episodes'] or 0
    current = work['current_episode'] or 0

    if is_movie:
        logged_eps = [None]
        final_ep = 1 if total > 0 else 0
    else:
        if start_episode is None:
            start_episode = current + 1
        if start_episode <= 0:
            conn.close()
            return False, '起始集数必须大于 0', []
        if total > 0 and start_episode > total:
            conn.close()
            return False, f'起始集数 {start_episode} 超过总集数 {total}', []
        if count <= 0:
            conn.close()
            return False, '观看集数必须大于 0', []
        logged_eps = list(range(start_episode, start_episode + count))
        if total > 0:
            max_allowed = total
            valid_eps = [e for e in logged_eps if e <= max_allowed]
            if not valid_eps:
                conn.close()
                return False, f'所有集数均超过总集数 {total}', []
            if len(valid_eps) < len(logged_eps):
                logged_eps = valid_eps
        final_ep = logged_eps[-1]

    if watched_at:
        try:
            dt = datetime.fromisoformat(watched_at)
            watched_at_iso = dt.isoformat()
        except ValueError:
            conn.close()
            return False, f'日期格式错误，应为 YYYY-MM-DD 或 YYYY-MM-DDTHH:MM', []
    else:
        watched_at_iso = datetime.now().isoformat()

    for ep in logged_eps:
        c.execute('INSERT INTO watch_logs (work_id, episode, watched_at) VALUES (?, ?, ?)',
            (work_id, ep, watched_at_iso))

    new_status = work['status']
    if is_movie:
        new_status = 'completed'
    elif total > 0 and final_ep >= total:
        new_status = 'completed'
    elif work['status'] in ('to-watch', 'on-hold'):
        new_status = 'watching'

    c.execute('UPDATE works SET current_episode = ?, last_watched_at = ?, status = ? WHERE id = ?',
        (final_ep if not is_movie else (total if total > 0 else 1), watched_at_iso, new_status, work_id))
    conn.commit()
    conn.close()
    return True, None, logged_eps

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
    query = '''SELECT wl.*, w.title as work_title, w.type as work_type, w.platform as work_platform
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

def _compute_next_air_dates(work, start, end):
    results = []
    if not work['air_weekday'] and not work['next_air_date']:
        return results
    today = date.today()
    weekday_idx = None
    if work['air_weekday']:
        weekday_idx = WEEKDAYS.index(work['air_weekday'])
    episodes_per = work['episodes_per_air'] or 1

    if work['next_air_date']:
        try:
            d = date.fromisoformat(work['next_air_date'][:10])
        except:
            d = None
        if d and start <= d <= end:
            results.append((d, work['next_air_date'][:10], episodes_per, work))

    if weekday_idx is not None:
        cursor = max(start, today)
        while cursor <= end:
            if cursor.weekday() == weekday_idx:
                iso = cursor.isoformat()
                if not (work['next_air_date'] and work['next_air_date'][:10] == iso):
                    results.append((cursor, iso, episodes_per, work))
            cursor += timedelta(days=1)
    results.sort(key=lambda x: x[0])
    return results

def get_calendar_works(range_type='week'):
    today = date.today()
    if range_type == 'today':
        start, end = today, today
    elif range_type == 'month':
        start = today.replace(day=1)
        if start.month == 12:
            end = date(start.year + 1, 1, 1) - timedelta(days=1)
        else:
            end = date(start.year, start.month + 1, 1) - timedelta(days=1)
    else:
        start = today
        end = today + timedelta(days=6)

    conn = get_conn()
    c = conn.cursor()
    c.execute('''SELECT * FROM works
        WHERE (next_air_date IS NOT NULL OR air_weekday IS NOT NULL)
        AND status IN ('to-watch', 'watching', 'on-hold')''')
    works = c.fetchall()
    conn.close()

    all_events = []
    for w in works:
        events = _compute_next_air_dates(w, start, end)
        all_events.extend(events)
    all_events.sort(key=lambda x: x[0])
    return start, end, all_events

def set_reminder(work_id, enabled=True, remind_days_before=None):
    conn = get_conn()
    c = conn.cursor()
    if remind_days_before is not None:
        c.execute('UPDATE works SET reminder_set = ?, remind_days_before = ? WHERE id = ?',
            (1 if enabled else 0, remind_days_before, work_id))
    else:
        c.execute('UPDATE works SET reminder_set = ? WHERE id = ?',
            (1 if enabled else 0, work_id))
    conn.commit()
    conn.close()

def get_reminders():
    conn = get_conn()
    c = conn.cursor()
    today = date.today()
    c.execute('''SELECT * FROM works WHERE reminder_set = 1
        AND (next_air_date IS NOT NULL OR air_weekday IS NOT NULL)''')
    works = c.fetchall()
    upcoming = []
    for w in works:
        days_before = w['remind_days_before'] or 1
        remind_start = today
        remind_end = today + timedelta(days=max(days_before, 1))
        events = _compute_next_air_dates(w, remind_start, remind_end)
        for ev in events:
            d, iso, ep_cnt, _ = ev
            upcoming.append((d, iso, ep_cnt, w))
    upcoming.sort(key=lambda x: x[0])

    c.execute('''SELECT * FROM works WHERE status = 'watching'
        AND (last_watched_at IS NULL OR DATE(last_watched_at) < ?)
        ORDER BY last_watched_at ASC''',
        ((today - timedelta(days=30)).isoformat(),))
    stalled = c.fetchall()
    conn.close()
    return upcoming, stalled

def get_monthly_stats(year, month):
    start_dt = date(year, month, 1)
    if month == 12:
        end_dt = date(year + 1, 1, 1)
    else:
        end_dt = date(year, month + 1, 1)
    start = start_dt.isoformat()
    end = end_dt.isoformat()

    conn = get_conn()
    c = conn.cursor()

    c.execute('''SELECT COUNT(DISTINCT wl.work_id) as works_watched,
        COUNT(wl.id) as episodes_watched
        FROM watch_logs wl WHERE wl.watched_at >= ? AND wl.watched_at < ?''',
        (start, end))
    totals = c.fetchone()

    c.execute('''SELECT DATE(wl.watched_at) as d, COUNT(*) as cnt
        FROM watch_logs wl
        WHERE wl.watched_at >= ? AND wl.watched_at < ?
        GROUP BY DATE(wl.watched_at) ORDER BY d ASC''',
        (start, end))
    daily = c.fetchall()
    watch_days = len(daily)
    streak = 0
    max_streak = 0
    prev = None
    for row in daily:
        d = date.fromisoformat(row['d'])
        if prev and (d - prev).days == 1:
            streak += 1
        else:
            streak = 1
        max_streak = max(max_streak, streak)
        prev = d

    c.execute('''SELECT w.platform, COUNT(wl.id) as cnt
        FROM watch_logs wl JOIN works w ON wl.work_id = w.id
        WHERE wl.watched_at >= ? AND wl.watched_at < ? AND w.platform IS NOT NULL
        GROUP BY w.platform ORDER BY cnt DESC''',
        (start, end))
    by_platform = c.fetchall()

    c.execute('''SELECT w.type, COUNT(DISTINCT wl.work_id) as works_cnt, COUNT(wl.id) as ep_cnt
        FROM watch_logs wl JOIN works w ON wl.work_id = w.id
        WHERE wl.watched_at >= ? AND wl.watched_at < ?
        GROUP BY w.type ORDER BY ep_cnt DESC''',
        (start, end))
    by_type = c.fetchall()

    c.execute('''SELECT w.id, w.title, w.type, COUNT(wl.id) as ep_cnt
        FROM watch_logs wl JOIN works w ON wl.work_id = w.id
        WHERE wl.watched_at >= ? AND wl.watched_at < ?
        GROUP BY w.id ORDER BY ep_cnt DESC LIMIT 10''',
        (start, end))
    top_works = c.fetchall()

    c.execute('''SELECT r.score
        FROM ratings r WHERE r.rated_at >= ? AND r.rated_at < ?''',
        (start, end))
    scores = [row[0] for row in c.fetchall()]
    avg_rating = sum(scores) / len(scores) if scores else None
    rating_dist = {}
    for s in scores:
        bucket = int(s // 2) * 2
        key = f'{bucket}-{bucket+1}'
        rating_dist[key] = rating_dist.get(key, 0) + 1

    conn.close()
    return {
        'totals': totals,
        'watch_days': watch_days,
        'max_streak': max_streak,
        'by_platform': by_platform,
        'by_type': by_type,
        'top_works': top_works,
        'avg_rating': avg_rating,
        'rating_dist': rating_dist,
        'daily_count': daily,
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
               'total_episodes', 'next_air_date', 'genre',
               'air_weekday', 'episodes_per_air', 'remind_days_before']
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
