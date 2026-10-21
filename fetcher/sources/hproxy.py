# -*- coding: utf-8 -*-
"""
-------------------------------------------------
   File Name：     hproxy.py
   Description :   HProxy 官方免费代理 API（无需 key，返回已验证代理）
   Author :        zhaoqi
   date：          2026/10/11
-------------------------------------------------
   Change Activity:
                   2026/10/11: 新增
-------------------------------------------------
   API: https://hproxy.com/api/proxy-list
     format=txt           一行一个 ip:port（默认）
     protocol=http,https  逗号分隔，匹配任一协议
     min_uptime_pct=0-100 只看历史可用率不低于该值的代理
     max_latency_ms       只看延迟不高于该值的代理
     limit/offset         分页；不传 limit 则一次返回全部匹配项
   响应头 X-Total-Available 为该过滤条件下的总条数。

   实测 2026/10/11：国内直连 200，protocol=http,https 返回 2570 条，
   且 HProxy 自身持续验证，可用率显著高于普通免费源。
   默认 enabled=False —— 只由 tools/free_pool.py 显式调用。
"""
__author__ = 'zhaoqi'

from fetcher.baseFetcher import BaseFetcher
from util.webRequest import WebRequest


class HProxyFetcher(BaseFetcher):
    """HProxy 免费代理列表 API"""

    name = "hproxy"
    url = "https://hproxy.com/api/proxy-list"
    enabled = False
    overseas = False  # 实测国内直连 200

    def fetch(self):
        url = ("https://hproxy.com/api/proxy-list?format=txt"
               "&protocol=http,https")
        r = WebRequest().get(url, timeout=25, retry_time=2)
        for proxy in self.yieldUniqueProxies(self.parseProxiesFromText(r.text)):
            yield proxy


if __name__ == '__main__':
    n = 0
    for _ in HProxyFetcher().fetch():
        n += 1
    print("hproxy 抓到 %d 条" % n)
