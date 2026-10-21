# -*- coding: utf-8 -*-
"""
-------------------------------------------------
   File Name：     mzyui.py
   Description :   mzyui/proxy-list（走 jsDelivr CDN，超大量聚合源）
   Author :        zhaoqi
   date：          2026/10/11
-------------------------------------------------
   Change Activity:
                   2026/10/11: 新增
-------------------------------------------------
   实测 2026/10/11：jsDelivr CDN 直连 200，http.txt **64236 条**（数量最大）。
   该源是聚合+去重，并非全部实时连接测试，可用率偏低，定位为"广撒网备用源"。
   因数量远超单轮校验预算，实际入库量由 free_pool.py 的 --max-check 抽样控制。
   默认 enabled=False —— 只由 tools/free_pool.py 显式调用。
"""
__author__ = 'zhaoqi'

from fetcher.baseFetcher import BaseFetcher
from util.webRequest import WebRequest


class MzyuiFetcher(BaseFetcher):
    """mzyui 聚合代理列表"""

    name = "mzyui"
    url = "https://github.com/mzyui/proxy-list"
    enabled = False
    overseas = False

    URLS = ("https://cdn.jsdelivr.net/gh/mzyui/proxy-list@main/http.txt",)

    def fetch(self):
        proxies = []
        for url in self.URLS:
            # 文件约 1.5MB(6.4万行)，timeout 需放宽，否则拿到空响应
            r = WebRequest().get(url, timeout=45, retry_time=3)
            proxies += self.parseProxiesFromText(r.text)
        for proxy in self.yieldUniqueProxies(proxies):
            yield proxy


if __name__ == '__main__':
    print("mzyui", sum(1 for _ in MzyuiFetcher().fetch()), "条")
