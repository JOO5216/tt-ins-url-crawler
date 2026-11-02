# tiktok拍同款抓取.py

**用途**：输入 TikTok 音乐页或使用该音乐的原视频 URL，收集同音乐视频及其博主；每个博主只保留一条。入口是 `main()`，`--self-test` 可运行解析检查。

```powershell
python "tiktok拍同款抓取.py" "https://www.tiktok.com/music/original-sound-7637835275050470164"
```

## 结构

1. `parse_video_url()` 规范化视频链接；`unique_creators()` 按账号去重。
2. `api_get()` 用 `curl_cffi`、脚本内 `PROXY` 和 `impersonate="chrome131"` 请求第三方 TikWM；它也供标签脚本复用。
3. `resolve_music_id()` 从音乐页 URL 或原视频接口响应取得音乐 ID；`fetch_all_by_api()` 用 `/music/posts` 和 `cursor` 翻页。
4. API 不可用时 `fetch_by_browser()` 使用 Playwright；`export_csv()` 写 `TikTok拍同款_时间.csv`。

**输出列**：序号、视频链接、博主账号、博主主页、来源链接、抓取方式。顶部 `TARGET_CREATORS` 为目标博主数；API 403 时浏览器抓到的数量受页面可见内容限制。
