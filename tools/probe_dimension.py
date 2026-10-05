# -*- coding: utf-8 -*-
"""
-------------------------------------------------
   File Name：     probe_dimension.py
   Description :   判断代理失效是"IP维度"还是"账号维度"
                  A: 固定 ip:port，换不同账号 -> 结果是否一致
                  B: 固定账号，换不同 IP     -> 结果分布
                  C: 同一账号在多次采集文件中绑定的 IP 是否稳定
   Author :        zhaoqi
   date：          2026/10/05
-------------------------------------------------
"""
__author__ = 'zhaoqi'

import os
import glob
import random
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor

for k in ("HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy",
          "ALL_PROXY", "all_proxy"):
    os.environ.pop(k, None)

import requests  # noqa: E402

SRC_DIR = os.path.expanduser("~/Downloads/output")
MERGED = os.path.expanduser("~/Downloads/output_merged_unique.txt")
ECHO = "https://myip.ipip.net"
TIMEOUT = 12
WORKERS = 20


def test(proxy):
    url = "http://" + proxy
    s = requests.Session()
    s.trust_env = False
    try:
        r = s.get(ECHO, proxies={"http": url, "https": url},
                  timeout=TIMEOUT, verify=False)
        return r.status_code == 200
    except Exception:
        return False
    finally:
        s.close()


def run(sample, label):
    with ThreadPoolExecutor(max_workers=WORKERS) as ex:
        res = list(ex.map(test, sample))
    ok = sum(res)
    print("%s: %d/%d 可用 (%.0f%%)" % (label, ok, len(res), 100.0 * ok / len(res)))
    return res


def main():
    with open(MERGED, "r", encoding="utf-8") as f:
        lines = [x.strip() for x in f if x.strip()]

    by_ip = defaultdict(list)
    by_auth = defaultdict(list)
    for l in lines:
        auth, ipport = l.split("@")
        by_ip[ipport].append(l)
        by_auth[auth].append(l)

    print("唯一 ip:port=%d, 唯一账号=%d" % (len(by_ip), len(by_auth)))

    # --- A: 固定 ip:port，换 12 个不同账号 ---
    print("\n[A] 固定 ip:port，换不同账号（判断 IP 维度）")
    ips = random.sample([k for k, v in by_ip.items() if len(v) >= 12], 6)
    sample = []
    groups = []
    for ip in ips:
        g = random.sample(by_ip[ip], 12)
        groups.append((ip, g))
        sample.extend(g)
    res = run(sample, "  A 合计")
    for (ip, g), _ in zip(groups, [0]):
        sub = res[sum(len(x[1]) for x in groups[:groups.index((ip, g))]):][:len(g)]
        print("   %-22s -> %d/12 可用" % (ip, sum(sub)))

    # --- B: 固定账号，换 12 个不同 IP ---
    print("\n[B] 固定账号，换不同 IP（判断账号维度）")
    auths = random.sample([k for k, v in by_auth.items() if len(v) >= 12], 6)
    sample = []
    groups = []
    for a in auths:
        g = random.sample(by_auth[a], 12)
        groups.append((a, g))
        sample.extend(g)
    res = run(sample, "  B 合计")
    off = 0
    for a, g in groups:
        sub = res[off:off + len(g)]
        off += len(g)
        print("   %-30s -> %d/12 可用" % (a, sum(sub)))

    # --- C: 账号与 IP 的绑定是否跨文件稳定 ---
    print("\n[C] 账号->IP 绑定跨文件稳定性")
    files = sorted(glob.glob(os.path.join(SRC_DIR, "*.txt")))[:3]
    maps = []
    for p in files:
        d = defaultdict(set)
        with open(p, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                auth, ipport = line.replace("http://", "").split("@")
                d[auth].add(ipport)
        maps.append(d)
    common = set(maps[0]) & set(maps[1]) & set(maps[2])
    print("   文件1账号数=%d 文件2=%d 文件3=%d 三者共有账号=%d"
          % (len(maps[0]), len(maps[1]), len(maps[2]), len(common)))
    same, diff = 0, 0
    for a in list(common)[:200]:
        if maps[0][a] == maps[1][a] == maps[2][a]:
            same += 1
        else:
            diff += 1
    print("   200 个共有账号中，三文件 IP 集合完全相同=%d 不同=%d" % (same, diff))
    if common:
        a = list(common)[0]
        print("   示例账号 %s: f1=%d 个IP, f2=%d, f3=%d, 交集=%d"
              % (a, len(maps[0][a]), len(maps[1][a]), len(maps[2][a]),
                 len(maps[0][a] & maps[1][a] & maps[2][a])))


if __name__ == "__main__":
    main()
