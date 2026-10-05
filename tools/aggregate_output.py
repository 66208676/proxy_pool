# -*- coding: utf-8 -*-
"""
-------------------------------------------------
   File Name：     aggregate_output.py
   Description :   聚合 ~/Downloads/output 下的代理清单，去重并与现有池子比对
   Author :        zhaoqi
   date：          2026/10/05
-------------------------------------------------
   Change Activity:
                   2026/10/05: 新增
-------------------------------------------------
"""
__author__ = 'zhaoqi'

import os
import re
import sys
import glob

SRC_DIR = os.path.expanduser("~/Downloads/output")
OUT_FILE = os.path.expanduser("~/Downloads/output_merged_unique.txt")

LINE_REGEX = re.compile(
    r"^(?:https?://)?"
    r"(?:(?P<auth>[^/@\s]+:[^/@\s]+)@)?"
    r"(?P<ip>\d{1,3}(?:\.\d{1,3}){3})"
    r":(?P<port>\d{1,5})$"
)


def main():
    files = sorted(glob.glob(os.path.join(SRC_DIR, "*.txt")))
    print("文件数: %d" % len(files))

    seen = set()
    total_lines = 0
    bad_lines = 0
    dup_in_file = 0
    accounts = set()
    ip_port_set = set()
    per_file_unique = []

    for i, path in enumerate(files, 1):
        local = set()
        with open(path, "r", encoding="utf-8", errors="ignore") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                total_lines += 1
                m = LINE_REGEX.match(line)
                if not m:
                    bad_lines += 1
                    continue
                auth = m.group("auth")
                key = "%s@%s:%s" % (auth, m.group("ip"), m.group("port")) if auth \
                    else "%s:%s" % (m.group("ip"), m.group("port"))
                if key in local:
                    dup_in_file += 1
                    continue
                local.add(key)
                seen.add(key)
                ip_port_set.add("%s:%s" % (m.group("ip"), m.group("port")))
                if auth:
                    accounts.add(auth)
        per_file_unique.append(len(local))
        if i % 100 == 0:
            print("  已处理 %d/%d 文件, 累计唯一 %d" % (i, len(files), len(seen)))

    print("=" * 50)
    print("原始行数        : %d" % total_lines)
    print("无法解析的行    : %d" % bad_lines)
    print("文件内重复行    : %d" % dup_in_file)
    print("全局唯一代理数  : %d" % len(seen))
    print("唯一 ip:port 数 : %d" % len(ip_port_set))
    print("不同账号数      : %d" % len(accounts))
    print("单文件唯一均值  : %.1f" % (sum(per_file_unique) / len(per_file_unique)))

    with open(OUT_FILE, "w", encoding="utf-8") as f:
        for key in sorted(seen):
            f.write(key + "\n")
    print("已写出: %s" % OUT_FILE)

    # 与现有池子比对
    try:
        import redis
        r = redis.Redis(host="127.0.0.1", port=6379, db=0,
                        decode_responses=True, protocol=2,
                        socket_timeout=10)
        existing = set(r.hkeys("use_proxy"))
        print("=" * 50)
        print("现有池子条目    : %d" % len(existing))
        inter = seen & existing
        print("与池子交集      : %d" % len(inter))
        print("池子中已有但不在本次清单: %d" % len(existing - seen))
        print("本次新增(不在池子)      : %d" % len(seen - existing))
    except Exception as e:
        print("读取 Redis 失败: %s" % e)


if __name__ == "__main__":
    main()
