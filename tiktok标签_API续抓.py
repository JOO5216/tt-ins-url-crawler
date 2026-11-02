"""加载已有 XLSX，API 限速续抓；每页保存记录和下一页游标。"""
import importlib.util
import argparse
import shutil
from datetime import datetime
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location('tag_base', ROOT / 'tiktok标签抓取.py')
base = importlib.util.module_from_spec(spec)
spec.loader.exec_module(base)


def request(core, url, params):
    for attempt in range(6):
        time.sleep(0.7)
        payload = core.api_get(url, params)
        if payload.get('code') == 0:
            return payload
        message = str(payload.get('msg') or payload.get('message') or payload)
        if 'limit' not in message.lower():
            raise RuntimeError(message)
        if attempt < 5:
            delay = 5 * (attempt + 1)
            print(f'触发限流，等待 {delay} 秒后重试同一页。', flush=True)
            time.sleep(delay)
    raise RuntimeError('多次限流，已暂停；重新运行相同命令可继续。')


def load_rows(path, tag):
    from openpyxl import load_workbook
    book = load_workbook(path, read_only=True, data_only=True)
    rows = {}
    try:
        values = book.active.iter_rows(values_only=True)
        if list(next(values)) != base.HEADERS:
            raise ValueError('源表列名与当前脚本不一致')
        for row in values:
            if not row[1]:
                continue
            if row[10] != '#' + tag:
                raise ValueError('源表包含其他标签，不能作为该标签的续抓结果')
            base.add_creator(rows, row[1], row[3], duration=row[5], plays=row[6],
                             likes=row[7], caption=row[9], cover=row[11])
    finally:
        book.close()
    return rows


def save_state(path, state):
    temp = path.with_suffix('.tmp')
    temp.write_text(json.dumps(state, ensure_ascii=False), encoding='utf-8')
    temp.replace(path)


def video_progress(videos, known_ids):
    ids = {str(v.get('video_id') or v.get('id')) for v in videos
           if v.get('video_id') or v.get('id')}
    new_count = len(ids - known_ids)
    known_ids.update(ids)
    return new_count


def reset_scan(state):
    state.update(cursor=0, page=0, done=False, seen_cursors=[],
                 seen_video_ids=[], stop_reason=None)


def run(tag, source, rescan=False):
    state_path = source.with_name(source.stem + '_API续抓.json')
    if state_path.exists():
        state = json.loads(state_path.read_text(encoding='utf-8'))
        if state['tag'] != tag:
            raise ValueError('断点标签不匹配')
    else:
        state = dict(tag=tag, rows=load_rows(source, tag), cursor=0,
                     page=0, challenge_id=None, done=False)
    if rescan:
        if state_path.exists():
            backup = state_path.with_name(state_path.name + datetime.now().strftime('.%Y%m%d_%H%M%S_%f.bak'))
            shutil.copy2(state_path, backup)
            print(f'旧断点已备份：{backup}')
        reset_scan(state)
        print('开始新一轮扫描；保留已有博主，重置本轮分页和视频进展统计。')
    rows = state['rows']
    video_ids = set(state.get('seen_video_ids', []))
    repeated_pages = 0
    log_path = source.with_name(source.stem + '_API分页日志.jsonl')
    seen = set(str(x) for x in state.get('seen_cursors', []))
    output = source.with_name(source.stem + '_API续抓.xlsx')
    if state['done']:
        print(f'已载入 {len(rows)} 个博主；上轮接口分页已结束，本次不发送请求。')
        print('如需重新扫描，请在命令末尾添加 --rescan。')
        return
    print(f'已载入 {len(rows)} 个博主，下一页为第 {state["page"] + 1} 页。', flush=True)
    core = base.load_core()
    try:
        save_state(state_path, state)
        if not state['challenge_id']:
            data = request(core, core.TIKWM + '/challenge/info', {'challenge_name': tag})['data']
            state['challenge_id'] = str(data['id'])
        while not state['done'] and len(rows) < base.TARGET_CREATORS:
            cursor = state['cursor']
            payload = request(core, core.TIKWM + '/challenge/posts',
                              dict(challenge_id=state['challenge_id'], count=30, cursor=cursor))
            data = payload.get('data') or {}
            videos = data.get('videos') or []
            before = len(rows)
            new_videos = video_progress(videos, video_ids)
            state['seen_video_ids'] = sorted(video_ids)
            repeated_pages = repeated_pages + 1 if videos and new_videos == 0 else 0
            for video in videos:
                handle = (video.get('author') or {}).get('unique_id')
                vid = video.get('video_id') or video.get('id')
                if handle and vid:
                    base.add_creator(rows, handle, f'https://www.tiktok.com/@{handle.lstrip("@")}/video/{vid}',
                                     duration=video.get('duration'), plays=video.get('play_count'),
                                     likes=video.get('digg_count'), caption=video.get('title'), cover=video.get('cover'))
            reason = base.page_stop_reason(data, cursor, seen)
            if not reason and repeated_pages >= 5:
                reason = '连续 5 页没有新视频 ID，疑似接口重复返回；保留当前游标暂停，并非全部抓完'
            base.log_page(log_path, page=state['page'] + 1, cursor=cursor,
                          next_cursor=data.get('cursor'), hasMore=data.get('hasMore'),
                          videos=len(videos), new_videos=new_videos,
                          new_creators=len(rows) - before, creators=len(rows), reason=reason)
            state['stop_reason'] = reason
            if reason and reason.startswith('接口明确'):
                state['done'] = True
            elif reason:
                raise RuntimeError(reason)
            else:
                nxt = data.get('cursor')
                if not videos or nxt is None or str(nxt) == str(cursor):
                    raise RuntimeError('分页数据异常，保留当前游标，稍后重新运行重试。')
                state['cursor'] = nxt
            seen.add(str(cursor))
            state['seen_cursors'] = list(seen)
            state['page'] += 1
            save_state(state_path, state)
            print(f'API 第 {state["page"]} 页：返回 {len(videos)} 个视频，'
                  f'新视频 {new_videos}，新博主 {len(rows) - before}，'
                  f'累计博主 {len(rows)}/{base.TARGET_CREATORS}，'
                  f'cursor {cursor} -> {data.get("cursor")}', flush=True)
        print('接口报告无更多数据。' if state['done'] else '已达到目标数量。')
    except KeyboardInterrupt:
        state['stop_reason'] = '用户中断'
        print('\n已暂停。')
    except Exception as error:
        state['stop_reason'] = str(error)
        print(f'暂停原因：{error}')
    finally:
        base.log_page(log_path, event='stop', page=state['page'], cursor=state['cursor'],
                      creators=len(rows), reason=state.get('stop_reason') or '达到目标数量')
        save_state(state_path, state)
        base.export_xlsx(rows, tag, output)
        print(f'已保存 {len(rows)} 个博主：{output}')
        if state['done']:
            print('本轮接口分页已结束，不代表该标签只有这些博主。重新扫描请添加 --rescan。')
        elif len(rows) >= base.TARGET_CREATORS:
            print('已达到目标数量，无需续抓。')
        else:
            print('本轮已暂停；再次运行时不带 --rescan，可从当前断点继续。')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='保留已有账号，断点续抓或重新扫描 Tag')
    parser.add_argument('tag')
    parser.add_argument('source', type=Path)
    parser.add_argument('--rescan', action='store_true', help='保留已有账号，从第一页重新扫描')
    args = parser.parse_args()
    run(base.parse_tag(args.tag), args.source.resolve(), args.rescan)
