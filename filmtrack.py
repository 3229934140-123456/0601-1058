#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""filmtrack - 影视追踪命令行工具"""

import argparse
import sys
import os
import json
import io
from datetime import datetime, timedelta, date

if sys.platform.startswith('win'):
    try:
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
        sys.stderr.reconfigure(encoding='utf-8', errors='replace')
    except Exception:
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
        sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')
else:
    try:
        sys.stdout.reconfigure(errors='replace')
        sys.stderr.reconfigure(errors='replace')
    except Exception:
        pass
from database import (
    init_db, add_work, get_work, search_works, list_works,
    update_status, watch_episodes, rate_work, add_note, get_notes,
    get_watch_logs, get_watch_log, get_calendar_works, set_reminder, get_reminders,
    get_monthly_stats, delete_work, update_work, validate_episode,
    delete_watch_log, update_watch_log, export_full_data,
    import_works_csv, import_works_text, get_ratings, find_duplicate_work,
    STATUS_OPTIONS, TYPE_OPTIONS, WEEKDAYS, WEEKDAY_CN
)

STATUS_COLORS = {
    'to-watch': '\033[93m',
    'watching': '\033[92m',
    'completed': '\033[94m',
    'on-hold': '\033[95m',
    'dropped': '\033[91m',
}
TYPE_COLORS = {
    'movie': '\033[96m',
    'series': '\033[95m',
    'anime': '\033[93m',
    'documentary': '\033[92m',
    'variety': '\033[94m',
    'other': '\033[90m',
}
RESET = '\033[0m'
BOLD = '\033[1m'
RED = '\033[91m'
GREEN = '\033[92m'
YELLOW = '\033[93m'
CYAN = '\033[96m'
DIM = '\033[2m'

def color_status(s):
    return STATUS_COLORS.get(s, '') + s + RESET

def color_type(t):
    return TYPE_COLORS.get(t, '') + t + RESET

def stars(score):
    if score is None:
        return '-'
    full = int(score)
    half = score - full >= 0.5
    return '★' * full + ('½' if half else '') + '☆' * (5 - full - (1 if half else 0))

def print_work_row(w, show_id=True):
    parts = []
    if show_id:
        parts.append(f'{BOLD}[{w["id"]:>3}]{RESET}')
    parts.append(color_type(f'[{w["type"]:<5}]'))
    title = w['title']
    if w['original_title']:
        title += f' ({w["original_title"]})'
    if w['year']:
        title += f' {w["year"]}'
    parts.append(title)
    parts.append(color_status(w['status']))
    if w['type'] in ('series', 'anime'):
        ep_str = f'E{w["current_episode"]}'
        if w['total_episodes']:
            ep_str += f'/{w["total_episodes"]}'
        parts.append(ep_str)
    if w['rating'] is not None:
        parts.append(f'{stars(w["rating"])} ({w["rating"]})')
    if w['platform']:
        parts.append(f'@{w["platform"]}')
    if w['air_weekday']:
        parts.append(f'每周{WEEKDAY_CN.get(w["air_weekday"], w["air_weekday"])}更新')
    print('  '.join(parts))

def error(msg):
    print(f'{RED}错误：{msg}{RESET}', file=sys.stderr)
    sys.exit(1)

def warn(msg):
    print(f'{YELLOW}⚠ {msg}{RESET}')

def cmd_search(args):
    results = search_works(args.keyword)
    if not results:
        print(f'未找到与 "{args.keyword}" 相关的作品')
        return
    print(f'找到 {len(results)} 个结果：')
    for w in results:
        print_work_row(w)

def cmd_add(args):
    dups = find_duplicate_work(args.title, args.original_title, args.year)
    if dups and not args.force:
        print(f'{YELLOW}⚠ 检测到可能重复的作品：{RESET}')
        for d in dups:
            print_work_row(d)
        ans = input('是否仍要继续添加？(y/N) ')
        if ans.lower() != 'y':
            print('已取消')
            return
    work_id, err = add_work(
        title=args.title,
        original_title=args.original_title,
        work_type=args.type,
        year=args.year,
        platform=args.platform,
        total_episodes=args.episodes or 0,
        genre=args.genre,
        next_air_date=args.next_air,
        air_weekday=args.air_weekday,
        episodes_per_air=args.episodes_per_air or 1,
        remind_days_before=args.remind_before or 1,
        skip_dup_check=True,
    )
    if err:
        error(err)
    work = get_work(work_id)
    print(f'{GREEN}✓{RESET} 已添加到片库：')
    print_work_row(work)

def cmd_watch(args):
    work = get_work(args.id)
    if not work:
        error(f'未找到 ID={args.id} 的作品')

    if args.movie or work['type'] == 'movie':
        ok, err, _ = watch_episodes(args.id, movie=True, watched_at=args.date)
        if not ok:
            error(err)
        work = get_work(args.id)
        date_str = f'（{args.date}）' if args.date else ''
        print(f'{GREEN}✓{RESET} 已记录完整观看：{work["title"]}{date_str}')
        if work['status'] == 'completed':
            print('🎉 已标记为完成')
        return

    count = args.count or 1
    start = args.episode

    ok, err, logged = watch_episodes(args.id, start_episode=start, count=count, watched_at=args.date)
    if not ok:
        error(err)
    work = get_work(args.id)
    date_str = f'（记录日期：{args.date}）' if args.date else ''
    if len(logged) == 1:
        ep = logged[0]
        print(f'{GREEN}✓{RESET} 已记录观看：{work["title"]} - 第 {ep} 集{date_str}')
    else:
        print(f'{GREEN}✓{RESET} 已记录观看：{work["title"]} - 第 {logged[0]}-{logged[-1]} 集（共 {len(logged)} 集）{date_str}')
    if work['status'] == 'completed':
        print('🎉 恭喜！已标记为完成')

def cmd_status(args):
    work = get_work(args.id)
    if not work:
        error(f'未找到 ID={args.id} 的作品')
    if args.episode is not None:
        ep, err = validate_episode(work, args.episode)
        if err:
            error(err)
    ok, err = update_status(args.id, args.status, args.episode)
    if not ok:
        error(err)
    work = get_work(args.id)
    print(f'{GREEN}✓{RESET} 状态已更新：')
    print_work_row(work)

def cmd_rate(args):
    work = get_work(args.id)
    if not work:
        error(f'未找到 ID={args.id} 的作品')
    if args.score < 0 or args.score > 10:
        error('评分应在 0-10 之间')
    rate_work(args.id, args.score)
    print(f'{GREEN}✓{RESET} 已为《{work["title"]}》打分：{stars(args.score)} ({args.score}/10)')

def cmd_note(args):
    work = get_work(args.id)
    if not work:
        error(f'未找到 ID={args.id} 的作品')
    if args.view:
        notes = get_notes(args.id)
        if not notes:
            print(f'《{work["title"]}》暂无笔记')
            return
        print(f'{BOLD}《{work["title"]}》的笔记：{RESET}')
        for n in notes:
            print(f'  [{n["created_at"][:10]}] {n["content"]}')
        return
    content = ' '.join(args.content) if args.content else None
    if not content:
        error('请提供笔记内容')
    add_note(args.id, content)
    print(f'{GREEN}✓{RESET} 已添加笔记到《{work["title"]}》')

def cmd_list(args):
    works = list_works(status=args.status, work_type=args.type, platform=args.platform)
    if not works:
        print('片库为空')
        return
    header_parts = ['列表']
    if args.status:
        header_parts.append(f'状态={color_status(args.status)}')
    if args.type:
        header_parts.append(f'类型={color_type(args.type)}')
    if args.platform:
        header_parts.append(f'平台=@{args.platform}')
    print(f'{" ".join(header_parts)}（共 {len(works)} 部）：')
    for w in works:
        print_work_row(w)

def cmd_history(args):
    if args.undo:
        if not args.log_id:
            error('撤销需要提供 --log-id')
        log = get_watch_log(args.log_id)
        if not log:
            error(f'未找到日志 ID={args.log_id}')
        work = get_work(log['work_id'])
        if not args.yes:
            ep_str = f' 第 {log["episode"]} 集' if log['episode'] else ' 完整观看'
            ans = input(f'确认撤销《{work["title"]}》{ep_str} ({log["watched_at"][:10]})？(y/N) ')
            if ans.lower() != 'y':
                print('已取消')
                return
        ok, err = delete_watch_log(args.log_id)
        if not ok:
            error(err)
        work = get_work(log['work_id'])
        print(f'{GREEN}✓{RESET} 已撤销，当前进度已重算：')
        print_work_row(work)
        return

    if args.edit:
        if not args.log_id:
            error('修改需要提供 --log-id')
        log = get_watch_log(args.log_id)
        if not log:
            error(f'未找到日志 ID={args.log_id}')
        if args.episode is None and args.date is None:
            print('未指定要修改的字段（--episode 或 --date）')
            return
        ok, err = update_watch_log(args.log_id, episode=args.episode, watched_at=args.date)
        if not ok:
            error(err)
        log = get_watch_log(args.log_id)
        work = get_work(log['work_id'])
        ep_str = f' 第 {log["episode"]} 集' if log['episode'] else ' 完整观看'
        print(f'{GREEN}✓{RESET} 日志已更新：{work["title"]}{ep_str} @ {log["watched_at"][:16]}')
        print(f'  当前进度已重算：E{work["current_episode"]}，状态 {color_status(work["status"])}')
        return

    logs = get_watch_logs(
        work_id=args.work_id,
        start_date=args.from_date,
        end_date=args.to_date,
        year=args.year,
        month=args.month,
    )
    if not logs:
        print('没有匹配的观看记录')
        return
    header = [f'共 {len(logs)} 条记录']
    if args.work_id:
        w = get_work(args.work_id)
        header.append(f'作品：{w["title"]}')
    if args.year and args.month:
        header.append(f'{args.year}年{args.month}月')
    elif args.from_date or args.to_date:
        header.append(f'{args.from_date or "始"} ~ {args.to_date or "今"}')
    print(BOLD + '  '.join(header) + RESET)
    for l in logs:
        ep_str = f'  E{l["episode"]:<4}' if l['episode'] else '  电影'
        wid = f'#{l["id"]:<5}'
        print(f'  {DIM}{wid}{RESET} {l["watched_at"][:10]}  {color_type(f"[{l['work_type']:<5}]")}  {l["work_title"]}{ep_str}  {f"@{l['work_platform']}" if l["work_platform"] else ""}')
    print(f'{DIM}使用 history --undo --log-id ID  撤销记录；history --edit --log-id ID --episode X --date YYYY-MM-DD 修改{RESET}')

def cmd_calendar(args):
    start, end, events = get_calendar_works(args.range)
    range_names = {'today': '今日', 'week': '本周', 'month': '本月'}
    range_label = range_names.get(args.range, args.range)
    print(f'{BOLD}📅 {range_label}更新日历（{start.isoformat()} ~ {end.isoformat()}）{RESET}')
    if not events:
        print(f'  {YELLOW}（此范围内暂无更新安排）{RESET}')
        return
    current_date = None
    for d, iso, ep_cnt, from_ep, to_ep, w in events:
        if d != current_date:
            current_date = d
            weekday = WEEKDAY_CN[WEEKDAYS[d.weekday()]]
            today_mark = ' 【今天】' if d == date.today() else ''
            print(f'\n  {BOLD}{iso} 周{weekday}{today_mark}{RESET}')
        ep_str = ''
        if w['type'] in ('series', 'anime'):
            if from_ep == to_ep:
                ep_str = f' E{from_ep}'
            else:
                ep_str = f' E{from_ep}-{to_ep}'
            if w['total_episodes']:
                ep_str += f'/{w["total_episodes"]}'
        if ep_cnt and ep_cnt > 1 and not ep_str:
            ep_str = f' 更新{ep_cnt}集'
        print(f'    • {w["title"]} [{w["type"]}]{ep_str}')

def cmd_stats(args):
    year = args.year or datetime.now().year
    month = args.month or datetime.now().month
    s = get_monthly_stats(year, month)
    print(f'{BOLD}📊 {year}年{month}月观影统计{RESET}')
    print('='*44)
    print(f'观看作品数：  {s["totals"]["works_watched"]}')
    print(f'观看集数：    {s["totals"]["episodes_watched"]}')
    print(f'观影天数：    {s["watch_days"]} 天')
    print(f'最长连续：    {s["max_streak"]} 天')
    if s["avg_rating"]:
        print(f'平均评分：    {s["avg_rating"]:.1f}/10  {stars(s["avg_rating"])}')

    if s["by_type"]:
        total_eps = sum(t['ep_cnt'] for t in s['by_type']) or 1
        print()
        print(f'{BOLD}类型占比（按集数）：{RESET}')
        for t in s['by_type']:
            pct = t['ep_cnt'] / total_eps * 100
            bar = '█' * int(pct / 5)
            print(f'  {color_type(t["type"]):<15} {t["works_cnt"]}部 / {t["ep_cnt"]}集  {bar} {pct:.0f}%')

    if s["by_platform"]:
        total_p = sum(p['cnt'] for p in s['by_platform']) or 1
        print()
        print(f'{BOLD}观看平台：{RESET}')
        for p in s['by_platform']:
            pct = p['cnt'] / total_p * 100
            bar = '█' * int(pct / 5)
            print(f'  @{p["platform"]:<13} {p["cnt"]}集  {bar} {pct:.0f}%')

    if s["rating_dist"]:
        print()
        print(f'{BOLD}评分分布：{RESET}')
        ordered = [k for k in ['0-2', '2-4', '4-6', '6-8', '8-10'] if k in s["rating_dist"]]
        max_cnt = max(s["rating_dist"].values()) or 1
        for key in ordered:
            cnt = s["rating_dist"][key]
            bar = '█' * int(cnt / max_cnt * 20)
            print(f'  {key}分  {cnt}部  {bar}')

    if s["top_works"]:
        print()
        print(f'{BOLD}观看最多（Top {len(s["top_works"])}）：{RESET}')
        for i, w in enumerate(s["top_works"], 1):
            ep_unit = '集' if w["type"] in ('series', 'anime') else '次'
            print(f'  {i:>2}. {w["title"]}  {w["ep_cnt"]}{ep_unit}')

def cmd_export(args):
    if args.full:
        data = export_full_data()
        if not data['works']:
            print('没有可导出的内容')
            return
        if args.format == 'json':
            text = json.dumps(data, ensure_ascii=False, indent=2)
        else:
            lines = []
            lines.append(f'# filmtrack 完整导出 - {datetime.now().strftime("%Y-%m-%d %H:%M")}')
            lines.append(f'# works: {len(data["works"])}, watch_logs: {len(data["watch_logs"])}, ratings: {len(data["ratings"])}, notes: {len(data["notes"])}')
            lines.append('')
            lines.append('## WORKS')
            for w in data['works']:
                fields = [str(w.get('id','')), w.get('title',''), w.get('original_title') or '',
                          w.get('type',''), str(w.get('year') or ''), w.get('platform') or '',
                          str(w.get('total_episodes') or 0), w.get('status',''),
                          str(w.get('current_episode') or 0),
                          str(w.get('rating') if w.get('rating') is not None else ''),
                          w.get('genre') or '', w.get('added_at','')[:10],
                          w.get('last_watched_at','')[:10] if w.get('last_watched_at') else '',
                          w.get('next_air_date') or '', w.get('air_weekday') or '',
                          str(w.get('episodes_per_air') or 1),
                          str(w.get('reminder_set') or 0),
                          str(w.get('remind_days_before') or 1),
                          (w.get('notes') or '').replace('\n', ' / ')]
                lines.append('|'.join(fields))
            lines.append('')
            lines.append('## WATCH_LOGS')
            for l in data['watch_logs']:
                lines.append(f'{l["work_id"]}|{l["episode"] if l["episode"] is not None else ""}|{l["watched_at"]}')
            lines.append('')
            lines.append('## RATINGS')
            for r in data['ratings']:
                lines.append(f'{r["work_id"]}|{r["score"]}|{r["rated_at"]}')
            lines.append('')
            lines.append('## NOTES')
            for n in data['notes']:
                lines.append(f'{n["work_id"]}|{n["created_at"]}|{n["content"].replace(chr(10), " / ")}')
            text = '\n'.join(lines)
        if args.output:
            with open(args.output, 'w', encoding='utf-8') as f:
                f.write(text)
            print(f'{GREEN}✓{RESET} 完整数据已导出到 {args.output}')
        else:
            print(text)
        return

    works = list_works(status=args.status, work_type=args.type, platform=args.platform)
    if not works:
        print('没有可导出的内容')
        return
    lines = []
    lines.append(f'# 影视片库清单 - 导出于 {datetime.now().strftime("%Y-%m-%d %H:%M")}')
    lines.append(f'共 {len(works)} 部作品')
    lines.append('')
    for w in works:
        parts = []
        parts.append(f'[{w["type"]}]')
        title = w['title']
        if w['original_title']:
            title += f' ({w["original_title"]})'
        if w['year']:
            title += f' {w["year"]}'
        parts.append(title)
        parts.append(f'- 状态: {w["status"]}')
        if w['type'] in ('series', 'anime') and (w['current_episode'] or w['total_episodes']):
            parts.append(f'E{w["current_episode"]}/{w["total_episodes"] or "?"}')
        if w['rating'] is not None:
            parts.append(f'评分: {w["rating"]}/10')
        if w['platform']:
            parts.append(f'平台: {w["platform"]}')
        if w['genre']:
            parts.append(f'类型: {w["genre"]}')
        lines.append(' | '.join(parts))
        logs = get_watch_logs(work_id=w['id'])
        if logs:
            lines.append(f'  观看历史:')
            for l in logs:
                ep = f'E{l["episode"]} ' if l['episode'] else ''
                lines.append(f'    {l["watched_at"][:10]} {ep}')
        ratings = get_ratings(work_id=w['id'])
        if ratings:
            lines.append(f'  评分记录:')
            for r in ratings:
                lines.append(f'    {r["rated_at"][:10]} {r["score"]}/10')
        if w['notes']:
            lines.append(f'  笔记:')
            for note_line in w['notes'].split('\n'):
                lines.append(f'    {note_line}')
        lines.append('')
    output = '\n'.join(lines)
    if args.output:
        with open(args.output, 'w', encoding='utf-8') as f:
            f.write(output)
        print(f'{GREEN}✓{RESET} 已导出到 {args.output}')
    else:
        print(output)

def cmd_import(args):
    path = args.file
    if not os.path.exists(path):
        error(f'文件不存在：{path}')
    fmt = args.format
    if not fmt:
        if path.lower().endswith('.csv'):
            fmt = 'csv'
        else:
            fmt = 'text'
    if fmt == 'csv':
        results = import_works_csv(path)
    else:
        results = import_works_text(path)
    ok_cnt = sum(1 for r in results if r['ok'])
    dup_cnt = sum(1 for r in results if (not r['ok']) and r.get('duplicate'))
    err_cnt = len(results) - ok_cnt - dup_cnt
    print(f'导入完成：成功 {GREEN}{ok_cnt}{RESET}，重复 {YELLOW}{dup_cnt}{RESET}，错误 {RED}{err_cnt}{RESET}')
    for r in results:
        row_val = r.get('row', '')
        if isinstance(row_val, dict):
            row_val = ' | '.join(f'{k}={v}' for k, v in list(row_val.items())[:4])
        row_str = str(row_val)[:60]
        if r['ok']:
            print(f'  {GREEN}✓{RESET} [ID={r["id"]}] {row_str}')
        elif r.get('duplicate'):
            print(f'  {YELLOW}⏭{RESET} 重复跳过: {r["error"]}')
        else:
            print(f'  {RED}✗{RESET} {row_str[:40]} → {r["error"]}')

def cmd_remind(args):
    if args.set is not None or args.days_before is not None:
        if not args.id:
            error('需要指定作品 ID（--id）')
        work = get_work(args.id)
        if not work:
            error(f'未找到 ID={args.id} 的作品')
        enabled = True if args.set is None else args.set
        set_reminder(args.id, enabled=enabled, remind_days_before=args.days_before)
        status = '开启' if enabled else '关闭'
        extra = ''
        if args.days_before is not None:
            extra = f'，提前 {args.days_before} 天提醒'
        print(f'{GREEN}✓{RESET} 已为《{work["title"]}》{status}提醒{extra}')
        return
    upcoming, stalled = get_reminders()
    print(f'{BOLD}🔔 提醒{RESET}')
    print('='*44)
    print(f'{BOLD}📺 即将开播/更新：{RESET}')
    if upcoming:
        today = date.today()
        for d, iso, ep_cnt, from_ep, to_ep, w in upcoming:
            days_left = (d - today).days
            if days_left == 0:
                day_label = '今天'
            elif days_left == 1:
                day_label = '明天'
            else:
                day_label = f'{days_left}天后'
            ep_str = ''
            if w['type'] in ('series', 'anime'):
                if from_ep == to_ep:
                    ep_str = f' E{from_ep}'
                else:
                    ep_str = f' E{from_ep}-{to_ep}'
            elif ep_cnt and ep_cnt > 1:
                ep_str = f'（更新{ep_cnt}集）'
            print(f'  • {iso}（{day_label}）  {w["title"]}{ep_str}')
    else:
        print(f'  {YELLOW}暂无{RESET}')

    print()
    print(f'{BOLD}💤 长期停更作品（超过30天未观看）：{RESET}')
    if stalled:
        for w in stalled:
            last = w['last_watched_at'][:10] if w['last_watched_at'] else '从未观看'
            ep_str = f'（已看到 E{w["current_episode"]}）' if w['current_episode'] else ''
            print(f'  • {w["title"]} {ep_str}  上次观看: {last}')
    else:
        print(f'  {GREEN}没有停更作品，很棒！{RESET}')

def cmd_show(args):
    work = get_work(args.id)
    if not work:
        error(f'未找到 ID={args.id} 的作品')
    print(f'{BOLD}{"="*52}{RESET}')
    print(f'{BOLD}{work["title"]}{RESET}')
    if work['original_title']:
        print(f'原名：{work["original_title"]}')
    print(f'类型：{color_type(work["type"])}  状态：{color_status(work["status"])}')
    if work['year']:
        print(f'年份：{work["year"]}')
    if work['platform']:
        print(f'平台：@{work["platform"]}')
    if work['genre']:
        print(f'分类：{work["genre"]}')
    if work['type'] in ('series', 'anime'):
        ep_total = work['total_episodes'] or '?'
        print(f'进度：第 {work["current_episode"]} 集 / 共 {ep_total} 集')
    if work['air_weekday']:
        ep_per = f'，每次更新 {work["episodes_per_air"] or 1} 集' if (work['episodes_per_air'] or 1) > 1 else ''
        print(f'更新：每周{WEEKDAY_CN.get(work["air_weekday"], work["air_weekday"])}{ep_per}')
    if work['next_air_date']:
        print(f'下次更新：{work["next_air_date"]}')
    if work['rating'] is not None:
        print(f'评分：{stars(work["rating"])}  ({work["rating"]}/10)')
    if work['reminder_set']:
        print(f'🔔 已开启提醒（提前 {work["remind_days_before"] or 1} 天）')
    print(f'添加时间：{work["added_at"][:10]}')
    if work['last_watched_at']:
        print(f'最近观看：{work["last_watched_at"][:10]}')
    notes = get_notes(args.id)
    if notes:
        print()
        print(f'{BOLD}笔记：{RESET}')
        for n in notes:
            print(f'  [{n["created_at"][:10]}] {n["content"]}')
    ratings = get_ratings(work_id=args.id)
    if ratings:
        print()
        print(f'{BOLD}评分记录：{RESET}')
        for r in ratings:
            print(f'  [{r["rated_at"][:10]}] {stars(r["score"])} {r["score"]}/10')
    logs = get_watch_logs(work_id=args.id)
    if logs:
        print()
        print(f'{BOLD}观看记录（{len(logs)} 条）：{RESET}')
        for l in logs[:10]:
            ep_str = f' E{l["episode"]}' if l['episode'] else ' 电影'
            print(f'  [#{l["id"]}] {l["watched_at"][:10]}{ep_str}')
        if len(logs) > 10:
            print(f'  {DIM}... 还有 {len(logs)-10} 条，使用 filmtrack history --work-id {args.id} 查看全部{RESET}')
    print(f'{BOLD}{"="*52}{RESET}')

def cmd_edit(args):
    work = get_work(args.id)
    if not work:
        error(f'未找到 ID={args.id} 的作品')
    kwargs = {
        'title': args.title,
        'original_title': args.original_title,
        'type': args.type,
        'year': args.year,
        'platform': args.platform,
        'total_episodes': args.episodes,
        'next_air_date': args.next_air,
        'genre': args.genre,
        'air_weekday': args.air_weekday,
        'episodes_per_air': args.episodes_per_air,
        'remind_days_before': args.remind_before,
    }
    kwargs = {k: v for k, v in kwargs.items() if v is not None}
    if not kwargs:
        print('未提供任何修改项')
        return
    update_work(args.id, **kwargs)
    work = get_work(args.id)
    print(f'{GREEN}✓{RESET} 已更新：')
    print_work_row(work)

def cmd_delete(args):
    work = get_work(args.id)
    if not work:
        error(f'未找到 ID={args.id} 的作品')
    if not args.yes:
        ans = input(f'确认删除《{work["title"]}》及其所有记录？(y/N) ')
        if ans.lower() != 'y':
            print('已取消')
            return
    delete_work(args.id)
    print(f'{GREEN}✓{RESET} 已删除《{work["title"]}》')

def main():
    parser = argparse.ArgumentParser(
        prog='filmtrack',
        description='影视追踪命令行工具 - 在终端记录你的观影进度',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog='''
示例：
  filmtrack add "怪奇物语" -t series -e 34 -p Netflix -y 2016 --air-weekday thu --episodes-per-air 1
  filmtrack watch 1 -c 3
  filmtrack watch 1 -d 2026-06-01
  filmtrack history -w 1
  filmtrack history --undo --log-id 42
  filmtrack history --edit --log-id 42 --date 2026-05-20
  filmtrack import list.csv
  filmtrack export --full -f json -o backup.json
  filmtrack calendar -r month
  filmtrack stats -m 6
        '''
    )
    sub = parser.add_subparsers(dest='command')

    p_search = sub.add_parser('search', help='搜索片库中的作品')
    p_search.add_argument('keyword', help='搜索关键词')
    p_search.set_defaults(func=cmd_search)

    p_add = sub.add_parser('add', help='添加作品到片库（自动检测重复）')
    p_add.add_argument('title', help='作品名称')
    p_add.add_argument('--original-title', '-ot', help='原名/外文名称')
    p_add.add_argument('--type', '-t', choices=TYPE_OPTIONS, default='series', help='类型')
    p_add.add_argument('--year', '-y', type=int, help='年份')
    p_add.add_argument('--platform', '-p', help='播放平台')
    p_add.add_argument('--episodes', '-e', type=int, help='总集数')
    p_add.add_argument('--genre', '-g', help='分类标签')
    p_add.add_argument('--next-air', help='下次更新日期 YYYY-MM-DD')
    p_add.add_argument('--air-weekday', choices=WEEKDAYS, help='每周几更新')
    p_add.add_argument('--episodes-per-air', type=int, help='每次更新集数')
    p_add.add_argument('--remind-before', type=int, help='提前几天提醒')
    p_add.add_argument('--force', '-f', action='store_true', help='跳过重复检测')
    p_add.set_defaults(func=cmd_add)

    p_watch = sub.add_parser('watch', help='记录观看')
    p_watch.add_argument('id', type=int, help='作品 ID')
    p_watch.add_argument('episode', type=int, nargs='?', help='起始集数')
    p_watch.add_argument('--count', '-c', type=int, help='连续观看集数（超过总集数会报错而非截断）')
    p_watch.add_argument('--date', '-d', help='补记观看日期 YYYY-MM-DD')
    p_watch.add_argument('--movie', '-m', action='store_true', help='电影完整观看')
    p_watch.set_defaults(func=cmd_watch)

    p_status = sub.add_parser('status', help='设置作品状态')
    p_status.add_argument('id', type=int, help='作品 ID')
    p_status.add_argument('status', choices=STATUS_OPTIONS, help='状态')
    p_status.add_argument('--episode', '-e', type=int, help='设置当前集数（严格校验）')
    p_status.set_defaults(func=cmd_status)

    p_rate = sub.add_parser('rate', help='给作品打分 (0-10)')
    p_rate.add_argument('id', type=int, help='作品 ID')
    p_rate.add_argument('score', type=float, help='分数 0-10')
    p_rate.set_defaults(func=cmd_rate)

    p_note = sub.add_parser('note', help='添加/查看笔记')
    p_note.add_argument('id', type=int, help='作品 ID')
    p_note.add_argument('content', nargs='*', help='笔记内容')
    p_note.add_argument('--view', '-v', action='store_true', help='查看笔记')
    p_note.set_defaults(func=cmd_note)

    p_hist = sub.add_parser('history', help='管理观看历史：查看/撤销/修改')
    p_hist.add_argument('--work-id', '-w', type=int, help='按作品筛选')
    p_hist.add_argument('--year', type=int, help='按年份筛选')
    p_hist.add_argument('--month', type=int, help='按月份筛选')
    p_hist.add_argument('--from-date', help='起始日期 YYYY-MM-DD')
    p_hist.add_argument('--to-date', help='结束日期 YYYY-MM-DD')
    p_hist.add_argument('--undo', action='store_true', help='撤销一条记录（需 --log-id）')
    p_hist.add_argument('--edit', action='store_true', help='修改一条记录（需 --log-id + --episode/--date）')
    p_hist.add_argument('--log-id', type=int, help='日志 ID')
    p_hist.add_argument('--episode', type=int, help='修改后的集数')
    p_hist.add_argument('--date', '-d', help='修改后的日期 YYYY-MM-DD')
    p_hist.add_argument('--yes', '-y', action='store_true', help='跳过撤销确认')
    p_hist.set_defaults(func=cmd_history)

    p_list = sub.add_parser('list', help='列出片单')
    p_list.add_argument('--status', '-s', choices=STATUS_OPTIONS, help='按状态筛选')
    p_list.add_argument('--type', '-t', choices=TYPE_OPTIONS, help='按类型筛选')
    p_list.add_argument('--platform', '-p', help='按平台筛选')
    p_list.set_defaults(func=cmd_list)

    p_cal = sub.add_parser('calendar', help='查看更新日历（已完结作品不再显示）')
    p_cal.add_argument('--range', '-r', choices=['today', 'week', 'month'], default='week',
                       help='today/week/month')
    p_cal.set_defaults(func=cmd_calendar)

    p_stats = sub.add_parser('stats', help='月度观影统计')
    p_stats.add_argument('--year', '-y', type=int, help='年份')
    p_stats.add_argument('--month', '-m', type=int, help='月份')
    p_stats.set_defaults(func=cmd_stats)

    p_export = sub.add_parser('export', help='导出（简单清单或完整备份）')
    p_export.add_argument('--output', '-o', help='输出文件路径')
    p_export.add_argument('--status', '-s', choices=STATUS_OPTIONS)
    p_export.add_argument('--type', '-t', choices=TYPE_OPTIONS)
    p_export.add_argument('--platform', '-p')
    p_export.add_argument('--full', '-f', action='store_true', help='完整导出（含观看日志、评分、笔记）便于迁移')
    p_export.add_argument('--format', choices=['text', 'json'], default='text', help='完整导出时的格式')
    p_export.set_defaults(func=cmd_export)

    p_import = sub.add_parser('import', help='从 CSV 或简单文本批量导入作品（自动检测重复）')
    p_import.add_argument('file', help='输入文件路径')
    p_import.add_argument('--format', '-f', choices=['csv', 'text'], help='文件格式（默认按扩展名推断）')
    p_import.set_defaults(func=cmd_import)

    p_remind = sub.add_parser('remind', help='查看和设置提醒')
    p_remind.add_argument('--id', type=int, help='作品 ID')
    p_remind.add_argument('--set', type=lambda x: x.lower() in ('1','true','yes','on'), help='on/off')
    p_remind.add_argument('--days-before', type=int, help='提前几天提醒')
    p_remind.set_defaults(func=cmd_remind)

    p_show = sub.add_parser('show', help='显示作品详情')
    p_show.add_argument('id', type=int, help='作品 ID')
    p_show.set_defaults(func=cmd_show)

    p_edit = sub.add_parser('edit', help='编辑作品信息')
    p_edit.add_argument('id', type=int, help='作品 ID')
    p_edit.add_argument('--title')
    p_edit.add_argument('--original-title', '-ot')
    p_edit.add_argument('--type', '-t', choices=TYPE_OPTIONS)
    p_edit.add_argument('--year', '-y', type=int)
    p_edit.add_argument('--platform', '-p')
    p_edit.add_argument('--episodes', '-e', type=int)
    p_edit.add_argument('--next-air')
    p_edit.add_argument('--genre', '-g')
    p_edit.add_argument('--air-weekday', choices=WEEKDAYS)
    p_edit.add_argument('--episodes-per-air', type=int)
    p_edit.add_argument('--remind-before', type=int)
    p_edit.set_defaults(func=cmd_edit)

    p_del = sub.add_parser('delete', help='删除作品')
    p_del.add_argument('id', type=int, help='作品 ID')
    p_del.add_argument('--yes', '-y', action='store_true', help='跳过确认')
    p_del.set_defaults(func=cmd_delete)

    args = parser.parse_args()
    if not args.command:
        parser.print_help()
        sys.exit(0)

    init_db()
    args.func(args)

if __name__ == '__main__':
    main()
