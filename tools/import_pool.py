# -*- coding: utf-8 -*-
"""
-------------------------------------------------
   File Name：     import_pool.py
   Description :   把校验通过的节点导入代理池（Redis），使用项目自身的 Proxy/ProxyHandler
   Author :        zhaoqi
   date：          2026/10/05
-------------------------------------------------
   用法：
     python tools/import_pool.py --in ~/Downloads/nodes_validated.json [--dry-run]

   只做 hset，不清空池子 —— 现有条目会保留（"补充"语义）。
   写入的 JSON 结构与 helper/proxy.py 的 Proxy.to_json 完全一致。
"""
__author__ = 'zhaoqi'

import os
import sys
import json
import time
import argparse
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from helper.proxy import Proxy            # noqa: E402
from handler.proxyHandler import ProxyHandler  # noqa: E402
from db.redisClient import RedisClient    # noqa: E402
from handler.configHandler import ConfigHandler  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--in", dest="inp",
                    default="~/Downloads/nodes_validated.json")
    ap.add_argument("--source", default="local_list")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    with open(os.path.expanduser(args.inp), encoding="utf-8") as f:
        detail = json.load(f)
    print("待导入节点: %d" % len(detail))

    conf = ConfigHandler()
    # RedisClient.__init__ 会 pop("username")，所以必须显式传 username
    db = RedisClient(host="127.0.0.1", port=6379, db=0,
                     username="", password=None)
    db.changeTable(conf.tableName)

    before = db.getCount()
    print("导入前池子: %s" % before)

    if args.dry_run:
        print("dry-run，不写入")
        return

    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    pipe = db._RedisClient__conn.pipeline(transaction=False)
    n = 0
    for node, item in detail.items():
        p = Proxy(proxy=item["proxy"], https=bool(item.get("https")),
                  source=args.source, check_count=1, last_status=True,
                  last_time=now, fail_count=0)
        pipe.hset(conf.tableName, p.proxy, p.to_json)
        n += 1
        if n % 5000 == 0:
            pipe.execute()
            print("  已写入 %d" % n, flush=True)
    pipe.execute()

    after = db.getCount()
    print("=" * 55)
    print("导入完成: 写入 %d 条" % n)
    print("导入前: %s" % before)
    print("导入后: %s" % after)


if __name__ == "__main__":
    main()
