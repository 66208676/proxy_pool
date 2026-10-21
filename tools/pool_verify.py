# -*- coding: utf-8 -*-
"""
-------------------------------------------------
   File Name：     pool_verify.py
   Description :   池内代理复检（独立进程）
                   读 Redis use_proxy → 异步并发探活 → 更新状态 / 剔除失效
                   不依赖常驻调度器，不重启任何服务，随起随退。
   Author :        zhaoqi
   date：          2026/10/12
-------------------------------------------------
   背景：
     原项目把「复检」放在 proxyPool.py schedule 常驻进程里（CHECK_THREAD_COUNT=20 同步线程）。
     该进程一旦退出，池子就只增不减（free_pool.py 还在补，死代理却没人清）。
     本脚本把复检拆成一次性进程，和采集一样由外部定时触发，池子不再依赖常驻进程。

   安全闸门（防止校验目标抽风误杀整池）：
     1. 异常闸门：总失败率 > --abort-fail-rate(默认 0.90) 且 Timeout 占比 > 0.80
        → 判定校验目标异常，本轮不删除任何代理，只报告。
     2. 比例闸门：单轮删除量不超过总量的 --max-del-ratio(默认 0.25)，超出按 fail_count 降序截断。
     3. --dry-run：只报告，不写 Redis。
     4. 只做「存活性」判定，不重算 https 标记（避免改动 /get/?type=https 的可用集）。

   用法：
     python tools/pool_verify.py                      # 全量复检
     python tools/pool_verify.py --limit 1000         # 抽样复检（控制耗时）
     python tools/pool_verify.py --dry-run            # 只看报告，不写库
     python tools/pool_verify.py --target ipip        # 换校验目标（国内快）
-------------------------------------------------
"""
__author__ = 'zhaoqi'

import os
import sys
import time
import json
import random
import asyncio
import argparse
import collections
from datetime import datetime

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tools"))

# 本机有环境透明代理，异步校验必须绕开
for k in ("HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy",
          "ALL_PROXY", "all_proxy"):
    os.environ.pop(k, None)

import fast_check                      # noqa: E402  复用其异步校验器
from helper.proxy import Proxy          # noqa: E402
from handler.configHandler import ConfigHandler  # noqa: E402


def upd(db, proxy_obj):
    """回写代理属性。
    注意：DbClient.update(key, value) 的签名与底层 redisClient.update(proxy_obj) 不一致，
    直接调工厂方法会 TypeError，这里走底层客户端。"""
    try:
        return db.client.update(proxy_obj)
    except AttributeError:
        return db.update(proxy_obj)


def load_pool():
    """从 Redis use_proxy 读出全部代理，返回 {proxy_str: Proxy}"""
    from db.dbClient import DbClient
    db = DbClient(ConfigHandler().dbConn)
    # DbClient 建好后默认表名为空，必须显式切换（Singleton，只影响本进程）
    db.changeTable(ConfigHandler().tableName)
    items = db.getAll(https=False) or []
    out = {}
    for raw in items:
        try:
            p = Proxy.createFromJson(raw)
        except Exception:
            continue
        if p.proxy:
            out[p.proxy] = p
    return out, db


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=0, help="抽样复检条数，0=全部")
    ap.add_argument("--target", default="httpbin", choices=list(fast_check.TARGETS))
    ap.add_argument("--concurrency", type=int, default=300)
    ap.add_argument("--timeout", type=float, default=6)
    ap.add_argument("--attempts", type=int, default=2, help="每条最多探测轮数，任一轮通过即存活")
    ap.add_argument("--max-fail", type=int, default=0,
                    help="累计失败超过该值才删除，0=沿用 setting.py 的 MAX_FAIL_COUNT")
    ap.add_argument("--max-del-ratio", type=float, default=0.25,
                    help="单轮删除量占比上限，超过则截断，防误杀")
    ap.add_argument("--abort-fail-rate", type=float, default=0.90,
                    help="总失败率超过该值且 Timeout 占主导时，判定目标异常，不删任何代理")
    ap.add_argument("--dry-run", action="store_true", help="只报告，不写 Redis")
    ap.add_argument("--seed", type=int, default=0)
    args = ap.parse_args()

    conf = ConfigHandler()
    max_fail = args.max_fail or conf.maxFailCount

    pool, db = load_pool()
    total = len(pool)
    if total == 0:
        print("池子为空，无需复检")
        return

    targets = list(pool.keys())
    if args.limit and args.limit < total:
        random.seed(args.seed)
        targets = random.sample(targets, args.limit)
    print("池内总数 %d 条，本轮复检 %d 条，目标 %s，并发 %d，%d 轮，超时 %.1fs"
          % (total, len(targets), args.target, args.concurrency, args.attempts, args.timeout))

    url, method = fast_check.TARGETS[args.target]
    t0 = time.time()
    results = asyncio.run(fast_check.run(targets, url, method, args.timeout,
                                         args.concurrency, args.attempts))
    dt = time.time() - t0

    alive, dead = [], []
    for p in targets:
        (alive if "ok" in results[p] else dead).append(p)

    reasons = collections.Counter(r for p in dead for r in results[p])
    fail_rate = len(dead) / float(len(targets))
    timeout_share = reasons.get("Timeout", 0) / float(max(len(dead), 1))

    print("=" * 58)
    print("耗时 %.1fs" % dt)
    print("存活 %d / %d = %.1f%%" % (len(alive), len(targets),
                                     100.0 * len(alive) / max(len(targets), 1)))
    print("失败原因:", dict(reasons.most_common(6)))

    # ---- 闸门 1：校验目标异常，不删 ----
    if dead and fail_rate > args.abort_fail_rate and timeout_share > 0.8:
        print("\n[闸门] 失败率 %.1f%% 且 Timeout 占 %.1f%% —— 判定校验目标(%s)异常，"
              "本轮不删除任何代理。建议换 --target 或降 --concurrency 后重试。"
              % (fail_rate * 100, timeout_share * 100, args.target))
        if not args.dry_run:
            print("[闸门] 仍将更新存活代理的 last_time/last_status（无损操作）")
            _touch(db, pool, alive, datetime.now())
        return

    # ---- 计算删除集 ----
    to_del = []
    for p in dead:
        obj = pool[p]
        obj.fail_count += 1
        obj.check_count += 1
        obj.last_status = False
        obj.last_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        if obj.fail_count > max_fail:
            to_del.append(p)

    # ---- 闸门 2：删除比例上限 ----
    cap = int(total * args.max_del_ratio)
    truncated = False
    if len(to_del) > cap:
        to_del.sort(key=lambda p: pool[p].fail_count, reverse=True)
        to_del = to_del[:cap]
        truncated = True
        print("\n[闸门] 待删数量超过总量的 %.0f%%（上限 %d 条），已按 fail_count 降序截断"
              % (args.max_del_ratio * 100, cap))

    print("本轮判定删除 %d 条（累计失败 > %d），存活更新 %d 条"
          % (len(to_del) if not truncated else len(to_del), max_fail, len(alive) + len(dead)))

    if args.dry_run:
        print("\n[dry-run] 未写 Redis。样例待删: %s" % to_del[:5])
        return

    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    # 存活：清零失败计数
    for p in alive:
        obj = pool[p]
        obj.check_count += 1
        obj.last_status = True
        obj.last_time = now
        if obj.fail_count > 0:
            obj.fail_count -= 1
        upd(db, obj)
    # 失败但未达阈值：回写累计次数
    for p in dead:
        if p not in to_del:
            upd(db, pool[p])
    # 删除
    for p in to_del:
        db.delete(p)

    after = db.getCount()
    print("[redis] 删除 %d 条，更新 %d 条，当前池子 %s" % (len(to_del), len(targets), after))


def _touch(db, pool, alive, now_dt):
    """目标异常时只更新存活代理的时间戳，不做删除"""
    now = now_dt.strftime("%Y-%m-%d %H:%M:%S")
    for p in alive:
        obj = pool[p]
        obj.last_status = True
        obj.last_time = now
        if obj.fail_count > 0:
            obj.fail_count -= 1
        upd(db, obj)
    print("[redis] 已更新 %d 条存活代理的时间戳" % len(alive))


if __name__ == "__main__":
    main()
