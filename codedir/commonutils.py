# coding=utf-8
"""
    @author MrLi:
    @Func: 生产者/消费者通用的工具
"""
import io, os, sys, codecs, json
import base64
from http.cookies import SimpleCookie
from bson import ObjectId
from requests.cookies import RequestsCookieJar
from requests.structures import CaseInsensitiveDict
from datetime import datetime
from time import struct_time
import time
import re

import pymongo
import requests

mongodb_db_name = 'consumer'
mongodb_collection_name = 'consumer__3.0__'

monthunit = {'Jan' : 1, 'Feb': 2, 'Mar': 3, 'Apr': 4,
             'May' : 5, 'Jun': 6, 'Jul': 7, 'Aug': 8,
             'Sept': 9, 'Oct': 10, 'Nov': 11, 'Dec': 12}


def load_configuration(f):
    import configparser
    config = configparser.ConfigParser()
    with codecs.open(f, 'r', encoding='utf-8') as instream:
        config.read_file(instream)
    return config


def covertSetCookie2List(v):
    s = v.split(';')
    res = list()
    for t in s:
        if ',' in t and 'expires=' not in t:
            res.append(t.replace(',', '|--|'))
        else:
            res.append(t)
    res = ';'.join(res).split('|--|')
    print(res)
    return res


def covertExpires2timestampe(s):
    temp = s.split(' ')
    stime = ' '.join([temp[1], temp[2]])
    p = r'(?P<day>\d+)-(?P<month>.+)-(?P<year>\d+) (?P<hour>\d+):(?P<minute>\d+):(?P<second>\d+)'
    m = re.match(p, stime)
    nv = m.groupdict()
    
    t = time.mktime((int(nv.get('year')),
                     monthunit.get(nv.get('month')),
                     int(nv.get('day')),
                     int(nv.get('hour')),
                     int(nv.get('minute')),
                     int(nv.get('second')), 3, 335,
                     -1))
    print(t)
    return t


class Covert(object):
    @staticmethod
    def covertBytes2Str(b):
        if len(b) == 0:
            return ''
        if isinstance(b, bytes):
            return str(base64.b64encode(b), encoding='utf-8')
        return b
    
    @staticmethod
    def covertStr2Str(s):
        if len(s) == 0:
            return b''
        return str(base64.b64decode(bytes(s, encoding='utf-8')), encoding='utf-8')
    
    @staticmethod
    def covertStr2Bytes(s):
        if len(s) == 0:
            return b''
        try:
            res = base64.b64decode(bytes(s, encoding='utf-8'))
        except Exception  as e:
            res = s
        return res
    
    @staticmethod
    def covertHeaders2Dict(headers):
        if isinstance(headers, CaseInsensitiveDict):
            return dict(headers)
        return headers._dict
    
    @staticmethod
    def covertDict2Headers(headers):
        if isinstance(headers, dict):
            return headers
        return {}
    
    @staticmethod
    def covertCookies2Dict(cookies):
        obj = dict()
        if isinstance(cookies, SimpleCookie):
            for cookie in cookies.values():
                obj[cookie.key] = cookie.value
        elif isinstance(cookies, RequestsCookieJar):
            for name, value in cookies.items():
                obj[name] = value
        return obj
    
    @staticmethod
    def covertDict2Cookies(cookies):
        if isinstance(cookies, dict):
            return cookies
        return {}
    
    @staticmethod
    def covertHttpFile2Dict(files):
        obj = dict()
        for name, httpfiles in files.items():
            obj[name] = [{'filename'    : httpfile.filename,
                          'body'        : Covert.covertBytes2Str(httpfile.body),
                          'content-type': httpfile.content_type}
                         for httpfile in httpfiles]
        return obj
    
    @staticmethod
    def covertDict2HttpFiles(obj):
        httpfile = list()
        for name, val in obj.items():
            for f in val:
                filename = f.get('filename')
                bytes = Covert.covertStr2Bytes(f.get('body'))
                buff = io.BytesIO()
                buff.write(bytes)
                buff.seek(0)
                contenttype = f.get('content-type')
                # httpfile[name].append((filename, buff, contenttype))
                httpfile.append((name, (filename, buff, contenttype)))
        return httpfile


class request_cache(object):
    """
    请求缓存-mongodb中
    1. 若请求未加入缓存->加入缓存
    2. 若请求已加入缓存->
    2.1 请求未完成->发起请求
    2.2 请求已完成->返回请求结果
    """
    
    def __init__(self, dbname=mongodb_db_name, collectionname=mongodb_collection_name):
        self.driver = pymongo.MongoClient(host='localhost',
                                          port=27017).get_database(dbname).get_collection(collectionname)
    
    def visited(self, item):
        """
        默认item 不带_id
        :param item:
        :return:
        """
        obj = self.driver.find_one(filter={'item_item': item.get('item_item')})
        if obj in (None,):
            try:
                self.driver.insert_one(item)
            except Exception as e:
                print(e)
            return False
        if obj.get('item_finsh') in (None, False):  # 请求已缓存,但请求未完成
            return False
        return obj
    
    def update(self, _id="", item=None):
        assert isinstance(_id, ObjectId)
        res = self.driver.update_one({'_id': _id},
                               {'$set': item})
        # print(res)
    
    def get(self, item):
        return self.driver.find_one(filter={'item_item': item})
    
    def task(self):
        with self.driver.find({'item_finish': None}) as cursor:
            # print('total: ', cursor.count())
            for i, record in enumerate(cursor):
                yield record
                
    def tasklimit(self, limit=10):
        with self.driver.find({'item_finish': None}).limit(limit) as cursor:
            # print('total: ', cursor.count())
            for i, record in enumerate(cursor):
                record['_id'] = str(record.get('_id'))
                yield record
    
    def taskfull(self):
        with self.driver.find({}) as cursor:
            print('total: ', cursor.count())
            for i, record in enumerate(cursor):
                yield record
    
    def count(self):
        with self.driver.find({}) as cursor:
            return cursor.count()
    
    def clear(self):
        self.driver.remove({})
        # print('clear ', mongodb_db_name, mongodb_collection_name, 'not allowed remove all')


class request_cache_web(request_cache):
    def __init__(self, url_target):
        # 更新记录接口
        super().__init__()
        self.url_update = ''.join([url_target, 'nocover/update'])
        # 请求任务接口
        self.url_task = ''.join([url_target, 'nocover/task'])
    
    def update(self, _id="", item=None):
        # item['_id'] = str(item.get('_id'))
        resp = requests.post(self.url_update,
                             data={
                                 '_id' : str(_id),
                                 'item': json.dumps(item),
                                 'token': '66123'
                             })
        print(resp.text)
    
    def task(self):
        resp = requests.post(self.url_task, data={
            'token'      : '66123',
            'item_finish': 'None'
        })
        assert resp.status_code == 200
        data = json.loads(resp.text)
        for record in data.get('res'):
            yield record


class impl_qzqd(object):
    def __init__(self, dbname='spider_qzqd_stable_20190929',
                 collectname='山西省晋中市权责清单数据爬取_record'):
        self.driver = pymongo.MongoClient(host='localhost',
                                          port=27017).get_database(dbname).get_collection(collectname)
    
    def value_location(self, namelist):
        res = list()
        condition = {name: '${name}'.format(name=name)
                     for name in namelist}
        with self.driver.aggregate([
            {
                '$group': {
                    '_id'  : condition,
                    'count': {
                        '$sum': 1
                    }
                }
            }
        ]) as cursor:
            for record in cursor:
                res.append(record)
        return res
    
    def value(self, item, name):
        res = list()
        with self.driver.aggregate([
            {'$match': item},
            {'$group': {'_id'  : {'record': '$record.{name}'.format(name=name)},
                        'count': {'$sum': 1}}}
        ]) as cursor:
            for record in cursor:
                res.append(record)
        print(len(res))
        return res
    
    def filterfrom(self, limit=1, condition=None, pagesize=10, pagenum=1, pagesizemax=100, pagenummax=20):
        """
        分页查询
        :param limit:
        :param condition:
        :param pagesize:
        :param pagenum:
        :param pagesizemax:
        :param pagenummax:
        :return:
        """
        if pagenum > pagesizemax or pagesize > pagesizemax:
            print('limit out limit: ', pagesize, '<', pagesizemax, pagenum, '<', pagenummax)
            return []
        res = list()
        with self.driver.find(condition).limit(limit).skip(pagesize * (pagenum - 1)) as cursor:
            for record in cursor:
                res.append(record)
        return res
    
    def filterone(self, _id):
        """
        查询详情数据
        :param _id:
        :return:
        """
        # if isinstance(_id, str):
        #     _id = ObjectId(_id)
        return self.driver.find_one({'_id': _id})


class dbana(object):
    def __init__(self, dbname, collectionname):
        self.driver = pymongo.MongoClient(host='localhost', port=27017).get_database(dbname).get_collection(
                collectionname)
    
    def keys(self, obj, prename=''):
        res = list()
        if isinstance(obj, dict):
            for name, val in obj.items():
                if len(prename) > 0:
                    res.append('.'.join([prename, name]))
                    res += self.keys(val, prename='.'.join([prename, name]))
                else:
                    res.append(name)
                    res += self.keys(val, prename=name)
        return res
    
    def get_all_key(self):
        obj = self.driver.find_one({})
        return self.keys(obj)


class SpiderTaskBase(object):
    def __init__(self, **kwargs):
        # 指定爬取页面的基本信息
        # 指定页面的分页信息
        # 指定页面分页部分,需要的数据
        # 指定页面详情页需要的数据
        pass


def main():
    pass


if __name__ == '__main__':
    main()
