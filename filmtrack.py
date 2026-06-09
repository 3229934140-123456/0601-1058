#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""filmtrack - 影视追踪命令行工具"""

import argparse
import sys
import os
from datetime import datetime
from database import (
    init_db, add_work, get_work, search_works, list_works,
    update_status, watch_episode, rate_work, add_note, get_notes,
    get_watch_logs, get_calendar_works, set_reminder, get_reminders,
    get_monthly_stats, delete_work, update_work,
    STATUS_OPTIONS, TYPE_OPTIONS
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

def color_status(s):
    return STATUS_COLORS.get(s, '') + s + RESET

def color_type(t):
    return TYPE_COLORS.get(t, '') + t + RESET

def stars(score):
    if score is None:
        return '-'
    full = int(score)
    half = score - full >= 0.5
    return '★' * full + ('☆' if half else '') + '☆' * (5 - full - (1 if half else 0))

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
    print('  '.join(parts))

def cmd_search(args):
    results = search_works(args.keyword)
    if not results:
        print(f'未找到与 "{args.keyword}" 相关的作品')
        return
    print(f'找到 {len(results)} 个结果：')
    for w in results:
        print_work_row(w)

def cmd_add(args):
    work_id = add_work(
        title=args.title,
        original_title=args.original_title,
        work_type=args.type,
        year=args.year,
        platform=args.platform,
        total_episodes=args.episodes or 0,
        genre=args.genre,
        next_air_date=args.next_air
    )
    work = get_work(work_id)
    print(f'已添加到片库：')
    print_work_row(work)

def cmd_watch(args):
    work = get_work(args.id)
    if not work:
        print(f'错误：未找到 ID={args.id} 的作品')
        sys.exit(1)
    ep = watch_episode(args.id, args.episode)
    if ep is None:
        print('记录失败')
        sys.exit(1)
    work = get_work(args.id)
    print(f'已记录观看：{work["title"]} - 第 {ep} 集')
    if work['status'] == 'completed':
        print('🎉 恭喜！已标记为完成')

def cmd_status(args):
    work = get_work(args.id)
    if not work:
        print(f'错误：未找到 ID={args.id} 的作品')
        sys.exit(1)
    update_status(args.id, args.status, args.episode)
    work = get_work(args.id)
    print('状态已更新：')
    print_work_row(work)

def cmd_rate(args):
    work = get_work(args.id)
    if not work:
        print(f'错误：未找到 ID={args.id} 的作品')
        sys.exit(1)
    if args.score < 0 or args.score > 10:
        print('错误：评分应在 0-10 之间')
        sys.exit(1)
    rate_work(args.id, args.score)
    print(f'已为《{work["title"]}》打分：{stars(args.score)} ({args.score}/10)')

def cmd_note(args):
    work = get_work(args.id)
    if not work:
        print(f'错误：未找到 ID={args.id} 的作品')
        sys.exit(1)
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
        print('错误：请提供笔记内容')
        sys.exit(1)
    add_note(args.id, content)
    print(f'已添加笔记到《{work["title"]}》')

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

def cmd_calendar(args):
    works = get_calendar_works()
    from datetime import timedelta
    today = datetime.now().date()
    week_end = today + timedelta(days=6)
    print(f'{BOLD}本周更新日历（{today.isoformat()} ~ {week_end.isoformat()}）{RESET}')
    if not works:
        print('  本周暂无更新安排')
        return
    for w in works:
        date_str = w['next_air_date']
        try:
            d = datetime.fromisoformat(date_str).date()
            weekday = ['一','二','三','四','五','六','日'][d.weekday()]
            date_str = f'{d.isoformat()} 周{weekday}'
        except:
            pass
        ep_str = ''
        if w['current_episode'] or w['total_episodes']:
            ep_str = f' E{w["current_episode"]+1}'
            if w['total_episodes']:
                ep_str += f'/{w["total_episodes"]}'
        print(f'  {date_str}  {BOLD}{w["title"]}{RESET}{ep_str}  [{w["type"]}]')

def cmd_stats(args):
    year = args.year or datetime.now().year
    month = args.month or datetime.now().month
    stats = get_monthly_stats(year, month)
    print(f'{BOLD}{year}年{month}月观影统计{RESET}')
    print('='*40)
    print(f'观看作品数：{stats["totals"]["works_watched"]}')
    print(f'观看集数：{stats["totals"]["episodes_watched"]}')
    if stats["avg_rating"]:
        print(f'平均评分：{stats["avg_rating"]:.1f}/10  {stars(stats["avg_rating"])}')
    if stats["by_type"]:
        print()
        print(f'{BOLD}按类型：{RESET}')
        for t in stats["by_type"]:
            print(f'  {color_type(t["type"]):<20} {t["cnt"]} 部')
    if stats["top_works"]:
        print()
        print(f'{BOLD}观看最多（Top {len(stats["top_works"])}）：{RESET}')
        for i, w in enumerate(stats["top_works"], 1):
            ep_unit = '集' if w["type"] in ('series','anime') else '次'
            print(f'  {i:>2}. {w["title"]}  {w["ep_cnt"]}{ep_unit}')

def cmd_export(args):
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
        if w['type'] in ('series','anime') and (w['current_episode'] or w['total_episodes']):
            parts.append(f'E{w["current_episode"]}/{w["total_episodes"] or "?"}')
        if w['rating'] is not None:
            parts.append(f'评分: {w["rating"]}/10')
        if w['platform']:
            parts.append(f'平台: {w["platform"]}')
        if w['genre']:
            parts.append(f'类型: {w["genre"]}')
        lines.append(' | '.join(parts))
        if w['notes']:
            lines.append(f'  笔记:')
            for note_line in w['notes'].split('\n'):
                lines.append(f'    {note_line}')
        lines.append('')
    output = '\n'.join(lines)
    if args.output:
        with open(args.output, 'w', encoding='utf-8') as f:
            f.write(output)
        print(f'已导出到 {args.output}')
    else:
        print(output)

def cmd_remind(args):
    if args.set is not None:
        work = get_work(args.id)
        if not work:
            print(f'错误：未找到 ID={args.id} 的作品')
            sys.exit(1)
        set_reminder(args.id, args.set)
        status = '开启' if args.set else '关闭'
        print(f'已为《{work["title"]}》{status}提醒')
        return
    upcoming, stalled = get_reminders()
    print(f'{BOLD}🔔 提醒{RESET}')
    print('='*40)
    print(f'{BOLD}即将播出（今天+明天）：{RESET}')
    if upcoming:
        for w in upcoming:
            print(f'  📺 {w["next_air_date"]}  {w["title"]}')
    else:
        print('  暂无')
    print()
    print(f'{BOLD}⚠️ 长期停更作品（超过30天未观看）：{RESET}')
    if stalled:
        for w in stalled:
            last = w['last_watched_at'][:10] if w['last_watched_at'] else '从未'
            ep_str = f'（已看到 E{w["current_episode"]}）' if w['current_episode'] else ''
            print(f'  💤 {w["title"]} {ep_str}  上次观看: {last}')
    else:
        print('  没有停更作品，很棒！')

def cmd_show(args):
    work = get_work(args.id)
    if not work:
        print(f'错误：未找到 ID={args.id} 的作品')
        sys.exit(1)
    print(f'{BOLD}{"="*50}{RESET}')
    print(f'{BOLD}{work["title"]}{RESET}')
    if work['original_title']:
        print(f'原名：{work["original_title"]}')
    print(f'类型：{color_type(work["type"])}  状态：{color_status(work["status"])}')
    if work['year']:
        print(f'年份：{work["year"]}')
    if work['platform']:
        print(f'平台：{work["platform"]}')
    if work['genre']:
        print(f'分类：{work["genre"]}')
    if work['type'] in ('series','anime'):
        ep_total = work['total_episodes'] or '?'
        print(f'进度：第 {work["current_episode"]} 集 / 共 {ep_total} 集')
    if work['rating'] is not None:
        print(f'评分：{stars(work["rating"])}  ({work["rating"]}/10)')
    if work['next_air_date']:
        print(f'下次更新：{work["next_air_date"]}')
    print(f'添加时间：{work["added_at"][:10]}')
    if work['last_watched_at']:
        print(f'最近观看：{work["last_watched_at"][:10]}')
    if work['reminder_set']:
        print('🔔 已开启提醒')
    notes = get_notes(args.id)
    if notes:
        print()
        print(f'{BOLD}笔记：{RESET}')
        for n in notes:
            print(f'  [{n["created_at"][:10]}] {n["content"]}')
    logs = get_watch_logs(work_id=args.id)
    if logs:
        print()
        print(f'{BOLD}最近观看记录（{len(logs)} 条）：{RESET}')
        for l in logs[:5]:
            ep_str = f' E{l["episode"]}' if l['episode'] else ''
            print(f'  {l["watched_at"][:10]}{ep_str}')
    print(f'{BOLD}{"="*50}{RESET}')

def cmd_edit(args):
    work = get_work(args.id)
    if not work:
        print(f'错误：未找到 ID={args.id} 的作品')
        sys.exit(1)
    kwargs = {
        'title': args.title,
        'original_title': args.original_title,
        'type': args.type,
        'year': args.year,
        'platform': args.platform,
        'total_episodes': args.episodes,
        'next_air_date': args.next_air,
        'genre': args.genre,
    }
    kwargs = {k: v for k, v in kwargs.items() if v is not None}
    if not kwargs:
        print('未提供任何修改项')
        return
    update_work(args.id, **kwargs)
    work = get_work(args.id)
    print('已更新：')
    print_work_row(work)

def cmd_delete(args):
    work = get_work(args.id)
    if not work:
        print(f'错误：未找到 ID={args.id} 的作品')
        sys.exit(1)
    if not args.yes:
        ans = input(f'确认删除《{work["title"]}》及其所有记录？(y/N) ')
        if ans.lower() != 'y':
            print('已取消')
            return
    delete_work(args.id)
    print(f'已删除《{work["title"]}》')

def main():
    parser = argparse.ArgumentParser(
        prog='filmtrack',
        description='影视追踪命令行工具 - 在终端记录你的观影进度',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog='''
示例：
  filmtrack add "怪奇物语" --type series --episodes 34 --platform Netflix --year 2016
  filmtrack search 物语
  filmtrack watch 1
  filmtrack rate 1 9.5
  filmtrack note 1 "第四季太精彩了！"
  filmtrack list --status watching
  filmtrack calendar
  filmtrack stats --month 5
  filmtrack remind
  filmtrack export -o mylist.txt
        '''
    )
    sub = parser.add_subparsers(dest='command')

    p_search = sub.add_parser('search', help='搜索片库中的作品')
    p_search.add_argument('keyword', help='搜索关键词')
    p_search.set_defaults(func=cmd_search)

    p_add = sub.add_parser('add', help='添加作品到片库')
    p_add.add_argument('title', help='作品名称')
    p_add.add_argument('--original-title', '-ot', help='原名/外文名称')
    p_add.add_argument('--type', '-t', choices=TYPE_OPTIONS, default='series', help='类型')
    p_add.add_argument('--year', '-y', type=int, help='年份')
    p_add.add_argument('--platform', '-p', help='播放平台（如 Netflix、HBO、B站）')
    p_add.add_argument('--episodes', '-e', type=int, help='总集数')
    p_add.add_argument('--genre', '-g', help='分类标签（如 科幻/悬疑）')
    p_add.add_argument('--next-air', help='下次更新日期 YYYY-MM-DD')
    p_add.set_defaults(func=cmd_add)

    p_watch = sub.add_parser('watch', help='记录观看一集')
    p_watch.add_argument('id', type=int, help='作品 ID')
    p_watch.add_argument('episode', type=int, nargs='?', help='集数（默认下一集）')
    p_watch.set_defaults(func=cmd_watch)

    p_status = sub.add_parser('status', help='设置作品状态')
    p_status.add_argument('id', type=int, help='作品 ID')
    p_status.add_argument('status', choices=STATUS_OPTIONS, help='状态')
    p_status.add_argument('--episode', '-e', type=int, help='同时设置当前集数')
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

    p_list = sub.add_parser('list', help='列出片单')
    p_list.add_argument('--status', '-s', choices=STATUS_OPTIONS, help='按状态筛选')
    p_list.add_argument('--type', '-t', choices=TYPE_OPTIONS, help='按类型筛选')
    p_list.add_argument('--platform', '-p', help='按平台筛选')
    p_list.set_defaults(func=cmd_list)

    p_cal = sub.add_parser('calendar', help='查看本周更新日历')
    p_cal.set_defaults(func=cmd_calendar)

    p_stats = sub.add_parser('stats', help='查看月度观影统计')
    p_stats.add_argument('--year', '-y', type=int, help='年份（默认今年）')
    p_stats.add_argument('--month', '-m', type=int, help='月份（默认本月）')
    p_stats.set_defaults(func=cmd_stats)

    p_export = sub.add_parser('export', help='导出片单为文本')
    p_export.add_argument('--output', '-o', help='输出文件路径（默认打印到终端）')
    p_export.add_argument('--status', '-s', choices=STATUS_OPTIONS, help='按状态筛选')
    p_export.add_argument('--type', '-t', choices=TYPE_OPTIONS, help='按类型筛选')
    p_export.add_argument('--platform', '-p', help='按平台筛选')
    p_export.set_defaults(func=cmd_export)

    p_remind = sub.add_parser('remind', help='查看和设置提醒')
    p_remind.add_argument('--id', type=int, help='作品 ID（配合 --set 使用）')
    p_remind.add_argument('--set', type=lambda x: x.lower() in ('1','true','yes','on'), help='开启/关闭提醒 (on/off)')
    p_remind.set_defaults(func=cmd_remind)

    p_show = sub.add_parser('show', help='显示作品详情')
    p_show.add_argument('id', type=int, help='作品 ID')
    p_show.set_defaults(func=cmd_show)

    p_edit = sub.add_parser('edit', help='编辑作品信息')
    p_edit.add_argument('id', type=int, help='作品 ID')
    p_edit.add_argument('--title', help='新标题')
    p_edit.add_argument('--original-title', '-ot', help='新原名')
    p_edit.add_argument('--type', '-t', choices=TYPE_OPTIONS, help='新类型')
    p_edit.add_argument('--year', '-y', type=int, help='新年份')
    p_edit.add_argument('--platform', '-p', help='新平台')
    p_edit.add_argument('--episodes', '-e', type=int, help='新总集数')
    p_edit.add_argument('--next-air', help='新下次更新日期')
    p_edit.add_argument('--genre', '-g', help='新分类标签')
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
