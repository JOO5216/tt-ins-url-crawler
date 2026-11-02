"""扫描两个指定标签，跨标签去重，只追加原表没有的博主。"""
import importlib.util
import json
import shutil
import time
import sys
from copy import copy
from pathlib import Path
from datetime import datetime
from openpyxl import load_workbook

ROOT = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location('resume', ROOT / 'tiktok标签_API续抓.py')
resume = importlib.util.module_from_spec(spec)
spec.loader.exec_module(resume)
TARGET = Path(r'D:\projects\codex-feishu\outputs\01a17d2f-623c-70b0-9df3-9ed813d1d790\TikTok标签账号_去重合并_20261027.xlsx')
STATE = TARGET.with_suffix('.scan.json')
LOG = TARGET.with_suffix('.scan.jsonl')


def next_no_gain(previous, added):
    # None 表示扫描失败，不是扫描成功但没有新账号。
    return previous if added is None else (previous + 1 if added == 0 else 0)


def reset_api_scan(state):
    for tag in ['asmrpersonalattention', 'asmrroleplay']:
        progress = state.setdefault(tag, {})
        progress.update(cursor=0, page=0, done=False, reason=None)


def main(rescan=False):
    backup = TARGET.with_name(TARGET.stem + '_抓取前备份.xlsx')
    if not backup.exists():
        shutil.copy2(TARGET, backup)
    book = load_workbook(TARGET)
    sheet = book.active
    assert [c.value for c in sheet[1]] == resume.base.HEADERS
    existing = {str(row[1]).strip().lstrip('@').casefold() for row in list(sheet.values)[1:] if row[1]}
    assert len(existing) == sheet.max_row - 1
    original_count = len(existing)
    state = json.loads(STATE.read_text(encoding='utf-8')) if STATE.exists() else {}
    if rescan:
        stamp = datetime.now().strftime('%Y%m%d_%H%M%S_%f')
        shutil.copy2(TARGET, TARGET.with_name(TARGET.stem + '_重扫前备份_' + stamp + '.xlsx'))
        if STATE.exists():
            shutil.copy2(STATE, STATE.with_name(STATE.name + '.' + stamp + '.bak'))
        reset_api_scan(state)
        resume.save_state(STATE, state)
        print(f'保留 {original_count} 个博主，两个标签从第一页开始新的 API 扫描。', flush=True)
    core = resume.base.load_core()
    print(f'API 路由：{core.PROXY or "直连"}；不自动回退其他出口。', flush=True)

    def save():
        temp = TARGET.with_name(TARGET.stem + '.saving.xlsx')
        book.save(temp)
        temp.replace(TARGET)
        resume.save_state(STATE, state)

    def add(video, tag):
        handle = str((video.get('author') or {}).get('unique_id') or '').strip().lstrip('@')
        vid = str(video.get('video_id') or video.get('id') or '')
        if not handle or not vid.isdigit() or handle.casefold() in existing:
            return
        existing.add(handle.casefold())
        sheet.append([len(existing), '@' + handle, None,
                      f'https://www.tiktok.com/@{handle}/video/{vid}',
                      f'https://www.tiktok.com/@{handle}', video.get('duration'),
                      video.get('play_count'), video.get('digg_count'), None,
                      video.get('title'), '#' + tag, video.get('cover')])
        for cell, template in zip(sheet[sheet.max_row], sheet[2]):
            cell._style = copy(template._style)
            if isinstance(cell.value, str):
                cell.data_type = 's'
        sheet.auto_filter.ref = sheet.dimensions

    def browser_scan():
        from playwright.sync_api import sync_playwright
        failed = False
        with sync_playwright() as pw:
            context = pw.chromium.launch_persistent_context(
                str(ROOT / '.tiktok_tag_playwright_profile'), channel='chrome', headless=False)
            page = context.pages[0] if context.pages else context.new_page()
            network_errors = []
            page.on('requestfailed', lambda request: network_errors.append(request.failure)
                    if request.resource_type in ('document', 'xhr', 'fetch')
                    and 'ERR_ABORTED' not in (request.failure or '') else None)
            for tag in ['asmrpersonalattention', 'asmrroleplay']:
                network_errors.clear()
                try:
                    response = page.goto('https://www.tiktok.com/tag/' + tag, wait_until='domcontentloaded', timeout=60000)
                    if response and response.status >= 400:
                        raise RuntimeError(f'页面 HTTP {response.status}')
                    page.wait_for_timeout(6000)
                    seen_urls = set()
                    stale = 0
                    reloads = 0
                    for step in range(2000):
                        cards = page.locator('a[href*="/video/"]').evaluate_all('''els => els.map(a => ({
                            url:a.href, cover:a.querySelector('img')?.currentSrc || null,
                            title:a.querySelector('img')?.alt || null}))''')
                        old = len(seen_urls)
                        before = len(existing)
                        for card in cards:
                            parsed = core.parse_video_url(card['url'])
                            if parsed:
                                seen_urls.add(parsed[0])
                                add(dict(id=parsed[0].rsplit('/',1)[-1], author={'unique_id':parsed[1]},
                                         title=card['title'], cover=card['cover']), tag)
                        stale = stale + 1 if len(seen_urls) == old else 0
                        if len(existing) > before:
                            save()
                            print(f'浏览器 {tag} 轮{step+1} 新增{len(existing)-before} 总计{len(existing)}', flush=True)
                        if stale >= 15:
                            if network_errors or not seen_urls:
                                raise RuntimeError(f'加载失败，不能认定无新增：{network_errors[-3:]}；有效视频 {len(seen_urls)}')
                            page.screenshot(path=str(TARGET.parent / (tag + '_stalled.png')))
                            print(f'{tag} 页面停滞，已保存截图，尝试重新加载={reloads == 0}', flush=True)
                            if reloads >= 1:
                                break
                            page.reload(wait_until='domcontentloaded')
                            page.wait_for_timeout(8000)
                            reloads += 1
                            stale = 0
                        page.mouse.move(500,400)
                        page.mouse.wheel(0,1000)
                        page.wait_for_timeout(2200)
                        if stale and stale % 5 == 0:
                            page.mouse.wheel(0,-600)
                            page.wait_for_timeout(1500)
                except Exception as error:
                    failed = True
                    print(f'浏览器 {tag}: {error}', flush=True)
                    print('此标签本轮失败，不计入无新增轮数；保存后等待重试。', flush=True)
            context.close()
        return not failed

    try:
        if '--browser' in sys.argv:
            from playwright.sync_api import Error as BrowserError
            try:
                succeeded = browser_scan()
            except BrowserError as error:
                print(f'浏览器连接失败，保存后等待重试：{error}', flush=True)
                succeeded = False
            if not succeeded:
                return None
            return len(existing) - original_count
        api_failed = False
        for tag in ['asmrpersonalattention', 'asmrroleplay']:
            progress = state.setdefault(tag, dict(cursor=0, page=0, done=False))
            if progress['done']:
                print(f'{tag} 已完成本轮 API 分页，跳过；不计为重新扫描。', flush=True)
                continue
            known = set()
            cursors = set()
            stale = 0
            errors = 0
            while not progress['done']:
                try:
                    if not progress.get('id'):
                        data = resume.request(core, core.TIKWM + '/challenge/info', {'challenge_name': tag})['data']
                        progress['id'] = str(data['id'])
                        resume.save_state(STATE, state)
                    cursor = progress['cursor']
                    data = resume.request(core, core.TIKWM + '/challenge/posts',
                        dict(challenge_id=progress['id'], count=30, cursor=cursor))['data']
                    videos = data.get('videos') or []
                    before = len(existing)
                    resume.video_progress(videos, known)
                    for video in videos:
                        handle = str((video.get('author') or {}).get('unique_id') or '').strip().lstrip('@')
                        vid = str(video.get('video_id') or video.get('id') or '')
                        if handle and vid.isdigit() and handle.casefold() not in existing:
                            existing.add(handle.casefold())
                            sheet.append([len(existing), '@' + handle, None,
                                          f'https://www.tiktok.com/@{handle}/video/{vid}',
                                          f'https://www.tiktok.com/@{handle}', video.get('duration'),
                                          video.get('play_count'), video.get('digg_count'), None,
                                          video.get('title'), '#' + tag, video.get('cover')])
                            for cell, template in zip(sheet[sheet.max_row], sheet[2]):
                                cell._style = copy(template._style)
                                if isinstance(cell.value, str):
                                    cell.data_type = 's'
                            sheet.auto_filter.ref = sheet.dimensions
                    new_creators = len(existing) - before
                    stale = stale + 1 if videos and new_creators == 0 else 0
                    reason = resume.base.page_stop_reason(data, cursor, cursors)
                    if not reason and stale >= 3:
                        reason = '连续三页重复视频，停止本轮扫描'
                    progress['page'] += 1
                    progress['reason'] = reason
                    progress['done'] = bool(reason and (reason.startswith('接口明确') or '重复视频' in reason))
                    if not reason:
                        progress['cursor'] = data['cursor']
                    cursors.add(cursor)
                    errors = 0
                    resume.base.log_page(LOG, tag=tag, page=progress['page'], cursor=cursor,
                        next_cursor=data.get('cursor'), hasMore=data.get('hasMore'),
                        videos=len(videos), new_creators=len(existing)-before, total=len(existing), reason=reason)
                    save()
                    if len(existing) > before or progress['page'] % 20 == 0 or reason:
                        print(f'{tag} 页{progress["page"]} 新增{len(existing)-before} 总计{len(existing)} {reason or ""}', flush=True)
                    if reason:
                        if not progress['done']:
                            api_failed = True
                        break
                except Exception as error:
                    errors += 1
                    progress['reason'] = str(error)
                    save()
                    print(f'{tag} 错误{errors}: {error}', flush=True)
                    if errors >= 3:
                        api_failed = True
                        break
                    time.sleep(5 * errors)
        return None if api_failed else len(existing) - original_count
    finally:
        save()
        print(f'本轮追加 {len(existing)-original_count}，总计 {len(existing)}，保存到 {TARGET}', flush=True)


if __name__ == '__main__':
    if '--self-test' in sys.argv:
        assert next_no_gain(0, None) == 0
        assert next_no_gain(1, None) == 1
        assert next_no_gain(1, 0) == 2
        assert next_no_gain(1, 3) == 0
        sample = {'asmrroleplay': {'cursor': 5040, 'page': 254, 'done': True, 'id': '42777685'}}
        reset_api_scan(sample)
        assert len(sample) == 2 and all(p['cursor'] == 0 and not p['done'] for p in sample.values())
        assert sample['asmrroleplay']['id'] == '42777685'
        print('失败不计无新增、成功计数和新增重置测试通过')
    elif '--continuous' in sys.argv:
        no_gain = 0
        failures = 0
        rescan = '--rescan' in sys.argv
        while no_gain < 2:
            added = main(rescan=rescan)
            rescan = False
            no_gain = next_no_gain(no_gain, added)
            if added is None:
                failures += 1
                delay = min(60 * failures, 300)
                print(f'本轮扫描失败，不计无新增。等待 {delay} 秒后自动重试。', flush=True)
                time.sleep(delay)
                continue
            failures = 0
            if '--browser' not in sys.argv:
                print('两个标签本轮 API 分页已结束（hasMore=false），结果已保存；未再次扫描。'
                      '如需新一轮扫描，添加 --rescan。', flush=True)
                break
            print(f'本轮新增 {added}；连续无新增轮数 {no_gain}/2', flush=True)
            if no_gain < 2:
                time.sleep(20)
        if '--browser' in sys.argv:
            print('两个标签连续两轮无新增，当前页面数据已无进展；结果均已保存。', flush=True)
    else:
        main(rescan='--rescan' in sys.argv)
