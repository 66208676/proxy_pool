# -*- coding: utf-8 -*-
"""
-------------------------------------------------
   File Name：     local_list.py
   Description :   本地代理清单源（支持带认证的代理）
   Author :        zhaoqi
   date：          2026/10/05
-------------------------------------------------
   Change Activity:
                   2026/10/05: 新增，用于把本地购买的代理清单接入代理池
-------------------------------------------------
   支持的行格式（每行一个，`#` 开头为注释）：
       http://user:pass@ip:port
       https://user:pass@ip:port
       user:pass@ip:port
       ip:port
   统一归一化为 `user:pass@ip:port`（与 helper/validator.py 的 IP_REGEX 一致）。

   清单路径优先取环境变量 LOCAL_PROXY_FILE，未设置时用 DEFAULT_PROXY_FILE。
"""
__author__ = 'zhaoqi'

import os
import re

from fetcher.baseFetcher import BaseFetcher

# 默认清单文件路径（可通过环境变量 LOCAL_PROXY_FILE 覆盖）
#
# 2026/10/05：清单已合并扩容。原文件 all_accounts_proxies_20261004.txt（3,400 条）
# 与本次从 ~/Downloads/output 聚合校验出的节点（约 4 万条）合并为下面这个文件。
# 之所以要让 fetcher 指向合并后的文件，是因为 Redis 未开持久化
# （启动参数带 --save "" --appendonly no），Redis 一重启池子就空了，
# 只有靠 fetcher 重新灌入。若仍指向旧文件，扩容进来的 4 万条会永久丢失。
DEFAULT_PROXY_FILE = os.path.expanduser(
    "~/Downloads/all_accounts_proxies_20261005.txt")

# 与 helper/validator.py 的 IP_REGEX 保持兼容，额外允许 http(s):// 前缀
LINE_REGEX = re.compile(
    r"^(?:https?://)?"
    r"(?:(?P<auth>[^/@\s]+:[^/@\s]+)@)?"
    r"(?P<ip>\d{1,3}(?:\.\d{1,3}){3})"
    r":(?P<port>\d{1,5})$"
)


class LocalListFetcher(BaseFetcher):
    """本地代理清单文件"""

    name = "local_list"
    url = "file://" + DEFAULT_PROXY_FILE

    @property
    def file_path(self):
        return os.path.expanduser(
            os.environ.get("LOCAL_PROXY_FILE", DEFAULT_PROXY_FILE))

    def fetch(self):
        path = self.file_path
        if not os.path.exists(path):
            raise FileNotFoundError("本地代理清单不存在: %s" % path)

        proxies = []
        skipped = 0
        with open(path, "r", encoding="utf-8", errors="ignore") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                m = LINE_REGEX.match(line)
                if not m:
                    skipped += 1
                    continue
                auth = m.group("auth")
                prefix = "%s@" % auth if auth else ""
                proxies.append("%s%s:%s" % (prefix, m.group("ip"), m.group("port")))

        if skipped:
            print("[local_list] 跳过无法解析的行: %d" % skipped)

        for proxy in self.yieldUniqueProxies(proxies):
            yield proxy


if __name__ == '__main__':
    count = 0
    for p in LocalListFetcher().fetch():
        count += 1
        if count <= 3:
            print(p)
    print("总计: %d" % count)
