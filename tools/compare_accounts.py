# -*- coding: utf-8 -*-
"""
-------------------------------------------------
   File Name：     compare_accounts.py
   Description :   对比"新清单账号"与"池子现有账号"在同一节点上的可用性
   Author :        zhaoqi
   date：          2026/10/05
-------------------------------------------------
   场景：新清单里的 ip:port 池子里全都有，但账号不同。
        判断新账号是"等价冗余"还是"能救回已失效的节点"。
"""
__author__ = 'zhaoqi'

import os
import re
import ssl
import json
import random
import asyncio
import argparse
import collections

for k in ("HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy",
          "ALL_PROXY", "all_proxy"):
    os.environ.pop(k, None)

import aiohttp  # noqa: E402
import redis     # noqa: E402

LINE = re.compile(
    r"^(?:https?://)?(?P<auth>[^/@\s]+:[^/@\s]+)@"
    r"(?P<ip>\d{1,3}(?:\.\d{1,3}){3}):(?P<port>\d{1,5})$")

SSL_CTX = ssl.create_default_context()
SSL_CTX.check_hostname = False
SSL_CTX.verify_mode = ssl.CERT_NONE

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 6.1; WOW64; rv:34.0) "
                  "Gecko/20100101 Firefox/34.0",
    "Accept": "*/*", "Connection": "keep-alive",
    "Accept-Language": "zh-CN,zh;q=0.8",
}
URL, METHOD = "http://httpbin.org/", "HEAD"


async def probe(session, proxy, timeout):
    try:
        async with session.request(METHOD, URL, proxy="http://" + proxy,
                                   timeout=aiohttp.ClientTimeout(total=timeout),
                                   allow_redirects=False) as r:
            return r.status == 200
    except Exception:
        return False


async def check_all(proxies, attempts, concurrency, timeout):
    passed = set()
    todo = list(proxies)
    for _ in range(attempts):
        if not todo:
            break
        conn = aiohttp.TCPConnector(limit=concurrency, force_close=True,
                                    ssl=SSL_CTX)
        async with aiohttp.ClientSession(connector=conn, headers=HEADERS,
                                         trust_env=False) as s:
            sem = asyncio.Semaphore(concurrency)

            async def one(p):
                async with sem:
                    if await probe(s, p, timeout):
                        passed.add(p)

            await asyncio.gather(*[one(p) for p in todo])
        todo = [p for p in todo if p not in passed]
    return passed


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--file",
                    default="~/Downloads/proxies_gn_001722.txt")
    ap.add_argument("--sample", type=int, default=80)
    ap.add_argument("--attempts", type=int, default=2)
    ap.add_argument("--concurrency", type=int, default=100)
    ap.add_argument("--timeout", type=float, default=6)
    ap.add_argument("--seed", type=int, default=20261005)
    args = ap.parse_args()

    new_map = {}
    with open(os.path.expanduser(args.file), encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            m = LINE.match(line)
            if m:
                new_map["%s:%s" % (m.group("ip"), m.group("port"))] = \
                    "%s@%s:%s" % (m.group("auth"), m.group("ip"), m.group("port"))
    print("新清单节点数: %d" % len(new_map))

    r = redis.Redis(host="127.0.0.1", port=6379, db=0, decode_responses=True,
                    protocol=2, socket_timeout=10)
    pool_map = {}
    for k in r.hkeys("use_proxy"):
        pool_map[k.split("@")[-1]] = k
    print("池子节点数: %d" % len(pool_map))

    common = sorted(set(new_map) & set(pool_map))
    print("两边都有的节点: %d" % len(common))

    rnd = random.Random(args.seed)
    sample = rnd.sample(common, min(args.sample, len(common)))
    print("抽样 %d 个节点做对比\n" % len(sample))

    new_list = [new_map[n] for n in sample]
    old_list = [pool_map[n] for n in sample]

    print("测新账号...")
    new_ok = asyncio.run(check_all(new_list, args.attempts,
                                   args.concurrency, args.timeout))
    print("测池子现有账号...")
    old_ok = asyncio.run(check_all(old_list, args.attempts,
                                   args.concurrency, args.timeout))

    both = only_new = only_old = neither = 0
    rescue = []
    for n in sample:
        a = new_map[n] in new_ok
        b = pool_map[n] in old_ok
        if a and b:
            both += 1
        elif a and not b:
            only_new += 1
            rescue.append((pool_map[n], new_map[n]))
        elif b and not a:
            only_old += 1
        else:
            neither += 1

    print("\n" + "=" * 55)
    print("样本 %d 个节点：" % len(sample))
    print("  新账号可用率     : %d/%d = %.1f%%"
          % (len(new_ok), len(sample), 100.0 * len(new_ok) / len(sample)))
    print("  池子账号可用率   : %d/%d = %.1f%%"
          % (len(old_ok), len(sample), 100.0 * len(old_ok) / len(sample)))
    print("-" * 55)
    print("  两者都可用       : %d" % both)
    print("  只有新账号可用   : %d   <- 新账号能救回的节点" % only_new)
    print("  只有池子账号可用 : %d" % only_old)
    print("  两者都不可用     : %d" % neither)
    if rescue[:5]:
        print("\n救回示例（池子账号 -> 新账号）:")
        for o, n in rescue[:5]:
            print("   %s  ->  %s" % (o, n))


if __name__ == "__main__":
    main()
