# -*- coding: utf-8 -*-

from cgi import escape
from collections import OrderedDict
import time
from datetime import datetime, timedelta
from flask import Flask, url_for, render_template
from flask.globals import current_app
from linebot.models import TextSendMessage

from error import error

import db

class webpage_manager(object):
    LATEX_SPLITTER = '(LaTeX_END)'

    def __init__(self, flask_app, mongo_db_uri):
        self._flask_app = flask_app
        self._route_method_name = 'get_webpage'
        self._error_list_route_name = 'get_error_list'

        self._system_stats = db.system_statistics(mongo_db_uri)
        self._content_holder = db.webpage_content_holder(mongo_db_uri)

    def rec_error(self, error_instance, decoded_traceback, occurred_at, simplified=None):
        """Get error webpage url + error list url"""
        self._system_stats.webpage_viewed(db.webpage_content_type.ERROR)
        with self._flask_app.app_context():
            err_detail = u'錯誤發生時間: {}\n'.format(datetime.now() + timedelta(hours=8))
            err_detail += u'頻道ID: {}\n\n'.format(occurred_at)
            err_detail += decoded_traceback
            if simplified is not None:
                err_detail += u'\n\n'
                try:
                    err_detail += simplified
                except UnicodeEncodeError:
                    err_detail += simplified.encode('utf-8')
                except UnicodeDecodeError:
                    err_detail += simplified.decode('utf-8')
            
            print '===================================='
            print 'ERROR CAPTURED.'
            print err_detail.encode('utf-8')
            print '===================================='

            error_url = self.rec_webpage(err_detail, db.webpage_content_type.ERROR, error_instance.__class__.__name__)

            return u'\n詳細錯誤URL: {}\n錯誤清單: {}'.format(error_url, url_for(self._error_list_route_name))
    
    def rec_webpage(self, content, type, short_description=None):
        """Return recorded webpage url."""
        self._system_stats.webpage_viewed(type)
        with self._flask_app.app_context():
            webpage_id = self._content_holder.rec_data(content, type, short_description)
            return url_for(self._route_method_name, seq_id=webpage_id)

    def get_error_dict(self):
        """
        { seq_id: url }
        """
        MAX_COUNT = 100
        return OrderedDict([(u'{} - {}'.format(data.timestamp.strftime('%Y-%m-%d %H:%M:%S'), data.short_description), url_for(self._route_method_name, seq_id=data.seq_id)) for data in self._content_holder.get_error_page_list(MAX_COUNT)])

    def get_webpage_data(self, id):
        if isinstance(id, (str, unicode)):
            id = int(id)
        webpage_data = self._content_holder.get_data(id)

        if webpage_data is None:
            return db.webpage_data.no_content_template()
        else:
            return webpage_data

    @staticmethod
    def render_webpage(page_data):
        content = page_data.content
        title = unicode(page_data.content_type)

        if page_data.content_type == db.webpage_content_type.LATEX:
            latex_script, normal_content = content.split(webpage_manager.LATEX_SPLITTER)
            return render_template('LaTeX.html', LaTeX_script=latex_script, Contents=webpage_manager.proc_str_to_render(normal_content), Title=title)
        elif page_data.content_type == db.webpage_content_type.STICKER_RANKING:
            content_data, foot = content[:-1], content[-1]
            return render_template('StickerRanking.html', Data=content_data, Foot=webpage_manager.proc_str_to_render(foot), Title=title)
        else:
            return render_template('WebPage.html', Contents=webpage_manager.proc_str_to_render(content), Title=title)

    @staticmethod
    def proc_str_to_render(s):
        return s.replace(' ', '&nbsp;').split('\n')

    @staticmethod
    def html_render_error_list(boot_up, error_dict):
        """
        { output_text: url }
        """
        return render_template('ErrorList.html', boot_up=boot_up, ErrorDict=error_dict)
