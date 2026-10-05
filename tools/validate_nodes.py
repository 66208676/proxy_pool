# -*- coding: utf-8 -*-
"""
-------------------------------------------------
   File Name：     validate_nodes.py
   Description :   对唯一节点做多轮校验：每个节点依次试候选账号，任一通过即保留
   Author :        zhaoqi
   date：          2026/10/05
-------------------------------------------------
   输入：~/Downloads/nodes_candidates.json
   输出：~/Downloads/nodes_validated.txt        （通过 http 校验的 user:pass@ip:port）
         ~/Downloads/nodes_validated_https.txt  （其中同时通过 https 校验的）
         ~/Downloads/nodes_validated.json       （含 https 标记的明细）

   校验口径与 setting.py 的 HTTP_URL / HTTPS_URL 完全一致，
   保证"我判定可用 = 池子复检也判定可用"。
"""
__author__ = 'zhaoqi'

import os
import ssl
import json
import time
import asyncio
import argparse
import collections

for k in ("HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy",
          "ALL_PROXY", "all_proxy"):
    os.environ.pop(k, None)

import aiohttp  # noqa: E402

HTTP_URL = ("http://httpbin.org/", "HEAD")
HTTPS_URL = ("https://www.qq.com/", "HEAD")

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


async def probe(session, proxy, url, method, timeout):
    """返回 True/False"""
    try:
        async with session.request(method, url, proxy="http://" + proxy,
                                   timeout=aiohttp.ClientTimeout(total=timeout),
                                   allow_redirects=False) as resp:
            return resp.status == 200
    except Exception:
        return False


async def check_batch(proxies, url, method, timeout, concurrency, attempts,
                      label):
    """对一批代理做校验，任一 attempt 通过即算通过。返回通过的集合"""
    passed = set()
    todo = list(proxies)
    for rnd in range(attempts):
        if not todo:
            break
        t0 = time.time()
        connector = aiohttp.TCPConnector(limit=concurrency, force_close=True,
                                         ssl=SSL_CTX)
        async with aiohttp.ClientSession(connector=connector, headers=HEADERS,
                                         trust_env=False) as session:
            sem = asyncio.Semaphore(concurrency)

            async def one(p):
                async with sem:
                    if await probe(session, p, url, method, timeout):
                        passed.add(p)

            await asyncio.gather(*[one(p) for p in todo])
        dt = time.time() - t0
        print("    [%s] 第 %d 轮 %d 条 耗时 %.1fs (%.0f/s) 通过累计 %d"
              % (label, rnd + 1, len(todo), dt, len(todo) / max(dt, 1e-9),
                 len(passed)), flush=True)
        todo = [p for p in todo if p not in passed]
    return passed


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--candidates", default="~/Downloads/nodes_candidates.json")
    ap.add_argument("--out", default="~/Downloads/nodes_validated.json")
    ap.add_argument("--rounds", type=int, default=5)
    ap.add_argument("--attempts", type=int, default=2)
    ap.add_argument("--concurrency", type=int, default=300)
    ap.add_argument("--timeout", type=float, default=6)
    ap.add_argument("--skip-https", action="store_true")
    args = ap.parse_args()

    with open(os.path.expanduser(args.candidates), encoding="utf-8") as f:
        cand = json.load(f)
    print("候选节点 %d 个" % len(cand), flush=True)

    # ---------- 阶段一：http 校验，逐轮换候选账号 ----------
    resolved = {}          # node -> proxy
    pending = list(cand.keys())
    for rnd in range(args.rounds):
        batch = []
        for node in pending:
            cs = cand[node]
            if rnd < len(cs):
                batch.append("%s@%s" % (cs[rnd], node))
        if not batch:
            break
        print("\n== http 校验 第 %d 轮: %d 条 ==" % (rnd + 1, len(batch)),
              flush=True)
        passed = asyncio.run(check_batch(batch, HTTP_URL[0], HTTP_URL[1],
                                         args.timeout, args.concurrency,
                                         args.attempts, "http"))
        for p in passed:
            node = p.split("@", 1)[1]
            resolved[node] = p
        pending = [n for n in cand if n not in resolved]
        print("  本轮解决 %d, 累计可用节点 %d, 剩余 %d"
              % (len(passed), len(resolved), len(pending)), flush=True)
        # 落盘中间结果，防止中断白跑
        with open(os.path.expanduser(args.out) + ".partial", "w",
                  encoding="utf-8") as f:
            json.dump(resolved, f)
        if not pending:
            break

    print("\nhttp 阶段完成: 可用 %d / %d = %.1f%%"
          % (len(resolved), len(cand), 100.0 * len(resolved) / len(cand)),
          flush=True)

    # ---------- 阶段二：https 校验 ----------
    https_ok = set()
    if not args.skip_https and resolved:
        proxies = list(resolved.values())
        print("\n== https 校验: %d 条 ==" % len(proxies), flush=True)
        https_ok = asyncio.run(check_batch(proxies, HTTPS_URL[0], HTTPS_URL[1],
                                           args.timeout + 2, args.concurrency,
                                           args.attempts, "https"))
        print("支持 https: %d / %d = %.1f%%"
              % (len(https_ok), len(proxies),
                 100.0 * len(https_ok) / len(proxies)), flush=True)

    # ---------- 输出 ----------
    out = os.path.expanduser(args.out)
    detail = {node: {"proxy": p, "https": p in https_ok}
              for node, p in resolved.items()}
    with open(out, "w", encoding="utf-8") as f:
        json.dump(detail, f)

    all_file = out.replace(".json", ".txt")
    https_file = out.replace(".json", "_https.txt")
    with open(all_file, "w", encoding="utf-8") as f:
        for node in sorted(detail):
            f.write(detail[node]["proxy"] + "\n")
    with open(https_file, "w", encoding="utf-8") as f:
        for node in sorted(detail):
            if detail[node]["https"]:
                f.write(detail[node]["proxy"] + "\n")

    print("\n" + "=" * 55)
    print("可用节点总数  : %d" % len(detail))
    print("其中 https    : %d" % len(https_ok))
    print("全量清单      : %s" % all_file)
    print("https 清单    : %s" % https_file)
    print("明细(含标记)  : %s" % out)


if __name__ == "__main__":
    main()
