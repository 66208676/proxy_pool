# 本地代理池部署说明

本文档记录把 **本机购买的代理清单** 接入 `jhao104/proxy_pool` 的全部配置改动、启动方式和实测结果。

- 项目路径：`/Users/zhaoqi/myWorkspace/proxy_pool`
- 上游清单：`/Users/zhaoqi/Downloads/all_accounts_proxies_20261004.txt`（3400 行）
- 清单格式：`http://user:pass@ip:port`

---

## 一、环境准备（已完成）

| 组件 | 状态 | 说明 |
|---|---|---|
| Redis | 已启动，`127.0.0.1:6379` | 数据目录 `~/.redis-data`，日志 `~/.redis-log/redis.log`，无密码 |
| Python venv | `./.venv`（Python 3.13.12） | 依赖已装好 |
| 调度进程 | `proxyPool.py schedule` | 采集 + 校验，由 `daemonize.py` 托管 |
| API 进程 | `proxyPool.py server` | 监听 `0.0.0.0:5010`，由 `daemonize.py` 托管 |

### 依赖版本说明

`requirements.txt` 里的 `lxml==4.9.2` 和 `gunicorn==19.9.0` 在 Python 3.13 上装不上
（lxml 4.9.2 没有 py3.13 的 wheel，源码编译失败）。已改用兼容版本：

```
requests 2.34.2   gunicorn 26.2.0   lxml 6.1.3      redis 8.1.0
APScheduler 3.11.3   click 8.5.0    Flask 3.1.3     Werkzeug 3.1.9
```

如果重新安装，用：

```bash
cd /Users/zhaoqi/myWorkspace/proxy_pool
./.venv/bin/pip install "requests>=2.31" "gunicorn>=21.2" "lxml>=5.2" \
  "redis>=5.0" "APScheduler>=3.10,<4.0" "click>=8.1" "Flask>=3.0" "werkzeug>=3.0"
```

> 注意 `APScheduler` 必须锁在 `3.x`——4.x 的 API 完全不兼容，代码会直接跑不起来。
> `redis` 必须 `>=5.0`——`db/redisClient.py` 用了 `protocol=2` 参数。

---

## 二、改动清单

### 新增文件

**`fetcher/sources/local_list.py`** — 本地清单代理源。

`proxy_pool` 的 fetcher 是插件式自动扫描的，把文件丢进 `fetcher/sources/` 就会被加载。
它读取本地清单，把 `http://user:pass@ip:port` 归一化成 `user:pass@ip:port`
（与 `helper/validator.py` 的 `IP_REGEX` 一致），并自动去重。

清单路径可用环境变量覆盖，不用改代码：

```bash
export LOCAL_PROXY_FILE=/path/to/your/proxies.txt
```

支持的行格式：`http://user:pass@ip:port`、`https://user:pass@ip:port`、
`user:pass@ip:port`、`ip:port`，`#` 开头为注释。

**`api/dashboard.html`** — Web 控制台页面（单文件，无外部依赖）。见第四节。

### 修改文件

| 文件 | 改动 | 原因 |
|---|---|---|
| `setting.py` | `DB_CONN` 改为 `redis://@127.0.0.1:6379/0` | 原值是 `redis://:pwdstring@127.0.0.1:6379/0`，带了个不存在的密码，连不上 |
| `setting.py` | `PROXY_REGION = False` | ① 该功能会对每条代理请求一次 `api.ip.sb/geoip`，3400 条 = 3400 次外部请求，极慢且会被限流；② 它的取 IP 写法是 `proxy.proxy.split(':')[0]`，遇到 `user:pass@ip:port` 会取到**用户名**而不是 IP |
| `setting.py` | `PROXY_FETCHER_EXCLUDE` 加入 14 个免费源类名 | 只保留 `local_list`。免费源对你的付费清单毫无价值，还会污染池子 |
| `setting.py` | `MAX_FAIL_COUNT: 0 → 2` | upstream 默认失败一次即删。对付费池太激进——偶发抖动就误删。改为容忍 2 次 |
| `setting.py` | 新增 `CHECK_THREAD_COUNT` / `FETCH_INTERVAL_MINUTES` / `CHECK_INTERVAL_MINUTES` | 见下方"调度节奏" |
| `handler/configHandler.py` | 新增 3 个对应的 `LazyProperty` | 让上面 3 个配置可被读取 |
| `helper/check.py` | `range(20)` → `range(conf.checkThreadCount)` | 线程数改为可配置 |
| `helper/scheduler.py` | 两个 `add_job` 的间隔改为读配置 | 间隔可配置 |
| `helper/scheduler.py` | `configure()` 补传 `logger=scheduler_log` | 见下方"修掉的第二个问题：调度日志被吞" |
| `helper/validator.py` | **修复 upstream bug**：https 校验的代理地址由 `https://{proxy}` 改为 `http://{proxy}` | 见下方"修复的 bug" |
| `daemonize.py`（新增） | 把 `schedule` / `server` 变成真正的后台守护进程 | 见下方"为什么需要 daemonize.py" |
| `api/proxyApi.py` | 新增 `/dashboard` 系列路由（4 个），并在 `api_list` 里登记 | upstream 无 Web UI，见第四节 |
| `.gitignore` | 加入 `log/`、`.venv/` | 避免日志、PID 文件被误提交 |

### 修掉的第二个问题：调度日志被吞（排查记录）

部署后 `log/scheduler.log` 里只有两行 `Adding job tentatively`，
**既没有 `Scheduler started`，也没有 `Added job`**，看起来像调度器卡死了。实际排查结论：
**调度器完全正常，只是日志被丢了。**

用 `faulthandler` 抓活进程栈，主线程停在
`blocking.py:28 in _main_loop` → `Event.wait` → `Condition.wait`，
即已经进入正常的主循环（不是卡住）。再正向验证一次：

```
>>> scheduler.state = 1                     # STATE_RUNNING
>>> pending_jobs = 0                        # 待排期任务已全部转正
    job id=proxy_check  next_run=... 13:09:03  trigger=interval[0:30:00]
    job id=proxy_fetch  next_run=... 14:39:03  trigger=interval[2:00:00]
    [job 触发] 第 1 次 12:39:29   # 5 秒周期任务实测 22 秒触发 4 次
```

**根因**：`apscheduler` 的 `configure()` 会把 `self._logger` 重置成
`logging.getLogger('apscheduler.scheduler')`。这个 logger 没有任何 handler，
INFO 级别的消息被静默丢弃（Python 的 `lastResort` handler 只输出 WARNING 及以上）。
而 `add_job` 发生在 `configure()` **之前**，所以那两行还能正常落到 `scheduler.log`。

**修复**：`configure()` 显式补传 `logger=scheduler_log`。修完后日志变为：

```
base.py[line:1092] INFO Added job "proxy检查" to job store "default"
base.py[line:214]  INFO Scheduler started
base.py[line:1153] DEBUG Looking for jobs to run
base.py[line:1260] DEBUG Next wakeup is due at ... 13:11:29 (in 1799.9 seconds)
```

> 这个修复只影响**可观测性**，不影响功能——`daemonize.py` 修的是进程存活，
> 这个是让调度决策可见。以后排查"任务到底有没有排上"直接看 `log/scheduler.log`。

### 修复的 bug（重要）

`helper/validator.py` 里 https 校验原本是：

```python
proxies = {"http": "http://{proxy}", "https": "https://{proxy}"}   # ← 错的
```

代理字典里的 scheme 表示**如何连接代理服务器本身**，不是目标站点的协议。
写成 `https://` 会让 requests 对明文 HTTP 代理发起 TLS 握手，结果是**每条代理的
https 校验都 ProxyError**。实测：

```
写法A (https://代理): ProxyError
写法B (http://代理):  status = 200     ← 修复后
```

后果有两个：`proxy.https` 全为 False（`/get?type=https` 取不到任何东西），
以及每条代理白等 10 秒超时。已改为 `http://`，修复后 3135/3294 条正确标记为支持 https。

### 调度节奏

upstream 默认 `proxy_check` 每 **2 分钟**全量复检、`proxy_fetch` 每 **5 分钟**重扫。
但 20 线程跑一轮 3400 条全量校验需要约 **12 分钟**——2 分钟的间隔会让任务无限堆积。
已调整为：

| 配置 | 默认 | 现值 | 说明 |
|---|---|---|---|
| `CHECK_INTERVAL_MINUTES` | 2 | **30** | 全量复检 |
| `FETCH_INTERVAL_MINUTES` | 5 | **120** | 重新读取清单并校验 |
| `CHECK_THREAD_COUNT` | 20 | **20** | 见下方警告 |

> **警告：不要盲目调高 `CHECK_THREAD_COUNT`。**
> 实测把它设为 60 时，进程会在开始校验数秒后被系统静默杀掉
> （无任何异常日志，退出码 137 / SIGKILL），疑似并发连接数触发系统限制。
> 20 线程可稳定跑完全量。若要调高，请从 30 开始逐步测试。

**启动时序**：`runScheduler()` 会先同步跑一次 `__runProxyFetch()`（读清单 + 全量校验，
实测 **约 12 分钟**），跑完才注册定时任务。所以：

- 进程刚启动的 12 分钟里，`log/scheduler.log` 是空的，这是**正常现象**，不是卡死；
- 首轮跑完会打印 `Scheduler started`，此时 `proxy_check` 的下次运行时间是「**当前 + 30 分钟**」，
  `proxy_fetch` 是「当前 + 120 分钟」。实测：
  ```
  Scheduler started                    2026-10-05 12:41:29
  job id=proxy_check  next_run=13:11:29   trigger=interval[0:30:00]
  job id=proxy_fetch  next_run=14:41:29   trigger=interval[2:00:00]
  ```
- 全量校验约 12 分钟 < 30 分钟间隔，所以不会堆积任务。

### 为什么需要 daemonize.py

macOS 没有 `setsid`，`nohup ... &` 起的进程仍然挂在当前 shell 的进程组里，
**shell 一退出（比如终端关闭、或调用它的自动化会话结束）就会被一起带走**。
实测：直接用 `nohup ... &` 起的调度进程在校验开始约 13 秒后就静默消失，
日志停在半截，没有任何异常输出。

`daemonize.py` 用**双 fork + `os.setsid()`** 把进程彻底脱离会话，
成为 `init` 的子进程，因此不会随终端或会话退出而死亡。
同时它顺带做了三件事：

1. 清掉 `HTTP_PROXY` / `HTTPS_PROXY` 等环境变量（本机有透明代理，不清掉会让 requests 走错路）；
2. 把 stdout/stderr 重定向到 `log/<name>.out`；
3. 写 PID 文件 `log/<name>.pid`，`stop` / `status` 靠它定位进程。

---

## 三、启动与停止

### 启动（两个进程都要起）

```bash
cd /Users/zhaoqi/myWorkspace/proxy_pool

# 1) Redis（如果没在跑）
redis-cli ping >/dev/null 2>&1 || redis-server --daemonize yes \
  --port 6379 --bind 127.0.0.1 --dir "$HOME/.redis-data" \
  --logfile "$HOME/.redis-log/redis.log" --save "" --appendonly no

# 2) 调度进程（采集 + 校验）。启动时先做一次全量校验，约 12 分钟
./.venv/bin/python daemonize.py schedule

# 3) API 服务
./.venv/bin/python daemonize.py server
```

输出形如：

```
schedule 已启动，PID=64245，日志: .../log/schedule.out
server   已启动，PID=64366，日志: .../log/server.out
```

### 停止

```bash
cd /Users/zhaoqi/myWorkspace/proxy_pool
./.venv/bin/python daemonize.py stop schedule
./.venv/bin/python daemonize.py stop server
```

> 不要用 `pkill -f proxyPool.py server` 收 API 进程——gunicorn 的 worker 是
> 主进程的子进程，`pkill` 匹配到的可能是 worker，主进程会立刻重新拉起一个，
> 导致端口一直被占。用 `daemonize.py stop` 会整组收干净。

### 查看状态

```bash
cd /Users/zhaoqi/myWorkspace/proxy_pool
./.venv/bin/python daemonize.py status        # 两个进程的运行状态

redis-cli -h 127.0.0.1 -p 6379 HLEN use_proxy # 池内代理数
curl -s --noproxy '*' http://127.0.0.1:5010/count/   # 统计

cat log/scheduler.log                         # 定时任务的排期与下次运行时间
tail -f log/schedule.out                      # 调度进程输出（采集 + 校验）
tail -f log/server.out                        # API 进程输出
tail -f log/checker.log                       # 校验明细
tail -f log/fetcher.log                       # 采集明细
```

> `log/scheduler.log` 里出现 `Scheduler started` 才代表定时任务已生效；
> 进程刚启动时它可能是空的（首轮全量校验还没跑完），属于正常。
>
> 日志会按天滚动（`TimedRotatingFileHandler`，保留 15 天）。
> 手动归档可参考 `log/archive/`。

> 本机有透明代理（`HTTP_PROXY=http://127.0.0.1:50038`），
> 访问本地 API 一定要加 `--noproxy '*'`，否则 curl 会把 `127.0.0.1:5010`
> 也交给上游代理，请求会失败。

---

## 四、Web 控制台与 API

### Web 控制台

**upstream 没有 Web UI**——`/` 只返回一段 JSON 接口清单（`api_list`），没有任何页面。
本次新增了一个控制台：

```
http://127.0.0.1:5010/dashboard
```

功能：

| 区域 | 内容 |
|---|---|
| 概览卡片 | 池内总数 / 支持 HTTPS / 仅 HTTP / 最近一次校验时间 |
| 调度器状态条 | 进程是否存活 + PID、下次全量校验时间、服务器时间（每 15 秒自动刷新） |
| 工具栏 | 搜索（IP / 端口 / 账号）、只看 HTTPS、每页条数 |
| 代理列表 | 服务端分页（3400 条不会一次性塞给浏览器）；认证部分弱化显示，`ip:port` 加粗 |
| 每行操作 | **测速**（弹窗实测出口 IP）、**复制**、**删除** |
| 「随机取一个」 | 调 `/get/` 取一条并弹出详情 |

「测速」会通过该代理真实请求一次 `https://myip.ipip.net` 并回显出口 IP，
用来判断代理是不是真的可用，而不是只看池子里的标记。

实现方式：页面是单文件 `api/dashboard.html`（无任何外部 CDN 依赖，离线可用），
由 Flask 的 `/dashboard` 路由直接返回，**与 API 同源**，因此没有跨域问题。
新增的接口：

| 接口 | 说明 |
|---|---|
| `GET /dashboard` | 控制台页面 |
| `GET /dashboard/stats` | 池子统计 + 调度器状态（读 `log/` 与 PID 文件推断） |
| `GET /dashboard/proxies?q=&https=&page=&size=` | 分页 + 搜索的代理列表 |
| `GET /dashboard/test?proxy=<user:pass@ip:port>` | 通过该代理真实请求一次，返回出口 IP |

> **安全说明**：`/dashboard/test` 的回显地址是**写死**的（`ECHO_URL`），不接受调用方传入 URL，
> 避免这个接口被当成任意请求转发器。但由于 `HOST = 0.0.0.0`，
> **局域网内任何人访问 `:5010/dashboard` 都能看到并操作你的池子**。
> 只在本机用的话建议把 `HOST` 改成 `127.0.0.1`（见第六节）。

---

### API 用法

服务地址 `http://127.0.0.1:5010`

| 接口 | 说明 |
|---|---|
| `GET /get/` | 随机返回一个代理 |
| `GET /get/?type=https` | 只返回支持 https 的代理 |
| `GET /pop/` | 返回并**删除**一个代理 |
| `GET /all/` | 返回全部代理 |
| `GET /count/` | 统计（总数、http/https 分布、来源分布） |
| `GET /delete/?proxy=xxx` | 删除指定代理 |

> **`type` 参数只认 `https`**：源码是 `request.args.get("type", "").lower() == 'https'`，
> 即只有传 `https` 才是过滤，传 `http` 或其它值等同于**不过滤**（所以 `/get/?type=http`
> 可能返回 `https: true` 的代理，这是 upstream 的既有行为，不是 bug）。
> 因为你的上游都是 HTTP 代理（靠 `CONNECT` 支持 https），
> 「支持 https」的 3136 条同时也都能跑 http，所以实际用 `?type=https` 就够。

### Python 用法

```python
import requests

API = "http://127.0.0.1:5010"

# 本机有透明代理，建 Session 时关掉 trust_env，否则本地 API 请求也会被劫走
s = requests.Session()
s.trust_env = False

def get_proxy():
    return s.get(f"{API}/get/").json()["proxy"]

def delete_proxy(p):
    s.get(f"{API}/delete/?proxy={p}")

for _ in range(5):
    p = get_proxy()
    url = "http://" + p
    try:
        r = s.get("https://myip.ipip.net",
                  proxies={"http": url, "https": url}, timeout=15)
        print(p, "->", r.text.strip())
    except Exception:
        delete_proxy(p)
```

> **注意 1**：返回的 `proxy` 字段已经带认证（形如 `user:pass@ip:port`），
> 拼成代理 URL 时要补 `http://` 前缀。`https` 键也用 `http://` 前缀
> —— 原因同上文"修复的 bug"。
>
> **注意 2**：国内网络直连 `api.ipify.org` 会 `Connection refused`，
> 验证出口 IP 请用 `https://myip.ipip.net`（返回"当前 IP：x.x.x.x 来自于：…"）。

### 命令行用法

```bash
P=$(curl -s --noproxy '*' http://127.0.0.1:5010/get/ \
      | python3 -c "import json,sys;print(json.load(sys.stdin)['proxy'])")
curl -x "http://$P" https://myip.ipip.net
```

### 怎么"自由切换"

`proxy_pool` 的语义是「**每次调用 `/get/` 随机给一个**」，所以切换和固定都很直白：

| 想要的效果 | 做法 |
|---|---|
| **切换**（换一个出口 IP） | 再调一次 `/get/`，拿到新的 `proxy` 即可 |
| **短期固定**（一段时间内都用同一个） | 把 `/get/` 返回的字符串**存在变量/文件里**，持续复用；不要重复调用 `/get/` |
| **固定到某个具体 IP** | 从 `/all/` 里筛出目标 IP 那条，直接用它的 `proxy` 字段 |
| **主动废弃某个** | `GET /delete/?proxy=<proxy>`，之后 `/get/` 不会再给到它 |

```python
import requests

API = "http://127.0.0.1:5010"
s = requests.Session(); s.trust_env = False

def pick(ip=None):
    """不指定 ip 就随机取一个；指定 ip 则从 /all/ 里精确挑出那一条"""
    if ip is None:
        return s.get(f"{API}/get/").json()["proxy"]
    for p in s.get(f"{API}/all/").json():
        if p["proxy"].endswith("@" + ip) or p["proxy"] == ip:
            return p["proxy"]
    raise LookupError(f"{ip} 不在池子里")

current = pick()                       # 固定下来，反复用
print("当前出口代理:", current)

def switch():
    global current
    current = pick()                   # 换一个
    return current
```

> 注意：`/get/` 返回的池子会随健康检查动态变化，被判定失效的代理会自动从池中移除，
> 所以**存下来的 proxy 也可能随时失效**，业务侧要保留失败重取（重新 `/get/`）的逻辑。

---

## 五、实测结果

首次全量采集 + 校验（20 线程，耗时 **730 秒**）：

| 指标 | 值 |
|---|---|
| 清单原始行数 | 3400 |
| **成功入池** | **3294**（96.9%） |
| 其中支持 HTTPS | 3135 |
| 仅支持 HTTP | 159 |
| 来源 | 全部 `local_list` |

抽样验证：从 `/get/` 连取 3 个代理实际发请求，**返回的出口 IP 与代理 IP 完全一致**，
证明代理链路真实生效。

```
acct1:***@104.207.50.98:3129  -> 104.207.50.98
acct2:***@209.50.169.1:3129   -> 209.50.169.1
acct3:***@65.111.26.127:3129  -> 65.111.26.127
```

后台调度器接管后的复核（`https://myip.ipip.net`）：

```
本机直连           -> 2409:8a50:2b9:...          中国 湖南 长沙 移动
acct4:***@65.111.23.151:3129   -> 65.111.23.151    出口已切换
acct5:***@216.26.245.120:3129  -> 216.26.245.120   出口已切换
acct6:***@209.50.172.224:3129  -> 209.50.172.224   出口已切换
```

---

## 六、注意事项

1. **凭据安全**：清单里是明文 `账号:密码`。本项目的 `.gitignore` 没有包含清单文件
   （清单在 `~/Downloads` 下，不在仓库内，所以没被提交）。**不要把清单复制进仓库**，
   若要放进来，先加进 `.gitignore`。
2. **API 无认证**：`setting.py` 的 `HOST = "0.0.0.0"`，即局域网内任何人都能访问
   `:5010` 拿走你的付费代理。若只在**本机**用，建议改为 `HOST = "127.0.0.1"`。
3. **`/pop/` 会删代理**：调试时误用会消耗池子。
4. **换清单不用改代码**：设 `LOCAL_PROXY_FILE` 环境变量指向新文件，重启调度进程即可。
   注意环境变量要传给守护进程——`daemonize.py` 在 fork 之后 `execv` 之前会继承当前
   环境，所以 `LOCAL_PROXY_FILE=/x/y.txt ./.venv/bin/python daemonize.py schedule` 是有效的。
5. **进程不会被系统守护**：`daemonize.py` 只保证进程不随终端退出而死，**重启电脑后仍需手动拉起**。
   要开机自启可配 `launchd`（macOS），把 `daemonize.py schedule` / `daemonize.py server`
   各写一个 LaunchAgent plist，`RunAtLoad` 设为 true 即可。
6. **本机透明代理**：环境里有 `HTTP_PROXY=http://127.0.0.1:50038` 等变量。
   `daemonize.py` 启动时会自动清掉，但你自己在终端里跑脚本、或调用本地 API 时仍需注意
   （curl 加 `--noproxy '*'`，requests 设 `session.trust_env = False`）。

---

## 七、2026/10/05 扩容：把 `~/Downloads/output` 的账号并入池子

### 输入与规模

`~/Downloads/output/` 下 976 个 `.txt`，每文件约 1000 行，格式 `http://user:pass@ip:port`。

| 指标 | 数值 |
|---|---|
| 原始行数 | 651,700（**行内与跨文件均零重复**，数据本身已去重） |
| 唯一 `账号@ip:port` | 651,700 |
| 唯一 `ip:port`（节点） | **40,704** |
| 不同账号数 | 6,517（每个账号固定绑定 100 个节点） |
| 与原有池子交集 | **0**（完全是另一批账号/IP） |

> 换算关系：40,704 个节点 × 平均 16 个账号 = 651,700。即**同一个 `ip:port` 被十几个
> 不同账号重复覆盖**，直接全量入池会得到 65 万条冗余条目。

### 关键判断一：失效是"节点级"还是"请求级"

用同一代理重复测 3 次，看成功率分布（`tools/probe_repeat.py`）：

```
目标 httpbin  单次成功率 p=0.678
  成功 3/3 :  28 条   (纯随机模型期望 18.7)
  成功 0/3 :   6 条   (纯随机模型期望  2.0)
```

实测分布在两端都**高于**纯随机模型的期望 → 呈**双峰**。结论：

- 存在**真实的永久死节点**（约 10%），必须剔除；
- 同时存在**大量瞬态失败**（单轮可用率只有 ~68%，主要是 ReadTimeout / ProxyError）；
- 因此**一轮定生死会误杀 30% 的可用节点**，必须用"重试"判定。

### 关键判断二：为什么要按节点去重

对同一 `ip:port` 用 12 个不同账号分别测，成功 8/12；对同一账号换 12 个不同 IP，
成功 8~12/12 —— 都贴近单次成功率，说明**可用性由节点决定，账号只是同一出口的不同凭据**。
所以按 `ip:port` 去重（保留一个可用账号）与保留全部 65 万条，**功能上等价**。

### 校验方案（`tools/validate_nodes.py`）

同步 20 线程太慢（65 万条要 39 小时），改用 **aiohttp 异步并发**：

| 方案 | 实测速度 |
|---|---|
| 原 20 线程同步 | ~4.7 条/秒 |
| 异步 并发 300 | **~106 条/秒**（httpbin）/ ~74 条/秒（qq.com） |

校验口径与 `setting.py` 的 `HTTP_URL` / `HTTPS_URL` **完全一致**，保证
"我判定可用 = 池子复检也判定可用"。

每个节点保留最多 8 个候选账号，**逐轮换账号重试**，任一通过即保留：

```
== http 校验 第 1 轮: 40704 条 ==  通过 39567   (剩 1137)
== http 校验 第 2 轮:  1137 条 ==  通过  1093   (剩   44)
== http 校验 第 3 轮:    44 条 ==  通过    42   (剩    2)
== http 校验 第 4 轮:     2 条 ==  通过     2   (剩    0)
http 阶段完成: 可用 40704 / 40704 = 100.0%
== https 校验: 40704 条 ==
支持 https: 40366 / 40704 = 99.2%
```

**结果：40,704 个节点全部至少有一个可用账号，零丢失。**

### 落库与源文件

- 明细：`~/Downloads/nodes_validated.json`（含 `https` 标记）
- 全量清单：`~/Downloads/nodes_validated.txt`（40,704 行）
- **合并源文件**：`~/Downloads/all_accounts_proxies_20261005.txt`
  = 旧清单 3,400 条 + 新校验通过 40,704 条 = **44,104 行**（无交集，直接拼接）

`fetcher/sources/local_list.py` 的 `DEFAULT_PROXY_FILE` 已改指向这个合并文件。
**这一步是必须的**：Redis 启动参数带 `--save "" --appendonly no`，**未开持久化**，
Redis 一重启池子就空，只能靠 fetcher 重新灌入；若 fetcher 仍指向旧文件，
扩容进来的 4 万条会永久丢失。

导入用 `tools/import_pool.py`，走项目自身的 `Proxy` / `RedisClient`，
写入的 JSON 与 `Proxy.to_json` 完全一致；只做 `hset`，**不清空池子**（"补充"语义）。

```
导入前: {'total': 3258,  'https': 3070}
导入后: {'total': 43962, 'https': 43436}
```

### 配置调整（`setting.py`）

池子从 3,258 条涨到 43,962 条后，池子自带的 20 线程同步复检**跑不动了**。
单条代理的线程耗时约 6 秒（httpbin + qq.com 两次请求），

```
43,962 × 6s ÷ 20 线程 ≈ 3.7 小时/轮
```

而原配置 `CHECK_INTERVAL_MINUTES = 30` 会让任务无限堆积。已调整：

| 配置 | 原值 | 现值 | 说明 |
|---|---|---|---|
| `CHECK_INTERVAL_MINUTES` | 30 | **360** | 全量复检，留约 2.3 小时空档 |
| `FETCH_INTERVAL_MINUTES` | 120 | **1440** | 每次采集要重校验全清单，24 小时一次 |

> **已知代价**：`runScheduler()` 启动时会先同步跑一次 `__runProxyFetch()`，
> 扩容后这一轮要 **约 3.7 小时**，期间调度器不注册定时任务（API 进程不受影响，
> 池子数据也已在 Redis 里）。这是"只调大间隔、不改校验器"方案的固有代价。
>
> **后续优化方向**（未实施）：把 `helper/check.py` 的线程池换成
> `tools/fast_check.py` 里的异步实现，43,962 条一轮可压到 **约 7 分钟**，
> 那样 `CHECK_INTERVAL_MINUTES` 就能回到 30 甚至更小。

### 复现命令

```bash
cd /Users/zhaoqi/myWorkspace/proxy_pool

# 1) 聚合 976 个文件，收敛成"唯一节点 + 候选账号"
./.venv/bin/python tools/dedupe_to_nodes.py

# 2) 多轮校验（约 15 分钟）
./.venv/bin/python tools/validate_nodes.py --rounds 5 --attempts 2 \
    --concurrency 300 --timeout 6

# 3) 导入池子（只增不删）
./.venv/bin/python tools/import_pool.py

# 4) 重启调度进程让新间隔生效
./.venv/bin/python daemonize.py stop schedule
./.venv/bin/python daemonize.py schedule
```

### 本次新增的工具脚本

| 脚本 | 用途 |
|---|---|
| `tools/aggregate_output.py` | 聚合 `output/` 并统计、与现有池子比对 |
| `tools/dedupe_to_nodes.py` | 收敛为 `ip:port → 候选账号列表` |
| `tools/probe_sample.py` | 抽样测可用率 |
| `tools/probe_dimension.py` | 判断失效是 IP 维度还是账号维度 |
| `tools/probe_repeat.py` | 重复测试，与二项分布对比判断失效性质 |
| `tools/fast_check.py` | 通用异步高并发校验器（可单独使用） |
| `tools/validate_nodes.py` | 多轮换账号校验主流程 |
| `tools/import_pool.py` | 导入 Redis（走项目自身 Proxy 类） |

---

## 八、增量补充流程（`tools/incremental_merge.py`）

后续每拿到一批新清单，用这一个脚本就够了，不要重跑第七节的整套流程：

```bash
cd /Users/zhaoqi/myWorkspace/proxy_pool

# 先 dry-run 看有多少是真新增
./.venv/bin/python tools/incremental_merge.py --in ~/Downloads/新清单.txt --dry-run

# 确认后正式跑：校验通过才入库，并自动追加进源文件
./.venv/bin/python tools/incremental_merge.py --in ~/Downloads/新清单.txt
```

它会：解析清单 → **按节点去重** → 跳过池子/源文件里已有的节点 →
只对真·新节点做多轮校验 → 入库 → 追加进 `all_accounts_proxies_20261005.txt`。

> **为什么默认按节点跳过**：第七节实测证明"可用性由节点决定，账号只是同一出口的
> 不同凭据"。同一节点加第二个账号不会提升可用率，只会让该节点被 `/get/` 抽中的概率翻倍。

### 案例：`proxies_gn_001722.txt`（2026/10/05 22:28）

| 项目 | 数值 |
|---|---|
| 行数 | 1,400 |
| 账号数 | 14（每个账号固定 100 节点） |
| 唯一节点 | 1,386 |
| **这 1,386 个节点在池子里** | **全部已有**（新增节点 = 0） |
| 14 个账号 | 全部是全新的 |

即"给已有节点换了一批新账号"。用 `tools/compare_accounts.py` 做 A/B 实测
（抽 80 个节点，新账号与池子现有账号各测一遍）：

```
新账号可用率     : 80/80 = 100.0%
池子账号可用率   : 80/80 = 100.0%
  只有新账号可用 : 0      <- 新账号救不回任何节点
  只有池子账号可用 : 0
```

结论：**功能上完全等价**，按既定策略跳过，池子与源文件均未改动。

> 若确实想把它们当"备份账号"加进去（例如担心某个账号被限速/封禁），
> 加 `--force-add-redundant`。但请注意上面实测的零收益。

### 排查记录：池子条数为什么会自己下降

扩容后发现 `HLEN use_proxy` 在缓慢下降（约 -5/分钟），一度怀疑有残留进程在删数据。
排查结论：**没有 bug，是外部客户端在正常调用 `/delete/`**。

排查手法（macOS 上没有 `timeout` 命令，`redis-cli MONITOR` 要这样限时）：

```bash
redis-cli -h 127.0.0.1 -p 6379 MONITOR > /tmp/mon.txt 2>&1 &
MPID=$!; sleep 25; kill -INT $MPID
grep -E '"(HDEL|DEL)"' /tmp/mon.txt          # 看谁在删
lsof -nP -iTCP:64431                          # 把 Redis 客户端端口映射回进程
grep -E "(pop|delete)" log/server.out         # 对照 API 访问日志
```

实测 60 秒窗口：`HLEN -5`，`/delete/` 6 次，`/get/` 55 次 —— 完全对得上。

**注意**：该客户端是「取一个 → 测一次 → 失败就 `delete`」的写法
（即第六节那个 Python 示例）。但第七节实测过**单轮校验有约 30% 是瞬态失败**，
所以这种"一次失败即删"会**误删掉大量实际可用的节点**。
若这个客户端是自己的业务脚本，建议改成**失败重试 2~3 次再决定是否删除**。

---

## 九、删除机制全景：什么情况会把代理从池子里删掉

代码里一共 **3 个真实删除入口 + 1 个非代码路径**。全仓库检索 `delete|hdel|pop` 可复核。

### 入口 1：调度器自动复检（`helper/check.py:134`）

只有走 `Checker("use")` 这条路径（即 `proxy_check` 定时任务）才会自动删，
`Checker("raw")`（`proxy_fetch` 采集）**只增不删**——采集失败只是不 `put`，不会删已有条目。

判定逻辑（`DoValidator.validator`）：

```python
if http_r:                       # httpbin.org HEAD 返回 200
    if proxy.fail_count > 0:
        proxy.fail_count -= 1    # 成功 -1，下限 0
    proxy.https = True if https_r else False
else:
    proxy.fail_count += 1        # 失败 +1
```

`__ifUse` 里 `if proxy.fail_count > self.conf.maxFailCount: delete()`。
`MAX_FAIL_COUNT = 2`，所以**删除条件是 `fail_count` 达到 3**。

三个容易踩的点：

1. **`fail_count` 是累积的、存在 Redis 里的**，跨轮次累加，不是单轮计数。
2. **每轮每个代理只变一次**。所以一个死节点需要**净失败 3 次**才被删。
   按现在的 `CHECK_INTERVAL_MINUTES = 360`，最坏要 **18 小时**才清掉；
   改回 30 分钟则是约 1.5 小时。这是"间隔调大"的隐性代价：**死节点滞留更久**。
3. **https 校验失败不会导致删除**。`httpsValidator` 只在 http 通过后才跑，
   失败时只把 `proxy.https` 置 False，**不碰 `fail_count`**。
   所以「支持 https」从 true 变 false 不会删代理——现在池子里 531 条
   `https=False` 就是证据。

**实测**：`checker.log` 里共 99 条 `delete`，**全部是 `count 3 delete`**（无一例外），
且**全部属于同一个账号 `52xqesydeljg`**。

> 这是一次典型的**账号整体失效**：该账号名下所有节点连续 3 轮校验失败，
> 被整批清掉。清理后该账号在池中条目为 0。
>
> **但那 99 个节点一个都没丢** —— 全部被其他账号重新顶上了
> （第七节的按节点导入用了不同账号覆盖同一节点）。
> 这反过来印证了"节点与账号解耦"的结论。

### 入口 2：客户端主动调 `/delete/`（`api/proxyApi.py:252`）

```python
@app.route('/delete/', methods=['GET'])
def delete():
    proxy = request.args.get('proxy')
    return {"code": 0, "src": proxy_handler.delete(Proxy(proxy))}
```

**无任何校验，传入即删**（按完整 `user:pass@ip:port` 字符串 HDEL）。

实测这是**当前最大的流出源**：

| 窗口 | /get | /delete | 删除占取用 |
|---|---|---|---|
| 近 3 分钟 | 178 | 15 | 8.4% |
| 近 10 分钟 | 525 | 99 | 18.9% |
| 近 30 分钟 | 667 | 144 | 21.6% |

约 **5 次/分钟 ≈ 300 次/小时**，而且「一次失败即删」——与 30% 的瞬态失败率严重不匹配，
**这是误删的主要来源**。

### 入口 3：客户端调 `/pop/`（`api/proxyApi.py:232`）

取出并删除（`redisClient.pop` → `hdel`）。语义就是"消耗一个"。
实测 **0 次**，目前没人用。

### 非代码路径：Redis 重启

```bash
redis-cli CONFIG GET save appendonly
#   save       -> ""      （禁用 RDB 快照）
#   appendonly -> "no"    （禁用 AOF）
#   TTL use_proxy -> -1   （永不过期，但重启即丢）
```

**完全没有持久化**。Redis 进程一重启，池子直接归零，
只能靠 `local_list` fetcher 从源文件重新灌入——这也是第七节强调
"必须把扩容清单写进 fetcher 源文件"的原因。

### 死代码

`RedisClient.clear()`（`db/redisClient.py:124`，整表 `DEL`）在 `api/ db/ handler/ helper/ util/`
和 `proxyPool.py` 里**没有任何调用者**，只在测试里用到。

### 小结：谁在删，删多少

| 来源 | 判定条件 | 速度 | 是否误删 |
|---|---|---|---|
| 调度器复检 | 净失败 3 次（≈3 轮） | 慢（最坏 18 小时） | 低，设计合理 |
| 客户端 `/delete/` | 调用方自己决定 | 快（约 300/小时） | **高，一次失败即删** |
| 客户端 `/pop/` | 调用即删 | — | 当前 0 次 |
| Redis 重启 | 进程重启 | 一次性全清 | — |

**当前池子健康度**：43,866 条里 `fail_count=0` 有 43,836 条、`=1` 有 30 条，
**没有任何一条 ≥ 2**，离删除阈值还有距离。



