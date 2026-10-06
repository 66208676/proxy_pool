# -*- coding: utf-8 -*-
"""
-------------------------------------------------
   File Name：     setting.py
   Description :   配置文件
   Author :        JHao
   date：          2019/2/15
-------------------------------------------------
   Change Activity:
                   2019/2/15:
-------------------------------------------------
"""

BANNER = r"""
****************************************************************
*** ______  ********************* ______ *********** _  ********
*** | ___ \_ ******************** | ___ \ ********* | | ********
*** | |_/ / \__ __   __  _ __   _ | |_/ /___ * ___  | | ********
*** |  __/|  _// _ \ \ \/ /| | | ||  __// _ \ / _ \ | | ********
*** | |   | | | (_) | >  < \ |_| || |  | (_) | (_) || |___  ****
*** \_|   |_|  \___/ /_/\_\ \__  |\_|   \___/ \___/ \_____/ ****
****                       __ / /                          *****
************************* /___ / *******************************
*************************       ********************************
****************************************************************
"""

VERSION = "2.4.0"

# ############### server config ###############
HOST = "0.0.0.0"

PORT = 5010

# ############### database config ###################
# db connection uri
# example:
#      Redis: redis://:password@ip:port/db
#      Ssdb:  ssdb://:password@ip:port
# 2026/10/05：本地 Redis（D:\software\Redis-x64-3.0.504）需要密码 123456，
# 故在此填入密码，否则 proxy_pool 无法连接本机 use_proxy。
DB_CONN = 'redis://:123456@127.0.0.1:6379/0'

# proxy table name
TABLE_NAME = 'use_proxy'


# ###### config the proxy fetch function ######
# 自动扫描 fetcher/sources/ 目录，加载所有 enabled=True 的 fetcher
# 如需临时禁用某个 fetcher，在下方黑名单中添加类名（不改源文件）
#
# 本地部署说明：只使用本地清单源 local_list，其余 14 个免费代理源全部禁用。
PROXY_FETCHER_EXCLUDE = [
    "DaiLi66Fetcher",
    "DocipFetcher",
    "FreeVPNNodeFetcher",
    "GeonodeFetcher",
    "GoodipsFetcher",
    "IhuanFetcher",
    "Ip3366Fetcher",
    "Ip89Fetcher",
    "KuaidailiFetcher",
    "KxdailiFetcher",
    "ProxiFlyFetcher",
    "RoundProxiesFetcher",
    "ScdnFetcher",
    "ZdayeFetcher",
]

# ############# proxy validator #################
# 代理验证目标网站
HTTP_URL = "http://httpbin.org"

HTTPS_URL = "https://www.qq.com"

# 代理验证时超时时间
VERIFY_TIMEOUT = 10

# 近PROXY_CHECK_COUNT次校验中允许的最大失败次数,超过则剔除代理
#
# upstream 默认 0（失败一次即删）。这对免费代理池合适，但对付费池过于激进：
# 付费池本身可用率 96%+，偶发网络抖动就会误删。设为 2 可容忍瞬态失败。
MAX_FAIL_COUNT = 2

# 近PROXY_CHECK_COUNT次校验中允许的最大失败率,超过则剔除代理
# MAX_FAIL_RATE = 0.1

# proxyCheck时代理数量少于POOL_SIZE_MIN触发抓取
POOL_SIZE_MIN = 20

# ############# proxy attributes #################
# 是否启用代理地域属性
#
# 本地部署说明：置为 False。原因有二——
#   1) regionGetter 会对每个代理请求一次 https://api.ip.sb/geoip/<ip>，
#      3252 条代理会产生 3252 次外部请求，极慢且易被限流；
#   2) regionGetter 用 proxy.proxy.split(':')[0] 取 IP，遇到带认证的
#      `user:pass@ip:port` 格式会取到用户名而非 IP。
PROXY_REGION = False

# ############# scheduler config #################

# 校验线程数（upstream 默认 20）。
# 注意：实测在本机把该值调到 60 会让进程在开始校验数秒后被系统静默杀掉
# （无任何异常日志，退出码 137/SIGKILL），疑似并发连接数触发了系统限制。
# 20 线程可稳定跑完全量，3000+ 条约需 8 分钟。如需调高请逐步测试（如 30/40）。
CHECK_THREAD_COUNT = 20

# 采集间隔（分钟）。清单是本地静态文件，不需要频繁重扫，upstream 默认 5。
#
# 2026/10/05 扩容后：清单从 3,400 条涨到约 44,000 条，
# 每次采集都要把清单全量重新校验一遍。实测 20 线程下每条代理约 6 秒线程耗时
# （httpbin + qq.com 两次请求），44,000 条 ≈ 3.7 小时。
# 因此采集间隔必须远大于单轮耗时，否则任务会无限堆积。
FETCH_INTERVAL_MINUTES = 1440

# 全量复检间隔（分钟）。upstream 默认 2，对 3000+ 条的池子来说过密。
#
# 2026/10/05 扩容后：池内约 44,000 条，20 线程跑一轮全量约需 3.7 小时，
# 故设为 6 小时（360 分钟），留出约 2.3 小时空档，避免任务堆积。
# 注意：这一轮耗时是估算值（按每条 ~6 秒线程耗时推算），
# 首次实测后如发现单轮超过 5 小时，应继续调大本值。
CHECK_INTERVAL_MINUTES = 360

# Set the timezone for the scheduler forcely (optional)
# If it is running on a VM, and
#   "ValueError: Timezone offset does not match system offset"
#   was raised during scheduling.
# Please uncomment the following line and set a timezone for the scheduler.
# Otherwise it will detect the timezone from the system automatically.

TIMEZONE = "Asia/Shanghai"
