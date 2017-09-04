# -*- coding: utf-8 -*-
from enum import Enum
import os

import urlparse
import psycopg2

from error import error

import collections

class kw_dict_mgr(object):

    def __init__(self, scheme, db_url):
        urlparse.uses_netloc.append(scheme)
        self.url = urlparse.urlparse(db_url)
        self._set_connection()




    def sql_cmd_only(self, cmd):
        return self.sql_cmd(cmd, None)

    def sql_cmd(self, cmd, dict):
        self._set_connection()
        self.cur.execute(cmd, dict)
        try:
            result = self.cur.fetchall()
        except psycopg2.ProgrammingError as ex:
            if ex.message == 'no results to fetch':
                result = None
            else:
                raise ex
        
        self._close_connection()
        return result



    @property
    def table_structure(self):
        cmd = u'CREATE TABLE keyword_dict( \
                id SERIAL, \
                keyword VARCHAR(500), \
                reply VARCHAR(500), \
                deleted BOOLEAN NOT NULL DEFAULT FALSE, \
                override BOOLEAN NOT NULL DEFAULT FALSE, \
                admin BOOLEAN NOT NULL DEFAULT FALSE, \
                used_count INTEGER NOT NULL, \
                creator VARCHAR(33) NOT NULL, \
                is_pic_reply BOOLEAN DEFAULT FALSE, \
                is_sticker_kw BOOLEAN DEFAULT FALSE, \
                deletor VARCHAR(33), \
                created_time TIMESTAMP DEFAULT NOW() AT TIME ZONE \'CCT\', \
                disabled_time TIMESTAMP, \
                last_call TIMESTAMP);'
        return cmd

    def insert_keyword(self, keyword, reply, creator_id, is_top, is_sticker_kw, is_pic_reply):
        keyword = keyword.replace('\\', '\\\\').replace(r'\\n', '\n')
        reply = reply.replace('\\', '\\\\').replace(r'\\n', '\n')
        is_illegal_reply_attachment = lambda reply_obj: reply_obj['attachment'] is not None and reply_obj['attachment'] > 25

        if keyword.replace(' ', '') == '':
            return error.main.invalid_thing_with_correct_format(u'關鍵字', u'字數大於0，但小於500字的字串', keyword)
        elif reply.replace(' ', '') == '':
            return error.main.invalid_thing_with_correct_format(u'回覆', u'字數大於0，但小於500字的字串', keyword)
        elif is_illegal_reply_attachment(kw_dict_mgr.split_reply(reply)):
            return error.main.invalid_thing_with_correct_format(u'圖片回覆附加文字', u'字數大於0，但小於25字的字串', keyword)
        else:
            cmd = u'INSERT INTO keyword_dict(keyword, reply, creator, used_count, admin, is_sticker_kw, is_pic_reply) \
                    VALUES(%(kw)s, %(rep)s, %(cid)s, 0, %(sys)s, %(stk_kw)s, %(pic_rep)s) \
                    RETURNING *;'
            cmd_dict = {'kw': keyword, 'rep': reply, 'cid': creator_id, 'sys': is_top, 'stk_kw': is_sticker_kw, 'pic_rep': is_pic_reply}
            cmd_override = u'UPDATE keyword_dict SET override = TRUE, deletor = %(dt)s, disabled_time = NOW() AT TIME ZONE \'CCT\' \
                             WHERE keyword = %(kw)s AND deleted = FALSE AND override = FALSE AND admin = %(adm)s'
            cmd_override_dict = {'kw': keyword, 'dt': creator_id, 'adm': is_top}
            self.sql_cmd(cmd_override, cmd_override_dict)
            result = self.sql_cmd(cmd, cmd_dict)

            return result

    def get_reply(self, keyword, is_sticker_kw):
        keyword = keyword.replace('\\', '\\\\').replace(r'\\n', '\n')
        keyword = keyword.replace('\\', '\\\\').replace(r'\\n', '\n')
        cmd = u'SELECT * FROM keyword_dict \
                WHERE keyword = %(kw)s AND deleted = FALSE AND override = FALSE AND is_sticker_kw = %(stk_kw)s\
                ORDER BY admin DESC, id DESC;'
        db_dict = {'kw': keyword, 'stk_kw': is_sticker_kw}
        result = self.sql_cmd(cmd, db_dict)
        if len(result) > 0:
            cmd_update = u'UPDATE keyword_dict SET used_count = used_count + 1, last_call = NOW() AT TIME ZONE \'CCT\' WHERE id = %(id)s AND (EXTRACT(EPOCH FROM (NOW() AT TIME ZONE \'CCT\' - last_call)) > 5 OR last_call IS NULL)'
            cmd_update_dict = {'id': result[0][int(kwdict_col.id)]}
            self.sql_cmd(cmd_update, cmd_update_dict)
            return result
        else:
            return None

    def search_keyword(self, keyword):
        keyword = keyword.replace('\\', '\\\\').replace(r'\\n', '\n')
        cmd = u'SELECT * FROM keyword_dict WHERE keyword LIKE %(kw)s OR reply LIKE %(kw)s ORDER BY id DESC;'
        cmd_dict = {'kw': '%' + keyword + '%'}
        result = self.sql_cmd(cmd, cmd_dict)
        return result

    def search_sticker_keyword(self, sticker_id):
        cmd = u'SELECT * FROM keyword_dict WHERE keyword = %(kw)s AND is_sticker_kw = TRUE ORDER BY id DESC;'
        cmd_dict = {'kw': sticker_id}
        result = self.sql_cmd(cmd, cmd_dict)
        return result

    def search_keyword_index(self, startIndex, endIndex):
        cmd = u'SELECT * FROM keyword_dict WHERE id >= %(si)s AND id <= %(ei)s ORDER BY id DESC;'
        cmd_dict = {'si': startIndex, 'ei': endIndex}
        result = self.sql_cmd(cmd, cmd_dict)
        return result

    def get_info(self, keyword):
        keyword = keyword.replace('\\', '\\\\').replace(r'\\n', '\n')
        cmd = u'SELECT * FROM keyword_dict WHERE keyword = %(kw)s OR reply = %(kw)s ORDER BY id DESC;'
        cmd_dict = {'kw': keyword}
        result = self.sql_cmd(cmd, cmd_dict)
        return result

    def get_info_id(self, id):
        cmd = u'SELECT * FROM keyword_dict WHERE id = %(id)s ORDER BY id DESC;'
        cmd_dict = {'id': id}
        result = self.sql_cmd(cmd, cmd_dict)
        return result

    def order_by_usedrank(self, limit=5000):
        cmd = u'SELECT *, RANK() OVER (ORDER BY used_count DESC) AS used_rank FROM keyword_dict ORDER BY used_rank ASC LIMIT %(limit)s;'
        cmd_dict = {'limit': limit}
        
        result = self.sql_cmd(cmd, cmd_dict)
        return result

    def user_created_rank(self, limit=50):
        """[0]=Rank, [1]=User ID, [2]=Count, [3]=Total Used Count, [4]=Used Count per Pair"""
        cmd = u' SELECT RANK() OVER (ORDER BY created_count DESC), *, ROUND(total_used / CAST(created_count as NUMERIC), 2) FROM (SELECT creator, COUNT(creator) AS created_count, SUM(used_count) AS total_used FROM keyword_dict GROUP BY creator ORDER BY created_count DESC) AS FOO LIMIT %(limit)s'
        cmd_dict = {'limit': limit}
        result = self.sql_cmd(cmd, cmd_dict)
        return result

    def most_used(self):
        cmd = u'SELECT * FROM keyword_dict WHERE used_count = (SELECT MAX(used_count) FROM keyword_dict) AND override = FALSE AND deleted = FALSE;'
        result = self.sql_cmd_only(cmd)
        return result

    def least_used(self):
        cmd = u'SELECT * FROM keyword_dict WHERE used_count = (SELECT MIN(used_count) FROM keyword_dict) AND override = FALSE AND deleted = FALSE ORDER BY id ASC'
        result = self.sql_cmd_only(cmd)
        return result

    def recently_called(self, limit=10):
        cmd = u'SELECT * FROM keyword_dict WHERE last_call IS NOT NULL ORDER BY last_call DESC LIMIT %(limit)s'
        cmd_dict = {'limit': limit}
        result = self.sql_cmd(cmd, cmd_dict)
        return result


    def delete_keyword(self, keyword, deletor, is_top):
        keyword = keyword.replace('\\', '\\\\').replace(r'\\n', '\n')
        cmd = u'UPDATE keyword_dict \
                SET deleted = TRUE, deletor = %(dt)s, disabled_time = NOW() AT TIME ZONE \'CCT\' \
                WHERE keyword = %(kw)s AND admin = %(top)s AND deleted = FALSE AND override = FALSE \
                RETURNING *;'
        cmd_dict = {'kw': keyword, 'top': is_top, 'dt': deletor}
        result = self.sql_cmd(cmd, cmd_dict)
        return result

    def delete_keyword_id(self, id, deletor, is_top):
        cmd = u'UPDATE keyword_dict \
                SET deleted = TRUE, deletor = %(dt)s, disabled_time = NOW() AT TIME ZONE \'CCT\' \
                WHERE id = %(id)s AND admin = %(top)s AND deleted = FALSE AND override = FALSE \
                RETURNING *;'
                
        cmd_dict = {'id': id, 'top': is_top, 'dt': deletor}
        result = self.sql_cmd(cmd, cmd_dict)
        return result

    def user_created_id_array(self, uid):
        cmd = u'SELECT id FROM keyword_dict WHERE creator = %(uid)s ORDER BY id ASC'
        cmd_dict = {'uid': uid}
        result = self.sql_cmd(cmd, cmd_dict)
        if len(result) > 0:
            result = [entry[0] for entry in result]
            return result
        else:
            return []

    def user_sort_by_created_pair(self):
        cmd = u'SELECT creator, COUNT(creator) FROM keyword_dict GROUP BY creator ORDER BY COUNT(creator) DESC;'
        result = self.sql_cmd_only(cmd)
        return result




    def row_count(self, is_active_only=False):
        cmd = u'SELECT COUNT(id) FROM keyword_dict{active};'.format(active=' WHERE deleted = FALSE AND override = FALSE' if is_active_only else '')
        result = self.sql_cmd_only(cmd)
        return int(result[0][0])

    def picture_reply_count(self, is_active_only=False):
        cmd = u'SELECT COUNT(id) FROM keyword_dict WHERE is_pic_reply = TRUE{active};'.format(active=' AND deleted = FALSE AND override = FALSE' if is_active_only else '')
        result = self.sql_cmd_only(cmd)
        return int(result[0][0])

    def sticker_keyword_count(self, is_active_only=False):
        cmd = u'SELECT COUNT(id) FROM keyword_dict WHERE is_sticker_kw = TRUE{active};'.format(active=' AND deleted = FALSE AND override = FALSE' if is_active_only else '')
        result = self.sql_cmd_only(cmd)
        return int(result[0][0])

    def used_count_sum(self):
        cmd = u'SELECT SUM(used_count) FROM keyword_dict;'
        result = self.sql_cmd_only(cmd)
        return int(result[0][0])

    def used_count_rank(self, id):
        cmd = u'SELECT used_rank FROM (SELECT RANK() OVER (ORDER BY used_count DESC) AS used_rank, * FROM keyword_dict) AS ranked WHERE id = %(id)s;'
        cmd_dict = {'id': id}
        result = self.sql_cmd(cmd, cmd_dict)
        return int(result[0][0])


    
    @staticmethod
    def list_keyword(data, limit=25):
        """return two object to access by [\'limited\'] and [\'full\']."""
        ret = {'limited': u'', 'full': u''}
        limited = False
        count = len(data)
        ret['full'] = u'共有{}筆結果\n\n'.format(count)

        if count <= 0:
            ret['limited'] = error.main.no_result()
        else:
            for index, row in enumerate(data, start=1):
                text = u'ID: {} - {} {}{}{}\n'.format(
                    row[int(kwdict_col.id)],
                    u'(貼圖ID {})'.format(row[int(kwdict_col.keyword)].decode('utf-8')) if row[int(kwdict_col.is_sticker_kw)] else row[int(kwdict_col.keyword)].decode('utf-8'),
                    u'[蓋]' if row[int(kwdict_col.override)] else u'',
                    u'[頂]' if row[int(kwdict_col.admin)] else u'',
                    u'[刪]' if row[int(kwdict_col.deleted)] else u'')

                ret['full'] += text

                if not limited:
                    ret['limited'] += text

                    if index >= limit:
                        ret['limited'] += u'...(還有{}筆)'.format(count - limit)
                        limited = True

        return ret

    @staticmethod
    def list_keyword_recently_called(data):
        ret = u'\n'.join([u'ID: {} - {} @{}'.format(row[int(kwdict_col.id)], 
                                                    u'(貼圖ID {})'.format(row[int(kwdict_col.keyword)].decode('utf-8')) if row[int(kwdict_col.is_sticker_kw)] else row[int(kwdict_col.keyword)].decode('utf-8'), 
                                                    row[int(kwdict_col.last_call)]) for row in data])

        return ret

    @staticmethod
    def entry_basic_info(entry_row):
        reply_splitter = ' '
        text = u'ID: {}\n'.format(entry_row[int(kwdict_col.id)])

        kw = entry_row[int(kwdict_col.keyword)].decode('utf-8')
        reply_iter = kw_dict_mgr.split_reply(entry_row[int(kwdict_col.reply)])
        reply_iter_attachment = reply_iter['attachment']
        is_pic_reply = entry_row[int(kwdict_col.is_pic_reply)]

        if not entry_row[int(kwdict_col.is_sticker_kw)]:
            text += u'關鍵字: {}\n'.format(kw)
        else:
            text += u'關鍵字: (貼圖ID: {})\n'.format(kw)

        text += u'回覆{}: {}'.format(u'圖片URL' if is_pic_reply else u'文字',
                                     reply_iter['main'])

        if reply_iter_attachment is not None and is_pic_reply:
            text += u'回覆文字: {}'.format(reply_iter_attachment)

        return text

    @staticmethod
    def entry_detailed_info(kwd_mgr, line_api_proc, entry_row):
        detailed = kw_dict_mgr.entry_basic_info(entry_row) + u'\n\n'
        detailed += u'屬性:\n'
        detailed += u'{} {} {}\n\n'.format(u'[ 置頂 ]' if entry_row[int(kwdict_col.admin)] else u'[ - ]',
                                        u'[ 覆蓋 ]' if entry_row[int(kwdict_col.override)] else u'[ - ]',
                                        u'[ 刪除 ]' if entry_row[int(kwdict_col.deleted)] else u'[ - ]')
        detailed += u'呼叫次數: {} (第{}名)\n'.format(entry_row[int(kwdict_col.used_count)], 
                                                       kwd_mgr.used_count_rank(entry_row[int(kwdict_col.id)]))
            
        if entry_row[int(kwdict_col.last_call)] is not None:
            detailed += u'最後呼叫時間:\n{}\n'.format(entry_row[int(kwdict_col.last_call)])

        creator_profile = line_api_proc.profile(entry_row[int(kwdict_col.creator)])
        detailed += u'\n製作者LINE使用者名稱:\n{}\n'.format(error.main.line_account_data_not_found() if creator_profile is None else creator_profile.display_name)
        detailed += u'製作者LINE UUID:\n{}\n'.format(entry_row[int(kwdict_col.creator)])
        detailed += u'製作時間:\n{}'.format(entry_row[int(kwdict_col.created_time)])

        if entry_row[int(kwdict_col.deletor)] is not None:
            deletor_profile = line_api_proc.profile(entry_row[int(kwdict_col.deletor)]) 
            detailed += u'\n刪除者LINE使用者名稱:\n{}\n'.format(error.main.line_account_data_not_found() if deletor_profile is None else deletor_profile.display_name)
            detailed += u'刪除者LINE UUID:\n{}\n'.format(entry_row[int(kwdict_col.deletor)])
            detailed += u'刪除時間:\n{}'.format(entry_row[int(kwdict_col.disabled_time)])

        return detailed

    @staticmethod
    def list_keyword_info(kwd_mgr, line_api_proc, data, limit=3):
        """return two object to access by [\'limited\'] and [\'full\']."""
        ret = {'limited': u'', 'full': u''}
        limited = False
        count = len(data)
        separator = u'====================\n'
        ret['full'] = u'共{}筆資料\n'.format(count)

        if count <= 0:
            ret['limited'] = error.main.no_result()
        else:
            for index, row in enumerate(data, start=1):
                text = separator
                text += kw_dict_mgr.entry_detailed_info(kwd_mgr, line_api_proc, row)
                text += u'\n'
                ret['full'] += text

                if not limited:
                    ret['limited'] += text

                    if index >= limit:
                        ret['limited'] += separator
                        ret['limited'] += u'還有{}筆資料沒有顯示。'.format(count - limit)
                        limited = True

        return ret

    @staticmethod
    def list_keyword_ranking(data):
        text = u'呼叫次數排行 (前{}名):'.format(len(data))

        for row in data:
            text += u'\n第{}名 - ID: {} - {} ({}次{})'.format(
                row[int(kwdict_col.used_rank)],
                row[int(kwdict_col.id)],
                u'(貼圖ID {id})'.format(id=row[int(kwdict_col.keyword)]) if row[int(kwdict_col.is_sticker_kw)] else row[int(kwdict_col.keyword)].decode('utf-8'), 
                row[int(kwdict_col.used_count)],
                u' - 已固定' if row[int(kwdict_col.deleted)] or row[int(kwdict_col.override)] else '')

        return text

    @staticmethod
    def list_user_created_ranking(line_api, data):
        text = u'回覆組製作排行 (前{}名):'.format(len(data))

        for row in data:
            profile = line_api.profile(row[1])
            if profile is None:
                uname = error.main.line_account_data_not_found()
            else:
                uname = profile.display_name
            text += u'\n\n第{}名 - {}\n製作{}組 | 共使用{}次 | 平均每組被使用{}次'.format(row[0], uname, row[2], row[3], row[4])

        return text

    

    @staticmethod
    def sticker_png_url(sticker_id):
        return 'https://sdl-stickershop.line.naver.jp/stickershop/v1/sticker/{stk_id}/android/sticker.png'.format(stk_id=sticker_id)
    
    @staticmethod
    def sticker_id(sticker_url):
        return sticker_url.replace('https://sdl-stickershop.line.naver.jp/stickershop/v1/sticker/', '').replace('/android/sticker.png', '')

    @staticmethod
    def split_reply(reply_text_in_db):
        """
        return:
            ['main'] = main part of reply
            ['attachment'] = attachment text
        """
        from msg_handler.text_msg import split

        reply_splitter = '  '
        split_iter = split(reply_text_in_db, reply_splitter, 2)

        return {'main': split_iter[0], 'attachment': split_iter[1]}



    def _close_connection(self):
        self.conn.commit()
        self.cur.close()
        self.conn.close()

    def _set_connection(self):
        self.conn = psycopg2.connect(
            database=self.url.path[1:],
            user=self.url.username,
            password=self.url.password,
            host=self.url.hostname,
            port=self.url.port
        )
        self.cur = self.conn.cursor()

class kwdict_col(Enum):
    id = 0
    keyword = 1
    reply = 2
    deleted = 3
    override = 4
    admin = 5
    used_count = 6
    creator = 7
    is_pic_reply = 8
    is_sticker_kw = 9
    deletor = 10
    created_time = 11
    disabled_time = 12
    last_call = 13

    used_rank = 14

    def __int__(self):
        return self.value
