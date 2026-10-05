# -*- coding: utf-8 -*-
"""
-------------------------------------------------
   File Name：     fast_check.py
   Description :   异步高并发代理校验器（替代 20 线程的同步校验，快 20 倍以上）
   Author :        zhaoqi
   date：          2026/10/05
-------------------------------------------------
   Change Activity:
                   2026/10/05: 新增
-------------------------------------------------
   用法：
     python tools/fast_check.py --in <清单> --out <结果> [--target httpbin|ipip]
                                [--attempts 2] [--concurrency 300] [--timeout 6]
   输出：每行 `proxy<TAB>ok/fail`，另打印统计。
"""
__author__ = 'zhaoqi'

import os
import ssl
import sys
import time
import json
import asyncio
import argparse
import collections

# 本机有环境透明代理，异步校验必须绕开
for k in ("HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy",
          "ALL_PROXY", "all_proxy"):
    os.environ.pop(k, None)

import aiohttp  # noqa: E402

TARGETS = {
    # 与 setting.py 的 HTTP_URL / HTTPS_URL 保持一致，保证"通过校验=池子认可"
    "httpbin": ("http://httpbin.org/", "HEAD"),
    "qq": ("https://www.qq.com/", "HEAD"),
    "ipip": ("https://myip.ipip.net/", "GET"),
}

SSL_CTX = ssl.create_default_context()
SSL_CTX.check_hostname = False
SSL_CTX.verify_mode = ssl.CERT_NONE

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 6.1; WOW64; rv:34.0) "
                  "Gecko/20100101 Firefox/34.0",
    "Accept": "*/*",
    "Connection": "keep-alive",
    "Accept-Language": "zh-CN,zh;q=0.8",
}


async def check_one(session, proxy, url, method, timeout):
    p = "http://" + proxy
    try:
        async with session.request(method, url, proxy=p,
                                   timeout=aiohttp.ClientTimeout(total=timeout),
                                   allow_redirects=False) as resp:
            return "ok" if resp.status == 200 else "HTTP %s" % resp.status
    except asyncio.TimeoutError:
        return "Timeout"
    except aiohttp.ClientProxyConnectionError:
        return "ProxyConnectError"
    except aiohttp.ClientConnectorError:
        return "ConnectorError"
    except aiohttp.ServerDisconnectedError:
        return "Disconnected"
    except Exception as e:
        return type(e).__name__


async def worker(name, queue, session, url, method, timeout, results):
    while True:
        try:
            proxy = queue.get_nowait()
        except asyncio.QueueEmpty:
            return
        r = await check_one(session, proxy, url, method, timeout)
        results[proxy].append(r)


async def run(proxies, url, method, timeout, concurrency, attempts):
    results = collections.defaultdict(list)
    connector = aiohttp.TCPConnector(limit=concurrency, ttl_dns_cache=300,
                                     ssl=SSL_CTX, force_close=True)
    async with aiohttp.ClientSession(connector=connector,
                                     headers=HEADERS,
                                     trust_env=False) as session:
        for round_no in range(attempts):
            queue = asyncio.Queue()
            for p in proxies:
                if round_no == 0 or "ok" not in results[p]:
                    queue.put_nowait(p)
            remaining = queue.qsize()
            if remaining == 0:
                break
            t0 = time.time()
            workers = [asyncio.create_task(
                worker(i, queue, session, url, method, timeout, results))
                for i in range(concurrency)]
            await asyncio.gather(*workers)
            dt = time.time() - t0
            ok = sum(1 for p in proxies if "ok" in results[p])
            print("  第 %d 轮: 测 %d 条, 耗时 %.1fs (%.0f req/s), 累计可用 %d"
                  % (round_no + 1, remaining, dt, remaining / dt, ok),
                  flush=True)
    return results


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--in", dest="inp", required=True)
    ap.add_argument("--out", dest="out", required=True)
    ap.add_argument("--target", default="httpbin", choices=list(TARGETS))
    ap.add_argument("--attempts", type=int, default=2)
    ap.add_argument("--concurrency", type=int, default=300)
    ap.add_argument("--timeout", type=float, default=6)
    ap.add_argument("--limit", type=int, default=0)
    args = ap.parse_args()

    url, method = TARGETS[args.target]
    with open(os.path.expanduser(args.inp), encoding="utf-8") as f:
        proxies = [x.strip() for x in f if x.strip()]
    if args.limit:
        proxies = proxies[:args.limit]
    print("清单 %d 条, 目标 %s %s, 并发 %d, 最多 %d 轮, 超时 %.1fs"
          % (len(proxies), method, url, args.concurrency, args.attempts, args.timeout))

    t0 = time.time()
    results = asyncio.run(run(proxies, url, method, args.timeout,
                              args.concurrency, args.attempts))
    dt = time.time() - t0

    ok_list, fail_list = [], []
    for p in proxies:
        rs = results[p]
        (ok_list if "ok" in rs else fail_list).append(p)

    with open(os.path.expanduser(args.out), "w", encoding="utf-8") as f:
        for p in ok_list:
            f.write(p + "\n")

    reasons = collections.Counter(r for p in fail_list for r in results[p])
    print("=" * 55)
    print("总耗时 %.1fs" % dt)
    print("可用 %d / %d = %.1f%%" % (len(ok_list), len(proxies),
                                     100.0 * len(ok_list) / max(len(proxies), 1)))
    print("失败原因:", dict(reasons.most_common(8)))
    print("可用清单已写出: %s" % args.out)


if __name__ == "__main__":
    main()
