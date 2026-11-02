# TikTok URL 抓取脚本

从 `C:\Users\panyu\Desktop\tt抓同款` 整理的可复用源码。当前目录没有确认可用的 Instagram URL 抓取脚本；`找图片/ins.py` 和 `ins找图.py` 的内容实际是 Facebook 脚本，因此没有收录。

## 文件用途

| 文件 | 用途 |
| --- | --- |
| `tiktok拍同款抓取.py` | 按 TikTok 音乐页抓取视频 URL 和博主；优先尝试 TikWM API，失败时尝试 Playwright。也是标签脚本的公共 API 模块。 |
| `tiktok标签抓取.py` | 按单个 Tag 抓取视频、账号、主页及播放量等字段；使用 API，必要时通过浏览器补充，按博主去重并导出 XLSX。 |
| `tiktok标签抓取_Playwright.py` | 仅用 Playwright 抓取单个 Tag，按博主去重导出 XLSX。 |
| `tiktok标签_API续抓.py` | 从已有的单 Tag XLSX 继续通过 API 抓取，保存游标和结果；依赖上面两个主脚本。 |
| `补充两个标签.py` | 扫描 `asmrpersonalattention` 和 `asmrroleplay` 两个 Tag，跨标签去重并追加到既有 XLSX。脚本中的 `TARGET` 是原电脑的绝对路径，复用时先修改。 |
| `tiktok抓取.py` | 通过 TikWM API 发现账号并保存到本地 SQLite/导出目录；包含特定筛选规则和固定代理配置。 |

## 安装与运行

```powershell
python -m pip install -r requirements.txt
python -m playwright install chromium
python "tiktok标签抓取.py" "https://www.tiktok.com/tag/asmrroleplay"
python "tiktok拍同款抓取.py" "https://www.tiktok.com/music/original-sound-7637835275050470164"
```

纯 Playwright 模式可运行 `python "tiktok标签抓取_Playwright.py" "https://www.tiktok.com/tag/asmrroleplay"`。单 Tag 续抓时，把已有 XLSX 作为第二个参数传给 `tiktok标签_API续抓.py`。运行前按本机情况修改 `tiktok拍同款抓取.py` 和 `tiktok抓取.py` 中的 `PROXY`；不使用代理时设为空字符串。`补充两个标签.py` 还需修改 `TARGET`。

这些脚本访问的是第三方 TikWM 接口，并非 TikTok 官方 API。接口可能限流或返回 403；导出结果和运行状态文件请留在本机，不要提交到仓库。
