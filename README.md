# TikTok URL 抓取脚本

本仓库收录 5 个 TikTok 脚本，用于抓取视频 URL、博主账号和主页。当前没有确认可用的 Instagram URL 抓取脚本；原目录中的 `ins.py` 和 `ins找图.py` 实际是 Facebook 脚本，未收录。

## 按需求选择

| 需求 | 脚本 | 方法 | 输出 | 说明 |
| --- | --- | --- | --- | --- |
| 音乐页“拍同款” | `tiktok拍同款抓取.py` | TikWM API 优先，Playwright 兜底 | CSV | [详细文档](docs/tiktok拍同款抓取.md) |
| 单个 Tag | `tiktok标签抓取.py` | TikWM API，Playwright 兜底 | XLSX、断点、日志 | [详细文档](docs/tiktok标签抓取.md) |
| 单个 Tag，只用浏览器 | `tiktok标签抓取_Playwright.py` | Playwright | XLSX | [详细文档](docs/tiktok标签抓取_Playwright.md) |
| 从已有单 Tag 表继续 | `tiktok标签_API续抓.py` | TikWM API | XLSX、断点、日志 | [详细文档](docs/tiktok标签_API续抓.md) |
| 预设标签批量发现账号 | `tiktok抓取.py` | TikWM API | SQLite、XLSX | [详细文档](docs/tiktok抓取.md) |

## 脚本依赖

`tiktok标签抓取.py` 调用同目录的 `tiktok拍同款抓取.py` 获取 API 请求函数；`tiktok标签_API续抓.py` 又调用标签主脚本的解析、去重和导出函数。这三个文件需放在一起。另两个脚本可独立运行。

## 安装

Windows PowerShell，Python 3.10+：

```powershell
cd "C:\Users\panyu\Desktop\tt-ins-url-crawler"
python -m pip install -r requirements.txt
python -m playwright install chromium
```

纯 API 模式无需安装 Chromium。运行前检查 `tiktok拍同款抓取.py` 和 `tiktok抓取.py` 中的 `PROXY`；无代理时设为空字符串。

## 常用命令

```powershell
python "tiktok拍同款抓取.py" "https://www.tiktok.com/music/original-sound-7637835275050470164"
python "tiktok标签抓取.py" "https://www.tiktok.com/tag/asmrroleplay"
python "tiktok标签抓取_Playwright.py" "https://www.tiktok.com/tag/asmrroleplay"
python "tiktok标签_API续抓.py" "asmrroleplay" "C:\path\to\existing.xlsx"
python "tiktok标签_API续抓.py" "asmrroleplay" "C:\path\to\existing.xlsx" --rescan
python "tiktok抓取.py"
```

标签主脚本再次运行同一 Tag 会读取断点；加 `--fresh` 则从头运行。续抓脚本的 `--rescan` 保留已有账号并重置分页。续抓输入表必须只有一个 Tag，且表头与标签主脚本一致。

标签 XLSX 含序号、TikTok账号、账号类型、视频URL、账号主页、时长(秒)、播放量、点赞量、封面人脸数、视频文案、来源标签、封面URL；账号类型和封面人脸数留空。音乐脚本输出视频链接、博主账号、博主主页、来源链接及抓取方式。

接口是第三方 TikWM，并非 TikTok 官方 API。403、限流和重复分页均可能发生；抓到的数量不代表标签或音乐下的全部内容。搜索、相关推荐和音乐扩展路径只是脚本尝试的补充路径，不能保证长期可用。Excel、CSV、SQLite、日志、浏览器配置和断点文件已被 `.gitignore` 排除。
