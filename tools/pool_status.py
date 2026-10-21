# -*- coding: utf-8 -*-
"""
-------------------------------------------------
   File Name：     pool_status.py
   Description :   代理池状态与最近抓取进度一览（只读，不修改任何数据）
   Author :        zhaoqi
   date：          2026/10/11
-------------------------------------------------
   Change Activity:
                   2026/10/11: 新增
-------------------------------------------------
用法：
  python tools/pool_status.py
输出：池子总量/来源分布、最近抓取产物、最近一次运行日志的进度摘要。
"""
__author__ = 'zhaoqi'

import os
import sys
import json
import glob
import urllib.request
from datetime import datetime

sys.path.insert(0, os.path.abspath(os.path.join(
    os.path.dirname(os.path.abspath(__file__)), '..')))

API = os.environ.get("POOL_API", "http://127.0.0.1:5010")
LOG_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'log')


def _open(url, timeout=6):
    """绕过本机环境代理直连本地 API"""
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    return opener.open(url, timeout=timeout).read().decode("utf-8")


def pool_summary():
    try:
        data = json.loads(_open(API.rstrip("/") + "/count/", timeout=6))
    except Exception as e:
        return "API 不可用(%s)：%s 未响应" % (type(e).__name__, API)
    total = data.get("count", 0)
    src = data.get("source", {}) or {}
    lines = ["代理池 %s" % API,
             "  总数: %d    https: %s" % (total, data.get("http_type", {}))]
    if src:
        top = sorted(src.items(), key=lambda kv: kv[1], reverse=True)[:10]
        paid = src.get("import", 0)
        free = total - paid
        lines.append("  付费(import): %d    免费来源新增: %d" % (paid, free))
        lines.append("  来源 Top10: " + ", ".join("%s=%d" % kv for kv in top))
    return "\n".join(lines)


def last_outputs(n=3):
    files = sorted(glob.glob(os.path.join(LOG_DIR, "free_pool_*.txt")),
                   key=os.path.getmtime, reverse=True)[:n]
    if not files:
        return "最近抓取产物: 无"
    out = ["最近抓取产物(最新 %d 个):" % len(files)]
    for f in files:
        with open(f, encoding="utf-8", errors="ignore") as fh:
            cnt = sum(1 for _ in fh if _.strip())
        mtime = datetime.fromtimestamp(os.path.getmtime(f)).strftime("%m-%d %H:%M:%S")
        out.append("  %s  %-34s %d 条" % (mtime, os.path.basename(f), cnt))
    return "\n".join(out)


def run_progress(tail_lines=12):
    path = os.path.join(LOG_DIR, "free_pool_run.log")
    if not os.path.exists(path):
        return "运行日志: 无"
    with open(path, encoding="utf-8", errors="ignore") as f:
        lines = [x.rstrip() for x in f if x.strip()]
    keep = [x for x in lines if "webRequest.py" not in x][-tail_lines:]
    mtime = datetime.fromtimestamp(os.path.getmtime(path)).strftime("%m-%d %H:%M:%S")
    head = "最近一次抓取进度(日志更新 %s):" % mtime
    return "\n".join([head] + ["  " + x for x in keep])


def main():
    print("=" * 62)
    print("代理池状态  %s" % datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
    print("=" * 62)
    print(pool_summary())
    print()
    print(last_outputs())
    print()
    print(run_progress())


if __name__ == "__main__":
    main()
