# -*- coding: utf-8 -*-
"""
-------------------------------------------------
   File Name：     proxyscrape.py
   Description :   ProxyScrape 免费代理源（纯文本 ip:port）
   Author :        zhaoqi
   date：          2026/10/11
-------------------------------------------------
   Change Activity:
                   2026/10/11: 新增
-------------------------------------------------
   实测 2026/10/11：国内直连不可达，必须走出口代理（overseas=True）；
   走池内代理请求可返回 553~875 条纯文本 ip:port。
   默认 enabled=False —— 只由 tools/free_pool.py 显式调用。
"""
__author__ = 'zhaoqi'

from fetcher.baseFetcher import BaseFetcher
from util.webRequest import WebRequest


class ProxyScrapeFetcher(BaseFetcher):
    """ProxyScrape 免费代理列表"""

    name = "proxyscrape"
    url = "https://api.proxyscrape.com/"
    enabled = False
    overseas = True

    def fetch(self):
        # protocol=https 实测 2140 条，与 http(553) 合并可提高 https 代理占比
        proxies = []
        for proto in ("http", "https"):
            url = ("https://api.proxyscrape.com/v2/?request=displayproxies"
                   "&protocol=%s&timeout=10000&country=all&anonymity=all&ssl=all" % proto)
            r = WebRequest().get(url, timeout=20, retry_time=2)
            proxies += self.parseProxiesFromText(r.text)
        for proxy in self.yieldUniqueProxies(proxies):
            yield proxy


if __name__ == '__main__':
    for p in ProxyScrapeFetcher().fetch():
        print(p)
