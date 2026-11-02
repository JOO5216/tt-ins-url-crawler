# tiktok抓取.py

**用途**：按预设种子 Tag 批量发现 TikTok 账号，依据元数据规则筛选个人博主和访谈类账号，输出账号及代表作品。直接运行 `main()`，没有单 Tag URL 命令行参数。

```powershell
python "tiktok抓取\tiktok抓取.py"
```

## 结构

1. 顶部配置区设定目标账号数、种子 Tag、并发数、代理、时长范围、数据库及导出目录。
2. `http_get()` 用 `curl_cffi` 请求 TikWM；`fetch_challenge_videos()`、`fetch_user_videos()`、`fetch_music_videos()` 获取元数据。
3. `classify()` 及 `looks_*()`、`has_guest_on_camera()` 等函数根据文案和 Tag 推断类型及出镜倾向。
4. `init_db()` 建立 SQLite；`scan_single_tag()` 扫描并发现新 Tag；`main()` 并发处理队列，`export_sharded_excels()` 分批导出。

默认在当前工作目录生成 `tiktok_accounts_meta.db` 和 `TikTok_Exports/`。SQLite 用于续跑和去重。出镜、无水印等判断只基于元数据，并未下载视频或封面进行视觉核验；复用前应检查顶部的任务专用筛选规则。
