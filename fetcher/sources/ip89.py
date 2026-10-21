# -*- coding: utf-8 -*-
"""
-------------------------------------------------
   File Name：     ip89.py
   Description :   89免费代理代理源
   Author :        JHao
   date：          2026/5/31
-------------------------------------------------
   Change Activity:
                   2026/05/31:
-------------------------------------------------
"""
__author__ = 'JHao'

import re

from fetcher.baseFetcher import BaseFetcher
from util.webRequest import WebRequest


class Ip89Fetcher(BaseFetcher):
    """89免费代理 https://www.89ip.cn/"""

    name = "ip89"
    url = "https://www.89ip.cn/"
    overseas = False

    # 每页约 40 条，抓多页可线性提高产量（实测 index_1..5 均可达）
    PAGES = 5
    PATTERN = re.compile(
        r'<td.*?>[\s\S]*?(\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3})[\s\S]*?</td>'
        r'[\s\S]*?<td.*?>[\s\S]*?(\d+)[\s\S]*?</td>')

    def fetch(self, pages=None):
        pages = pages or self.PAGES
        found = []
        for i in range(1, pages + 1):
            r = WebRequest().get("https://www.89ip.cn/index_%d.html" % i, timeout=15)
            found += [':'.join(m) for m in self.PATTERN.findall(r.text or "")]
        for proxy in self.yieldUniqueProxies(found):
            yield proxy


if __name__ == '__main__':
    for proxy in Ip89Fetcher().fetch():
        print(proxy)