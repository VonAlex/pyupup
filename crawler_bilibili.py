#!/usr/bin/python3
# -*- coding: utf-8 -*-
'''
根据 up 主的 id 下载其所有的视频信息，包括弹幕和评论
'''

import requests
from lxml import etree
import json
import math
import time
import threading
import sys
import signal
from queue import Queue


user_agent = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) ' \
             'AppleWebKit/537.36 (KHTML, like Gecko) ' \
             'Chrome/80.0.3987.149 Safari/537.36'
headers = {'User-Agent': user_agent}

# proxy 来源 https://www.xicidaili.com/nn/
proxies = {
    "http": "http://116.196.85.150:3128",
    "https": "http://117.88.176.41:3000",
}

stop = False  # 控制是否停止


class Parser(threading.Thread):
    def __init__(self, tid, queue):
        threading.Thread.__init__(self)
        self.tid = tid
        self.queue = queue  # 任务队列

    def run(self):
        print('启动线程：', self.tid)

        while not stop:
            try:
                bvid = self.queue.get(False)
                if not bvid:
                    pass
                self.parse(bvid)
                self.queue.task_done()
            except Exception as e:
                print(e)
                pass

        print('退出了该线程：', self.tid)

    # 根据 bvid 获得 cid (av 号)
    def get_cid(self, bvid):
        url = 'https://api.bilibili.com/x/player/pagelist?bvid={}&jsonp=jsonp'.format(bvid)
        res = requests.get(url, headers=headers).json()
        return res['data'][0]['cid']

    # 获得一个视频的基本信息
    def get_info(self, cid, bvid):
        print("开始获取基本信息", self.tid)
        vinfo = dict()
        url = 'https://api.bilibili.com/x/web-interface/view?cid={}&bvid={}'.format(cid, bvid)

        # proxies = proxies，尝试使用代理池
        res = requests.get(url, headers=headers).json()
        if res is None:
            print('获得基本信息错误')
            return vinfo

        data = res['data']
        vinfo['title'] = data['title']  # 视频标题
        time_local = time.localtime(data['pubdate'])
        vinfo['更新日期'] = time.strftime('%Y-%m-%d %H:%M:%S', time_local)  # 发布日期
        vinfo['封面图'] = data['pic']
        vinfo['aid'] = data['aid']
        vinfo['描述'] = data['desc']
        vinfo['up主'] = data['owner']['name']
        vinfo['cid'] = data['cid']
        vinfo['播放量'] = data['stat']['view']
        vinfo['弹幕数'] = data['stat']['danmaku']
        vinfo['评论数'] = data['stat']['reply']
        vinfo['收藏'] = data['stat']['favorite']
        vinfo['硬币'] = data['stat']['coin']
        vinfo['分享'] = data['stat']['share']
        vinfo['喜欢'] = data['stat']['like']
        vinfo['dislike'] = data['stat']['dislike']
        print("基本信息解析结束", self.tid)
        return vinfo

    def get_dms(self, cid):
        print("开始获取弹幕信息", self.tid)
        url = 'https://api.bilibili.com/x/v1/dm/list.so?oid={}'.format(cid)
        res = requests.get(url, headers=headers).content
        sel = etree.HTML(res)
        dms = sel.xpath(r'//d/text()')
        print("弹幕解析结束", self.tid)
        return dms

    def get_replies(self, aid):
        print("开始爬取评论信息", self.tid)
        reps = []
        pn = 1
        while True:
            print('开始爬取第', pn, '页评论', self.tid)
            url = 'https://api.bilibili.com/x/v2/reply?jsonp=jsonp&pn={}&type=1&oid={}&sort=2'.format(pn, aid)
            res = requests.get(url, headers=headers).json()
            replies = res['data']['replies']
            if not replies:
                print('评论爬取完毕，共', pn, '页', self.tid)
                break
            for reply in replies:
                reps.append(reply['content']['message'])
                re_replies = reply['replies']
                if not re_replies:
                    continue
                for re_reply in re_replies:
                    reps.append(re_reply['content']['message'])
            # 下一页
            pn += 1
            time.sleep(3)
        return reps

    def parse(self, bvid):
        cid = self.get_cid(bvid)
        info = self.get_info(cid, bvid)

        json_info = json.dumps(info, ensure_ascii=False, indent=4, separators=(',', ':'))
        print(self.tid, '开始写入基本信息', bvid)
        self.save(bvid, '-------------------------------基本信息----------------------------\n')
        self.save(bvid, json_info)
        print(self.tid, '写入基本信息结束', bvid)

        aid = info['aid']
        reps = self.get_replies(aid)
        print(self.tid, '开始写入评论信息')
        json_info = json.dumps(reps, ensure_ascii=False, indent=4, separators=(',', ':'))
        self.save(bvid, '\n\n----------------------------评论信息---------------------------\n')
        self.save(bvid, json_info)
        print(self.tid, '写入评论信息结束')

        dms = self.get_dms(cid)
        json_info = json.dumps(dms, ensure_ascii=False, indent=4, separators=(',', ':'))
        print(self.tid, '开始写入弹幕信息')
        self.save(bvid, '\n\n----------------------------弹幕信息----------------------------\n')
        self.save(bvid, json_info)
        print(self.tid, '写入弹幕信息结束')

    # 保存到从文件里，可以拓展到写入多种存储介质
    def save(self, bvid, data):
        fname = '{}.txt'.format(bvid)
        try:
            with open(fname, 'a+', encoding='utf-8') as f:
                f.write(str(data))
            print('保存成功')
        except Exception as e:
            print('保存失败', e)


def get_bvids_url(mid, ps, pn):
    url = 'https://api.bilibili.com/x/space/arc/search?mid={}&ps={}&tid=0&pn={}&keyword=&order=pubdate&jsonp=jsonp'.\
        format(mid, ps, pn)
    return url


# 获得 up主所有视频的 bv 号
def get_bvids(mid):
    bvids = {}
    pn = 1
    while True:
        print('正在获取第', pn, '页 bvid')

        bv_url = get_bvids_url(mid, ps=30, pn=pn)
        res = requests.get(bv_url, headers=headers, proxies=proxies).json()
        vlist = res['data']['list']['vlist']
        if not vlist:
            break

        for item in vlist:
            print('获得 bvid', item['bvid'])
            if bvids[pn] is None:
                bvids[pn] = []
            bvids[pn].append(item['bvid'])

        # 进入下一页
        pn += 1
        time.sleep(3)

    print('获取', mid, '所有视频 bvid 结束')
    return bvids


def sig_handler(signum, frame):
    global stop
    stop = True
    exit(1)


def main(mid):
    bvid_queue = Queue()
    bvids = get_bvids(mid)
    tids = []
    for pn in bvids.keys():
        tids.append('thread-{}'.format(pn))
        for bvid in bvids[pn]:
            bvid_queue.put(bvid)

    threads = []
    for tid in tids:
        t = Parser(tid, bvid_queue)
        t.start()
        threads.append(t)

    bvid_queue.join()  # 阻塞直到 queue 里的  bvid 取完 (bv 号)
    for tt in threads:
        tt.join()
    print("craw come to the end ^_^")


if __name__ == '__main__':
    signal.signal(signal.SIGINT, sig_handler)
    signal.signal(signal.SIGTERM, sig_handler)
    # 输入 up 主的 userid，如 7584632
    mid = sys.argv[1]
    if not mid:
        print('enter userid, pls')
        exit(-1)
    main(mid)
