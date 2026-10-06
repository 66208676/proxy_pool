# -*- coding: utf-8 -*-
"""
一次性导入脚本：把本地 proxies.txt 灌入代理池 Redis（use_proxy hash）。
使用项目自带的 Proxy 序列化，保证格式与 proxy_pool 读取一致。
"""
import sys
import re

sys.path.insert(0, r"D:/myWorkspace/proxy_pool")
from helper.proxy import Proxy  # noqa: E402
import redis  # noqa: E402

LINE_REGEX = re.compile(
    r"^(?:https?://)?"
    r"(?:(?P<auth>[^/@\s]+:[^/@\s]+)@)?"
    r"(?P<ip>\d{1,3}(?:\.\d{1,3}){3})"
    r":(?P<port>\d{1,5})$"
)

SRC = r"D:/Program Files/Downloads/proxies.txt"
TABLE = "use_proxy"
HOST, PORT, PW, DB = "127.0.0.1", 6379, "123456", 0


def main():
    r = redis.Redis(host=HOST, port=PORT, password=PW, db=DB,
                    decode_responses=True, protocol=2)
    before = r.hlen(TABLE)

    seen = set()
    pipe = r.pipeline(transaction=False)
    batch = 0
    imported = 0
    skipped = 0

    with open(SRC, "r", encoding="utf-8", errors="ignore") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            m = LINE_REGEX.match(line)
            if not m:
                skipped += 1
                continue
            auth = m.group("auth")
            prefix = ("%s@" % auth) if auth else ""
            key = "%s%s:%s" % (prefix, m.group("ip"), m.group("port"))
            if key in seen:
                continue
            seen.add(key)
            p = Proxy(proxy=key, source="import", https=False)
            pipe.hset(TABLE, key, p.to_json)
            batch += 1
            imported += 1
            if batch >= 2000:
                pipe.execute()
                pipe = r.pipeline(transaction=False)
                batch = 0
    if batch:
        pipe.execute()

    after = r.hlen(TABLE)
    print("导入前 use_proxy 数量:", before)
    print("本次解析并导入(去重后唯一):", imported)
    print("无法解析跳过:", skipped)
    print("导入后 use_proxy 数量:", after)


if __name__ == "__main__":
    main()
