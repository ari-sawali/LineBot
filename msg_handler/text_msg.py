# -*- coding: utf-8 -*-
import errno, os, sys
import validators
import urllib
from urlparse import urlparse
import requests
from datetime import datetime, timedelta
from collections import OrderedDict
import socket

from flask import request, url_for
import hashlib 

from linebot import (
    LineBotApi, WebhookHandler, exceptions
)
from linebot.models import (
    MessageEvent, TextMessage, TextSendMessage,
    SourceUser, SourceGroup, SourceRoom,
    TemplateSendMessage, ConfirmTemplate, MessageTemplateAction,
    ButtonsTemplate, URITemplateAction, PostbackTemplateAction,
    CarouselTemplate, CarouselColumn, PostbackEvent,
    StickerMessage, StickerSendMessage, LocationMessage, LocationSendMessage,
    ImageMessage, VideoMessage, AudioMessage,
    UnfollowEvent, FollowEvent, JoinEvent, LeaveEvent, BeaconEvent
)

from db import kw_dict_mgr, kwdict_col, group_ban, gb_col, message_tracker, msg_track_col

from error import error
from bot import system, webpage_auto_gen
from bot.system import line_api_proc, system_data, string_can_be_float, string_can_be_int

# tool import
from tool import mff, random_gen
import tool.curr_exc
from db.msg_track import msg_event_type

class text_msg(object):
    def __init__(self, flask_app, api_proc, kw_dict_mgr, 
                 group_ban, msg_trk, oxford_obj, permission_key_list, 
                 system_data, game_object, webpage_generator,
                 imgur_api_proc):
        self._flask_app = flask_app

        self.kwd = kw_dict_mgr
        self.gb = group_ban
        self.msg_trk = msg_trk
        self.oxford_obj = oxford_obj
        self.permission_verifier = system.permission_verifier(permission_key_list)
        self.api_proc = api_proc
        self.system_data = system_data
        self.game_object = game_object
        self.webpage_generator = webpage_generator
        self.imgur_api_proc = imgur_api_proc

    def S(self, src, params):
        key = params.pop(1)
        sql = params[1]

        if isinstance(src, SourceUser) and self.permission_verifier.permission_level(key) >= system.permission.bot_admin:
            results = self.kwd.sql_cmd_only(sql)
            text = u'資料庫指令:\n{}\n\n'.format(sql)
            if results is not None and len(results) > 0:
                text += u'輸出結果(共{}筆):'.format(len(results))
                for result in results:
                    text += u'\n[{}]'.format(', '.join(str(s).decode('utf-8') for s in result))
            else:
                text += error.main.no_result()
        else:
            text = error.main.restricted(3)

        return text

    def A(self, src, params, pinned=False):
        new_uid = line_api_proc.source_user_id(src)
        
        if not line_api_proc.is_valid_user_id(new_uid):
            text = error.main.unable_to_receive_user_id()
        else:
            if params[4] is not None:
                action_kw = params[1]
                kw = params[2]
                action_rep = params[3]
                rep = params[4]
                rep_obj = kw_dict_mgr.split_reply(rep)

                is_stk_int = system.string_can_be_int(kw)
                is_kw_pic_hash = len(kw) == 56
                 
                if action_kw != 'PIC':
                    results = None
                    text = error.main.incorrect_param(u'參數1', u'PIC')
                elif not is_stk_int and not is_kw_pic_hash:
                    results = None
                    text = error.main.incorrect_param(u'參數2', u'整數數字或共計56字元的16進制SHA224檔案雜湊碼')
                elif action_rep != 'PIC':
                    results = None
                    text =  error.main.incorrect_param(u'參數3', u'PIC')
                else:
                    rep_pic_url = rep_obj['main']

                    if system.string_can_be_int(rep_pic_url):
                        rep = rep.replace(rep_pic_url, kw_dict_mgr.sticker_png_url(rep_pic_url))
                        url_val_result = True
                    else:
                        url_val_result = url_val_result = True if validators.url(rep_pic_url) and urlparse(rep_pic_url).scheme == 'https' else False

                    if type(url_val_result) is bool and url_val_result:
                        results = self.kwd.insert_keyword(kw, rep, new_uid, pinned, is_stk_int, True, is_kw_pic_hash)
                    else:
                        results = None
                        text = error.main.incorrect_param(u'參數4', u'HTTPS協定，並且是合法的網址')
            elif params[3] is not None:
                rep = params[3]
                rep_obj = kw_dict_mgr.split_reply(rep)

                if params[2] == 'PIC':
                    kw = params[1]
                    rep_pic_url = rep_obj['main']

                    if system.string_can_be_int(rep_pic_url):
                        rep = rep.replace(rep_pic_url, kw_dict_mgr.sticker_png_url(rep_pic_url))
                        url_val_result = True
                    else:
                        url_val_result = True if validators.url(rep_pic_url) and urlparse(rep_pic_url).scheme == 'https' else False

                    if type(url_val_result) is bool and url_val_result:
                        results = self.kwd.insert_keyword(kw, rep, new_uid, pinned, False, True)
                    else:
                        results = None
                        text = error.main.incorrect_param(u'參數3', u'HTTPS協定，並且是合法的網址')
                elif params[1] == 'PIC':
                    kw = params[2]

                    is_stk_int = system.string_can_be_int(kw)
                    is_kw_pic_hash = len(kw) == 56

                    if is_stk_int ^ is_kw_pic_hash:
                        results = self.kwd.insert_keyword(kw, rep, new_uid, pinned, is_stk_int, False, is_kw_pic_hash)
                    else:
                        results = None
                        text = error.main.incorrect_param(u'參數2', u'整數數字或共計56字元的16進制SHA224檔案雜湊碼')
                else:
                    text = error.main.unable_to_determine()
                    results = None
            elif params[2] is not None:
                kw = params[1]
                rep = params[2]

                results = self.kwd.insert_keyword(kw, rep, new_uid, pinned, False, False)
            else:
                results = None
                text = error.main.lack_of_thing(u'參數')

            if results is not None:
                if isinstance(results, (str, unicode)):
                    text = results
                else:
                    text = u'已新增回覆組。{}\n'.format(u'(置頂)' if pinned else '')
                    for result in results:
                        text += kw_dict_mgr.entry_basic_info(result)

        return text

    def M(self, src, params):
        key = params.pop(1)
        if not isinstance(src, SourceUser) or self.permission_verifier.permission_level(key) < system.permission.moderator:
            text = error.main.restricted(1)
        elif not line_api_proc.is_valid_user_id(line_api_proc.source_user_id(src)):
            text = error.main.unable_to_receive_user_id()
        else:
            text = self.A(src, params, True)

        return text

    def D(self, src, params, pinned=False):
        deletor_uid = line_api_proc.source_user_id(src)
        if not line_api_proc.is_valid_user_id(deletor_uid):
            text = error.main.unable_to_receive_user_id()
        else:
            if params[2] is None:
                kw = params[1]

                results = self.kwd.delete_keyword(kw, deletor_uid, pinned)
            else:
                action = params[1]

                if action == 'ID':
                    pair_id = params[2]

                    if system.string_can_be_int(pair_id):
                        results = self.kwd.delete_keyword_id(pair_id, deletor_uid, pinned)
                    else:
                        results = None
                        text = error.main.incorrect_param(u'參數2', u'整數數字')
                else:
                    results = None
                    text = error.main.incorrect_param(u'參數1', u'ID')

            if results is not None:
                for result in results:
                    line_profile = self.api_proc.profile(result[int(kwdict_col.creator)])

                    text = u'已刪除回覆組。{}\n'.format(u'(置頂)' if pinned else '')
                    text += kw_dict_mgr.entry_basic_info(result)
                    text += u'\n此回覆組由 {} 製作。'.format(
                         error.main.line_account_data_not_found() if line_profile is None else line_profile.display_name)
            else:
                if system.string_can_be_int(params[1]):
                    text = error.main.miscellaneous(u'偵測到參數1是整數。若欲使用ID作為刪除根據，請參閱小水母使用說明。')
                else:
                    text = error.main.pair_not_exist_or_insuffieicnt_permission()

        return text

    def R(self, src, params):
        key = params.pop(1)
        if not isinstance(src, SourceUser) or self.permission_verifier.permission_level(key) < system.permission.group_admin:
            text = error.main.restricted(2)
        elif not line_api_proc.is_valid_user_id(line_api_proc.source_user_id(src)):
            text = error.main.unable_to_receive_user_id()
        else:
            text = self.D(src, params, True)

        return text

    def Q(self, src, params):
        if params[2] is not None:
            si = params[1]
            ei = params[2]
            text = u'搜尋範圍: 【回覆組ID】介於【{}】和【{}】之間的回覆組。\n'.format(si, ei)

            try:
                begin_index = int(si)
                end_index = int(ei)

                if end_index - begin_index < 0:
                    results = None
                    text += error.main.incorrect_param(u'參數2', u'大於參數1的數字')
                else:
                    results = self.kwd.search_keyword_index(begin_index, end_index)
            except ValueError:
                results = None
                text += error.main.incorrect_param(u'參數1和參數2', u'整數數字')
        else:
            kw = params[1]
            text = u'搜尋範圍: 【關鍵字】或【回覆】包含【{}】的回覆組。\n'.format(kw)

            results = self.kwd.search_keyword(kw)

        if results is not None:
            q_list = kw_dict_mgr.list_keyword(results)
            text = q_list['limited']
            text += u'\n完整搜尋結果顯示: {}'.format(self.webpage_generator.rec_query(q_list['full']))
        else:
            if params[2] is not None:
                text = u'找不到和指定的ID範圍({}~{})有關的結果。'.format(si, ei)
            else:
                text = u'找不到和指定的關鍵字({})有關的結果。'.format(kw)

        return text

    def I(self, src, params):
        error_occurred = False
        if params[2] is not None:
            action = params[1]
            pair_id = params[2]
            text = u'搜尋條件: 【回覆組ID】為【{}】的回覆組。\n'.format(pair_id)

            if action != 'ID':
                results = None
                error_occurred = True
                text += error.main.invalid_thing_with_correct_format(u'參數1', u'ID', action)
            else:
                if system.string_can_be_int(pair_id):
                    results = self.kwd.get_info_id(pair_id)   
                else:
                    results = None
                    error_occurred = True
                    text += error.main.invalid_thing_with_correct_format(u'參數2', u'正整數', pair_id)
        else:
            kw = params[1]
            text = u'搜尋條件: 【關鍵字】或【回覆】為【{}】的回覆組。\n'.format(kw)

            results = self.kwd.get_info(kw)

        if results is not None:
            i_object = kw_dict_mgr.list_keyword_info(self.kwd, self.api_proc, results)
            text += i_object['limited']
            text += u'\n完整資訊URL: {}'.format(self.webpage_generator.rec_info(i_object['full']))
        elif not error_occurred:
            text = error.main.miscellaneous(u'查無相符資料。')

        return text

    def K(self, src, params):
        ranking_type = params[1]
        limit = params[2]

        try:
            limit = int(limit)
        except ValueError as err:
            text = error.main.incorrect_param(u'參數2(數量)', u'整數')
        else:
            Valid = True

            if ranking_type == 'USER':
                text = kw_dict_mgr.list_user_created_ranking(self.api_proc, self.kwd.user_created_rank(limit))
            elif ranking_type == 'KW':
                text = kw_dict_mgr.list_keyword_ranking(self.kwd.order_by_usedrank(limit))
            elif ranking_type == 'KWRC':
                text = kw_dict_mgr.list_keyword_recently_called(self.kwd.recently_called(limit))
            else:
                text = error.main.incorrect_param(u'參數1(種類)', u'USER(使用者排行)、KW(關鍵字排行)或KWRC(呼叫時間排行)')
                Valid = False

            if Valid:
                with self._flask_app.test_request_context():
                    text += u'\n\n完整使用者排名: {}\n完整關鍵字排名: {}\n完整最新呼叫表: {}'.format(
                        request.url_root + url_for('full_ranking', type='user')[1:],
                        request.url_root + url_for('full_ranking', type='used')[1:],
                        request.url_root + url_for('full_ranking', type='called')[1:])

        return text

    def P(self, src, params, oxr_client):
        wrong_param1 = error.main.invalid_thing_with_correct_format(u'參數1', u'MSG、KW、IMG、SYS或EXC', params[1])

        if params[1] is not None:
            category = params[1]

            if category == 'MSG':
                limit = 5

                sum_data = self.msg_trk.count_sum()
                tracking_data = message_tracker.entry_detail_list(self.msg_trk.order_by_recorded_msg_count(), limit, self.gb)

                if sum_data is not None:
                    text = u'【訊息流量統計】'
                    text += u'\n收到(無對應回覆組): {}則文字訊息 | {}則貼圖訊息'.format(sum_data[msg_event_type.recv_txt], sum_data[msg_event_type.recv_stk])
                    text += u'\n收到(有對應回覆組): {}則文字訊息 | {}則貼圖訊息'.format(sum_data[msg_event_type.recv_txt_repl], sum_data[msg_event_type.recv_stk_repl])
                    text += u'\n回覆: {}則文字訊息 | {}則貼圖訊息'.format(sum_data[msg_event_type.send_txt], sum_data[msg_event_type.send_stk])

                    text += u'\n\n【群組訊息統計資料 - 前{}名】\n'.format(limit)
                    text += tracking_data['limited']
                    text += u'\n\n完整資訊URL: {}'.format(self.webpage_generator.rec_info(tracking_data['full']))
                else:
                    text = u'沒有訊息量追蹤紀錄。'
            elif category == 'KW':
                kwpct = self.kwd.row_count()

                user_list = self.kwd.user_sort_by_created_pair()
                user_list_top = None if user_list is None else user_list[0]
                line_profile = self.api_proc.profile(user_list_top[0])
                
                limit = 10

                first = self.kwd.most_used()
                last = self.kwd.least_used()
                last_count = 0 if last is None else len(last)

                text = u'【回覆組相關統計資料】'
                text += u'\n\n已使用回覆組【{}】次'.format(self.kwd.used_count_sum())
                text += u'\n\n已登錄【{}】組回覆組\n【{}】組貼圖關鍵字 | 【{}】組圖片回覆'.format(
                    kwpct,
                    self.kwd.sticker_keyword_count(),
                    self.kwd.picture_reply_count())
                text += u'\n\n共【{}】組回覆組可使用 ({:.2%})\n【{}】組貼圖關鍵字 | 【{}】組圖片回覆'.format(
                    self.kwd.row_count(True),
                    self.kwd.row_count(True) / float(kwpct),
                    self.kwd.sticker_keyword_count(True),
                    self.kwd.picture_reply_count(True))
                
                if user_list_top is not None:
                    text += u'\n\n製作最多回覆組的LINE使用者ID:\n{}'.format(user_list_top[0])
                    text += u'\n製作最多回覆組的LINE使用者:\n{}【{}組 - {:.2%}】'.format(
                        error.main.line_account_data_not_found() if line_profile is None else line_profile.display_name,
                        user_list_top[1],
                        user_list_top[1] / float(kwpct))
                else:
                    text += u'\n查無LINE使用者回覆組製作資料。'

                if first is not None:
                    text += u'\n\n使用次數最多的回覆組【{}次，{}組】:\n'.format(first[0][int(kwdict_col.used_count)], len(first))
                    text += u'\n'.join([u'ID: {} - {}'.format(entry[int(kwdict_col.id)],
                                                             u'(貼圖ID {})'.format(entry[int(kwdict_col.keyword)].decode('utf-8')) if entry[int(kwdict_col.is_sticker_kw)] else entry[int(kwdict_col.keyword)].decode('utf-8')) for entry in first[0 : limit - 1]])
                else:
                    text += u'使用次數查詢失敗(最多)。'

                if last is not None:
                    text += u'\n\n使用次數最少的回覆組【{}次，{}組】:\n'.format(last[0][int(kwdict_col.used_count)], len(last))
                    text += u'\n'.join([u'ID: {} - {}'.format(entry[int(kwdict_col.id)],
                                                             u'(貼圖ID {})'.format(entry[int(kwdict_col.keyword)].decode('utf-8')) if entry[int(kwdict_col.is_sticker_kw)] else entry[int(kwdict_col.keyword)].decode('utf-8')) for entry in last[0 : limit - 1]])
                else:
                    text += u'使用次數查詢失敗(最少)。'

                if last_count - limit > 0:
                    text += u'\n...(還有{}組)'.format(last_count - limit)

                text += u'\n\n最近被使用的{}組回覆組:\n'.format(limit)
                text += kw_dict_mgr.list_keyword_recently_called(self.kwd.recently_called(limit))
            elif category == 'SYS':
                global game_object

                text = u'【系統統計資料 - 開機後重設】\n'
                text += u'開機時間: {} (UTC+8)\n'.format(self.system_data.boot_up)
                text += u'\n【自動產生網頁相關】\n瀏覽次數: {}'.format(self.system_data.webpage_viewed)
                text += u'\n\n【系統指令相關(包含呼叫失敗)】\n總呼叫次數: {}\n'.format(self.system_data.sys_cmd_called)
                text += u'\n'.join([u'指令{} - {}'.format(cmd, cmd_obj.count) for cmd, cmd_obj in self.system_data.sys_cmd_dict.items()])
                text += u'\n\n【內建小工具相關】\nMFF傷害計算輔助 - {}'.format(self.system_data.helper_cmd_dict['MFF'].count)
                text += u'\n計算機 - {}'.format(self.system_data.helper_cmd_dict['CALC'].count)
                text += u'\n\n【小遊戲相關】\n猜拳遊戲數量 - {}\n猜拳次數 - {}'.format(self.game_object.rps_instance_count, self.system_data.game_cmd_dict['RPS'].count)
            elif category == 'IMG':
                ip_address = socket.gethostbyname(socket.getfqdn(socket.gethostname()))
                
                user_limit = self.imgur_api_proc.user_limit
                user_remaining = self.imgur_api_proc.user_remaining
                user_reset = self.imgur_api_proc.user_reset
                client_limit = self.imgur_api_proc.client_limit
                client_remaining = self.imgur_api_proc.client_remaining

                text = u'【IMGUR API相關資料】\n'
                text += u'額度相關說明請參閱使用說明書(輸入"小水母"可以獲取連結)\n\n'

                text += u'連結IP: {}\n'.format(ip_address)
                text += u'IP可用額度: {} ({:.2%})\n'.format(user_remaining, float(user_remaining) / float(user_limit))
                text += u'IP上限額度: {}\n'.format(user_limit)
                text += u'IP積分重設時間: {} (UTC+8)\n\n'.format((user_reset + timedelta(hours=9)).strftime('%Y-%m-%d %H:%M:%S'))
                text += u'目前API擁有額度: {} ({:.2%})\n'.format(client_remaining, float(client_remaining) / float(client_limit))
                text += u'今日API上限額度: {}'.format(client_limit)
            elif category == 'EXC':
                usage_dict = oxr_client.get_usage_dict()
                text = tool.curr_exc.oxr.usage_str(usage_dict)
            else:
                text = wrong_param1
        else:
            text = wrong_param1

        return text

    def G(self, src, params):
        if params[1] is not None:
            gid = params[1]
        else:
            gid = line_api_proc.source_channel_id(src)

        if params[1] is None and isinstance(src, SourceUser):
            text = error.main.incorrect_channel(False, True, True)
        else:
            if line_api_proc.is_valid_room_group_id(gid):
                group_detail = self.gb.get_group_by_id(gid)

                uids = OrderedDict([(u'管理員', group_detail[int(gb_col.admin)]), 
                                    (u'副管I', group_detail[int(gb_col.moderator1)]), 
                                    (u'副管II', group_detail[int(gb_col.moderator2)]), 
                                    (u'副管III', group_detail[int(gb_col.moderator3)])])

                group_tracking_data = self.msg_trk.get_data(gid)
                text = message_tracker.entry_detail(group_tracking_data, self.gb)

                for txt, uid in uids.items():
                    if uid is not None:
                        prof = self.api_proc.profile(uid)
                        text += u'\n\n{}: {}\n'.format(txt, error.main.line_account_data_not_found() if prof is None else prof.display_name)
                        text += u'{} 使用者ID: {}'.format(txt, uid)
            else:
                text = error.main.invalid_thing_with_correct_format(u'群組/房間ID', u'R或C開頭，並且長度為33字元', gid)

        return text

    def GA(self, src, params):
        perm_dict = {3: u'權限: 開發者/機器人管理員',
                     2: u'權限: Group Admin',
                     1: u'權限: Group Moderator',
                     0: u'權限: User'}
        perm = int(self.permission_verifier.permission_level(params.pop(1)))
        pert = perm_dict[perm]

        param_count = len(params) - params.count(None)

        if isinstance(src, SourceUser):
            # Set bot auto-reply switch
            if perm >= 1 and param_count == 3:
                action = params[1].replace(' ', '')
                gid = params[2]
                pw = params[3]

                action_dict = {'SF': True, 'ST': False}
                status_silence = {True: u'停用', False: u'啟用'}

                if action in action_dict:
                    settarget = action_dict[action]
                    result = self.gb.set_silence(gid, str(settarget), pw)

                    if not isinstance(result, (str, unicode)) and result:
                        text = u'群組自動回覆功能已{}。\n\n群組/房間ID: {}'.format(status_silence[settarget], gid)
                    else:
                        text = u'群組靜音設定變更失敗。\n錯誤: {}\n\n群組/房間ID: {}\n'.format(gid, result)
                else:
                    text = error.main.invalid_thing(u'參數1(動作)', action)
            # Set new admin/moderator 
            elif perm >= 2 and param_count == 5:
                action = params[1].replace(' ', '')
                gid = params[2]
                new_uid = None if params[3] == 'DELETE' else params[3]
                pw = params[4]
                new_pw = None if params[5] == 'DELETE' else params[5]

                legal_action = ['SA', 'SM1', 'SM2', 'SM3', 'DM1', 'DM2', 'DM3']

                if action.startswith('S'):
                    action_dict = {legal_action[0]: (self.gb.change_admin, u'群組管理員'), 
                                   legal_action[1]: (self.gb.set_mod1, u'群組副管 1'), 
                                   legal_action[2]: (self.gb.set_mod2, u'群組副管 2'), 
                                   legal_action[3]: (self.gb.set_mod3, u'群組副管 3')}

                    line_profile = self.api_proc.profile(new_uid)

                    if line_profile is not None:
                        result = action_dict[action][0](gid, new_uid, pw, new_pw)
                        position = action_dict[action][1]

                        if not isinstance(result, (str, unicode)) and result:

                            text = u'{}已變更。\n'.format(position)
                            text += u'群組/房間ID: {}\n\n'.format(gid)
                            text += u'新{}使用者ID: {}\n'.format(position, new_uid)
                            text += u'新{}使用者名稱: {}\n\n'.format(position, line_profile.display_name)
                            text += u'新{}密碼: {}\n'.format(position, new_pw)
                            text += u'請記好密碼，嚴禁洩漏，或在群頻中直接開關群組自動回覆功能！'
                        else:
                            text = u'{}變更失敗。\n錯誤: {}'.format(position, result)
                    else:
                        text = error.main.line_account_data_not_found()
                elif action.startswith('D'):
                    action_dict = {legal_action[4]: (self.gb.set_mod1, u'群組副管 1'),
                                   legal_action[5]: (self.gb.set_mod2, u'群組副管 2'),
                                   legal_action[6]: (self.gb.set_mod3, u'群組副管 3')}
                    position = action_dict[action][1]

                    result = action_dict[action][0](gid, new_uid, pw, new_pw)
                    if not isinstance(result, (str, unicode)) and result:

                        text = u'{}已刪除。\n'.format(position)
                        text += u'群組/房間ID: {}'.format(gid)
                    else:
                        text = u'{}刪除失敗。\n錯誤: {}'.format(position, result)
                else:
                    text = error.main.invalid_thing(u'指令', action)
            else:
                text = error.main.miscellaneous(u'無對應指令。有可能是因為權限不足或是缺少參數而造成。')
        else:
            text = error.main.incorrect_channel()

        return pert, text

    def H(self, src, params):
        if params[1] is not None:
            uid = params[1]
            line_profile = self.api_proc.profile(uid)
            
            source_type = u'使用者詳細資訊'

            if not line_api_proc.is_valid_user_id(uid):
                text = error.main.invalid_thing_with_correct_format(u'使用者ID', u'U開頭，並且長度為33字元', uid)
            else:
                if line_profile is not None:
                    kwid_arr = self.kwd.user_created_id_array(uid)
                    if kwid_arr is None:
                        kwid_arr = [u'無']

                    text = u'使用者ID: {}\n'.format(uid)
                    text += u'使用者名稱: {}\n'.format(line_profile.display_name)
                    text += u'使用者頭貼網址: {}\n'.format(line_profile.picture_url)
                    text += u'使用者狀態訊息: {}\n\n'.format(line_profile.status_message)
                    text += u'使用者製作的回覆組ID: {}'.format(u', '.join(map(unicode, kwid_arr)))
                else:
                    text = u'找不到使用者ID - {} 的詳細資訊。'.format(uid)
        else:
            text = line_api_proc.source_channel_id(src)
            if isinstance(src, SourceUser):
                source_type = u'頻道種類: 使用者(私訊)'
            elif isinstance(src, SourceGroup):
                source_type = u'頻道種類: 群組'
            elif isinstance(src, SourceRoom):
                source_type = u'頻道種類: 房間'
            else:
                source_type = u'頻道種類: 不明'

        return [source_type, text]

    def SHA(self, src, params):
        target = params[1]

        if target is not None:
            text = hashlib.sha224(target.encode('utf-8')).hexdigest()
        else:
            text = error.main.incorrect_param(u'參數1', u'非空參數')

        return text

    def O(self, src, params):
        voc = params[1]

        if not self.oxford_obj.enabled:
            text = error.main.miscellaneous(u'牛津字典功能已停用。可能是因為超過單月查詢次數或無效的API密鑰。')
        else:
            j = self.oxford_obj.get_data_json(voc)

            if type(j) is int:
                code = j

                if code == 404:
                    text = error.main.no_result()
                else:
                    text = u'查詢字典時發生錯誤。\n\n狀態碼: {} ({}).'.format(code, httplib.responses[code])
            else:
                text = u''
                section_splitter = u'.................................................................'

                lexents = j['results'][0]['lexicalEntries']
                for lexent in lexents:
                    text += u'=={} ({})=='.format(lexent['text'], lexent['lexicalCategory'])
                    
                    if 'derivativeOf' in lexent:
                        derivative_arr = lexent['derivativeOf']
                        text += u'\nDerivative: {}'.format(', '.join([derivative_data['text'] for derivative_data in derivative_arr]))

                    lexentarr = lexent['entries']
                    for lexentElem in lexentarr:
                        if 'senses' in lexentElem:
                            sens = lexentElem['senses']
                            
                            text += u'\nDefinition:'
                            for index, sen in enumerate(sens, start=1):
                                if 'definitions' in sen:
                                    for de in sen['definitions']:
                                        text += u'\n{}. {} {}'.format(index, de, u'({})'.format(u', '.join(sen['registers'])) if u'registers' in sen else u'')
                                        
                                if 'crossReferenceMarkers' in sen:
                                    for crm in sen['crossReferenceMarkers']:
                                        text += u'\n{}. {} (Cross Reference Marker)'.format(index, crm)
                                
                                if 'examples' in sen:
                                    for ex in sen['examples']:
                                        text += u'\n------{}'.format(ex['text'])
                        else:
                            text += u'\n(Senses not found in dictionary.)'

                    text += u'\n{}\n'.format(section_splitter)

                text += u'Powered by Oxford Dictionary.'

        return text

    def RD(self, src, params):
        if params[2] is not None:
            if params[1].endswith('%') and params[1].count('%') == 1:
                opportunity = params[1].replace('%', '')
                scout_count = params[2]
                shot_count = 0
                miss_count = 0
                if not system.string_can_be_float(opportunity):
                    text = error.main.incorrect_param(u'參數1(機率)', u'百分比加上符號%')
                elif not system.string_can_be_float(scout_count):
                    text = error.main.incorrect_param(u'參數2(抽籤次數)', u'整數')
                elif int(scout_count) > 999999:
                    text = error.main.invalid_thing_with_correct_format(u'參數2(抽籤次數)', u'小於999999的整數', scout_count)
                else:
                    opportunity = float(opportunity) / 100.0
                    scout_count = int(scout_count)

                    for i in range(int(scout_count)):
                        result = random_gen.random_drawer.draw_probability(opportunity)
                        if result:
                            shot_count += 1
                        else:
                            miss_count += 1
                    text = u'抽籤機率【{:.2%}】\n抽籤結果【中{}次 | 失{}次】\n實際中率【{:.2%}】\n中1+機率【{:.2%}】\n中2+機率【{:.2%}】'.format(
                        opportunity, shot_count, miss_count, 
                        shot_count / float(scout_count), 
                        1 - (1 - opportunity) ** scout_count,
                        (1 - (1 - opportunity) ** (scout_count - 1)) * opportunity)
            else:
                start_index = params[1]
                end_index = params[2]
                if not start_index.isnumeric():
                    text = error.main.invalid_thing_with_correct_format(u'起始抽籤數字', u'整數', start_index)
                elif not end_index.isnumeric():
                    text = error.main.invalid_thing_with_correct_format(u'終止抽籤數字', u'整數', start_index)
                else:
                    text = u'抽籤範圍【{}~{}】\n抽籤結果【{}】'.format(start_index, end_index, random_gen.random_drawer.draw_number(start_index, end_index))
        elif params[1] is not None:
            text_splitter = '  '
            if text_splitter in params[1]:
                texts = params[1]
                text_list = texts.split(text_splitter)
                text = u'抽籤範圍【{}】\n抽籤結果【{}】'.format(', '.join(text_list), random_gen.random_drawer.draw_text(text_list))
            elif params[1].endswith('%') and params[1].count('%') == 1:
                opportunity = params[1].replace('%', '')
                text = u'抽籤機率【{}%】\n抽籤結果【{}】'.format(
                    opportunity, 
                    u'恭喜中獎' if random_gen.random_drawer.draw_probability(float(opportunity) / 100.0) else u'銘謝惠顧')
            else:
                text = error.main.invalid_thing(u'參數1', params[1])
        else:
            text = error.main.lack_of_thing(u'參數')

        return text

    def STK(self, src, params):
        last_sticker = self.system_data.get_last_sticker(line_api_proc.source_channel_id(src))
        if last_sticker is not None:
            text = u'最後一個貼圖的貼圖ID為{}。'.format(last_sticker)
        else:
            text = u'沒有登記到本頻道的最後貼圖ID。如果已經有貼過貼圖，則可能是因為機器人剛剛才啟動而造成。\n\n本次開機時間: {}'.format(self.system_data.boot_up)

        return text

    def PIC(self, src, params):
        last_pic_sha = self.system_data.get_last_pic_sha(line_api_proc.source_channel_id(src))
        if last_pic_sha is not None:
            text = u'最後圖片雜湊碼(SHA224)'
            return [text, last_pic_sha]
        else:
            text = u'沒有登記到本頻道的最後圖片雜湊。如果已經有貼過圖片，則可能是因為機器人剛剛才啟動而造成。\n\n本次開機時間: {}'.format(self.system_data.boot_up)
            return [text]

    def T(self, src, params):
        if params[1] is not None:
            text = params[1]

            if isinstance(text, unicode):
                # unicode to utf-8
                text = text.encode('utf-8')
            else:
                try:
                    # maybe utf-8
                    text = text.decode('utf-8').encode('utf-8')
                except UnicodeError:
                    # gbk to utf-8
                    text = text.decode('gbk').encode('utf-8')
        else:
            text = error.main.lack_of_thing(u'參數')
        
        return urllib.quote(text)

    def C(self, src, params, oxr_client):
        if params[3] is not None:
            amount = params[1]
            source_currency = params[2]
            target_currency = params[3]

            if not system.string_can_be_float(amount):
                text = error.main.invalid_thing_with_correct_format(u'轉換值', u'整數或小數', amount)
            elif not tool.curr_exc.oxr.is_legal_symbol_text(source_currency):
                text = error.main.invalid_thing_with_correct_format(u'原始值貨幣', u'3英文字元的貨幣代號', source_currency)
            elif not tool.curr_exc.oxr.is_legal_symbol_text(target_currency):
                text = error.main.invalid_thing_with_correct_format(u'目標值貨幣', u'3英文字元的貨幣代號', target_currency)
            else:
                text = oxr_client.convert(source_currency, target_currency, amount)['string']
        elif params[2] is not None:
            historical_date = params[1]
            target_symbol = params[2]

            if not system.string_can_be_int(historical_date) and not len(historical_date) == 8:
                text = error.main.invalid_thing_with_correct_format(u'日期', u'8位數整數，代表(年年年年月月日日)', historical_date)
            elif not tool.curr_exc.oxr.is_legal_symbol_text(target_symbol):
                text = error.main.invalid_thing_with_correct_format(u'貨幣單位', u'3字元貨幣代號，多貨幣時以空格分隔', target_symbol)
            else:
                data_dict = oxr_client.get_historical_dict(historical_date, target_symbol)
                text = tool.curr_exc.oxr.historical_str(data_dict)
        elif params[1] is not None:
            param = params[1]
            if param == '$':
                available_currencies_dict = oxr_client.get_available_currencies_dict()
                text = tool.curr_exc.oxr.available_currencies_str(available_currencies_dict)
            elif system.string_can_be_int(param) and len(param) == 8:
                historical_all_dict = oxr_client.get_historical_dict(param)
                text = tool.curr_exc.oxr.historical_str(historical_all_dict)
            elif tool.curr_exc.oxr.is_legal_symbol_text(param):
                latset_dict = oxr_client.get_latest_dict(param)
                text = tool.curr_exc.oxr.latest_str(latset_dict)
            else:
                text = error.main.incorrect_param(u'參數1', u'貨幣符號($)、希望幣種(NTD, USD) 或 希望歷史時間(20170505)')
        else:
            latset_dict = oxr_client.get_latest_dict()
            text = tool.curr_exc.oxr.latest_str(latset_dict)

        return text


    def split_verify(self, cmd, splitter, param_text):
        if cmd not in self.system_data.sys_cmd_dict:
            return error.main.invalid_thing(u'指令', cmd)

        max_prm = self.system_data.sys_cmd_dict[cmd].split_max
        min_prm = self.system_data.sys_cmd_dict[cmd].split_min
        params = split(param_text, splitter, max_prm)

        if min_prm > len(params) - params.count(None):
            return error.main.lack_of_thing(u'參數')

        params.insert(0, None)
        return params


class helper(object):
    def __init__(self, sys_data):
        self.system_data = sys_data

    def MFF(self, params):
        if params.count(not None) == 0:
            return [TextSendMessage(text=mff.mff_dmg_calc.help_code()),
                    TextSendMessage(text=u'下則訊息是訊息範本，您可以直接將其複製，更改其內容，然後使用。或是遵照以下格式輸入資料。\n\n{代碼(參見上方)} {參數}(%)\n\n例如:\nMFF\nSKC 100%\n魔力 1090%\n魔力 10.9\n\n欲察看更多範例，請前往 https://sites.google.com/view/jellybot/mff傷害計算'),
                    TextSendMessage(text=mff.mff_dmg_calc.help_sample())]
        else:
            content = params[0]

            job = mff.mff_dmg_calc.text_job_parser(content)

            dmg_calc_dict = [[u'破防前非爆擊(弱點屬性)', mff.mff_dmg_calc.dmg_weak(job)],
                             [u'破防前爆擊(弱點屬性)', mff.mff_dmg_calc.dmg_crt_weak(job)],
                             [u'已破防非爆擊(弱點屬性)', mff.mff_dmg_calc.dmg_break_weak(job)],
                             [u'已破防爆擊(弱點屬性)', mff.mff_dmg_calc.dmg_break_crt_weak(job)],
                             [u'破防前非爆擊(非弱點屬性)', mff.mff_dmg_calc.dmg(job)],
                             [u'破防前爆擊(非弱點屬性)', mff.mff_dmg_calc.dmg_crt(job)],
                             [u'已破防非爆擊(非弱點屬性)', mff.mff_dmg_calc.dmg_break(job)],
                             [u'已破防爆擊(非弱點屬性)', mff.mff_dmg_calc.dmg_break_crt(job)]]

            text = u'傷害表:'
            for title, value in dmg_calc_dict:
                text += u'\n\n'
                text += u'{}\n首發: {:.0f}\n連發: {:.0f}\n累積傷害(依次): {}'.format(
                    title,
                    value['first'],
                    value['continual'],
                    u', '.join('{:.0f}'.format(x) for x in value['list_of_sum']))
            
            return TextSendMessage(text=text)

    def split_verify(self, cmd, splitter, param_text):
        if cmd not in self.system_data.helper_cmd_dict:
            return error.main.invalid_thing(u'指令', cmd)

        max_prm = self.system_data.helper_cmd_dict[cmd].split_max
        min_prm = self.system_data.helper_cmd_dict[cmd].split_min
        params = split(param_text, splitter, max_prm)

        if min_prm > len(params) - params.count(None):
            return error.main.lack_of_thing(u'參數')

        params.insert(0, None)
        return params


class oxford_dict(object):
    def __init__(self, language):
        """
        Set environment variable "OXFORD_ID", "OXFORD_KEY" as presented api id and api key.
        """
        self._language = language
        self._url = 'https://od-api.oxforddictionaries.com:443/api/v1/entries/{}/'.format(self._language)
        self._id = os.getenv('OXFORD_ID', None)
        self._key = os.getenv('OXFORD_KEY', None)
        self._enabled = False if self._id is None or self._key is None else True

    def get_data_json(self, word):
        url = self._url + word.lower()
        r = requests.get(url, headers = {'app_id': self._id, 'app_key': self._key})
        status_code = r.status_code

        if status_code != requests.codes.ok:
            return status_code
        else:
            return r.json()

    @property
    def enabled(self):
        return self._enabled

    @enabled.setter
    def enabled(self, value):
        self._enabled = value


 
def split(text, splitter, size):
    list = []

    if text is not None:
        for i in range(size):
            if splitter not in text or i == size - 1:
                list.append(text)
                break
            list.append(text[0:text.index(splitter)])
            text = text[text.index(splitter)+len(splitter):]

    while len(list) < size:
        list.append(None)
    
    return list

