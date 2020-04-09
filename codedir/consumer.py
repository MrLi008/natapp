# coding=utf-8
"""
    @author MrLi:
    @Func:
简要思路描述
1. 请求url productor获取转发请求需要的基本数据
2, 请求url target,得到结果数据并回传,只包含结果数据item_res和item
"""
import io, os, sys, codecs, json
import pickle
import filetype
import time
import traceback
import hashlib
import queue
import tornado
from bs4 import BeautifulSoup
import re
import base64
import requests
import threading
from urllib.parse import urlparse
from concurrent import futures

import pymongo
from bson.objectid import ObjectId

# 当前文件所在路径
dir_main_file = os.path.dirname(os.path.abspath(__file__))
sys.path.append(dir_main_file)

import commonutils

configurepath = '/'.join([dir_main_file, 'conf.txt'])
configure = commonutils.load_configuration(f=configurepath)
# sess = requests.Session()
sess = requests
consumerlist = list()
# isproxy = True
isproxy = False
if isproxy:
    request_proxy = {
        'http' : 'http://127.0.0.1:50445',
        'https': 'http://127.0.0.1:50445',
    }
else:
    request_proxy = {}


class Consumer(object):
    def __init__(self, url_productor):
        # 读取默认配置
        self.url_productor = url_productor
        self.timeout = 2
        self.url_request_task = ''
        self.url_finish_task = ''
        # self.source = commonutils.request_cache()
        self.source = commonutils.request_cache_web(url_target=url_productor)
        
    def __str__(self):
        s = '{url_productor}'.format(url_productor=self.url_productor)
        return s
    
    __repr__ = __str__
    
    def update(self):
        self.url_request_task = ''.join([self.url_productor, 'nocover/request_task'])
        self.url_finish_task = ''.join([self.url_productor, 'nocover/finish_task'])
    
    def process_task(self, obj, istest=False):
        one = self.source.visited(item=obj)
        sess = requests.Session()
        
        print(obj.get('item_url'), obj.get('item_item'))
        if one and not istest:
            print(obj.get('item_url'), 'cache: ')
            return one
        if obj.get('item_url') != '' and obj.get('item_url')[0] == '.':
            print('err: ', obj.get('item_url'))
        
        url = obj.get('item_url')
        method = obj.get('item_method')
        cookies = json.loads(obj.get('item_cookies'))
        headers = json.loads(obj.get('item_headers'))
        if len(cookies) == 0 and istest:
            cookies = json.loads(obj.get('item_cookies_request'))
            headers = json.loads(obj.get('item_headers_request'))
        
        files = commonutils.Covert.covertDict2HttpFiles(obj.get('item_files'))
        targethost = urlparse(url).netloc
        headers['Host'] = targethost
        headers['Connection'] = 'close'
        if 'Referer' in headers:
            temp = headers['Referer']
            parse = urlparse(temp)
            referer = ''.join([parse.scheme, '://', urlparse(url).netloc, parse.path])
            if len(parse.query) > 0:
                referer = '?'.join([referer, parse.query])
            headers['Referer'] = referer
        data = commonutils.Covert.covertStr2Bytes(obj.get('item_body'))
        requestheader = headers
        # data = ""
        # 2 发起请求
        try:
            if method.lower() == 'get':
                if len(data) == 0:
                    resp = sess.get(url, data=data, cookies=cookies, headers=headers,
                                    timeout=self.timeout, proxies=request_proxy)
                else:
                    resp = sess.get(url, params=data, cookies=cookies, headers=headers,
                                    timeout=self.timeout, proxies=request_proxy)
            elif method.lower() == 'post':
                if len(files) == 0:
                    resp = sess.post(url, data=data, cookies=cookies, headers=headers,
                                     timeout=self.timeout, proxies=request_proxy)
                else:  # 文件转发
                    resp = sess.post(url, files=files, timeout=self.timeout, proxies=request_proxy)
            else:
                print('Only Support GET and POST Method. Other method not support now...yours: ', method)
        except Exception as e:
            print(e, url)
            return obj
        res = commonutils.Covert.covertBytes2Str(resp.content)
        print(url, 'status code: ', resp.status_code, len(res), 're cache.')
        # 3. 准备回传数据
        headers = commonutils.Covert.covertHeaders2Dict(resp.headers)
        headers.update({'Host': targethost})
        obj.update({'item_res'            : res,
                    'item_cookies'        : json.dumps(resp.cookies.get_dict()),
                    'item_headers'        : json.dumps(headers),
                    'item_cookies_request': json.dumps(cookies),
                    'item_headers_request': json.dumps(requestheader),
                    'item_count'          : obj.get('item_count', 0) + 1})
        
        obj.get('_id')
        if obj.get('item_res') or obj.get('item_count', 0) > 5:
            obj['item_finish'] = True
        
        self.source.update(_id=obj.get('_id'),
                           item=obj)


def main_single_test():
    # 模拟请求
    t = threading.Thread(target=requests.get, args=['http://localhost:8008'])
    t.start()
    # 处理开始
    consumer = Consumer(url_productor=configure.get('consumer', 'url_base'))
    consumer.update()
    consumer.task()


def main_single_user():
    consumer = Consumer(url_productor=configure.get('consumer', 'url_base'))
    consumer.update()
    with futures.ThreadPoolExecutor(max_workers=20) as tpool:
        while True:
            # consumer.task()
            time.sleep(0.1)
            b = time.time()
            reslist = [tpool.submit(consumer.task) for i in range(30)]
            for i, f in enumerate(futures.wait(reslist, timeout=5)):
                print(i / len(reslist))
            print('...over', time.time() - b, 's')
            # if len(reslist) > 100000:
            #     break
        # for i, f in enumerate(futures.as_completed(reslist)):
        #     pass


def main_task_from_cache():
    # source = commonutils.request_cache()
    # source = commonutils.request_cache_web()
    # source.clear()
    consumer = Consumer(url_productor=configure.get('consumer', 'url_base'))
    consumer.update()
    with futures.ThreadPoolExecutor(max_workers=20) as executor:
        while True:
            tasklist = list()
            # for record in source.task():
            for record in consumer.source.task():
                tasklist.append(executor.submit(consumer.process_task, record))
            # for i, f in enumerate(futures.wait(tasklist, timeout=5)):
            #     pass
            for i, f in enumerate(futures.as_completed(tasklist)):
                print(i)
            time.sleep(0.2)


def main_task_from_cache_full():
    source = commonutils.request_cache()
    # source.clear()
    consumer = Consumer(url_productor=configure.get('consumer', 'url_base'))
    consumer.update()
    with futures.ThreadPoolExecutor(max_workers=20) as executor:
        while True:
            tasklist = list()
            for record in source.task():
                for i in range(10):
                    tasklist.append(executor.submit(consumer.process_task, record))
            # for i, f in enumerate(futures.wait(tasklist, timeout=5)):
            #     pass
            for i, f in enumerate(futures.as_completed(tasklist)):
                print(i)
            # time.sleep(0.2)


if __name__ == '__main__':
    # main()
    # main_single_user()
    main_task_from_cache()
    # main_task_from_cache_full()
