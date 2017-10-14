# -*- coding: utf-8 -*-

# TODO: keep webpage content in specified (7 days?) time, auto delete after data expired. Append expire date at the end of webpage

from enum import Enum
from error import error
from cgi import escape
from collections import defaultdict

import time
from datetime import datetime, timedelta
from flask import Flask, url_for, render_template
from flask.globals import current_app

from linebot.models import TextSendMessage

class webpage(object):
    def __init__(self, flask_app):
        self._flask_app = flask_app
        self._error_route = 'Error'
        self._query_route = 'FullQuery'
        self._info_route = 'FullInfo'
        self._text_route = 'Text'
        self._latex_route = 'LaTeX'
        self._page_content = {self._error_route: defaultdict(unicode), 
                              self._query_route: defaultdict(unicode), 
                              self._info_route: defaultdict(unicode), 
                              self._text_route: defaultdict(unicode), 
                              self._latex_route: defaultdict(unicode)}


    def rec_error(self, err_sum, decoded_traceback, channel_id):
        with self._flask_app.app_context():
            timestamp = str(int(time.time()) + 8*60*60)
            err_detail = u'錯誤發生時間: {}\n'.format(datetime.now() + timedelta(hours=8))
            err_detail += u'頻道ID: {}'.format(channel_id)
            err_detail += u'\n\n'
            err_detail += decoded_traceback
            
            print err_sum.encode('utf-8')
            print err_detail.encode('utf-8')
            self._page_content[self._error_route][timestamp] = err_detail

            err_list = u'詳細錯誤URL: {}\n錯誤清單: {}'.format(
                url_for('get_error_message', timestamp=timestamp),
                url_for('get_error_list'))
            
            return err_sum + u'\n\n' + err_list
    
    def rec_query(self, full_query):
        with self._flask_app.app_context():
            timestamp = str(int(time.time()))
            self._page_content[self._query_route][timestamp] = full_query
            return url_for('full_query', timestamp=timestamp)
    
    def rec_info(self, full_info):
        with self._flask_app.app_context():
            timestamp = str(int(time.time()))
            self._page_content[self._info_route][timestamp] = full_info
            return url_for('full_info', timestamp=timestamp)
    
    def rec_text(self, text_list):
        with self._flask_app.app_context():
            if not isinstance(text_list, (list, tuple)):
                text_list = [text_list]
    
            timestamp = str(int(time.time()))
            self._page_content[self._text_route][timestamp] = u'\n===============================\n'.join(
                [u'【Message {}】\n\n{}'.format(index, txt) for index, txt in enumerate(text_list, start=1)])
            
            return url_for('full_content', timestamp=timestamp)
    
    def rec_latex(self, latex):
        with self._flask_app.app_context():
            timestamp = str(int(time.time()))
            self._page_content[self._latex_route][timestamp] = latex
            
            return url_for('latex_webpage', timestamp=timestamp)

    def error_timestamp_list(self):
        sorted_list = sorted(self._page_content[self._error_route].keys(), key=self._page_content[self._error_route].get, reverse=True)
        return sorted_list

    def get_content(self, type, timestamp):
        timestamp = str(timestamp)
        content = None
        if type == content_type.Error:
            content = self._page_content[self._error_route].get(timestamp)
            type_chn = u'錯誤'
        elif type == content_type.Query:
            content = self._page_content[self._query_route].get(timestamp)
            type_chn = u'索引'
        elif type == content_type.Info:
            content = self._page_content[self._info_route].get(timestamp)
            type_chn = u'查詢詳細資料'
        elif type == content_type.Text:
            content = self._page_content[self._text_route].get(timestamp)
            type_chn = u'回傳文字'
        elif type == content_type.LaTeX:
            content = self._page_content[self._latex_route].get(timestamp)
            type_chn = u'製作LaTeX成像'

        if content is None:
            return error.webpage.no_content_at_time(type_chn, float(timestamp))
        else:
            return content

    @staticmethod
    def html_render(content, title=None):
        return render_template('WebPage.html', Contents=content.replace(' ', '&nbsp;').split('\n'), Title=title)

    @staticmethod
    def latex_render(latex_script):
        return render_template('LaTeX.html', LaTeX_script=latex_script)

    @staticmethod
    def html_render_error_list(boot_up, error_dict):
            """
            Error dict 
            key=timestamp
            value=URL
            """
            return render_template('ErrorList.html', boot_up=boot_up, ErrorDict=error_dict)

class content_type(Enum):
    Error = 0
    Query = 1
    Info = 2
    Text = 3
    LaTeX = 4

