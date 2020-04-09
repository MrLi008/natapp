# coding=utf-8
'''
:func 爬虫任务配置
:author: MrLi
:date: 

'''
import sys
import os
import codecs
import json

import requests
from bs4 import BeautifulSoup
from queue import Queue
import commonutils
from concurrent import futures
import time

dir_main_file = os.path.dirname(os.path.abspath(__file__))
configurepath = '/'.join([dir_main_file, 'conf.txt'])
configue = commonutils.load_configuration(f=configurepath)
from consumer import Consumer


def mulitclient(totalrequest=1):
    """ 通过consumer 缓存访问记录后,使用此函数,实现性能和并发量测试"""
    source = commonutils.request_cache()
    # source.clear()
    consumer = Consumer(url_productor=configue.get('consumer', 'url_base'))
    consumer.update()
    with futures.ThreadPoolExecutor(max_workers=20) as executor:
        tasklist = list()
        begin = time.time()
        for i in range(totalrequest):
            for record in source.taskfull():
                tasklist.append(executor.submit(consumer.process_task, record, True))
        for i, f in enumerate(futures.as_completed(tasklist)):
            print(i)
        end = time.time()
        realtotalrequest = len(tasklist)
    print('性能分析结果: ')
    print('总次数: ', source.count(), totalrequest * source.count(), realtotalrequest)
    print('总耗时: ', end - begin, 's', (end - begin) / 60, 'min', (end-begin)/60/60, 'hour')
    print('IPO均值: ', realtotalrequest/(end-begin), '次/秒')
    
    
def main():
    taskname = 'test'
    firstpage = 'http://www.4399.com/'
    domain = 'www.4399.com'
    fn = lambda html: ['http://{domain}'.format(domain=taga.get('href').strip()) for taga in
                       BeautifulSoup(html, 'html.parser').find_all('a')
                       if taga.get('href').strip()[0] == '/']
    requests.post('http://localhost:8008/nocover/spider/taskinit',
                  data={
                      'taskname' : taskname,
                      'firstpage': firstpage
                  })
    aqueue = Queue()
    aqueue.put(firstpage)
    count = 0
    while not aqueue.empty() and count < 100:
        count += 1
        a = aqueue.get()
        resp = requests.get(a)
        for hreflist in map(fn, resp.text):
            for href in hreflist:
                aqueue.put(href)
    print('task finish.')


if __name__ == '__main__':
    # main()
    mulitclient(10)
