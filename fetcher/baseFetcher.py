# -*- coding: utf-8 -*-
"""
-------------------------------------------------
   File Name：     baseFetcher.py
   Description :   代理源基类
   Author :        JHao
   date：          2026/5/31
-------------------------------------------------
   Change Activity:
                   2026/05/31:
-------------------------------------------------
"""
__author__ = 'JHao'

import re


class BaseFetcher(object):
    """代理源基类"""

    # ---- 子类必须声明 ----
    name = ""        # 唯一标识，如 "zdaye"
    url = ""         # 源网站首页 URL

    # ---- 子类可覆盖 ----
    enabled = True   # 是否启用，设为 False 可禁用该源

    # 该源是否在国外：True = 抓取时走出口代理(upstream)，False = 直连。
    # 仅影响抓取阶段的 WebRequest，不影响代理校验与 API。
    overseas = False

    def fetch(self):
        """爬取代理，yield "host:port" 字符串"""
        raise NotImplementedError

    @staticmethod
    def parseProxiesFromText(text):
        """从文本中用正则提取 ip:port"""
        if not text:
            return []
        proxy_pattern = re.compile(
            r'(?<![\d.])(\d{1,3}(?:\.\d{1,3}){3})(?:\s*:\s*|\s+)(\d{2,5})(?!\d)')
        return ["%s:%s" % proxy for proxy in proxy_pattern.findall(text)]

    @staticmethod
    def yieldUniqueProxies(proxies):
        """去重 yield"""
        seen = set()
        for proxy in proxies:
            if proxy not in seen:
                seen.add(proxy)
                yield proxy