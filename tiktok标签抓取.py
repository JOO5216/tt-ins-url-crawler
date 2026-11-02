# -*- coding: utf-8 -*-
"""抓取 TikTok 单个 Tag 下 3000 个不同博主及其代表视频。"""

import re
import json
import importlib.util
import random
import sys
import time
from datetime import datetime
from pathlib import Path
from urllib.parse import quote, unquote, urlsplit


SCRIPT_DIR = Path(__file__).resolve().parent
CORE_PATH = SCRIPT_DIR / "tiktok拍同款抓取.py"
PROFILE_DIR = SCRIPT_DIR / ".tiktok_tag_playwright_profile"
TARGET_CREATORS = 3000
MAX_SCROLLS = 800
HEADERS = ['序号', 'TikTok账号', '账号类型', '视频URL', '账号主页',
           '时长(秒)', '播放量', '点赞量', '封面人脸数', '视频文案', '来源标签', '封面URL']


def page_stop_reason(data, cursor, seen):
    if 'hasMore' not in data:
        return '分页异常：缺少 hasMore'
    if data['hasMore'] in (False, 0, '0', 'false'):
        return '接口明确返回 hasMore=false；仅代表本次接口结果结束'
    if not data.get('videos'):
        return '分页异常：hasMore 为真但视频列表为空'
    if data.get('cursor') is None:
        return '分页异常：缺少下一页 cursor'
    if str(data['cursor']) in {str(x) for x in seen} | {str(cursor)}:
        return '分页异常：下一页 cursor 重复'
    return None


def log_page(path, **record):
    with Path(path).open('a', encoding='utf-8') as file:
        file.write(json.dumps(record, ensure_ascii=False) + '\n')


def add_creator(rows, handle, url, **metadata):
    handle = '@' + handle.strip().lstrip('@')
    key = handle.casefold()
    if key == '@' or key in rows or len(rows) >= TARGET_CREATORS:
        return False
    rows[key] = dict(handle=handle, url=url, **metadata)
    return True


def export_xlsx(rows, tag, output=None):
    from openpyxl import Workbook
    from openpyxl.utils import get_column_letter
    safe_tag = re.sub(r'[<>:"/\\|?*\x00-\x1f]', '_', tag)
    output = output or SCRIPT_DIR / f'TikTok标签_{safe_tag}_{datetime.now():%Y%m%d_%H%M%S_%f}.xlsx'
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = 'TikTok账号'
    sheet.append(HEADERS)
    for index, row in enumerate(rows.values(), 1):
        values = [index, row['handle'], None, row['url'],
                  'https://www.tiktok.com/' + row['handle'], row.get('duration'),
                  row.get('plays'), row.get('likes'), None, row.get('caption'),
                  '#' + tag, row.get('cover')]
        sheet.append(values)
        for cell in sheet[sheet.max_row]:
            if isinstance(cell.value, str):
                cell.data_type = 's'
    sheet.freeze_panes = 'A2'
    sheet.auto_filter.ref = sheet.dimensions
    for i, width in enumerate([8, 25, 14, 55, 40, 12, 16, 16, 14, 60, 24, 55], 1):
        sheet.column_dimensions[get_column_letter(i)].width = width
    workbook.save(output)
    return output


def load_core():
    if not CORE_PATH.exists():
        raise SystemExit(f"缺少依赖脚本：{CORE_PATH}")
    spec = importlib.util.spec_from_file_location("tiktok_music_core", CORE_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def parse_tag(value):
    value = value.strip()
    if value.startswith(("http://", "https://")):
        parts = [unquote(part) for part in urlsplit(value).path.split("/") if part]
        if "tag" not in parts or parts.index("tag") + 1 >= len(parts):
            raise SystemExit("这不是 TikTok Tag 链接，应类似：https://www.tiktok.com/tag/ballet")
        return parts[parts.index("tag") + 1].lstrip("#")
    return value.lstrip("#")


def safe_tag_name(tag):
    return re.sub(r'[<>:"/\\|?*\x00-\x1f]', '_', tag)


def checkpoint_path(tag):
    return SCRIPT_DIR / f'.tag_{safe_tag_name(tag)}_checkpoint.json'


def load_checkpoint(tag):
    path = checkpoint_path(tag)
    if not path.exists():
        return None
    try:
        state = json.loads(path.read_text(encoding='utf-8'))
    except (OSError, json.JSONDecodeError):
        return None
    if state.get('tag') != tag:
        return None
    return state


def save_checkpoint(state):
    path = checkpoint_path(state['tag'])
    temp = path.with_suffix('.tmp')
    temp.write_text(json.dumps(state, ensure_ascii=False), encoding='utf-8')
    temp.replace(path)


def video_has_tag(video, tag):
    tag_key = tag.casefold().replace(' ', '')
    chunks = [str(video.get('title') or video.get('desc') or '')]
    for key in ('challenges', 'challenges_info', 'challenge'):
        value = video.get(key)
        if value:
            chunks.append(json.dumps(value, ensure_ascii=False))
    blob = ' '.join(chunks).casefold().replace(' ', '')
    return tag_key in blob or f'#{tag_key}' in blob


def ingest_video(rows, video, bag, require_tag=None):
    if require_tag and not video_has_tag(video, require_tag):
        return False
    author = video.get('author') or {}
    handle = str(author.get('unique_id') or author.get('uniqueId') or '').lstrip('@').strip()
    video_id = str(video.get('video_id') or video.get('id') or '').strip()
    if not handle or not video_id.isdigit():
        return False
    music = video.get('music_info') or video.get('music') or {}
    music_id = str(music.get('id') or '').strip()
    if music_id.isdigit():
        bag['music_ids'][music_id] = True
    bag['video_ids'][video_id] = True
    return add_creator(
        rows, handle, f'https://www.tiktok.com/@{handle}/video/{video_id}',
        duration=video.get('duration'), plays=video.get('play_count'),
        likes=video.get('digg_count'), caption=video.get('title') or video.get('desc'),
        cover=video.get('cover') or video.get('origin_cover'),
    )


def ingest_many(rows, videos, bag, require_tag=None):
    added = 0
    for video in videos or []:
        if ingest_video(rows, video, bag, require_tag=require_tag):
            added += 1
    return added


def api_call(core, path, params, retries=8):
    last_error = None
    for attempt in range(retries):
        if attempt:
            delay = min(60, 5 * attempt) + random.uniform(0.2, 0.8)
            print(f'等待 {delay:.0f} 秒后重试（{attempt + 1}/{retries}）')
            time.sleep(delay)
        else:
            time.sleep(1.2 + random.uniform(0, 0.4))
        try:
            payload = core.api_get(f'{core.TIKWM}{path}', params)
        except core.ApiUnavailable as error:
            last_error = str(error)
            print(f'请求失败：{error}')
            continue
        if payload.get('code') == 0:
            return payload
        last_error = str(payload.get('msg') or payload.get('message') or payload)
        print(f'接口返回失败：{last_error}')
        if 'limit' not in last_error.lower() and attempt >= 3:
            break
    return {'code': -1, 'msg': last_error, 'data': {}}


def persist_bag(bag, rows):
    state = bag['state']
    state['rows'] = rows
    state['video_ids'] = list(bag['video_ids'])
    state['music_ids'] = list(bag['music_ids'])
    save_checkpoint(state)


def paginate(core, path, params, rows, bag, log_path, label, require_tag=None, max_pages=None):
    cursor = params.get('cursor', 0)
    seen = set()
    page_no = 0
    stale = 0
    while len(rows) < TARGET_CREATORS:
        if max_pages is not None and page_no >= max_pages:
            break
        if str(cursor) in seen:
            print(f'{label}：cursor 重复，结束本路')
            break
        seen.add(str(cursor))
        query = dict(params)
        query['cursor'] = cursor
        query.setdefault('count', 30)
        payload = api_call(core, path, query)
        data = payload.get('data') or {}
        videos = data.get('videos') or data.get('itemList') or []
        page_no += 1
        before = len(rows)
        added = ingest_many(rows, videos, bag, require_tag=require_tag)
        if payload.get('code') != 0:
            reason = f"接口失败：{payload.get('msg')}"
        else:
            check = dict(data)
            check['videos'] = videos
            reason = page_stop_reason(check, cursor, seen) if 'hasMore' in data else (
                None if videos and data.get('cursor') not in {None, cursor} else '本路没有更多分页'
            )
        if added == 0 and videos:
            stale += 1
        else:
            stale = 0
        if stale >= 5:
            reason = reason or '连续 5 页没有新博主'
        log_page(log_path, source=label, page=page_no, cursor=cursor,
                 next_cursor=data.get('cursor'), hasMore=data.get('hasMore'),
                 videos=len(videos), new_creators=added, creators=len(rows),
                 reason=reason)
        print(f'{label} 第 {page_no} 页：返回 {len(videos)} 条，新增博主 {len(rows) - before}，'
              f'累计 {len(rows)}/{TARGET_CREATORS}')
        persist_bag(bag, rows)
        if len(rows) >= TARGET_CREATORS:
            return
        if reason or not videos:
            if reason:
                print(f'{label} 结束：{reason}')
            break
        cursor = data.get('cursor')
        if cursor is None:
            break


def resolve_challenge_id(core, tag):
    payload = api_call(core, '/challenge/info', {'challenge_name': tag})
    if payload.get('code') != 0:
        raise core.ApiUnavailable(f"TikWM 无法解析 Tag：{payload.get('msg')}")
    challenge_id = str((payload.get('data') or {}).get('id') or '')
    if not challenge_id:
        raise core.ApiUnavailable('Tag 响应中没有 challenge_id')
    return challenge_id


def fetch_challenge(core, challenge_id, rows, bag, log_path):
    print(f'challenge_id：{challenge_id}，开始标签视频分页')
    paginate(core, '/challenge/posts',
             {'challenge_id': challenge_id, 'count': 30, 'cursor': 0},
             rows, bag, log_path, '标签接口')


def fetch_search(core, tag, rows, bag, log_path):
    combos = [(0, 0), (1, 0), (3, 0), (0, 7), (0, 30), (1, 30), (3, 90), (0, 180)]
    for sort_type, publish_time in combos:
        if len(rows) >= TARGET_CREATORS:
            return
        label = f'搜索 sort={sort_type} time={publish_time}'
        print(f'标签接口不足，改用 {label}')
        paginate(core, '/feed/search',
                 {'keywords': tag, 'count': 30, 'cursor': 0,
                  'sort_type': sort_type, 'publish_time': publish_time},
                 rows, bag, log_path, label, require_tag=tag)


def fetch_related(core, rows, bag, log_path, tag):
    video_ids = list(bag['video_ids'])[:120]
    print(f'从已抓到的 {len(video_ids)} 条视频做相关推荐扩展（仅保留带 #{tag} 的作品）')
    for index, video_id in enumerate(video_ids, 1):
        if len(rows) >= TARGET_CREATORS:
            return
        paginate(core, '/related/posts',
                 {'video_id': video_id, 'count': 20, 'cursor': 0},
                 rows, bag, log_path, f'相关视频 {index}/{len(video_ids)}',
                 require_tag=tag, max_pages=2)


def fetch_music(core, rows, bag, log_path, tag):
    music_ids = list(bag['music_ids'])[:40]
    print(f'从 {len(music_ids)} 个原声扩展（仅保留带 #{tag} 的作品）')
    for index, music_id in enumerate(music_ids, 1):
        if len(rows) >= TARGET_CREATORS:
            return
        paginate(core, '/music/posts',
                 {'music_id': music_id, 'count': 30, 'cursor': 0},
                 rows, bag, log_path, f'原声 {index}/{len(music_ids)}',
                 require_tag=tag, max_pages=3)


def collect_browser_json(obj, rows, bag, tag):
    if isinstance(obj, dict):
        author = obj.get('author') if isinstance(obj.get('author'), dict) else {}
        handle = author.get('uniqueId') or author.get('unique_id')
        video_id = obj.get('id') or obj.get('video_id')
        desc = obj.get('desc') or obj.get('title') or ''
        stats = obj.get('stats') or {}
        video = {
            'id': video_id,
            'title': desc,
            'author': {'unique_id': handle},
            'duration': (obj.get('video') or {}).get('duration') or obj.get('duration'),
            'play_count': stats.get('playCount') or obj.get('play_count'),
            'digg_count': stats.get('diggCount') or obj.get('digg_count'),
            'cover': ((obj.get('video') or {}).get('cover') or obj.get('cover')),
            'challenges': obj.get('challenges') or obj.get('textExtra'),
            'music_info': {'id': (obj.get('music') or {}).get('id')},
        }
        if handle and str(video_id or '').isdigit():
            ingest_video(rows, video, bag)
        for value in obj.values():
            collect_browser_json(value, rows, bag, tag)
    elif isinstance(obj, list):
        for item in obj:
            collect_browser_json(item, rows, bag, tag)


def scan_browser_page(page, core, rows, bag, tag, label):
    before = len(rows)
    cards = page.locator('a[href*="/video/"]').evaluate_all("""els => els.map(a => {
        const img = a.querySelector('img');
        return {url: a.href, cover: img?.currentSrc || img?.src || null,
                caption: img?.alt || null};
    })""")
    for card in cards:
        parsed = core.parse_video_url(card['url'])
        if not parsed:
            continue
        url, handle = parsed
        video_id = url.rsplit('/', 1)[-1]
        cover = card['cover']
        if cover and not cover.startswith(('https://', 'http://')):
            cover = None
        bag['video_ids'][video_id] = True
        add_creator(rows, handle, url, cover=cover, caption=card['caption'])
    added = len(rows) - before
    print(f'{label}：页面卡片新增 {added}，累计 {len(rows)}/{TARGET_CREATORS}')
    return added


def fetch_by_browser(core, tag, rows, bag):
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print('未安装 Playwright，跳过浏览器兜底。可运行：python -m pip install playwright')
        return rows

    tag_url = f'https://www.tiktok.com/tag/{quote(tag)}'
    search_url = f'https://www.tiktok.com/search?q={quote("#" + tag)}'
    PROFILE_DIR.mkdir(parents=True, exist_ok=True)

    with sync_playwright() as playwright:
        context = playwright.chromium.launch_persistent_context(
            str(PROFILE_DIR), channel='chrome', headless=False, viewport=None
        )
        page = context.pages[0] if context.pages else context.new_page()

        def on_response(response):
            url = response.url.lower()
            if not any(key in url for key in ('item_list', 'search/item', 'challenge/', 'api/post/item')):
                return
            if 'json' not in (response.headers.get('content-type') or ''):
                return
            try:
                collect_browser_json(response.json(), rows, bag, tag)
            except Exception:
                return

        page.on('response', on_response)
        try:
            for name, url in (('标签页', tag_url), ('搜索页', search_url)):
                if len(rows) >= TARGET_CREATORS:
                    break
                print(f'打开浏览器{name}：{url}')
                page.goto(url, wait_until='domcontentloaded', timeout=60_000)
                page.wait_for_timeout(5000)
                if page.locator('a[href*="/video/"]').count() == 0:
                    input('如浏览器要求登录或验证，请完成后按回车：')
                stale = 0
                reloads = 0
                for round_no in range(1, MAX_SCROLLS + 1):
                    if len(rows) >= TARGET_CREATORS:
                        break
                    before = len(rows)
                    scan_browser_page(page, core, rows, bag, tag, f'浏览器{name}第 {round_no} 次')
                    persist_bag(bag, rows)
                    if len(rows) == before:
                        stale += 1
                    else:
                        stale = 0
                    if stale >= 12:
                        if reloads == 0:
                            print(f'{name} 停滞，重新加载一次')
                            page.reload(wait_until='domcontentloaded')
                            page.wait_for_timeout(6000)
                            reloads += 1
                            stale = 0
                            continue
                        break
                    page.mouse.wheel(0, 1400)
                    page.wait_for_timeout(1800)
                    if stale and stale % 4 == 0:
                        page.mouse.wheel(0, -500)
                        page.wait_for_timeout(800)
        except KeyboardInterrupt:
            print(f'\n已暂停浏览器，保留当前 {len(rows)} 个不同博主。')
        finally:
            try:
                context.close()
            except Exception:
                pass
    return rows


def fetch_all(core, tag, rows, state):
    bag = {
        'state': state,
        'video_ids': {vid: True for vid in state.get('video_ids', [])},
        'music_ids': {mid: True for mid in state.get('music_ids', [])},
        'rows': rows,
    }
    log_path = SCRIPT_DIR / f'API分页_{safe_tag_name(tag)}_{datetime.now():%Y%m%d_%H%M%S}.jsonl'
    state['log_path'] = str(log_path)

    def persist():
        state['video_ids'] = list(bag['video_ids'])
        state['music_ids'] = list(bag['music_ids'])
        state['rows'] = rows
        save_checkpoint(state)

    persist()

    try:
        if len(rows) < TARGET_CREATORS:
            try:
                challenge_id = state.get('challenge_id') or resolve_challenge_id(core, tag)
                state['challenge_id'] = challenge_id
                persist()
                fetch_challenge(core, challenge_id, rows, bag, log_path)
            except core.ApiUnavailable as error:
                print(f'标签接口不可用：{error}')
        persist()
        if len(rows) < TARGET_CREATORS:
            fetch_search(core, tag, rows, bag, log_path)
        persist()
        if len(rows) < TARGET_CREATORS:
            fetch_related(core, rows, bag, log_path, tag)
        persist()
        if len(rows) < TARGET_CREATORS:
            fetch_music(core, rows, bag, log_path, tag)
        persist()
        if len(rows) < TARGET_CREATORS:
            print(f'接口累计 {len(rows)} 个博主，未到 {TARGET_CREATORS}，继续浏览器兜底')
            fetch_by_browser(core, tag, rows, bag)
    finally:
        persist()
    if not rows:
        raise core.ApiUnavailable('没有抓到任何视频')
    return rows


def main():
    try:
        import openpyxl  # noqa: F401
    except ImportError:
        raise SystemExit('请先安装 Excel 导出依赖：python -m pip install openpyxl')
    core = load_core()
    source = sys.argv[1] if len(sys.argv) > 1 else input('粘贴 TikTok Tag 链接或输入 Tag 名称：')
    tag = parse_tag(source)
    if not tag:
        raise SystemExit('Tag 不能为空')

    state = load_checkpoint(tag) if '--fresh' not in sys.argv else None
    if state:
        rows = state.get('rows') or {}
        print(f'已从断点恢复 {len(rows)} 个博主：{checkpoint_path(tag)}')
    else:
        rows = {}
        state = {'tag': tag, 'rows': rows, 'video_ids': [], 'music_ids': [], 'challenge_id': None}

    try:
        fetch_all(core, tag, rows, state)
    except KeyboardInterrupt:
        print('\n已停止，将导出已取得的数据。')
    finally:
        state['rows'] = rows
        save_checkpoint(state)
        output = export_xlsx(rows, tag)
        print(f'已保存 {len(rows)} 个不同博主：{output}')
        print(f'断点文件：{checkpoint_path(tag)}（再次运行同一标签会继续；加 --fresh 则从头抓）')
        if len(rows) < TARGET_CREATORS:
            print(f'本次未达到 {TARGET_CREATORS} 个博主，文件仅包含已取得的结果。')


def self_test():
    assert parse_tag('https://www.tiktok.com/tag/ballet?lang=en') == 'ballet'
    assert parse_tag('#街舞') == '街舞'
    assert video_has_tag({'title': 'try #Ballet now'}, 'ballet')
    assert not video_has_tag({'title': 'unrelated clip'}, 'ballet')
    from tempfile import TemporaryDirectory
    from openpyxl import load_workbook
    rows = {}
    add_creator(rows, 'Alice', 'https://www.tiktok.com/@Alice/video/123', plays=0, caption='=test')
    add_creator(rows, '@alice', 'https://www.tiktok.com/@alice/video/456')
    add_creator(rows, 'bob', 'https://www.tiktok.com/@bob/video/789')
    assert len(rows) == 2
    with TemporaryDirectory() as folder:
        path = export_xlsx(rows, 'test', Path(folder) / 'test.xlsx')
        book = load_workbook(path)
        sheet = book.active
        assert [cell.value for cell in sheet[1]] == HEADERS
        assert sheet.max_row == 3 and sheet.max_column == 12
        assert sheet['G2'].value == 0 and sheet['G3'].value is None
        assert sheet['C2'].value is None and sheet['I2'].value is None
        assert sheet['J2'].data_type == 's'
        book.close()
    print('解析测试通过')


if __name__ == '__main__':
    if '--self-test' in sys.argv:
        self_test()
    else:
        main()
