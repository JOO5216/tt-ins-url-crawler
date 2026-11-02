# tiktok标签_API续抓.py

**用途**：从已有单 Tag XLSX 读取账号，继续扫描 TikWM Tag API，保留旧账号并对新增账号去重。需与 `tiktok标签抓取.py`、`tiktok拍同款抓取.py` 同目录。

```powershell
python "tiktok标签_API续抓.py" "asmrroleplay" "C:\path\to\existing.xlsx"
python "tiktok标签_API续抓.py" "asmrroleplay" "C:\path\to\existing.xlsx" --rescan
```

## 结构

1. `load_rows()` 校验表头和来源 Tag，载入已有账号。
2. `run()` 加载或建立 `_API续抓.json` 断点；`--rescan` 备份旧断点、重置分页，但保留账号。
3. `request()` 调用公共 `api_get()`，限流时等待；用 `/challenge/info` 获取 ID，再用 `/challenge/posts` 和 `cursor` 翻页。
4. `video_progress()`、`page_stop_reason()` 检查重复视频和分页异常；每页保存日志与断点，退出时导出 `_API续抓.xlsx`。

本脚本只调用 Tag API，没有 Playwright 回退。`hasMore=false` 只表示本轮接口结束；重新扫描加 `--rescan`。输入 XLSX 只能包含同一 Tag，不适用于混合标签表。
