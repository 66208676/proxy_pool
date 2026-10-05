# -*- coding: utf-8 -*-
"""
-------------------------------------------------
   File Name：     proxyScheduler
   Description :
   Author :        JHao
   date：          2019/8/5
-------------------------------------------------
   Change Activity:
                   2019/08/05: proxyScheduler
                   2021/02/23: runProxyCheck时,剩余代理少于POOL_SIZE_MIN时执行抓取
-------------------------------------------------
"""
__author__ = 'JHao'

from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.executors.pool import ProcessPoolExecutor

from util.six import Queue
from helper.fetch import Fetcher
from helper.check import Checker
from handler.logHandler import LogHandler
from handler.proxyHandler import ProxyHandler
from handler.configHandler import ConfigHandler


def __runProxyFetch():
    proxy_queue = Queue()
    proxy_fetcher = Fetcher()

    for proxy in proxy_fetcher.run():
        proxy_queue.put(proxy)

    Checker("raw", proxy_queue)


def __runProxyCheck():
    proxy_handler = ProxyHandler()
    proxy_queue = Queue()
    if proxy_handler.db.getCount().get("total", 0) < proxy_handler.conf.poolSizeMin:
        __runProxyFetch()
    for proxy in proxy_handler.getAll():
        proxy_queue.put(proxy)
    Checker("use", proxy_queue)


def runScheduler():
    __runProxyFetch()

    conf = ConfigHandler()
    timezone = conf.timezone
    scheduler_log = LogHandler("scheduler")
    scheduler = BlockingScheduler(logger=scheduler_log, timezone=timezone)

    scheduler.add_job(__runProxyFetch, 'interval',
                      minutes=conf.fetchIntervalMinutes,
                      id="proxy_fetch", name="proxy采集")
    scheduler.add_job(__runProxyCheck, 'interval',
                      minutes=conf.checkIntervalMinutes,
                      id="proxy_check", name="proxy检查")
    executors = {
        'default': {'type': 'threadpool', 'max_workers': 20},
        'processpool': ProcessPoolExecutor(max_workers=5)
    }
    job_defaults = {
        'coalesce': False,
        'max_instances': 10
    }

    # configure() 会把 self._logger 重置为 logging.getLogger('apscheduler.scheduler')，
    # 那个 logger 没有任何 handler，INFO 级别的 "Scheduler started" / "Added job"
    # 会被静默丢弃（Python 的 lastResort handler 只输出 WARNING 及以上）。
    # 显式把 logger 传进来，调度器的排期决策才会出现在 log/scheduler.log 里。
    scheduler.configure(executors=executors, job_defaults=job_defaults,
                        timezone=timezone, logger=scheduler_log)

    scheduler.start()


if __name__ == '__main__':
    runScheduler()
