# coding=utf-8
"""
    @author MrLi:
    @Func: 接收用户请求并保留缓存
"""
import io, os, sys, codecs, json
import pickle
import filetype
import time
import hashlib
import queue
import tornado
from bs4 import BeautifulSoup
import re
import requests
import base64
from datetime import datetime
from bson import ObjectId

# 当前文件所在路径
dir_main_file = os.path.dirname(os.path.abspath(__file__))
sys.path.append(dir_main_file)

from tornado import ioloop as ti
from tornado import web as tweb
from tornado import options as toption
from tornado.concurrent import run_on_executor
from tornado.httpserver import HTTPServer

from concurrent import futures
from http.cookies import SimpleCookie
import traceback

import commonutils

configpath = '/'.join([dir_main_file, 'conf.txt'])
configure = commonutils.load_configuration(f=configpath)
# 是否缓存url,http历史请求
is_cache = configure.get('productor', 'is_cache') == 'True'
# filtertypes = ['.jpg', '.gif', '.png', '.ico']
filtertypes = ['.jpg', '.gif', '.png', '.ico', '.css']


# queue,记录所有请求,并提供给consumer
# taskqueue = queue.Queue()


class TaskQueue(object):
    """ 封装任务序列"""
    
    def __init__(self):
        self.taskqueue = queue.Queue()
    
    def clear(self):
        """ 清空序列"""
        self.taskqueue.queue.clear()
    
    def put(self, item):
        """添加任务,添加纪录/默认是时间序列,可区分是否缓存"""
        self.taskqueue.put(item)
    
    def get(self):
        """做任务"""
        if self.taskqueue.empty():
            return None
        item = self.taskqueue.get(timeout=1)
        self.taskqueue.task_done()
        return item
    
    def size(self):
        return self.taskqueue.qsize()


class TaskItem(object):
    def __init__(self):
        self.tq = TaskQueue()
        # 缓存
        self.dbcache = commonutils.request_cache()
        self.impl_qzqd = commonutils.impl_qzqd()
        self.url_target = configure.get('consumer', 'url_target')
        # self.is_img_loading = False
        self.is_img_loading = True
        
        self.counter_add = 0
        self.counter_finish = 0
    
    """ 每次请求的标准数据格式"""
    args = ['item_url', 'item_body', 'item_cookies', 'item_headers', 'item_method', 'item_files',
            'item_res', 'item_finish',
            ]
    
    def __str__(self):
        s = 'history: {history},taskqueue:{taskqueue}-rest: {rest}'.format(history=self.counter_add,
                                                                           taskqueue=self.tq.taskqueue.qsize(),
                                                                           rest=self.dbcache.count())
        return s
    
    def task_add(self, kwargs):
        """ 添加任务"""
        record = {k: kwargs.get(k, None) for k in self.args}
        record['url_target'] = self.url_target
        if record['item_url'] is not None:
            # 去掉time标记
            record['item_url'] = re.subn('_=\d+', '', record['item_url'])[0]
        
        item = self.getitem(record)
        if not self.is_img_loading:
            if record.get('item_url')[-4:].lower() in filtertypes:
                return ""
        # print('item add: ', item)
        record['item_item'] = item  # 添加标记
        # 若任务已被完成
        obj = self.dbcache.visited(record)
        if obj:
            return obj.get('item')
        self.counter_add += 1
        return item
    
    def task_clear(self):
        self.tq.clear()
        self.dbcache.clear()
    
    def task_update_target(self, url_target):
        self.task_clear()
        self.url_target = url_target
    
    def task_update_is_img_loading(self, is_img_loading):
        if is_img_loading == 'True':
            self.is_img_loading = True
        else:
            self.is_img_loading = False
    
    def get_item_res(self, item):
        if item == "":
            return None
        for i in range(100):
            temp = self.dbcache.get(item)
            if temp and temp.get('item_finish'):
                return temp
            time.sleep(0.2)
    
    # 序列标记, 用于更新任务及保存结果
    def getitem(self, kw):
        url = kw.get('item_url')
        method = kw.get('item_method')
        body = kw.get('item_body')
        # cookies = kw.get('item_cookies')
        # headers = kw.get('item_headers')
        timeseq = "_with_cache"
        url_target = kw.get('url_target')
        if not is_cache:
            timeseq = time.time()
        s = 'From-{url}-By-{method}-{body}-{cookies}{headers}-{url_target}{time}'.format(url=url,
                                                                                         method=method,
                                                                                         body=body,
                                                                                         time=timeseq,
                                                                                         headers="headers",
                                                                                         cookies="cookies",
                                                                                         url_target=url_target,
                                                                                         # headers=headers,
                                                                                         # cookies=cookies,
                                                                                         )
        return hashlib.md5(s.encode(encoding='utf-8')).hexdigest()


"""#####################################################################
    # Tornado Handle Define>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>
"""
taskobj = TaskItem()


class ExecutorHandle(tweb.RequestHandler):
    executor = futures.ThreadPoolExecutor(max_workers=80)
    taskobj = taskobj


class productor(ExecutorHandle):
    imgtypes = ['.gif', '.png', '.jpg', '.ico']
    
    def _item(self, url):
        item_body = commonutils.Covert.covertBytes2Str(self.request.body)
        item_cookies = json.dumps(commonutils.Covert.covertCookies2Dict(self.request.cookies))
        item_headers = json.dumps(commonutils.Covert.covertHeaders2Dict(self.request.headers))
        item_files = commonutils.Covert.covertHttpFile2Dict(self.request.files)
        return {
            'item_url'    : url, 'item_body': item_body,
            'item_cookies': item_cookies, 'item_headers': item_headers,
            'item_method' : self.request.method, 'item_files': item_files
        }
    
    def filter(self, url):
        """ url拦截器"""
        prefix = 'nocover'
        if url[:len(prefix)] == prefix:
            return True
        return False
    
    def covertHTML2SafeHTML(self, html):
        s = re.subn(r'document.write.*\)', '', html)[0]
        
        p = r'.*(?P<hrefline>window.location.href = (?P<href>.*));.*'
        html_res = list()
        for h in html.split('\n'):
            res = re.match(p, h)
            if res:
                res = res.groupdict()
                h = h.replace(res.get('hrefline'), 'opt.go({href})'.format(href=res.get('href')))
            html_res.append(h)
        s = ''.join(html_res)
        s = s.replace(self.taskobj.url_target, '/')
        return s
    
    def updateheader(self, url, item):
        headers = json.loads(item.get('item_headers'))
        
        # if ':' in name]
        
        if 'Host' in headers:
            self.set_header('Host', headers.get('Host'))
        if 'Referer' in headers:
            self.set_header('Referer', headers.get('Referer'))
        
        if 'Set-Cookie' in headers:
            for cookiestr in commonutils.covertSetCookie2List(headers.get('Set-Cookie')):
                s = SimpleCookie()
                s.load(cookiestr)
                for name, cookie in s.items():
                    self.set_cookie(name, cookie.value, domain=cookie.get('domain'),
                                    # expires= commonutils.covertExpires2timestampe(cookie.get('expires')),
                                    path=cookie.get('path'),
                                    httponly=cookie.get('httponly'),
                                    max_age=cookie.get('max-age'))
            # try:
            #     self.set_cookie(name=name, value=value, **kw)
            # except Exception as e:
            #     traceback.print_exc()
        # 修正content-type
        res = commonutils.Covert.covertStr2Bytes(item.get('item_res'))
        if url.lower()[-4:] in self.imgtypes:
            if url.lower()[-4:] == '.jpg':
                self.set_header('Content-Type', 'image/jpeg')
            else:
                self.set_header('Content-Type', 'image/{imgtype}'.format(imgtype=url[-3:]))
            self.write(res)
            return
        if len(re.findall(r'.*css.*', url.lower())) > 0:
            self.set_header('Content-Type', 'text/css')
        elif len(re.findall(r'.*js.*', url.lower())) > 0:
            self.set_header('Content-Type', 'application/javascript')
        # res = str(res, encoding='utf-8', errors='ignore')
        encoding = requests.utils.get_encodings_from_content(str(res))
        if len(encoding) > 0:
            encoding = encoding[0]
        else:
            encoding = 'utf-8'
        # print('encoding: ', encoding)
        try:
            res = str(res, encoding=encoding, errors='ignore')
        except Exception as e:
            print(e, res)
        res = self.covertHTML2SafeHTML(res)
        try:
            res = json.loads(res)
        except Exception as e:
            print(e, )
        
        self.write(res)
    
    @run_on_executor
    def process(self, url):
        if self.filter(url):
            return '拦截失败...'
        if url[0] == '/':
            url = url[1:]
        if url[:4] == 'http':
            print(url, 'confirm not localhost:8008')
        url = ''.join([self.taskobj.url_target, url])
        item = self.taskobj.task_add(self._item(url))
        res = self.taskobj.get_item_res(item)
        if res in (None, ""):
            return ""
        return self.updateheader(url, res)
    
    @tornado.gen.coroutine
    def get(self, url):
        yield self.process(self.request.uri)
    
    @tornado.gen.coroutine
    def post(self, url):
        yield self.process(url)


class clear_cache(ExecutorHandle):
    @tornado.gen.coroutine
    def get(self):
        self.taskobj.task_clear()
        self.write({'res': 'clear ok-{taskobj}'.format(taskobj=str(self.taskobj))})


class request_user_new(ExecutorHandle):
    def _item(self):
        url_target = self.get_argument('url_target')
        taskobj.task_update_target(url_target=url_target)
        return {
            "url_target": url_target
        }
    
    @run_on_executor
    def process(self):
        return self._item()
    
    @tornado.gen.coroutine
    def get(self):
        self.render('request_user_new.html', res={'Empty': 'Empty'})
    
    @tornado.gen.coroutine
    def post(self, ):
        res = yield self.process()
        self.render('request_user_new.html', res=res)


class request_is_img_loading(ExecutorHandle):
    @run_on_executor
    def process(self):
        taskobj.task_update_is_img_loading(self.get_argument('is_img_loading'))
    
    @tornado.gen.coroutine
    def get(self):
        res = yield self.process()
        self.write({'res': res})
    
    @tornado.gen.coroutine
    def post(self):
        res = yield self.process()
        self.write({'res': res})


class request_update(ExecutorHandle):
    def post(self, *args, **kwargs):
        token = self.get_argument('token')
        assert token == '66123'
        _id = self.get_argument('_id')
        item = json.loads(self.get_argument('item'))
        # item = self.get_argument('item')
        del item['_id']
        taskobj.dbcache.update(ObjectId(_id),
                               item=item)
        self.write('Success')


class request_task(ExecutorHandle):
    def post(self, *args, **kwargs):
        token = self.get_argument('token')
        assert token == '66123'
        condition = {'item_finish': self.get_argument('item_finish')}
        limit = 10
        res = [r for r in taskobj.dbcache.tasklimit(limit)]
        self.write({'res': res})


class iframe(ExecutorHandle):
    default_form = {
        'taskname'     : {
            'tip'          : '任务名称(不能重复)',
            'default-value': "数据爬取任务测试",
        },
        'province'     : {
            'tip'          : '所属省份',
            'default-value': '山西省',
        },
        'city'         : {
            'tip'          : '所属市',
            'default-value': '太原市',
        },
        'county'       : {
            'tip'          : '所属区县',
            'default-value': '万柏林区',
        },
        'firstpage'    : {
            'tip'          : '爬虫第一个页面(通过按钮选择)',
            'default-value': '/',
        },
        'tag_mark'     : {
            'tip'          : '区域标记',
            'default-value': '',
        },
        'tag_mark_item': {
            'tip'          : '选择数据列',
            'default-value': ''
        },
        'tag_nextpage' : {
            'tip'          : '翻页按钮',
            'default-value': '',
        }
    }
    context = {
        'default_form': default_form,
        'obj'         : None,
        'url_target'  : taskobj.url_target,
    }
    
    def get(self):
        self.render('iframe.html', **self.context)
    
    def post(self):
        """
        提交任务,开始任务测试.
        :return: None
        """
        self.context['obj'] = {name: self.get_argument(name) for name in self.default_form}
        
        self.render('iframe.html', **self.context)


class iframe_href(ExecutorHandle):
    default_form = {
        'dbname'        : {
            'tip'          : '数据库名称',
            'default-value': 'spider_qzqd_stable_20190929',
        },
        'collectionname': {
            'tip'          : 'document名称',
            'default-value': '山西省晋中市权责清单数据爬取_record'
        },
        'step'          : {
            'tip'          : 'step',
            'default-value': 'all-key'
        }
    }
    context = {
        'default_form': default_form,
        'obj'         : None,
        'form'        : None,
        'all_key'     : []
    }
    
    def get(self):
        self.render('iframehref.html', **self.context)
    
    def post(self):
        self.context['form'] = {name: self.get_argument(name) for name in self.context.get('default_form')}
        anaobj = commonutils.dbana(dbname=self.get_argument('dbname'),
                                   collectionname=self.get_argument('collectionname'))
        step = self.get_argument('step')
        if step == 'all-key':
            self.context['all_key'] = anaobj.get_all_key()
        self.render('iframehref.html', **self.context)


class showfilter(ExecutorHandle):
    condition = ['province', 'city', 'county']  # 省,市区
    record = []  # 详细查询条件
    context = {
    }
    
    def initcontext(self):
        # 分组查询
        res_condition = self.taskobj.impl_qzqd.value_location(namelist=self.condition)
        res = dict()
        for val in res_condition:
            p = val.get('_id').get('province')
            city = val.get('_id').get('city')
            county = val.get('_id').get('county')
            if p not in res:
                res[p] = dict()
            if city not in res.get(p):
                res[p][city] = dict()
            res[p][city][county] = ""
        self.context['filter'] = res
    
    def get(self):
        if len(self.context) == 0:
            self.initcontext()
        self.render('showfilter.html', context=self.context, data=None, filter=self.context.get('filter'))
    
    def post(self):
        if self.context is {}:
            self.initcontext()
        step = self.get_argument('step')
        cond = self.get_argument('filters', None)
        
        if step in ['city', 'county']:
            temp = self.context.get('filter')
            flag = True
            for c in cond.split(','):
                if c not in temp:
                    print('err....', temp, c)
                    flag = False
                    break
                temp = temp[c]
            if flag:
                self.write(temp)
        elif step == 'details':
            temp = self.context.get('filter')
            condition = {name: value for name, value in zip(['province', 'city', 'county'], cond.split(','))}
            condition_record = self.taskobj.impl_qzqd.filterfrom(condition=condition)
            if len(condition_record) > 0:
                condition_record = condition_record[0]
                condition_record = {name: "" for name in condition_record.get('record')}
                self.record = [name for name in condition_record][:3]
                self.write(condition_record)
        elif step == 'record':
            temp = self.context.get('filter')
            condition = {name: value for name, value in zip(['province', 'city', 'county'], cond.split(','))}
            recordname = self.get_argument('recordname')
            data = self.taskobj.impl_qzqd.value(condition, recordname)
            res = {v.get('_id').get('record', ""): ""
                   for v in data
                   if v.get('_id').get('record', "") and len(v.get('_id').get('record', "")) > 0}
            self.write(res)
        elif step == 'recordfilter':
            temp = self.context.get('filter')
            condition = {name: value for name, value in zip(['province', 'city', 'county'], cond.split(','))}
            recordname = self.get_argument('recordname')
            recordfilter = self.get_argument('recordfilter')
            condition['record.{recordname}'.format(recordname=recordname)] = recordfilter
            limit = self.get_argument('limit', 10)
            pagesize = self.get_argument('pagesize', 10)
            pagenum = self.get_argument('pagenum', 1)
            res = self.taskobj.impl_qzqd.filterfrom(limit=limit, condition=condition,
                                                    pagesize=pagesize,
                                                    pagenum=pagenum)
            self.write({'res': res})
        elif step == 'record_one':
            record_id = self.get_argument('record_id')
            res = self.taskobj.impl_qzqd.filterone(record_id)
            self.write(res)


"""#####################################################################
    # Tornado Handle Define<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<
"""


def application(port):
    urls = [
        (r'/nocover/clear_cache', clear_cache),
        (r'/nocover/request_user_new', request_user_new),
        (r'/nocover/request_is_img_loading', request_is_img_loading),
        (r'/nocover/iframe', iframe),
        (r'/nocover/showfilter', showfilter),
        (r'/nocover/iframehref', iframe_href),
        
        (r'/nocover/update', request_update),
        (r'/nocover/task', request_task),
        (r'/(?P<url>.*)', productor),
    ]
    print('\n'.join(['http://localhost:{port}{url}'.format(port=port, url=url[0])
                     for url in urls]))
    return tweb.Application(
            urls,
            template_path='/'.join([dir_main_file, 'templates']),
            # static_path='/'.join([dir_main_file, 'static']),
            # autoreload=True
    )


def main():
    # toption.define('taskobj', TaskItem(), type=TaskItem)
    # toption.options.parse_command_line()
    port = configure.getint('productor', 'port')
    app = application(port)
    http_server = HTTPServer(app)
    http_server.listen(port)
    http_server.start()
    ti.IOLoop.instance().start()


if __name__ == '__main__':
    main()
