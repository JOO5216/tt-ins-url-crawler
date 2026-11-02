# tiktok标签抓取_Playwright.py

**用途**：仅用 Playwright 浏览 Tag 页面，收集视频 URL、账号和主页，按账号去重导出 XLSX；不调用 TikWM API。`--self-test` 可运行本地解析检查。

```powershell
python "tiktok标签抓取_Playwright.py" "https://www.tiktok.com/tag/asmrroleplay"
```

## 结构

1. `parse_tag()` 解析 Tag，`parse_video_url()` 识别视频 URL。
2. `fetch_by_browser()` 打开页面并滚动；`collect_cards()` 读取卡片、过滤重复视频，`add_creator()` 按账号去重。
3. `export_xlsx()` 输出与标签主脚本相同的 12 列；账号类型、封面人脸数留空。

浏览器配置保存在 `.tiktok_tag_playwright_profile`，未纳入 Git。顶部 `TARGET_CREATORS` 为 10000，`STALL_ROUNDS` 控制连续无新增时停止。实际结果受网络、页面加载和可见内容限制；本脚本没有 API 续抓断点。
