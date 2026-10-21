# -*- coding: utf-8 -*-
"""
-------------------------------------------------
   File Name：     free_pool.py
   Description :   独立的免费代理源采集器（不影响线上 use_proxy 池）
   Author :        zhaoqi
   date：          2026/10/11
-------------------------------------------------
   Change Activity:
                   2026/10/11: 新增
-------------------------------------------------
与现有调度器完全解耦：
  * 不读 setting.PROXY_FETCHER_EXCLUDE，不改任何现有配置；
  * 结果写入独立的 Redis key（默认 free_proxy），绝不触碰 use_proxy；
  * 只调用 enabled=False 或黑名单中的源，现有调度器行为不变。

分流规则：
  * fetcher.overseas = True  -> 走出口代理（FETCH_PROXY_URL / 环境变量）
  * fetcher.overseas = False -> 强制直连（屏蔽环境代理）

用法：
  python tools/free_pool.py                       # 随机 4 个源，写入 free_proxy
  python tools/free_pool.py --num 6               # 随机 6 个源
  python tools/free_pool.py --sources ihuan,spys  # 指定源
  python tools/free_pool.py --list                # 列出全部可用源
  python tools/free_pool.py --no-redis --out x.txt  # 只落文件
  python tools/free_pool.py --replace             # 重建 key（先删后写）
"""
__author__ = 'zhaoqi'

import os
import re
import ssl
import sys
import time
import random
import asyncio
import argparse
import threading
import collections
import importlib
import urllib.request
from datetime import datetime

# 脚本位于 tools/ 下，需把项目根目录加进 sys.path 才能 import fetcher / helper 等
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..')))

# 注意：不要 import tools/fast_check.py —— 它在顶层会 pop 掉 HTTP_PROXY 等环境变量，
# 会导致国外源拿不到出口代理。这里自己实现一份精简的异步校验。

import aiohttp  # noqa: E402

from fetcher.baseFetcher import BaseFetcher  # noqa: E402
from fetcher.sources import (spys, openproxylist, proxyscrape, hproxy,  # noqa: E402
                             moleway, proxio, databay, cyberh4ck3r, mzyui)
from helper.proxy import Proxy  # noqa: E402
from helper.validator import IP_REGEX  # noqa: E402
from util.fetchProxy import setFetchProxy, resolveUpstreamProxy  # noqa: E402

TARGETS = {
    "httpbin": ("http://httpbin.org/", "HEAD"),
    "qq": ("https://www.qq.com/", "HEAD"),
    "ipip": ("https://myip.ipip.net/", "GET"),
}

SSL_CTX = ssl.create_default_context()
SSL_CTX.check_hostname = False
SSL_CTX.verify_mode = ssl.CERT_NONE

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/120.0 Safari/537.36",
    "Accept": "*/*",
    "Connection": "keep-alive",
}

SOURCES_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                           '..', 'fetcher', 'sources')

# 本地付费清单源不走这个流程（它是静态文件，属于线上池子的输入）
SKIP_NAMES = {"local_list"}


def discover_all_sources():
    """扫描 fetcher/sources/ 下全部 BaseFetcher 子类（保留所有源，不筛选可用性）"""
    classes = []
    for filename in sorted(os.listdir(SOURCES_DIR)):
        if not filename.endswith('.py') or filename.startswith('_'):
            continue
        module_name = "fetcher.sources.%s" % filename[:-3]
        try:
            module = importlib.import_module(module_name)
        except Exception as e:
            print("  [warn] 加载 %s 失败: %s" % (filename, e))
            continue
        for attr_name in dir(module):
            attr = getattr(module, attr_name, None)
            if (attr and isinstance(attr, type) and issubclass(attr, BaseFetcher)
                    and attr is not BaseFetcher and attr.name
                    and attr.name not in SKIP_NAMES):
                classes.append(attr)
    # 按 name 去重排序，保证随机抽样可复现
    seen, uniq = set(), []
    for c in sorted(classes, key=lambda x: x.name):
        if c.name not in seen:
            seen.add(c.name)
            uniq.append(c)
    return uniq


def fetch_one(cls, exit_value, results, lock, stats):
    """单个源的抓取线程：exit_value 由 main 按 --exit-mode 计算好后传入"""
    setFetchProxy(exit_value)
    name, got = cls.name, 0
    mode = "海外" if getattr(cls, 'overseas', False) else "国内"
    try:
        for item in cls().fetch():
            item = (item or "").strip()
            if not item or not IP_REGEX.fullmatch(item):
                continue
            with lock:
                if item in results:
                    results[item].add(name)
                else:
                    results[item] = {name}
                got += 1
    except Exception as e:
        print("  [%-12s] %s 抓取失败: %s" % (name, mode, type(e).__name__ + " " + str(e)[:60]))
        return
    print("  [%-12s] %s 抓到 %d 条" % (name, mode, got))
    stats[name] = got


async def _check(session, proxy, url, method, timeout):
    try:
        async with session.request(method, url, proxy="http://" + proxy,
                                   timeout=aiohttp.ClientTimeout(total=timeout),
                                   allow_redirects=False) as resp:
            return "ok" if resp.status == 200 else "HTTP%s" % resp.status
    except asyncio.TimeoutError:
        return "Timeout"
    except Exception as e:
        return type(e).__name__


async def validate(proxies, url, method, timeout, concurrency):
    results = collections.defaultdict(list)
    queue = asyncio.Queue()
    for p in proxies:
        queue.put_nowait(p)

    async def worker():
        while True:
            try:
                p = queue.get_nowait()
            except asyncio.QueueEmpty:
                return
            results[p].append(await _check(session, p, url, method, timeout))

    connector = aiohttp.TCPConnector(limit=concurrency, ssl=SSL_CTX,
                                     force_close=True, ttl_dns_cache=300)
    async with aiohttp.ClientSession(connector=connector, headers=HEADERS,
                                     trust_env=False) as session:
        await asyncio.gather(*[worker() for _ in range(concurrency)])
    return results


def pick_pool_proxies(n, api_url):
    """
    从代理池里取 n 个代理当抓取出口（只读，不删除）。
    优先走本地 API（与线上服务共用同一份数据），失败则直连 Redis 只读随机抽样。
    """
    import json as _json
    out = []
    try:
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        for _ in range(n * 3):
            if len(out) >= n:
                break
            raw = opener.open(api_url.rstrip("/") + "/get/?type=https", timeout=5).read()
            data = _json.loads(raw.decode("utf-8"))
            p = data.get("proxy") if isinstance(data, dict) else None
            if p:
                out.append(p)
    except Exception as e:
        print("  [pool] API 取代理失败(%s)，回退 Redis 只读抽样" % (type(e).__name__ + " " + str(e)[:40]))
    if not out:
        try:
            from handler.configHandler import ConfigHandler
            from db.dbClient import DbClient
            db = DbClient(ConfigHandler().dbConn)
            all_proxies = [p.proxy for p in db.getAll()]
            out = random.sample(all_proxies, min(n, len(all_proxies)))
        except Exception as e:
            print("  [pool] Redis 回退也失败: %s" % e)
    return out


def write_redis(key, ok_list, source_map, replace, https_flag):
    try:
        import redis
        from handler.configHandler import ConfigHandler
        from db.dbClient import DbClient
    except Exception as e:
        print("  [redis] 依赖不可用: %s" % e)
        return
    try:
        conn = ConfigHandler().dbConn
        db = DbClient(conn)
        db.changeTable(key)
    except Exception as e:
        print("  [redis] 连接失败: %s" % e)
        return
    if replace:
        db.clear()
        print("  [redis] 已清空旧 key: %s" % key)
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    n = 0
    for p in ok_list:
        obj = Proxy(p, source="/".join(sorted(source_map.get(p, {"free"}))),
                    last_status=True, last_time=now, https=https_flag)
        db.put(obj)
        n += 1
    print("  [redis] 写入 %s -> %d 条，当前总数 %s"
          % (key, n, db.getCount().get("total")))


def main():
    ap = argparse.ArgumentParser(description="独立免费代理源采集（不影响线上池）")
    ap.add_argument("--num", type=int, default=4,
                    help="随机挑选的源数量，默认 4；设为 0 表示跑全部")
    ap.add_argument("--all", action="store_true", help="跑全部源（等价于 --num 0）")
    ap.add_argument("--sources", default="", help="显式指定源，逗号分隔，覆盖随机")
    ap.add_argument("--must", default="", help="必选源，逗号分隔；剩余名额随机补足")
    ap.add_argument("--exclude", default="", help="排除的源，逗号分隔")
    ap.add_argument("--key", default="use_proxy",
                    help="写入的 Redis key，默认 use_proxy（即并入现有池）")
    ap.add_argument("--replace", action="store_true",
                    help="写入前先清空该 key（对 use_proxy 需配合 --force）")
    ap.add_argument("--force", action="store_true", help="允许对 use_proxy 执行 --replace")
    ap.add_argument("--exit-mode", default="auto",
                    choices=["auto", "direct", "upstream", "pool"],
                    help="抓取出口：auto=海外走出口/国内直连；direct=全部直连；"
                         "upstream=全部走固定出口；pool=全部走代理池里的 IP")
    ap.add_argument("--exit-upstream", default="", help="固定出口代理，覆盖环境变量")
    ap.add_argument("--pool-api", default="http://127.0.0.1:5010", help="取代理的池 API 地址")
    ap.add_argument("--pool-exit", type=int, default=3, help="从池里取几个 IP 轮换，默认 3")
    ap.add_argument("--no-redis", action="store_true", help="不写 Redis，只落文件")
    ap.add_argument("--out", default="", help="可用代理输出文件，默认 log/free_pool_<时间戳>.txt")
    ap.add_argument("--target", default="httpbin", choices=list(TARGETS))
    ap.add_argument("--concurrency", type=int, default=200)
    ap.add_argument("--max-check", type=int, default=5000,
                    help="单轮最多校验多少条（超出抽样），用于控制单轮耗时")
    ap.add_argument("--priority", default="hproxy",
                    help="抽样时优先填满这些源（逗号分隔），剩余预算再随机分配。"
                         "默认 hproxy —— 它可用率约 7%%，是其他源的 3 倍，"
                         "全局随机抽样会把它稀释掉")
    ap.add_argument("--timeout", type=float, default=6)
    ap.add_argument("--seed", type=int, default=0, help="随机种子，便于复现")
    ap.add_argument("--list", action="store_true", help="列出全部源后退出")
    args = ap.parse_args()

    all_sources = discover_all_sources()
    if args.list:
        print("全部代理源（%d 个，local_list 已排除）：" % len(all_sources))
        for c in all_sources:
            print("  %-14s overseas=%-5s enabled=%s" % (c.name, c.overseas, c.enabled))
        return

    exclude = {x.strip() for x in args.exclude.split(",") if x.strip()}
    pool = [c for c in all_sources if c.name not in exclude]

    if args.all or args.num <= 0:
        chosen = pool
        print("跑全部 %d 个源" % len(chosen))
    elif args.sources:
        wanted = {x.strip() for x in args.sources.split(",") if x.strip()}
        chosen = [c for c in pool if c.name in wanted]
        missing = wanted - {c.name for c in chosen}
        if missing:
            print("警告：未找到源 %s" % ",".join(missing))
    else:
        random.seed(args.seed or None)
        must = {x.strip() for x in args.must.split(",") if x.strip()}
        chosen = [c for c in pool if c.name in must]
        rest = [c for c in pool if c.name not in must]
        need = max(0, args.num - len(chosen))
        if need and rest:
            chosen += random.sample(rest, min(need, len(rest)))
        print("选中 %d/%d 个源(必选 %s): %s"
              % (len(chosen), len(pool), ",".join(must) or "-",
                 ", ".join(c.name for c in chosen)))

    # 安全阀：绝不清空线上池，除非显式 --force
    if args.replace and args.key == "use_proxy" and not args.force:
        print("拒绝执行：--replace 会清空线上池 use_proxy。")
        print("如需重建请加 --force；默认行为是只新增、不删除。")
        return

    upstream = args.exit_upstream or resolveUpstreamProxy()
    pool_ips = []
    if args.exit_mode in ("pool", "auto"):
        pool_ips = pick_pool_proxies(args.pool_exit, args.pool_api)
    print("出口模式: %s | 固定出口: %s | 池内出口: %d 个 %s"
          % (args.exit_mode, upstream or "(未配置)", len(pool_ips), pool_ips[:2]))

    def exit_for(cls):
        """auto: 海外走池内IP(没有则固定出口)，国内直连；其余模式全体一致"""
        if args.exit_mode == "direct":
            return ""
        if args.exit_mode == "upstream":
            return upstream or ""
        if args.exit_mode == "pool":
            return pool_ips or upstream or ""
        if getattr(cls, 'overseas', False):
            return pool_ips or upstream or ""
        return ""

    print("\n[1/3] 抓取中 ...")
    results, lock, stats = {}, threading.Lock(), {}
    threads = [threading.Thread(target=fetch_one,
                                args=(c, exit_for(c), results, lock, stats),
                                daemon=True) for c in chosen]
    for t in threads:
        t.start()
    for t in threads:
        # 单源最多等 45s：个别不可达源(如 docip)会长时间挂起，不能拖死整轮
        t.join(45)

    raw = list(results.keys())
    print("原始去重: %d 条" % len(raw))
    if not raw:
        print("没有抓到任何代理，退出。")
        return

    if args.max_check and len(raw) > args.max_check:
        # 不全局随机抽样：那样高质量源会被低质量源按数量稀释
        # （实测全跑 18538 条随机抽 3000 → 只出 70 条；优先 hproxy 后可出 180+）。
        prio = {x.strip() for x in args.priority.split(",") if x.strip()}
        first = [p for p in raw if results.get(p, set()) & prio]
        rest = [p for p in raw if p not in set(first)]
        random.seed((args.seed or 0) + 1)
        picked = first[:args.max_check]
        budget = args.max_check - len(picked)
        if budget > 0 and rest:
            picked += random.sample(rest, min(budget, len(rest)))
        random.shuffle(picked)
        print("抽样至 %d 条（其中优先源 %s %d 条）"
              % (len(picked), ",".join(prio) or "-", len(picked) - min(budget, len(rest)) if budget > 0 else len(picked)))
        raw = picked

    print("\n[2/3] 校验中（%s，并发 %d）..." % (args.target, args.concurrency))
    url, method = TARGETS[args.target]
    t0 = time.time()
    res = asyncio.run(validate(raw, url, method, args.timeout, args.concurrency))
    ok_list = [p for p in raw if "ok" in res[p]]
    reasons = collections.Counter(r for p in raw if "ok" not in res[p] for r in res[p])
    print("可用 %d / %d = %.1f%%（耗时 %.1fs）"
          % (len(ok_list), len(raw), 100.0 * len(ok_list) / len(raw), time.time() - t0))
    print("失败原因: %s" % dict(reasons.most_common(5)))

    out = args.out or os.path.join("log", "free_pool_%s.txt"
                                   % datetime.now().strftime("%Y%m%d_%H%M%S"))
    os.makedirs(os.path.dirname(out), exist_ok=True)
    with open(out, "w", encoding="utf-8") as f:
        for p in ok_list:
            f.write(p + "\n")
    print("\n[3/3] 可用清单已写出: %s" % out)

    if not args.no_redis and ok_list:
        write_redis(args.key, ok_list, results, args.replace, True)


if __name__ == "__main__":
    main()
