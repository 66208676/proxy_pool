# -*- coding: utf-8 -*-
"""
-------------------------------------------------
   File Name：     probe_sample.py
   Description :   抽样探测代理可用率，判断"账号维度"还是"IP维度"失效
   Author :        zhaoqi
   date：          2026/10/05
-------------------------------------------------
"""
__author__ = 'zhaoqi'

import os
import random
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed

# 关掉环境透明代理（本机有 HTTP_PROXY，会干扰直连判断）
for k in ("HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy",
          "ALL_PROXY", "all_proxy"):
    os.environ.pop(k, None)

import requests  # noqa: E402

MERGED = os.path.expanduser("~/Downloads/output_merged_unique.txt")
ECHO = "https://myip.ipip.net"
TIMEOUT = 12


def test(proxy):
    url = "http://" + proxy
    s = requests.Session()
    s.trust_env = False
    try:
        r = s.get(ECHO, proxies={"http": url, "https": url},
                  timeout=TIMEOUT, verify=False)
        ok = r.status_code == 200
        return proxy, ok, r.text.strip()[:60] if ok else "HTTP %s" % r.status_code
    except Exception as e:
        return proxy, False, type(e).__name__
    finally:
        s.close()


def main():
    mode = sys.argv[1] if len(sys.argv) > 1 else "random"
    n = int(sys.argv[2]) if len(sys.argv) > 2 else 200

    with open(MERGED, "r", encoding="utf-8") as f:
        lines = [x.strip() for x in f if x.strip()]

    if mode == "random":
        sample = random.sample(lines, n)
    elif mode == "accounts":
        # 每个账号取第一条，抽 n 个账号
        seen = {}
        for line in lines:
            auth = line.split("@")[0]
            if auth not in seen:
                seen[auth] = line
        sample = random.sample(list(seen.values()), min(n, len(seen)))
    elif mode == "sameip":
        # 同一个 ip:port，取 n 个不同账号
        target = lines[0].split("@")[1]
        sample = [l for l in lines if l.endswith("@" + target)][:n]
    else:
        sample = lines[:n]

    print("模式=%s 样本=%d" % (mode, len(sample)))
    ok_count = 0
    reasons = {}
    alive = []
    with ThreadPoolExecutor(max_workers=20) as ex:
        futs = [ex.submit(test, p) for p in sample]
        for i, fut in enumerate(as_completed(futs), 1):
            proxy, ok, info = fut.result()
            if ok:
                ok_count += 1
                alive.append(proxy)
            else:
                reasons[info] = reasons.get(info, 0) + 1
            if i % 50 == 0:
                print("  进度 %d/%d  可用 %d" % (i, len(sample), ok_count))

    print("=" * 50)
    print("可用: %d/%d = %.1f%%" % (ok_count, len(sample), 100.0 * ok_count / len(sample)))
    print("失败原因分布:", sorted(reasons.items(), key=lambda x: -x[1]))
    for p in alive[:10]:
        print("  OK", p)


if __name__ == "__main__":
    main()
