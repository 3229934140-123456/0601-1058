import sqlite3
import os
import csv
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

def find_duplicate_work(title, original_title=None, year=None):
    conn = get_conn()
    c = conn.cursor()
    query = 'SELECT * FROM works WHERE LOWER(title) = LOWER(?)'
    params = [title]
    if original_title:
        query += ' OR LOWER(original_title) = LOWER(?)'
        params.append(original_title)
    if year:
        query += ' AND year = ?'
        params.append(year)
    c.execute(query, params)
    rows = c.fetchall()
    conn.close()
    return rows

def add_work(title, original_title=None, work_type='series', year=None,
             platform=None, total_episodes=0, genre=None, next_air_date=None,
             air_weekday=None, episodes_per_air=1, remind_days_before=1,
             skip_dup_check=False):
    if not skip_dup_check:
        dups = find_duplicate_work(title, original_title, year)
        if dups:
            return None, f'已存在相同作品：[ID={dups[0]["id"]}] {dups[0]["title"]}'
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
    return work_id, None

def get_work(work_id):
    conn = get_conn()
    c = conn.cursor()
    c.execute('SELECT * FROM works WHERE id = ?', (work_id,))
    row = c.fetchone()
    conn.close()
    return row

def get_watch_log(log_id):
    conn = get_conn()
    c = conn.cursor()
    c.execute('SELECT * FROM watch_logs WHERE id = ?', (log_id,))
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

def _recalc_work_progress(conn, work_id):
    c = conn.cursor()
    c.execute('SELECT * FROM works WHERE id = ?', (work_id,))
    work = c.fetchone()
    if not work:
        return
    is_movie = work['type'] == 'movie'
    total = work['total_episodes'] or 0
    if is_movie:
        c.execute('SELECT COUNT(*) as cnt, MAX(watched_at) as last_at FROM watch_logs WHERE work_id = ?', (work_id,))
        r = c.fetchone()
        has_logs = r['cnt'] > 0
        new_ep = (total if total > 0 else 1) if has_logs else 0
        new_status = 'completed' if has_logs else work['status']
        last_at = r['last_at']
    else:
        c.execute('''SELECT MAX(episode) as max_ep, MAX(watched_at) as last_at
            FROM watch_logs WHERE work_id = ? AND episode IS NOT NULL''', (work_id,))
        r = c.fetchone()
        max_ep = r['max_ep'] or 0
        new_ep = max_ep
        last_at = r['last_at']
        if max_ep <= 0:
            new_status = work['status'] if work['status'] != 'completed' else 'to-watch'
        elif total > 0 and max_ep >= total:
            new_status = 'completed'
        else:
            new_status = 'watching' if work['status'] not in ('dropped', 'on-hold') else work['status']
    c.execute('UPDATE works SET current_episode = ?, last_watched_at = ?, status = ? WHERE id = ?',
        (new_ep, last_at, new_status, work_id))
    conn.commit()

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
        if count <= 0:
            conn.close()
            return False, '观看集数必须大于 0', []
        end_episode = start_episode + count - 1
        if total > 0:
            if start_episode > total:
                conn.close()
                return False, f'起始集数 {start_episode} 超过总集数 {total}', []
            if end_episode > total:
                conn.close()
                return False, f'想记录到第 {end_episode} 集，但总集数只有 {total}', []
        logged_eps = list(range(start_episode, end_episode + 1))
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

def delete_watch_log(log_id):
    conn = get_conn()
    c = conn.cursor()
    c.execute('SELECT work_id FROM watch_logs WHERE id = ?', (log_id,))
    row = c.fetchone()
    if not row:
        conn.close()
        return False, '日志不存在'
    work_id = row['work_id']
    c.execute('DELETE FROM watch_logs WHERE id = ?', (log_id,))
    conn.commit()
    _recalc_work_progress(conn, work_id)
    conn.close()
    return True, None

def update_watch_log(log_id, episode=None, watched_at=None):
    conn = get_conn()
    c = conn.cursor()
    c.execute('SELECT * FROM watch_logs WHERE id = ?', (log_id,))
    log = c.fetchone()
    if not log:
        conn.close()
        return False, '日志不存在'
    work = get_work(log['work_id'])
    if not work:
        conn.close()
        return False, '关联作品不存在'
    new_ep = log['episode']
    new_at = log['watched_at']
    if episode is not None:
        if work['type'] != 'movie':
            ep, err = validate_episode(work, episode)
            if err:
                conn.close()
                return False, err
            new_ep = ep
        else:
            new_ep = episode
    if watched_at is not None:
        try:
            dt = datetime.fromisoformat(watched_at)
            new_at = dt.isoformat()
        except ValueError:
            conn.close()
            return False, f'日期格式错误，应为 YYYY-MM-DD 或 YYYY-MM-DDTHH:MM'
    c.execute('UPDATE watch_logs SET episode = ?, watched_at = ? WHERE id = ?',
        (new_ep, new_at, log_id))
    conn.commit()
    _recalc_work_progress(conn, log['work_id'])
    conn.close()
    return True, None

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

def get_ratings(work_id=None):
    conn = get_conn()
    c = conn.cursor()
    if work_id:
        c.execute('SELECT * FROM ratings WHERE work_id = ? ORDER BY rated_at DESC', (work_id,))
    else:
        c.execute('SELECT r.*, w.title as work_title FROM ratings r JOIN works w ON r.work_id = w.id ORDER BY rated_at DESC')
    rows = c.fetchall()
    conn.close()
    return rows

def get_watch_logs(work_id=None, start_date=None, end_date=None, year=None, month=None):
    conn = get_conn()
    c = conn.cursor()
    query = '''SELECT wl.*, w.title as work_title, w.type as work_type, w.platform as work_platform
        FROM watch_logs wl JOIN works w ON wl.work_id = w.id WHERE 1=1'''
    params = []
    if work_id:
        query += ' AND wl.work_id = ?'
        params.append(work_id)
    if year and month:
        start = f'{year:04d}-{month:02d}-01'
        if month == 12:
            end = f'{year+1:04d}-01-01'
        else:
            end = f'{year:04d}-{month+1:02d}-01'
        query += ' AND wl.watched_at >= ? AND wl.watched_at < ?'
        params.extend([start, end])
    else:
        if start_date:
            query += ' AND wl.watched_at >= ?'
            params.append(start_date)
        if end_date:
            query += ' AND wl.watched_at <= ?'
            params.append(end_date)
    query += ' ORDER BY wl.watched_at DESC, wl.id DESC'
    c.execute(query, params)
    rows = c.fetchall()
    conn.close()
    return rows

def _compute_next_air_dates(work, start, end):
    if not work['air_weekday'] and not work['next_air_date']:
        return []
    total = work['total_episodes'] or 0
    if total > 0 and work['current_episode'] and work['current_episode'] >= total:
        return []
    today = date.today()
    weekday_idx = None
    if work['air_weekday']:
        weekday_idx = WEEKDAYS.index(work['air_weekday'])
    episodes_per = work['episodes_per_air'] or 1
    current_ep = work['current_episode'] or 0

    air_dates = []
    if work['next_air_date']:
        try:
            d = date.fromisoformat(work['next_air_date'][:10])
            if start <= d <= end:
                air_dates.append(d)
        except:
            pass

    if weekday_idx is not None:
        cursor = max(start, today)
        while cursor <= end:
            if cursor.weekday() == weekday_idx:
                if not (work['next_air_date'] and work['next_air_date'][:10] == cursor.isoformat()):
                    air_dates.append(cursor)
            cursor += timedelta(days=1)

    air_dates.sort()
    results = []
    ep_offset = 0
    for d in air_dates:
        from_ep = current_ep + 1 + ep_offset
        to_ep = current_ep + episodes_per + ep_offset
        if total > 0:
            if from_ep > total:
                break
            to_ep = min(to_ep, total)
        results.append((d, d.isoformat(), episodes_per, from_ep, to_ep, work))
        ep_offset += episodes_per
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
            d, iso, ep_cnt, from_ep, to_ep, _ = ev
            upcoming.append((d, iso, ep_cnt, from_ep, to_ep, w))
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
        end_dt = date(year, 12, 31)
    else:
        end_dt = date(year, month + 1, 1) - timedelta(days=1)
    return get_stats(start_dt, end_dt)

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

def export_full_data():
    conn = get_conn()
    c = conn.cursor()
    c.execute('SELECT * FROM works ORDER BY id')
    works = [dict(r) for r in c.fetchall()]
    c.execute('SELECT * FROM watch_logs ORDER BY work_id, watched_at')
    logs = [dict(r) for r in c.fetchall()]
    c.execute('SELECT * FROM ratings ORDER BY work_id, rated_at')
    ratings = [dict(r) for r in c.fetchall()]
    c.execute('SELECT * FROM notes ORDER BY work_id, created_at')
    notes = [dict(r) for r in c.fetchall()]
    conn.close()
    return {'works': works, 'watch_logs': logs, 'ratings': ratings, 'notes': notes}

def import_works_csv(path):
    results = []
    with open(path, 'r', encoding='utf-8-sig', newline='') as f:
        reader = csv.DictReader(f)
        for row in reader:
            title = (row.get('title') or row.get('标题') or '').strip()
            if not title:
                results.append({'row': dict(row), 'ok': False, 'error': '缺少标题'})
                continue
            work_type = (row.get('type') or row.get('类型') or 'series').strip().lower()
            if work_type not in TYPE_OPTIONS:
                work_type = 'series'
            year_raw = row.get('year') or row.get('年份')
            year = int(year_raw) if year_raw and str(year_raw).strip().isdigit() else None
            platform = (row.get('platform') or row.get('平台') or '').strip() or None
            ep_raw = row.get('episodes') or row.get('总集数') or row.get('集数')
            total_episodes = int(ep_raw) if ep_raw and str(ep_raw).strip().isdigit() else 0
            genre = (row.get('genre') or row.get('分类') or '').strip() or None
            air_weekday = (row.get('air_weekday') or row.get('更新星期') or '').strip().lower()
            if air_weekday not in WEEKDAYS:
                air_weekday = None
            ep_per_raw = row.get('episodes_per_air') or row.get('每次更新集数')
            episodes_per_air = int(ep_per_raw) if ep_per_raw and str(ep_per_raw).strip().isdigit() else 1
            rb_raw = row.get('remind_days_before') or row.get('提醒天数')
            remind_days_before = int(rb_raw) if rb_raw and str(rb_raw).strip().isdigit() else 1
            original_title = (row.get('original_title') or row.get('原名') or '').strip() or None
            next_air = (row.get('next_air_date') or row.get('下次更新') or '').strip() or None
            wid, err = add_work(
                title=title, original_title=original_title, work_type=work_type,
                year=year, platform=platform, total_episodes=total_episodes,
                genre=genre, next_air_date=next_air,
                air_weekday=air_weekday, episodes_per_air=episodes_per_air,
                remind_days_before=remind_days_before
            )
            if err:
                results.append({'row': dict(row), 'ok': False, 'error': err, 'duplicate': True})
            else:
                results.append({'row': dict(row), 'ok': True, 'id': wid})
    return results

def import_works_text(path):
    results = []
    with open(path, 'r', encoding='utf-8') as f:
        for lineno, line in enumerate(f, 1):
            line = line.strip()
            if not line or line.startswith('#'):
                continue
            parts = [p.strip() for p in line.split('|')]
            if not parts or not parts[0]:
                results.append({'row': line, 'ok': False, 'error': f'第 {lineno} 行无法解析'})
                continue
            title = parts[0]
            work_type = 'series'
            year = None
            platform = None
            total_episodes = 0
            air_weekday = None
            remind_days_before = 1
            for p in parts[1:]:
                if p.lower() in TYPE_OPTIONS:
                    work_type = p.lower()
                elif p.isdigit() and len(p) == 4:
                    year = int(p)
                elif p.startswith('@'):
                    platform = p[1:]
                elif p.lower().startswith('e') and p[1:].isdigit():
                    total_episodes = int(p[1:])
                elif p.lower() in WEEKDAYS or p in ['周' + WEEKDAY_CN.get(p.lower(), '') for p in WEEKDAYS]:
                    if p.lower() in WEEKDAYS:
                        air_weekday = p.lower()
                    else:
                        for k, v in WEEKDAY_CN.items():
                            if p == '周' + v:
                                air_weekday = k
                                break
                elif p.isdigit():
                    try:
                        remind_days_before = int(p)
                    except:
                        pass
            wid, err = add_work(
                title=title, work_type=work_type, year=year, platform=platform,
                total_episodes=total_episodes, air_weekday=air_weekday,
                remind_days_before=remind_days_before
            )
            if err:
                results.append({'row': line, 'ok': False, 'error': err, 'duplicate': True})
            else:
                results.append({'row': line, 'ok': True, 'id': wid})
    return results

def list_works(status=None, work_type=None, platform=None,
               min_rating=None, max_rating=None,
               has_notes=None, stalled_days=None, reminder_only=None):
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
    if min_rating is not None:
        query += ' AND rating >= ?'
        params.append(min_rating)
    if max_rating is not None:
        query += ' AND rating <= ?'
        params.append(max_rating)
    if has_notes is True:
        query += " AND (notes IS NOT NULL AND notes <> '')"
    elif has_notes is False:
        query += " AND (notes IS NULL OR notes = '')"
    if reminder_only is True:
        query += ' AND reminder_set = 1'
    elif reminder_only is False:
        query += ' AND (reminder_set IS NULL OR reminder_set = 0)'
    if stalled_days is not None and stalled_days > 0:
        cutoff = (date.today() - timedelta(days=stalled_days)).isoformat()
        query += ' AND status IN (?, ?) AND (last_watched_at IS NULL OR DATE(last_watched_at) < ?)'
        params.extend(['watching', 'on-hold', cutoff])
    query += ' ORDER BY last_watched_at DESC, added_at DESC'
    c.execute(query, params)
    rows = c.fetchall()
    conn.close()
    return rows

def get_duplicate_works():
    conn = get_conn()
    c = conn.cursor()
    c.execute('''SELECT LOWER(COALESCE(title,'')) as key, GROUP_CONCAT(id) as ids, COUNT(*) as cnt
        FROM works GROUP BY key HAVING cnt > 1 ORDER BY cnt DESC''')
    groups = []
    for row in c.fetchall():
        ids = [int(x) for x in row['ids'].split(',')]
        c.execute('SELECT * FROM works WHERE id IN ({}) ORDER BY id'.format(','.join('?' * len(ids))), ids)
        groups.append(list(c.fetchall()))
    conn.close()
    return groups

def get_organize_report():
    report = {}
    report['duplicates'] = get_duplicate_works()
    conn = get_conn()
    c = conn.cursor()
    c.execute('''SELECT * FROM works
        WHERE type IN ('series','anime') AND (total_episodes IS NULL OR total_episodes = 0)
        ORDER BY id''')
    report['missing_episodes'] = c.fetchall()
    c.execute('''SELECT * FROM works
        WHERE total_episodes > 0 AND COALESCE(current_episode,0) >= total_episodes AND status != 'completed'
        ORDER BY id''')
    report['finished_not_completed'] = c.fetchall()
    c.execute('''SELECT * FROM works
        WHERE air_weekday IS NOT NULL AND total_episodes > 0
        AND COALESCE(current_episode,0) >= total_episodes
        ORDER BY id''')
    report['aired_but_completed'] = c.fetchall()
    cutoff = (date.today() - timedelta(days=60)).isoformat()
    c.execute('''SELECT * FROM works
        WHERE status = 'watching' AND (last_watched_at IS NULL OR DATE(last_watched_at) < ?)
        ORDER BY last_watched_at ASC''', (cutoff,))
    report['long_stalled'] = c.fetchall()
    conn.close()
    return report

def get_stats(start_date, end_date):
    start = start_date.isoformat()
    end = (end_date + timedelta(days=1)).isoformat()
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

    c.execute('''SELECT w.id, w.title, w.type, w.rating, COUNT(wl.id) as ep_cnt
        FROM watch_logs wl JOIN works w ON wl.work_id = w.id
        WHERE wl.watched_at >= ? AND wl.watched_at < ?
        GROUP BY w.id ORDER BY ep_cnt DESC LIMIT 20''',
        (start, end))
    top_works = c.fetchall()

    c.execute('''SELECT r.score, r.work_id, w.title
        FROM ratings r JOIN works w ON r.work_id = w.id
        WHERE r.rated_at >= ? AND r.rated_at < ? ORDER BY r.score DESC''',
        (start, end))
    rated = c.fetchall()
    scores = [r['score'] for r in rated]
    avg_rating = sum(scores) / len(scores) if scores else None
    buckets = [('0-2', 0, 2, False), ('2-4', 2, 4, False), ('4-6', 4, 6, False),
               ('6-8', 6, 8, False), ('8-10', 8, 10, True)]
    rating_dist = {}
    for key, lo, hi, inclusive in buckets:
        if inclusive:
            rating_dist[key] = sum(1 for s in scores if lo <= s <= hi)
        else:
            rating_dist[key] = sum(1 for s in scores if lo <= s < hi)

    conn.close()
    return {
        'start_date': start_date,
        'end_date': end_date,
        'totals': totals,
        'watch_days': watch_days,
        'max_streak': max_streak,
        'by_platform': by_platform,
        'by_type': by_type,
        'top_works': top_works,
        'rated_works': rated,
        'avg_rating': avg_rating,
        'rating_dist': rating_dist,
        'daily_count': daily,
    }

def get_yearly_stats(year):
    return get_stats(date(year, 1, 1), date(year, 12, 31))

def restore_full_data(data, conflict='skip'):
    """从 export --full 导出的 JSON 完整恢复。conflict: skip/merge/create"""
    results = []
    conn = get_conn()
    try:
        works_data = data.get('works', [])
        logs_data = data.get('watch_logs', [])
        ratings_data = data.get('ratings', [])
        notes_data = data.get('notes', [])
        id_map = {}
        for w in works_data:
            dups = find_duplicate_work(w.get('title'), w.get('original_title'), w.get('year'))
            if dups:
                existing = dups[0]
                if conflict == 'skip':
                    results.append({'action': 'skip', 'title': w.get('title'),
                                    'existing_id': existing['id'], 'reason': '已存在同名作品'})
                    id_map[w['id']] = existing['id']
                    continue
                elif conflict == 'merge':
                    id_map[w['id']] = existing['id']
                    results.append({'action': 'merge', 'title': w.get('title'),
                                    'existing_id': existing['id'],
                                    'reason': '合并历史/评分/笔记到已有作品'})
                    continue
                # conflict == 'create': 继续往下新建
            c = conn.cursor()
            c.execute('''INSERT INTO works (title, original_title, type, year, platform,
                total_episodes, status, current_episode, rating, genre, added_at,
                last_watched_at, next_air_date, air_weekday, episodes_per_air,
                reminder_set, remind_days_before, notes)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)''',
                (w.get('title'), w.get('original_title'), w.get('type','series'),
                 w.get('year'), w.get('platform'), w.get('total_episodes') or 0,
                 w.get('status','to-watch'), w.get('current_episode') or 0,
                 w.get('rating'), w.get('genre'), w.get('added_at'),
                 w.get('last_watched_at'), w.get('next_air_date'),
                 w.get('air_weekday'), w.get('episodes_per_air') or 1,
                 w.get('reminder_set') or 0, w.get('remind_days_before') or 1,
                 w.get('notes') or ''))
            new_id = c.lastrowid
            id_map[w['id']] = new_id
            results.append({'action': 'create', 'title': w.get('title'), 'new_id': new_id})
        conn.commit()

        for l in logs_data:
            old_wid = l.get('work_id')
            if old_wid not in id_map:
                continue
            new_wid = id_map[old_wid]
            c = conn.cursor()
            if conflict == 'merge':
                c.execute('''SELECT id FROM watch_logs
                    WHERE work_id = ? AND episode IS ? AND watched_at = ?''',
                    (new_wid, l.get('episode'), l.get('watched_at')))
                if c.fetchone():
                    continue
            c.execute('''INSERT INTO watch_logs (work_id, episode, watched_at)
                VALUES (?, ?, ?)''', (new_wid, l.get('episode'), l.get('watched_at')))
        conn.commit()

        for r in ratings_data:
            old_wid = r.get('work_id')
            if old_wid not in id_map:
                continue
            new_wid = id_map[old_wid]
            c = conn.cursor()
            if conflict == 'merge':
                c.execute('''SELECT id FROM ratings
                    WHERE work_id = ? AND score = ? AND rated_at = ?''',
                    (new_wid, r.get('score'), r.get('rated_at')))
                if c.fetchone():
                    continue
            c.execute('''INSERT INTO ratings (work_id, score, rated_at)
                VALUES (?, ?, ?)''', (new_wid, r.get('score'), r.get('rated_at')))
            c.execute('UPDATE works SET rating = COALESCE((SELECT MAX(score) FROM ratings WHERE work_id = ?), rating) WHERE id = ?',
                (new_wid, new_wid))
        conn.commit()

        for n in notes_data:
            old_wid = n.get('work_id')
            if old_wid not in id_map:
                continue
            new_wid = id_map[old_wid]
            c = conn.cursor()
            if conflict == 'merge':
                c.execute('''SELECT id FROM notes
                    WHERE work_id = ? AND content = ? AND created_at = ?''',
                    (new_wid, n.get('content'), n.get('created_at')))
                if c.fetchone():
                    continue
            c.execute('''INSERT INTO notes (work_id, content, created_at)
                VALUES (?, ?, ?)''', (new_wid, n.get('content'), n.get('created_at')))
        conn.commit()

        if conflict == 'merge':
            for new_wid in set(id_map.values()):
                _recalc_work_progress(conn, new_wid)
        conn.commit()
    finally:
        conn.close()
    return results
