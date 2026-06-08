# NodeLoc Daily Sign

中文 | [English](README.md)

NodeLoc Daily Sign 是一个用于 NodeLoc 账号日常维护的 Python 工具。它可以执行每日签到、检查 Cookie 是否有效、读取 Discourse 账号统计，并且可以用 Playwright 打开真实帖子页面，让论坛前端按正常方式记录阅读进度。

它不会自动回复、自动发帖、伪造大量阅读时间，也不会协调多个账号去刷同一个内容。

## 功能

- 支持一个或多个账号每日签到。
- 本地记录当天已完成状态，重复运行时不会反复请求签到接口。
- 通过当前用户接口检查 Cookie 是否有效。
- 可选 Playwright 浏览器读帖。
- 输出阅读时间、进入主题数、已读帖子数、访问天数的前后对比报告。
- 如果读帖结束后统计没有变化，会自动换一批候选主题重试。
- 提供本地 Web 控制台，可以运行任务、查看实时日志、查看报告、编辑脱敏配置。
- 支持 daemon 模式，每天定时运行一次。

## 安装

建议使用 Python 3.11 或更新版本。

```bash
python -m pip install -r requirements.txt
```

如果要启用浏览器读帖，还需要安装 Playwright 的 Chromium：

```bash
python -m playwright install chromium
```

## 创建账号配置

复制示例配置：

```bash
copy accounts.example.json accounts.json
```

Linux 或 macOS：

```bash
cp accounts.example.json accounts.json
```

然后编辑 `accounts.json`，填入你自己的账号信息：

```json
{
  "accounts": [
    {
      "name": "account-1",
      "cookie": "_t=...; _forum_session=...",
      "csrf_token": ""
    }
  ]
}
```

`accounts.json` 里有登录凭证，必须自己保管。仓库默认会忽略这个文件，不会上传。

## 如何获取自己的 Cookie

请使用已经登录 NodeLoc 的浏览器。Chrome 和 Edge 的操作基本一样。

1. 打开 [https://www.nodeloc.com/](https://www.nodeloc.com/) 并登录。
2. 按 `F12` 打开开发者工具。
3. 切到 `Network` 面板。
4. 刷新 NodeLoc 页面。
5. 在请求列表里点击任意一个域名是 `www.nodeloc.com` 的请求。
6. 打开这个请求的 `Headers` 面板。
7. 找到 `Request Headers`。
8. 找到名为 `Cookie` 的请求头。
9. 复制 `Cookie` 后面的完整内容。
10. 把它粘贴到 `accounts.json` 里对应账号的 `cookie` 字段。

Cookie 通常是一长串内容，里面可能包含 `_t=...`、`_forum_session=...` 等片段。请复制完整的 `Cookie` 请求头，不要只复制其中一段。

如果你看不到 `Cookie` 请求头，先确认开发者工具是在刷新页面之前打开的。也可以试着点击 `/session/current.json`、`/latest.json` 或帖子页面相关的已登录请求。

Cookie 等同于登录凭证，不要发给别人，也不要提交到 GitHub。

## CSRF Token

先把 `csrf_token` 留空。脚本会使用 Cookie 自动请求 `/session/csrf.json` 获取 CSRF Token。

只有自动获取失败时，才需要手动填写 `csrf_token`。获取方法如下：

1. 保持开发者工具打开，并停留在 `Network` 面板。
2. 手动点击一次 NodeLoc 签到按钮，或者找一个包含 `x-csrf-token` 的请求。
3. 打开这个请求的 `Headers`。
4. 复制请求头里的 `x-csrf-token`。
5. 粘贴到 `accounts.json` 里的 `csrf_token` 字段。

大多数情况下不需要手动填写这个字段。

## 检查配置

第一次使用建议先 dry-run：

```bash
python nodeloc_daily_sign.py --dry-run --once
```

完整维护流程的 dry-run：

```bash
python nodeloc_daily_sign.py --maintain --dry-run --once --max-accounts 1
```

Dry-run 会加载配置并检查流程，不会真正签到，也不会启动浏览器读帖。

## 运行每日签到

真实签到一次：

```bash
python nodeloc_daily_sign.py --once
```

脚本会把当天完成状态写入 `.nodeloc_state.json`。如果某个账号今天已经签到过，再次运行会在本地跳过它。

只有你明确想再次请求签到接口时，才使用 `--force`：

```bash
python nodeloc_daily_sign.py --once --force
```

## 运行每日维护

只执行签到和统计，不读帖：

```bash
python nodeloc_daily_sign.py --maintain --no-reading --once
```

对一个账号做短时间浏览器读帖测试：

```bash
python nodeloc_daily_sign.py --maintain --reading --force-reading --reading-minutes 0.05 --topics-per-account 1 --once --max-accounts 1
```

按配置执行完整维护：

```bash
python nodeloc_daily_sign.py --maintain --reading --once
```

报告默认写到 `reports/`。也可以用 `--report-file path/to/report.txt` 指定报告文件。

## 阅读配置

在 `accounts.json` 里配置阅读行为：

```json
{
  "reading": {
    "enabled": false,
    "minutes_per_account": 5,
    "topics_per_account": 3,
    "min_stay_seconds": 30,
    "max_stay_seconds": 75,
    "scrolls_per_topic": 8,
    "headless": true,
    "target_time_read_minutes": 0,
    "target_topics_entered": 0,
    "target_posts_read_count": 0,
    "rescue_attempts": 2,
    "rescue_topic_multiplier": 3
  }
}
```

如果设置了任意目标，维护器只会在账号当前数据低于目标时读帖。如果没有设置目标，但启用了阅读，它会执行配置里的每日阅读会话。

读帖结束后，程序会重新查询 NodeLoc 的真实统计。若所有增长都是 0，报告会标记 `metrics_not_changed`。

## Web 控制台

启动本地 Web 控制台：

```bash
python nodeloc_daily_sign.py --web --host 127.0.0.1 --port 8787
```

浏览器打开 [http://127.0.0.1:8787](http://127.0.0.1:8787)。

控制台包含这些页面：

- `总览`：账号状态和最近指标。
- `运行任务`：dry-run、只签到、完整维护。
- `实时日志`：任务运行中的实时事件。
- `历史报告`：最近生成的文本报告。
- `配置`：脱敏配置查看和编辑。

如果要给局域网或公网访问，必须设置 token：

```bash
python nodeloc_daily_sign.py --web --host 0.0.0.0 --port 8787 --web-token CHANGE_ME
```

也可以使用环境变量：

```bash
set NODELOC_WEB_TOKEN=CHANGE_ME
python nodeloc_daily_sign.py --web --host 0.0.0.0 --port 8787
```

Web 控制台不会显示完整 Cookie 或 CSRF Token。保存脱敏配置时，会保留原来的密钥字段。

## 每日定时

作为长期进程运行，每天固定时间执行：

```bash
python nodeloc_daily_sign.py --daemon --run-at 08:10
```

如果启动后想先立即跑一次，再等待下一次定时，添加 `--run-now`：

```bash
python nodeloc_daily_sign.py --daemon --run-at 08:10 --run-now
```

Cron 示例：

```cron
10 8 * * * cd /path/to/NodeLoc-DailySign && /usr/bin/python3 nodeloc_daily_sign.py --once >> sign.log 2>&1
```

`--run-at` 和 cron 都使用服务器本地时间。

## 代理

如果服务器访问 NodeLoc 不稳定，可以在 `accounts.json` 里设置代理：

```json
{
  "proxy": "http://127.0.0.1:10808"
}
```

## 不能上传的文件

不要上传这些文件：

- `accounts.json`
- `.nodeloc_state.json`
- `cok.txt`
- `*.har`
- `reports/`
- `output/`
- `.env`

这些文件已经在 `.gitignore` 里。推送前仍然建议检查一遍，密钥进了 Git 历史会很烦。

## 测试

运行测试：

```bash
python -m pytest -q
```

## 项目结构

- `nodeloc_daily_sign.py`：命令入口。
- `nodeloc_maintainer/domain/`：数据模型和站点常量。
- `nodeloc_maintainer/application/`：签到、统计、阅读决策、报告和维护流程。
- `nodeloc_maintainer/infrastructure/`：HTTP 客户端、配置加载、本地状态、Playwright 阅读、报告和定时工具。
- `nodeloc_maintainer/interfaces/`：CLI 和 Web 控制台。
- `tools/`：辅助脚本。
- `tests/`：行为测试。
