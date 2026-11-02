# tiktok标签抓取.py

**用途**：输入 Tag 名称或 TikTok Tag URL，抓取视频与博主，按账号大小写无关去重，导出 XLSX。`--self-test` 检查解析；`--fresh` 忽略旧断点。

```powershell
python "tiktok标签抓取.py" "https://www.tiktok.com/tag/asmrroleplay"
```

## 结构

1. `load_core()` 从同目录加载 `tiktok拍同款抓取.py`，复用其 API 请求和代理设置。
2. `parse_tag()` 解析输入；`ingest_video()`、`add_creator()` 提取账号、视频 URL、时长、播放量、点赞量、文案、封面并去重。
3. `api_call()` 控制间隔及重试；`paginate()` 检查游标、`hasMore` 和重复页，写分页日志。
4. `fetch_all()` 依次尝试 `/challenge/info`、`/challenge/posts`、搜索、相关推荐和音乐扩展；目标未满时由 `fetch_by_browser()` 兜底。补充接口不保证长期可用。
5. `save_checkpoint()` 保存账号、视频和音乐 ID；`export_xlsx()` 输出 12 列 XLSX。中断时仍保存已有结果。

输出在脚本目录：`TikTok标签_*.xlsx`、断点 JSON 和 `API分页_*.jsonl`。顶部 `TARGET_CREATORS` 默认为 3000。账号类型、封面人脸数留空。接口结束或达到目标均不代表完整抓取整个 Tag。
