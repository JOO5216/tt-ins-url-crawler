# -*- coding: utf-8 -*-
"""仅通过 Playwright 抓取 Tag，按博主去重并导出 XLSX。"""

import re
import sys
from datetime import datetime
from pathlib import Path
from urllib.parse import quote, unquote, urlsplit


SCRIPT_DIR = Path(__file__).resolve().parent
PROFILE_DIR = SCRIPT_DIR / ".tiktok_tag_playwright_profile"
TARGET_CREATORS = 10000
STALL_ROUNDS = 20
HEADERS = ['序号', 'TikTok账号', '账号类型', '视频URL', '账号主页',
           '时长(秒)', '播放量', '点赞量', '封面人脸数', '视频文案', '来源标签', '封面URL']


def add_creator(rows, handle, url, **metadata):
    handle = '@' + handle.strip().lstrip('@')
    key = handle.casefold()
    if key == '@' or key in rows or len(rows) >= TARGET_CREATORS:
        return
    rows[key] = dict(handle=handle, url=url, **metadata)


def export_xlsx(rows, tag, output=None):
    from openpyxl import Workbook
    from openpyxl.utils import get_column_letter
    safe_tag = re.sub(r'[<>:"/\\|?*\x00-\x1f]', '_', tag)
    output = output or SCRIPT_DIR / f'TikTok标签_Playwright_{safe_tag}_{datetime.now():%Y%m%d_%H%M%S_%f}.xlsx'
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


def parse_tag(value):
    value = value.strip()
    if value.startswith(("http://", "https://")):
        parts = [unquote(part) for part in urlsplit(value).path.split("/") if part]
        if "tag" not in parts or parts.index("tag") + 1 >= len(parts):
            raise SystemExit("这不是 TikTok Tag 链接，应类似：https://www.tiktok.com/tag/ballet")
        return parts[parts.index("tag") + 1].lstrip("#")
    return value.lstrip("#")


def parse_video_url(url):
    parts = urlsplit(url)
    if parts.hostname not in {'www.tiktok.com', 'tiktok.com', 'm.tiktok.com'}:
        return None
    match = re.fullmatch(r'/@([^/]+)/video/(\d+)/?', parts.path)
    if match:
        handle, video_id = match.groups()
        return f'https://www.tiktok.com/@{handle}/video/{video_id}', '@' + handle


def collect_cards(rows, seen_videos, cards):
    before = len(seen_videos)
    for card in cards:
        parsed = parse_video_url(card['url'])
        if not parsed:
            continue
        url, handle = parsed
        seen_videos.add(url.rsplit('/', 1)[-1])
        cover = card.get('cover')
        if cover and not cover.startswith(('https://', 'http://')):
            cover = None
        add_creator(rows, handle, url, cover=cover, caption=card.get('caption'))
    return len(seen_videos) - before


def fetch_by_browser(tag_url, rows, tag):
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        raise SystemExit("浏览器兜底需要 Playwright：python -m pip install playwright")

    with sync_playwright() as playwright:
        context = playwright.chromium.launch_persistent_context(
            str(PROFILE_DIR), channel="chrome", headless=False, viewport=None
        )
        page = context.pages[0] if context.pages else context.new_page()
        page.goto(tag_url, wait_until="domcontentloaded", timeout=60_000)
        page.wait_for_timeout(5000)
        if page.locator('a[href*="/video/"]').count() == 0:
            input("如浏览器要求登录或验证，请完成后按回车：")

        no_new_rounds = 0
        seen_videos = set()
        round_no = 0
        checkpoint = SCRIPT_DIR / f"TikTok标签_Playwright_阶段结果_{datetime.now():%Y%m%d_%H%M%S_%f}.xlsx"
        try:
            while len(rows) < TARGET_CREATORS:
                round_no += 1
                cards = page.locator('a[href*="/video/"]').evaluate_all("""els => els.map(a => {
                    const img = a.querySelector('img');
                    return {url: a.href, cover: img?.currentSrc || img?.src || null,
                            caption: img?.alt || null};
                })""")
                added = collect_cards(rows, seen_videos, cards)
                creator_count = len(rows)
                if added:
                    export_xlsx(rows, tag, checkpoint)
                no_new_rounds = no_new_rounds + 1 if added == 0 else 0
                print(
                    f"浏览器第 {round_no} 次滚动：新增视频 {added}，"
                    f"不同博主 {creator_count}/{TARGET_CREATORS}"
                )
                if creator_count >= TARGET_CREATORS:
                    break
                if no_new_rounds >= STALL_ROUNDS:
                    print('连续多轮没有新视频，可能是加载受阻或已到页面末尾。')
                    choice = input('请检查浏览器并完成需要的登录/验证。回车继续，输入 q 导出结束：')
                    if choice.strip().lower() == 'q':
                        break
                    no_new_rounds = 0
                page.mouse.move(650, 450)
                page.mouse.wheel(0, 900)
                page.wait_for_timeout(2500)
                if no_new_rounds and no_new_rounds % 5 == 0:
                    page.mouse.wheel(0, -500)
                    page.wait_for_timeout(1000)
                    page.mouse.wheel(0, 1000)
                    page.wait_for_timeout(5000)
        except KeyboardInterrupt:
            creator_count = len(rows)
            print(f"\n已暂停，保留当前 {creator_count} 个不同博主并导出。")

        try:
            context.close()
        except Exception:
            pass
        return rows


def main():
    try:
        import openpyxl
    except ImportError:
        raise SystemExit('请先安装 Excel 导出依赖：python -m pip install openpyxl')
    source = sys.argv[1] if len(sys.argv) > 1 else input("粘贴 TikTok Tag 链接或输入 Tag 名称：")
    tag = parse_tag(source)
    if not tag:
        raise SystemExit("Tag 不能为空")
    tag_url = f"https://www.tiktok.com/tag/{quote(tag)}"

    rows = {}
    try:
        fetch_by_browser(tag_url, rows, tag)
    except KeyboardInterrupt:
        print('\n已停止，将导出已取得的数据。')
    finally:
        output = export_xlsx(rows, tag)
        print(f'已保存 {len(rows)} 个不同博主：{output}')
        if len(rows) < TARGET_CREATORS:
            print(f'本次未达到 {TARGET_CREATORS}  个博主，文件仅包含已取得的结果。')


def self_test():
    assert parse_tag("https://www.tiktok.com/tag/ballet?lang=en") == "ballet"
    assert parse_tag("#街舞") == "街舞"
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
    rows = {}
    seen = set()
    assert collect_cards(rows, seen, [{'url': 'https://www.tiktok.com/@alice/video/1'}]) == 1
    assert collect_cards(rows, seen, [{'url': 'https://www.tiktok.com/@Alice/video/2'}]) == 1
    assert len(rows) == 1
    assert collect_cards(rows, seen, [{'url': 'https://www.tiktok.com/@Alice/video/2'}]) == 0
    assert len(seen) == 2
    print("去重、新视频进展及 XLSX 读回测试通过")


if __name__ == "__main__":
    if "--self-test" in sys.argv:
        self_test()
    else:
        main()


