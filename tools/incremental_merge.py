# -*- coding: utf-8 -*-
"""
-------------------------------------------------
   File Name：     incremental_merge.py
   Description :   增量补充代理池：只补"池子里还没有的节点"，自动去重 + 校验 + 入库 + 落源文件
   Author :        zhaoqi
   date：          2026/10/05
-------------------------------------------------
   用法：
     python tools/incremental_merge.py --in <新清单> [--in <新清单2> ...]
                                       [--dry-run]
                                       [--force-add-redundant]

   默认策略（与"每个节点只留一个可用账号"的约定一致）：
     节点已存在于池子或源文件  -> 跳过（记为 redundant）
     节点是全新的              -> 校验通过后入库，并追加进源文件

   --force-add-redundant：把"节点已存在但整串是新的"的条目也当备份账号加进去。
   注意：实测这些备份账号与现有账号在同一节点上完全等价（80/80 vs 80/80，
   零救回），加进去只会让节点重复，一般不需要。
"""
__author__ = 'zhaoqi'

import os
import re
import sys
import json
import argparse
from collections import defaultdict

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import asyncio  # noqa: E402
import redis     # noqa: E402

from validate_nodes import check_batch, HTTP_URL, HTTPS_URL  # noqa: E402
from helper.proxy import Proxy                                # noqa: E402
from db.redisClient import RedisClient                        # noqa: E402
from handler.configHandler import ConfigHandler               # noqa: E402

LINE = re.compile(
    r"^(?:https?://)?(?P<auth>[^/@\s]+:[^/@\s]+)@"
    r"(?P<ip>\d{1,3}(?:\.\d{1,3}){3}):(?P<port>\d{1,5})$")

SRC_FILE = os.path.expanduser("~/Downloads/all_accounts_proxies_20261005.txt")


def parse_files(paths):
    """解析清单文件 -> {node: [proxy, ...]}（保留所有账号，节点内去重）"""
    nodes = defaultdict(list)
    total = bad = 0
    for path in paths:
        with open(os.path.expanduser(path), encoding="utf-8", errors="ignore") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                total += 1
                m = LINE.match(line)
                if not m:
                    bad += 1
                    continue
                node = "%s:%s" % (m.group("ip"), m.group("port"))
                proxy = "%s@%s" % (m.group("auth"), node)
                if proxy not in nodes[node]:
                    nodes[node].append(proxy)
    return nodes, total, bad


def load_known():
    """返回 (池子已有整串集合, 源文件已有整串集合)"""
    r = redis.Redis(host="127.0.0.1", port=6379, db=0, decode_responses=True,
                    protocol=2, socket_timeout=10)
    pool = set(r.hkeys("use_proxy"))
    src = set()
    if os.path.exists(SRC_FILE):
        with open(SRC_FILE, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    src.add(line.replace("http://", "").replace("https://", ""))
    return pool, src


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--in", dest="inputs", action="append", required=True)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--force-add-redundant", action="store_true")
    ap.add_argument("--rounds", type=int, default=5)
    ap.add_argument("--attempts", type=int, default=2)
    ap.add_argument("--concurrency", type=int, default=300)
    ap.add_argument("--timeout", type=float, default=6)
    ap.add_argument("--skip-https", action="store_true")
    args = ap.parse_args()

    cand, total, bad = parse_files(args.inputs)
    print("输入文件 %d 个，行数 %d，解析失败 %d" % (len(args.inputs), total, bad))
    print("唯一节点 %d 个" % len(cand))

    pool, src = load_known()
    pool_nodes = {k.split("@")[-1] for k in pool}
    src_nodes = {k.split("@")[-1] for k in src}
    known_nodes = pool_nodes | src_nodes
    print("池子 %d 条 / %d 节点；源文件 %d 条 / %d 节点"
          % (len(pool), len(pool_nodes), len(src), len(src_nodes)))

    new_nodes, redundant = {}, {}
    for node, proxies in cand.items():
        if node in known_nodes:
            redundant[node] = proxies
        else:
            new_nodes[node] = proxies

    print("-" * 55)
    print("节点已存在（跳过）: %d" % len(redundant))
    print("节点是全新的      : %d" % len(new_nodes))

    if args.force_add_redundant:
        # 只补"整串在池子和源文件里都没有"的，避免真正重复的行
        extra = 0
        for node, proxies in redundant.items():
            fresh = [p for p in proxies if p not in pool and p not in src]
            if fresh:
                new_nodes.setdefault(node, []).extend(fresh)
                extra += len(fresh)
        print("--force-add-redundant: 额外纳入 %d 条备份账号" % extra)

    if not new_nodes:
        print("\n没有需要补充的节点，池子与源文件均无需改动。")
        return

    # ---------- 校验：每个节点逐轮换账号 ----------
    resolved = {}
    pending = list(new_nodes.keys())
    for rnd in range(args.rounds):
        batch = []
        for node in pending:
            cs = new_nodes[node]
            if rnd < len(cs):
                batch.append(cs[rnd])
        if not batch:
            break
        print("\n== 校验第 %d 轮: %d 条 ==" % (rnd + 1, len(batch)), flush=True)
        passed = asyncio.run(check_batch(batch, HTTP_URL[0], HTTP_URL[1],
                                         args.timeout, args.concurrency,
                                         args.attempts, "http"))
        for p in passed:
            resolved[p.split("@", 1)[1]] = p
        pending = [n for n in new_nodes if n not in resolved]
        if not pending:
            break

    print("\n校验完成: 可用 %d / %d = %.1f%%"
          % (len(resolved), len(new_nodes),
             100.0 * len(resolved) / max(len(new_nodes), 1)))

    # ---------- https 标记 ----------
    https_ok = set()
    if not args.skip_https and resolved:
        print("== https 校验: %d 条 ==" % len(resolved), flush=True)
        https_ok = asyncio.run(check_batch(list(resolved.values()),
                                           HTTPS_URL[0], HTTPS_URL[1],
                                           args.timeout + 2, args.concurrency,
                                           args.attempts, "https"))
        print("支持 https: %d / %d" % (len(https_ok), len(resolved)))

    if args.dry_run:
        print("\ndry-run：不写库、不改源文件")
        return

    # ---------- 入库 ----------
    conf = ConfigHandler()
    db = RedisClient(host="127.0.0.1", port=6379, db=0,
                     username="", password=None)
    db.changeTable(conf.tableName)
    before = db.getCount()

    from datetime import datetime
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    conn = db._RedisClient__conn
    pipe = conn.pipeline(transaction=False)
    for i, (node, p) in enumerate(sorted(resolved.items()), 1):
        obj = Proxy(proxy=p, https=(p in https_ok), source="local_list",
                    check_count=1, last_status=True, last_time=now,
                    fail_count=0)
        pipe.hset(conf.tableName, obj.proxy, obj.to_json)
        if i % 5000 == 0:
            pipe.execute()
    pipe.execute()

    # ---------- 追加进源文件 ----------
    with open(SRC_FILE, "a", encoding="utf-8") as f:
        for node, p in sorted(resolved.items()):
            f.write("http://" + p + "\n")

    after = db.getCount()
    print("=" * 55)
    print("入库: %d 条（跳过冗余节点 %d 个）" % (len(resolved), len(redundant)))
    print("池子: %s -> %s" % (before, after))
    print("源文件已追加: %s" % SRC_FILE)


if __name__ == "__main__":
    main()
