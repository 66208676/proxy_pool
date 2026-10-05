# -*- coding: utf-8 -*-
"""
-------------------------------------------------
   File Name：     dedupe_to_nodes.py
   Description :   把 976 个 output 文件收敛成"唯一节点 + 候选账号列表"
   Author :        zhaoqi
   date：          2026/10/05
-------------------------------------------------
   输入：~/Downloads/output/*.txt
   输出：~/Downloads/nodes_candidates.json
         {"ip:port": ["auth1", "auth2", ...]}  每个节点最多保留 MAX_CAND 个候选账号
"""
__author__ = 'zhaoqi'

import os
import re
import glob
import json
import random
from collections import defaultdict

SRC_DIR = os.path.expanduser("~/Downloads/output")
OUT = os.path.expanduser("~/Downloads/nodes_candidates.json")
MAX_CAND = 8          # 每个节点保留的候选账号上限
SEED = 20261005       # 固定随机种子，保证可复现

LINE_REGEX = re.compile(
    r"^(?:https?://)?(?P<auth>[^/@\s]+:[^/@\s]+)@"
    r"(?P<ip>\d{1,3}(?:\.\d{1,3}){3}):(?P<port>\d{1,5})$"
)


def main():
    files = sorted(glob.glob(os.path.join(SRC_DIR, "*.txt")))
    print("扫描 %d 个文件" % len(files))

    node_auths = defaultdict(set)
    total = 0
    bad = 0
    for i, path in enumerate(files, 1):
        with open(path, encoding="utf-8", errors="ignore") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                total += 1
                m = LINE_REGEX.match(line)
                if not m:
                    bad += 1
                    continue
                node_auths["%s:%s" % (m.group("ip"), m.group("port"))].add(
                    m.group("auth"))
        if i % 200 == 0:
            print("  %d/%d 文件, 累计节点 %d" % (i, len(files), len(node_auths)))

    rnd = random.Random(SEED)
    result = {}
    cand_hist = defaultdict(int)
    for node, auths in node_auths.items():
        cands = sorted(auths)
        rnd.shuffle(cands)
        result[node] = cands[:MAX_CAND]
        cand_hist[len(cands)] += 1

    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(result, f)

    print("=" * 55)
    print("原始行数        : %d" % total)
    print("解析失败        : %d" % bad)
    print("唯一节点 ip:port: %d" % len(result))
    print("候选账号数分布  :", dict(sorted(cand_hist.items())[:20]))
    print("已写出          : %s (%.1f MB)"
          % (OUT, os.path.getsize(OUT) / 1024 / 1024))


if __name__ == "__main__":
    main()
