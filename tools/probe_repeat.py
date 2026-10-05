# -*- coding: utf-8 -*-
"""
-------------------------------------------------
   File Name：     probe_repeat.py
   Description :   同一代理重复测试，判断失败是"节点永久失效"还是"请求级随机"
                  - 每个代理测 N 次，统计 0/N、1/N ... N/N 的分布
                  - 与二项分布理论值对比
                  - 换用不同目标站，排除测试目标自身限流的干扰
   Author :        zhaoqi
   date：          2026/10/05
-------------------------------------------------
"""
__author__ = 'zhaoqi'

import os
import sys
import random
import collections
from concurrent.futures import ThreadPoolExecutor

for k in ("HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy",
          "ALL_PROXY", "all_proxy"):
    os.environ.pop(k, None)

import requests  # noqa: E402

MERGED = os.path.expanduser("~/Downloads/output_merged_unique.txt")
TIMEOUT = 10
WORKERS = 20

TARGETS = {
    "ipip":  ("https://myip.ipip.net", "GET"),
    "qq":    ("https://www.qq.com", "HEAD"),
    "httpbin": ("http://httpbin.org", "HEAD"),
}


def test(proxy, url, method):
    u = "http://" + proxy
    s = requests.Session()
    s.trust_env = False
    try:
        r = s.request(method, url, proxies={"http": u, "https": u},
                      timeout=TIMEOUT, verify=False)
        if r.status_code == 200:
            return "ok"
        return "HTTP %s" % r.status_code
    except Exception as e:
        return type(e).__name__
    finally:
        s.close()


def main():
    target = sys.argv[1] if len(sys.argv) > 1 else "qq"
    n_proxy = int(sys.argv[2]) if len(sys.argv) > 2 else 60
    repeats = int(sys.argv[3]) if len(sys.argv) > 3 else 3
    url, method = TARGETS[target]

    with open(MERGED, "r", encoding="utf-8") as f:
        lines = [x.strip() for x in f if x.strip()]
    sample = random.sample(lines, n_proxy)

    tasks = [(p, url, method) for p in sample for _ in range(repeats)]
    with ThreadPoolExecutor(max_workers=WORKERS) as ex:
        results = list(ex.map(lambda t: test(*t), tasks))

    per = collections.defaultdict(list)
    for (p, _, _), r in zip(tasks, results):
        per[p].append(r)

    dist = collections.Counter()
    reasons = collections.Counter()
    for p, rs in per.items():
        ok = sum(1 for r in rs if r == "ok")
        dist[ok] += 1
        for r in rs:
            if r != "ok":
                reasons[r] += 1

    print("目标=%s (%s %s)  代理数=%d  每代理测 %d 次  总请求=%d"
          % (target, method, url, n_proxy, repeats, len(tasks)))
    print("-" * 55)
    for k in range(repeats, -1, -1):
        bar = "#" * dist[k]
        print("  成功 %d/%d : %3d 条  %s" % (k, repeats, dist[k], bar))
    print("-" * 55)
    total_ok = sum(1 for r in results if r == "ok")
    p = total_ok / len(results)
    print("单次成功率 p = %.3f" % p)
    # 纯随机模型下的理论分布
    import math
    print("纯随机模型理论分布（p=%.3f）:" % p)
    for k in range(repeats, -1, -1):
        c = math.comb(repeats, k) * p ** k * (1 - p) ** (repeats - k)
        print("  成功 %d/%d : 期望 %5.1f 条" % (k, repeats, c * n_proxy))
    print("失败原因:", dict(reasons.most_common()))


if __name__ == "__main__":
    main()
