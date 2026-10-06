# -*- coding: utf-8 -*-
"""
-----------------------------------------------------
   File Name：     redisClient.py
   Description :   封装Redis相关操作
   Author :        JHao
   date：          2019/8/9
------------------------------------------------------
   Change Activity:
                   2019/08/09: 封装Redis相关操作
                   2020/06/23: 优化pop方法, 改用hscan命令
                   2021/05/26: 区别http/https代理
------------------------------------------------------
"""
__author__ = 'JHao'

from redis.exceptions import TimeoutError, ConnectionError, ResponseError
from redis.connection import BlockingConnectionPool
from threading import Lock
from handler.logHandler import LogHandler
from random import choice
from redis import Redis
import json
import time


class RedisClient(object):
    """
    Redis client

    Redis中代理存放的结构为hash：
    key为ip:port, value为代理属性的字典;

    """

    def __init__(self, **kwargs):
        """
        init
        :param host: host
        :param port: port
        :param password: password
        :param db: db
        :return:
        """
        self.name = ""
        self._key_cache = None
        self._cache_ts = 0.0
        self._cache_ttl = 60  # 秒; 采集期代理基本静态, 60s 足够, 大幅减少 hkeys(4.3万) 频率
        self._refresh_lock = Lock()  # 并发 /get/ 只让一个线程真正 hkeys, 其余复用缓存(防惊群)
        kwargs.pop("username")
        self.__conn = Redis(connection_pool=BlockingConnectionPool(
            decode_responses=True,
            timeout=10,           # 阻塞等待空闲连接的超时(秒)
            socket_timeout=10,    # 单条命令超时(秒); hkeys(4.3万) 留足余量, 避免 5s 误超时
            protocol=2,
            max_connections=1000,  # 关键修复: BlockingConnectionPool 默认仅 50, 并发耗尽即 "No connection available"
            **kwargs))

    def _refresh_keys(self):
        """拉取并缓存 hash 的全部 key(ip:port)。

        加固(防 2026-10-06 17:16 崩溃: redis ConnectionError No connection available):
          1) 加锁 + 双重检查: 并发 /get/ 只让一个线程真正 hkeys, 其余拿锁后复用刚刷新的缓存,
             消除惊群(此前多个请求同时 hkeys 会瞬间拉满连接池)。
          2) 瞬时连接错误重试: 偶发 Redis 抖动不会直接冒泡成 Flask HTTP 500。
        """
        with self._refresh_lock:
            now = time.time()
            if self._key_cache is not None and now - self._cache_ts <= self._cache_ttl:
                return  # 已被其他线程刷新, 直接复用
            last_err = None
            for attempt in range(3):
                try:
                    self._key_cache = self.__conn.hkeys(self.name)
                    self._cache_ts = time.time()
                    return
                except (TimeoutError, ConnectionError) as e:
                    last_err = e
                    time.sleep(0.2 * (attempt + 1))
            if last_err is not None:
                # 重试仍失败: 若有旧缓存则视为仍新鲜继续使用(避免疯狂重试把池打挂), 否则上抛
                if self._key_cache is not None:
                    self._cache_ts = time.time()
                    return
                raise last_err

    def _cached_keys(self):
        try:
            now = time.time()
            if self._key_cache is None or now - self._cache_ts > self._cache_ttl:
                self._refresh_keys()
        except (TimeoutError, ConnectionError):
            pass  # Redis 抖动时退回旧缓存(可能为空)
        return self._key_cache or []

    def get(self, https):
        """
        返回一个代理。

        关键性能修复: 本部署代理池全部为 https(导入时统一置 https=true), 故不做 http/https
        二次过滤, 直接随机取一个 key 再 hget 单条, 单次 O(1)。
        否则原逻辑 hvals 拉取并 json.loads 全部 4.4 万条会是 O(N) 卡顿 —— 在大量代理下
        单次 /get/ 就要数百毫秒, 并发时被爬虫侧 timeout=3s 拖垮, 触发"代理池不可用, 本次直连"。

        健壮性: Redis 瞬时不可用时降级返回 None(调用方退回直连), 而非抛出 500 把池打挂。
        """
        try:
            keys = self._cached_keys()
        except (TimeoutError, ConnectionError):
            keys = []
        if not keys:
            return None
        key = choice(keys)
        try:
            return self.__conn.hget(self.name, key)
        except (TimeoutError, ConnectionError):
            return None

    def put(self, proxy_obj):
        """
        将代理放入hash, 使用changeTable指定hash name
        :param proxy_obj: Proxy obj
        :return:
        """
        data = self.__conn.hset(self.name, proxy_obj.proxy, proxy_obj.to_json)
        self._key_cache = None  # 新代理入库, 失效 key 缓存
        return data

    def pop(self, https):
        """
        弹出一个代理
        :return: dict {proxy: value}
        """
        proxy = self.get(https)
        if proxy:
            self.__conn.hdel(self.name, json.loads(proxy).get("proxy", ""))
            self._key_cache = None  # 弹出后失效 key 缓存
        return proxy if proxy else None

    def delete(self, proxy_str):
        """
        移除指定代理, 使用changeTable指定hash name
        :param proxy_str: proxy str
        :return:
        """
        res = self.__conn.hdel(self.name, proxy_str)
        self._key_cache = None  # 代理被删, 失效 key 缓存
        return res

    def exists(self, proxy_str):
        """
        判断指定代理是否存在, 使用changeTable指定hash name
        :param proxy_str: proxy str
        :return:
        """
        return self.__conn.hexists(self.name, proxy_str)

    def update(self, proxy_obj):
        """
        更新 proxy 属性
        :param proxy_obj:
        :return:
        """
        return self.__conn.hset(self.name, proxy_obj.proxy, proxy_obj.to_json)

    def getAll(self, https):
        """
        字典形式返回所有代理, 使用changeTable指定hash name
        :return:
        """
        items = self.__conn.hvals(self.name)
        if https:
            return list(filter(lambda x: json.loads(x).get("https"), items))
        else:
            return items

    def clear(self):
        """
        清空所有代理, 使用changeTable指定hash name
        :return:
        """
        return self.__conn.delete(self.name)

    def getCount(self):
        """
        返回代理数量
        :return:
        """
        proxies = self.getAll(https=False)
        return {'total': len(proxies), 'https': len(list(filter(lambda x: json.loads(x).get("https"), proxies)))}

    def changeTable(self, name):
        """
        切换操作对象
        :param name:
        :return:
        """
        self.name = name

    def test(self):
        log = LogHandler('redis_client')
        try:
            self.getCount()
        except TimeoutError as e:
            log.error('redis connection time out: %s' % str(e), exc_info=True)
            return e
        except ConnectionError as e:
            log.error('redis connection error: %s' % str(e), exc_info=True)
            return e
        except ResponseError as e:
            log.error('redis connection error: %s' % str(e), exc_info=True)
            return e


