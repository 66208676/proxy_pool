# -*- coding: utf-8 -*-
"""
-------------------------------------------------
   File Name：     spys.py
   Description :   spys.me 免费代理源（纯文本 ip:port）
   Author :        zhaoqi
   date：          2026/10/11
-------------------------------------------------
   Change Activity:
                   2026/10/11: 新增
-------------------------------------------------
   实测 2026/10/11：国内直连 200 可达，返回纯文本，每行 ip:port。
   默认 enabled=False —— 不进现有调度器，只由 tools/free_pool.py 显式调用，
   避免污染线上 use_proxy 池。
"""
__author__ = 'zhaoqi'

from fetcher.baseFetcher import BaseFetcher
from util.webRequest import WebRequest


class SpysFetcher(BaseFetcher):
    """spys.me 免费代理列表"""

    name = "spys"
    url = "https://spys.me/proxy.txt"
    enabled = False
    overseas = False

    def fetch(self):
        r = WebRequest().get(self.url, timeout=20, retry_time=2)
        for proxy in self.yieldUniqueProxies(self.parseProxiesFromText(r.text)):
            yield proxy


if __name__ == '__main__':
    for p in SpysFetcher().fetch():
        print(p)
