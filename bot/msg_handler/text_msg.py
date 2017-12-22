# -*- coding: utf-8 -*-
import os, sys
import json
from datetime import datetime, timedelta
import hashlib
import re

from flask import request, url_for
import pymongo
import ast
from linebot.models import TextSendMessage

import tool
from error import error
import bot, db, ext

class special_text_handler(object):
    def __init__(self, mongo_db_uri, line_api_wrapper, weather_reporter):
        self._line_api_wrapper = line_api_wrapper
        self._weather_reporter = weather_reporter
        self._weather_config = db.weather_report_config(mongo_db_uri)
        self._system_stats = db.system_statistics(mongo_db_uri)

        self._special_keyword = {
            u'天氣': (self._handle_text_spec_weather, (False,)),
            u'詳細天氣': (self._handle_text_spec_weather, (True,))
        }

    def handle_text(self, event):
        """Return replied or not."""
        token = event.reply_token
        msg_text = event.message.text

        uid = bot.line_api_wrapper.source_user_id(event.source)

        spec = self._special_keyword.get(msg_text, None)
        
        if spec is not None:
            spec_func, spec_param = spec
            rep_text = spec_func(*(spec_param + (uid,)))

            if isinstance(rep_text, (str, unicode)):
                self._line_api_wrapper.reply_message_text(token, rep_text)
            else:
                self._line_api_wrapper.reply_message(token, rep_text)

            return True

        return False

    def _handle_text_spec_weather(self, detailed, uid):
        self._system_stats.extend_function_used(db.extend_function_category.REQUEST_WEATHER_REPORT)

        config_data = self._weather_config.get_config(uid) 
        if config_data is not None and len(config_data.config) > 0:
            ret = [self._weather_reporter.get_data_by_owm_id(cfg.city_id, tool.weather.output_config(cfg.mode), cfg.interval, cfg.data_range) for cfg in config_data.config]

            return u'\n==========\n'.join(ret)
        else:
            command_head = bot.msg_handler.text_msg_handler.HEAD + u'天氣查詢 '

            template_title = u'快速天氣查詢'
            template_title_alt = u'快速天氣查詢樣板，請使用手機查看。'
            template_actions = { 
                tool.weather.owm.DEFAULT_TAICHUNG.name: command_head + str(tool.weather.owm.DEFAULT_TAICHUNG.id),
                tool.weather.owm.DEFAULT_TAIPEI.name: command_head + str(tool.weather.owm.DEFAULT_TAIPEI.id),
                tool.weather.owm.DEFAULT_KAOHSIUNG.name: command_head + str(tool.weather.owm.DEFAULT_KAOHSIUNG.id),
                tool.weather.owm.DEFAULT_HONG_KONG.name: command_head + str(tool.weather.owm.DEFAULT_HONG_KONG.id),
                tool.weather.owm.DEFAULT_KUALA_LUMPER.name: command_head + str(tool.weather.owm.DEFAULT_KUALA_LUMPER.id),
                tool.weather.owm.DEFAULT_MACAU.name: command_head + str(tool.weather.owm.DEFAULT_MACAU.id)
            }

            if detailed:
                template_actions = { k: v + (u'詳' if detailed else u'簡') for k, v in template_actions.iteritems() }

            return bot.line_api_wrapper.wrap_template_with_action(template_actions, template_title_alt, template_title)

class text_msg_handler(object):
    # TODO: Check and modify all codes that will create shortcut action (see references of line_api_wrapper.wrap_template_with_action)
    # TODO: https://pypi.python.org/pypi/economics/

    HEAD = u'小水母 '
    REMOTE_SPLITTER = u'\n'

    def __init__(self, flask_app, config_manager, line_api_wrapper, mongo_db_uri, oxford_api, system_data, webpage_generator, imgur_api_wrapper, oxr_client, string_calculator, weather_reporter, file_tmp_path):
        self._mongo_uri = mongo_db_uri
        self._flask_app = flask_app
        self._config_manager = config_manager

        self._array_separator = self._config_manager.get(bot.config_category.KEYWORD_DICT, bot.config_category_kw_dict.ARRAY_SEPARATOR)

        self._system_data = system_data
        self._system_config = db.system_config(mongo_db_uri)
        self._system_stats = db.system_statistics(mongo_db_uri)
        self._stk_rec = db.sticker_recorder(mongo_db_uri)
        self._loop_prev = bot.infinite_loop_preventer(self._config_manager.getint(bot.config_category.SYSTEM, bot.config_category_system.DUPLICATE_CONTENT_BAN_COUNT), self._config_manager.getint(bot.config_category.SYSTEM, bot.config_category_system.UNLOCK_PASSWORD_LENGTH))

        self._kwd_public = db.group_dict_manager(mongo_db_uri, config_manager.getint(bot.config_category.KEYWORD_DICT, bot.config_category_kw_dict.CREATE_DUPLICATE), config_manager.getint(bot.config_category.KEYWORD_DICT, bot.config_category_kw_dict.REPEAT_CALL))
        self._kwd_global = db.word_dict_global(mongo_db_uri)
        self._group_manager = db.group_manager(mongo_db_uri)
        self._oxford_dict = oxford_api
        self._line_api_wrapper = line_api_wrapper
        self._webpage_generator = webpage_generator
        self._imgur_api_wrapper = imgur_api_wrapper
        self._oxr_client = oxr_client
        self._string_calculator = string_calculator
        self._weather_reporter = weather_reporter
        self._weather_config = db.weather_report_config(mongo_db_uri)
        self._weather_id_reg = tool.weather.weather_reporter.CITY_ID_REGISTRY
        self._sticker_dl = tool.line_sticker_downloader(file_tmp_path)
        
        self._pymongo_client = None
        
    def handle_text(self, event, user_permission, group_config_type):
        """Return whether message has been replied"""
        token = event.reply_token
        text = unicode(event.message.text)
        src = event.source

        src_gid = bot.line_api_wrapper.source_channel_id(src)
        src_uid = bot.line_api_wrapper.source_user_id(src)

        texts = split(text, text_msg_handler.REMOTE_SPLITTER, 2)
        if bot.line_api_wrapper.is_valid_room_group_id(texts[0], True, True):
            attempt_to_remote = True
            execute_remote_gid = texts[0]
            text = texts[1]
        else:
            attempt_to_remote = False
            execute_remote_gid = src_gid
            text = texts[0]

        cmd_data = None
        for cmd_kw, cmd_obj in bot.sys_cmd_dict.iteritems():
            if text.startswith(text_msg_handler.HEAD + cmd_kw):
                cmd_data = cmd_obj
                break

        # terminate if set to silence
        if group_config_type <= db.config_type.SILENCE and cmd_data.function_code != 'GA':
            print 'Terminate because the group is set to silence and function code is not GA.'
            return False

        if cmd_data is None:
            print 'Called an not existed command.'
            return False

        # log statistics
        self._system_stats.command_called(cmd_data.head)

        # get function
        cmd_function = getattr(self, '_{}'.format(cmd_data.function_code))

        # override user_permission(command executor) and group_config_type if the command is attempt to control remotely
        if attempt_to_remote and cmd_data.remotable >= bot.remote.GROUP_ID_ONLY:
            user_permission = self._group_manager.get_user_permission(execute_remote_gid, src_uid)

            if bot.line_api_wrapper.is_valid_room_group_id(execute_remote_gid):
                group_config_type = self._group_manager.get_group_config_type(execute_remote_gid)
            else:
                group_config_type = db.config_type.ALL

        # check the action is valid with the provided permission
        low_perm = cmd_data.lowest_permission
        if user_permission == bot.permission.RESTRICTED:
            self._line_api_wrapper.reply_message_text(token, error.permission.user_is_resticted())
            return True
        elif user_permission < low_perm:
            self._line_api_wrapper.reply_message_text(token, error.permission.restricted(low_perm))
            return True

        # handle command
        if attempt_to_remote:
            handle_result = cmd_function(src, execute_remote_gid, group_config_type, user_permission, text)
        else:
            handle_result = cmd_function(src, src_gid, group_config_type, user_permission, text)

        # reply handle result
        if handle_result is None:
            return self._line_api_wrapper.reply_message_text(token, error.sys_command.syntax_error(cmd_data.function_code))
        else:
            if isinstance(handle_result, (str, unicode)):
                self._line_api_wrapper.reply_message_text(token, handle_result)
            else:
                self._line_api_wrapper.reply_message(token, handle_result)

        return True

    def _get_kwd_instance(self, src, config, execute_remote_gid=None):
        cid = bot.line_api_wrapper.source_channel_id(src)

        if bot.line_api_wrapper.is_valid_room_group_id(execute_remote_gid):
            config = self._group_manager.get_group_config_type(execute_remote_gid)

        if config is not None and config == db.config_type.ALL:
            manager_range = db.group_dict_manager_range.GROUP_AND_PUBLIC
        else:
            manager_range = db.group_dict_manager_range.GROUP_ONLY

        if execute_remote_gid == bot.remote.GLOBAL_TOKEN():
            kwd_instance = self._kwd_public.clone_instance(self._mongo_uri, db.PUBLIC_GROUP_ID, db.group_dict_manager_range.GLOBAL)
        elif execute_remote_gid == cid:
            kwd_instance = self._kwd_public.clone_instance(self._mongo_uri, execute_remote_gid, manager_range)
        else:
            source_type = bot.line_event_source_type.determine(src)
            if source_type == bot.line_event_source_type.USER:
                kwd_instance = self._kwd_public
            elif source_type == bot.line_event_source_type.GROUP or source_type == bot.line_event_source_type.ROOM:
                kwd_instance = self._kwd_public.clone_instance(self._mongo_uri, cid, manager_range)
            else:
                raise ValueError(error.main.miscellaneous(u'Unknown source type.'))

        return kwd_instance

    def _get_query_result(self, src, group_config_type, execute_in_gid, regex_result, kwd_instance, exact_same):
        expr = None
        if regex_result.match_at == 0:
            action = regex_result.group(1)

            if action == u'可以用的':
                expr = u'搜尋範圍: 本頻道( {} )可用的回覆組'.format(execute_in_gid)
                result_data = kwd_instance.search_all_available_pair()
            elif action == u'全部':
                expr = u'搜尋範圍: 全域回覆組'
                result_data = self._get_kwd_instance(src, group_config_type, bot.remote.GLOBAL_TOKEN()).search_all_available_pair()
            else:
                result_data = error.sys_command.action_not_implemented(u'Q/I', regex_result.match_at, action)
        elif regex_result.match_at == 1:
            start_id = ext.string_to_int(regex_result.group(1))
            end_id = ext.string_to_int(regex_result.group(3))

            if start_id is None:
                result_data = error.main.invalid_thing_with_correct_format(u'參數1', u'正整數(代表起始ID)', regex_result.group(1))
            elif end_id is None:
                result_data = error.main.invalid_thing_with_correct_format(u'參數3', u'正整數(代表終止ID)', regex_result.group(3))
            elif end_id - start_id < 0:
                result_data = error.main.miscellaneous(u'起始數字不得大於終止數字。')
            else:
                expr = u'搜尋範圍: ID介於【{}】~【{}】之間的回覆組'.format(start_id, end_id)
                result_data = kwd_instance.search_pair_by_index(start_id, end_id)
        elif regex_result.match_at == 2:
            uid = regex_result.group(1)

            if not bot.line_api_wrapper.is_valid_user_id(uid):
                result_data = error.line_bot_api.illegal_user_id(uid)
            else:
                try:
                    user_name = self._line_api_wrapper.profile_name(uid, src)
                except bot.UserProfileNotFoundError:
                    user_name = error.main.line_account_data_not_found()

                expr = u'搜尋範圍: 由 {} ({}) 製作的回覆組'.format(user_name, uid)
                result_data = kwd_instance.search_pair_by_creator(uid)
        elif regex_result.match_at == 3:
            gid = regex_result.group(1)

            if not bot.line_api_wrapper.is_valid_room_group_id(gid, True, True):
                result_data = error.line_bot_api.illegal_room_group_id(gid)
            else:
                expr = u'搜尋範圍: 群組ID {} 內可用的回覆組'.format(gid)
                result_data = self._kwd_global.get_pairs_by_group_id(gid, True)
        elif regex_result.match_at == 4:
            is_ids = regex_result.group(2) is not None

            if is_ids:
                index_source = ext.string_to_int(*regex_result.group(3).split(self._array_separator))
                if isinstance(index_source, int):
                    index_source = [index_source]
            else:
                index_source = regex_result.group(1)

            if index_source is None:
                result_data = error.main.invalid_thing_with_correct_format(u'參數1', u'正整數、正整數陣列(代表ID)或字串、字串陣列(代表關鍵字)', regex_result.group(1))
            else:
                if is_ids:
                    expr = u'搜尋範圍: ID為【{}】的回覆組'.format(u'、'.join([str(id) for id in index_source]))
                    result_data = kwd_instance.search_pair_by_index(index_source)
                else:
                    expr = u'搜尋範圍: 關鍵字 或 回覆 {}【{}】的回覆組'.format(u'為' if exact_same else u'含', index_source)
                    result_data = kwd_instance.search_pair_by_keyword(index_source, exact_same)
        else:
            raise RegexNotImplemented(error.sys_command.regex_not_implemented(u'Q/I', regex_result.match_at, regex_result.regex))

        return result_data, expr

    def _S(self, src, execute_in_gid, group_config_type, executor_permission, text, pinned=False):
        regex_list = [ur'小水母 DB ?資料庫(.+)(?<! ) ?主指令(.+)(?<! ) ?主參數(.+)(?<! ) ?參數(.+)(?<! )']
        
        regex_result = tool.regex_finder.find_match(regex_list, text)

        if regex_result is None:
            return

        if self._pymongo_client is None:
            self._pymongo_client = pymongo.MongoClient(self._mongo_uri)

        if regex_result.match_at == 0:
            db_name = regex_result.group(1)
            main_cmd = regex_result.group(2)
            main_prm = regex_result.group(3)
            prm_dict = regex_result.group(4)

            try:
                prm_dict = ast.literal_eval(prm_dict)
            except ValueError as ex:
                return error.main.miscellaneous(u'參數4字串型別分析失敗。\n{}\n\n訊息: {}'.format(prm_dict, ex.message))

            if not isinstance(prm_dict, dict):
                return error.main.miscellaneous(u'輸入參數必須是合法dictionary型別。{}'.format(type(prm_dict)))

            text = u'目標資料庫:\n{}\n'.format(db_name)
            text += u'資料庫主指令:\n{}\n'.format(main_cmd)
            text += u'資料庫主指令參數:\n{}\n'.format(main_prm)
            text += u'資料庫副指令:\n{}\n\n'.format(prm_dict)

            try:
                result = self._pymongo_client.get_database(db_name).command(main_cmd, main_prm, **prm_dict)

                text += ext.object_to_json(result)
            except pymongo.errors.OperationFailure as ex:
                text += u'資料庫指令執行失敗。\n錯誤碼: {}\n錯誤訊息: {}'.format(ex.code, ex.message)

            return text
        else:
            raise RegexNotImplemented(error.sys_command.regex_not_implemented(u'S', regex_result.match_at, regex_result.regex))
    
    def _A(self, src, execute_in_gid, group_config_type, executor_permission, text, pinned=False):
        if pinned:
            regex_list = [ur'小水母 置頂 ?(\s|附加(.+)(?<! ))? ?(收到 ?(.+)(?<! )|看到 ?([0-9a-f]{56})|被貼 ?(\d+)) ?(回答 ?(.+)(?<! )|回圖 ?(https://.+)|回貼 ?(\d+))']
        else:
            regex_list = [ur'小水母 記住 ?(\s|附加(.+)(?<! ))? ?(收到 ?(.+)(?<! )|看到 ?([0-9a-f]{56})|被貼 ?(\d+)) ?(回答 ?(.+)(?<! )|回圖 ?(https://.+)|回貼 ?(\d+))']
        
        regex_result = tool.regex_finder.find_match(regex_list, text)

        if regex_result is None:
            return

        # try to get complete profile
        try:
            new_profile_uid = bot.line_api_wrapper.source_user_id(src)
            self._line_api_wrapper.profile_name(new_profile_uid)
        except bot.UserProfileNotFoundError as ex:
            return error.line_bot_api.unable_to_receive_user_id()

        # verify uid structure
        if not bot.line_api_wrapper.is_valid_user_id(new_profile_uid):
            return error.line_bot_api.illegal_user_id(new_profile_uid)

        # assign keyword instance
        kwd_instance = self._get_kwd_instance(src, group_config_type, execute_in_gid)

        if regex_result.match_at == 0:
            rcv_type = regex_result.group(3)[:2]
            rep_type = regex_result.group(7)[:2]

            # checking type of keyword and reply
            try:
                rcv_type = db.word_type.determine_by_word(rcv_type)
                rep_type = db.word_type.determine_by_word(rep_type)
            except db.UnknownFlagError:
                return error.sys_command.action_not_implemented(u'A', regex_result.match_at, u'{} & {}'.format(rcv_type, rep_type))

            if rcv_type == db.word_type.TEXT:
                rcv_content = regex_result.group(4)
            elif rcv_type == db.word_type.PICTURE:
                rcv_content = regex_result.group(5)
            elif rcv_type == db.word_type.STICKER:
                rcv_content = regex_result.group(6)
            else:
                return error.sys_command.action_not_implemented(u'A', regex_result.match_at, u'{} (rcv)'.format(rcv_type))

            if rep_type == db.word_type.TEXT:
                rep_content = regex_result.group(8)
            elif rep_type == db.word_type.PICTURE:
                rep_content = regex_result.group(9)
            elif rep_type == db.word_type.STICKER:
                rep_content = regex_result.group(10)
            else:
                return error.sys_command.action_not_implemented(u'A', regex_result.match_at, u'{} (rep)'.format(rep_type))
            
            rep_att = regex_result.group(2)
            if rep_att is not None and not (rep_type == db.word_type.PICTURE or rep_type == db.word_type.STICKER):
                return error.main.miscellaneous(u'附加回覆只可以在回覆種類為圖片或貼圖時使用。')

            # create and write
            result = kwd_instance.insert_keyword(rcv_content, rep_content, new_profile_uid, pinned, rcv_type, rep_type, None, rep_att)

            # check whether success
            if isinstance(result, (str, unicode)):
                return result
            elif isinstance(result, db.pair_data):
                return u'回覆組新增成功。\n' + result.basic_text(True)
            else:
                raise ValueError('Unknown type of return result.')
        else:
            raise RegexNotImplemented(error.sys_command.regex_not_implemented(u'A/M', regex_result.match_at, regex_result.regex))
        
    def _M(self, src, execute_in_gid, group_config_type, executor_permission, text):
        return self._A(src, execute_in_gid, group_config_type, executor_permission, text, True)
    
    def _D(self, src, execute_in_gid, group_config_type, executor_permission, text, pinned=False):
        if pinned:
            regex_list = [ur'小水母 忘記置頂的 ?((ID ?)(\d{1}[\d\s]*)|.+)']
        else:
            regex_list = [ur'小水母 忘記 ?((ID ?)(\d{1}[\d\s]*)|.+)']

        regex_result = tool.regex_finder.find_match(regex_list, text)

        if regex_result is None:
            return
        
        # try to get complete profile
        try:
            del_profile_uid = bot.line_api_wrapper.source_user_id(src)
            self._line_api_wrapper.profile_name(del_profile_uid)
        except bot.UserProfileNotFoundError as ex:
            return error.line_bot_api.unable_to_receive_user_id()

        # verify uid structure
        if not bot.line_api_wrapper.is_valid_user_id(del_profile_uid):
            return error.line_bot_api.illegal_user_id(del_profile_uid)
        
        # assign keyword instance
        kwd_instance = self._get_kwd_instance(src, group_config_type, execute_in_gid)

        if regex_result.match_at == 0:
            is_ids = regex_result.group(2) is not None

            if is_ids:
                disable_targets = ext.string_to_int(*regex_result.group(3).split(self._array_separator))
                if disable_targets is None:
                    return error.main.invalid_thing_with_correct_format(u'參數2', u'整數數字，或指定字元分隔的數字陣列(代表ID)', disable_targets)

                disable_result_id_list = kwd_instance.disable_keyword_by_id(disable_targets, del_profile_uid, pinned)
            else:
                disable_targets = regex_result.group(1).split(self._array_separator)

                disable_result_id_list = kwd_instance.disable_keyword(disable_targets, del_profile_uid, pinned)

            if len(disable_result_id_list) > 0:
                text = u'回覆組刪除成功。\n'
                text += '\n'.join([data.basic_text(True) for data in disable_result_id_list])
                return text
            else:
                return error.main.miscellaneous(error.main.pair_not_exist_or_insuffieicnt_permission() + u'若欲使用ID作為刪除根據，請參閱小水母使用說明。')
        else:
            raise RegexNotImplemented(error.sys_command.regex_not_implemented(u'D/R', regex_result.match_at, regex_result.regex))

    def _R(self, src, execute_in_gid, group_config_type, executor_permission, text):
        return self._D(src, execute_in_gid, group_config_type, executor_permission, text, True)
    
    def _Q(self, src, execute_in_gid, group_config_type, executor_permission, text):
        regex_list = [ur'小水母 找 ?(可以用的|全部)',
                      ur'小水母 找 ?ID範圍 ?(\d+)(到|~)(\d+)',
                      ur'小水母 找 ?([U]{1}[0-9a-f]{32}) ?做的',
                      ur'小水母 找 ?([CR]{1}[0-9a-f]{32}|PUBLIC|GLOBAL) ?裡面的',
                      ur'小水母 找 ?((ID ?)(\d{1}[\d\s]*)|.+)']
        
        regex_result = tool.regex_finder.find_match(regex_list, text)

        if regex_result is None:
            return
        
        # assign keyword instance
        kwd_instance = self._get_kwd_instance(src, group_config_type, execute_in_gid)

        # create query result
        query_result = self._get_query_result(src, group_config_type, execute_in_gid, regex_result, kwd_instance, False)
        if isinstance(query_result[0], (str, unicode)):
            return query_result

        # process output
        max_count = self._config_manager.getint(bot.config.config_category.KEYWORD_DICT, bot.config.config_category_kw_dict.MAX_QUERY_OUTPUT_COUNT)
        str_length = self._config_manager.getint(bot.config.config_category.KEYWORD_DICT, bot.config.config_category_kw_dict.MAX_SIMPLE_STRING_LENGTH)
        output = db.keyword_dict.group_dict_manager.list_keyword(query_result[0], max_count, query_result[1], error.main.no_result(), str_length)

        text = output.limited
        if output.has_result:
            text += u'\n\n完整結果: {}'.format(self._webpage_generator.rec_webpage(output.full, db.webpage_content_type.QUERY))
        return text
    
    def _I(self, src, execute_in_gid, group_config_type, executor_permission, text):
        regex_list = [ur'小水母 詳細找 ?(可以用的|全部)',
                      ur'小水母 詳細找 ?ID範圍 ?(\d+)(到|~)(\d+)',
                      ur'小水母 詳細找 ?([U]{1}[0-9a-f]{32}) ?做的',
                      ur'小水母 詳細找 ?([CR]{1}[0-9a-f]{32}|PUBLIC|GLOBAL) ?裡面的', 
                      ur'小水母 詳細找 ?((ID ?)(\d{1}[\d\s]*)|.+)']
        
        regex_result = tool.regex_finder.find_match(regex_list, text)

        if regex_result is None:
            return
        
        # assign keyword instance
        kwd_instance = self._get_kwd_instance(src, group_config_type, execute_in_gid)

        # create query result
        query_result = self._get_query_result(src, group_config_type, execute_in_gid, regex_result, kwd_instance, True)
        if isinstance(query_result[0], (str, unicode)):
            return query_result
        
        # process output
        max_count = self._config_manager.getint(bot.config.config_category.KEYWORD_DICT, bot.config.config_category_kw_dict.MAX_INFO_OUTPUT_COUNT)
        output = db.keyword_dict.group_dict_manager.list_keyword_info(query_result[0], kwd_instance, self._line_api_wrapper, max_count, query_result[1].replace('\n', ''), error.main.no_result())

        text = output.limited
        if output.has_result:
            text += u'\n\n完整結果: {}'.format(self._webpage_generator.rec_webpage(output.full, db.webpage_content_type.INFO))
        return text
    
    def _X(self, src, execute_in_gid, group_config_type, executor_permission, text):
        regex_list = [ur'小水母 複製 ?((ID ?)(\d{1}[\d\s]*)|.+)到([CR]{1}[0-9a-f]{32}|PUBLIC|這裡)', 
                      ur'小水母 複製群組([CR]{1}[0-9a-f]{32})?裡面的( 包含置頂)?到([CR]{1}[0-9a-f]{32}|PUBLIC|這裡)']
        
        regex_result = tool.regex_finder.find_match(regex_list, text)

        if regex_result is None:
            return

        executor_uid = bot.line_api_wrapper.source_user_id(src)

        able_to_copy_pinned = executor_permission >= bot.permission.MODERATOR

        if regex_result.match_at == 0:
            target_gid = regex_result.group(4)
            if target_gid == u'這裡':
                target_gid = execute_in_gid

            if not bot.line_api_wrapper.is_valid_room_group_id(target_gid, True) and not target_gid == execute_in_gid:
                return error.main.invalid_thing_with_correct_format(u'參數1', u'合法群組ID、"這裡"或"PUBLIC"(複製目標)', regex_result.group(4))

            is_ids = regex_result.group(2) is not None

            if is_ids:
                source = ext.string_to_int(*regex_result.group(3).split(self._array_separator))
                if isinstance(source, int):
                    source = [source]
            else:
                source = regex_result.group(1)

            if source is None:
                return error.main.invalid_thing_with_correct_format(u'參數1', u'正整數、正整數陣列(代表ID)或字串、字串陣列(代表關鍵字)', regex_result.group(1))

            if is_ids:
                result_ids = self._kwd_global.clone_by_id(source, target_gid, executor_uid, False, able_to_copy_pinned)
            else:
                result_ids = self._kwd_global.clone_by_word(source, target_gid, executor_uid, False, able_to_copy_pinned)
        elif regex_result.match_at == 1:
            source_gid = regex_result.group(1)
            if source_gid is None:
                source_gid = execute_in_gid
            target_gid = regex_result.group(3)
            if target_gid == u'這裡':
                target_gid = execute_in_gid
            include_pinned = regex_result.group(2) is not None and able_to_copy_pinned

            if not bot.line_api_wrapper.is_valid_room_group_id(source_gid, True) and not source_gid == execute_in_gid:
                return error.main.invalid_thing_with_correct_format(u'參數1', u'合法群組ID、"這裡"或"PUBLIC"(複製來源)', regex_result.group(1))

            if not bot.line_api_wrapper.is_valid_room_group_id(target_gid, True) and not target_gid == execute_in_gid:
                return error.main.invalid_thing_with_correct_format(u'參數2', u'合法群組ID、"這裡"或"PUBLIC"(複製來源)', regex_result.group(2))

            if source_gid == target_gid:
                return error.main.miscellaneous("回覆組複製來源和目的地相同。")

            result_ids = self._kwd_global.clone_from_group(source_gid, target_gid, executor_uid, False, include_pinned)
        else:
            raise RegexNotImplemented(error.sys_command.regex_not_implemented(u'X', regex_result.match_at, regex_result.regex))

        if len(result_ids) > 0:
            first_id_str = str(result_ids[0])
            last_id_str = str(result_ids[-1])
            return [bot.line_api_wrapper.wrap_text_message(u'回覆組複製完畢。\n新建回覆組ID: {}'.format(u'、'.join([u'#{}'.format(id) for id in result_ids])), self._webpage_generator),
                    bot.line_api_wrapper.wrap_template_with_action({
                        u'回覆組資料查詢(簡略)': text_msg_handler.HEAD + u'找ID範圍' + first_id_str + u'到' + last_id_str,
                        u'回覆組資料查詢(詳細)': text_msg_handler.HEAD + u'詳細找ID範圍' + first_id_str + u'到' + last_id_str } ,u'新建回覆組相關指令樣板', u'相關指令')]
        else:
            return u'回覆組複製失敗。回覆組來源沒有符合條件的回覆組可供複製。'
        
    def _X2(self, src, execute_in_gid, group_config_type, executor_permission, text):
        regex_list = [ur'小水母 清除(於([CR]{1}[0-9a-f]{32})中)?所有的回覆組571a95ae875a9ae315fad8cdf814858d9441c5ec671f0fb373b5f340']

        regex_result = tool.regex_finder.find_match(regex_list, text)

        if regex_result is None:
            return

        executor_uid = bot.line_api_wrapper.source_user_id(src)
        
        if regex_result.match_at == 0:
            target_gid = regex_result.group(2)
            if target_gid is None:
                target_gid = execute_in_gid

            try:
                clear_count = self._kwd_global.clear(target_gid, executor_uid)
            except db.ActionNotAllowed as ex:
                return ex.message

            if clear_count > 0:
                return u'已刪除群組所屬回覆組(共{}組)。'.format(clear_count)
            else:
                return u'沒有刪除任何回覆組。'
        else:
            raise RegexNotImplemented(error.sys_command.regex_not_implemented(u'X2', regex_result.match_at, regex_result.regex))
        
    def _E(self, src, execute_in_gid, group_config_type, executor_permission, text):
        regex_list = [ur'小水母 修改 ?((ID ?)(\d{1}[\d\s]*)|.+)跟(.+)(無|有)關', 
                      ur'小水母 修改 ?((ID ?)(\d{1}[\d\s]*)|.+)(不)?置頂']
        
        regex_result = tool.regex_finder.find_match(regex_list, text)

        if regex_result is None:
            return
        
        # assign keyword instance
        kwd_instance = self._get_kwd_instance(src, group_config_type, execute_in_gid)
        
        # validate and assign modify target array
        is_ids = regex_result.group(2) is not None
        if is_ids:
            target_array = ext.string_to_int(*regex_result.group(3).split(self._array_separator))
            if isinstance(target_array, int):
                target_array = [target_array]
        else:
            target_array = regex_result.group(1).split(self._array_separator)

        if target_array is None:
            return error.main.invalid_thing_with_correct_format(u'參數1', u'正整數、正整數陣列(代表ID)或字串、字串陣列(代表關鍵字)', regex_result.group(1))

        # create template of target item
        if is_ids:
            expr = u'、'.join([u'#{}'.format(str(id)) for id in target_array])

            shortcut_template = bot.line_api_wrapper.wrap_template_with_action({ '回覆組詳細資訊(#{})'.format(id): text_msg_handler.HEAD + u'詳細找ID {}'.format(id) for id in target_array }, u'更動回覆組ID: {}'.format(expr), u'相關指令')
        else:
            expr = u'關鍵字: ' + u'、'.join(target_array)

            shortcut_template = bot.line_api_wrapper.wrap_template_with_action({ '回覆組詳細資訊()'.format(kw): u'詳細找{}'.format(kw) for kw in target_array }, u'更動回覆組: {}'.format(expr), u'相關指令')

        if regex_result.match_at == 0:
            linked_word_list = regex_result.group(4).split(self._array_separator)
            action = regex_result.group(5)

            able_to_mod_pin = executor_permission >= bot.permission.MODERATOR

            if action == u'有':
                is_add = True
            elif action == u'無':
                is_add = False
            else:
                return error.sys_command.action_not_implemented(u'E', regex_result.match_at, action)

            if is_ids:
                if is_add:
                    result = kwd_instance.add_linked_word_by_id(target_array, linked_word_list, able_to_mod_pin)
                else:
                    result = kwd_instance.del_linked_word_by_id(target_array, linked_word_list, able_to_mod_pin)
            else:
                if is_add:
                    result = kwd_instance.add_linked_word_by_word(target_array, linked_word_list, able_to_mod_pin)
                else:
                    result = kwd_instance.del_linked_word_by_word(target_array, linked_word_list, able_to_mod_pin)

            if result:
                return (bot.line_api_wrapper.wrap_text_message(u'{} 相關回覆組變更成功。'.format(expr), self._webpage_generator), shortcut_template)
            else:
                return '{} 相關回覆組變更失敗。可能是因為ID不存在或權限不足而造成。'.format(expr)
        elif regex_result.match_at == 1:
            action = regex_result.group(4)
            if action is None:
                pinned = True
            elif action == u'不':
                pinned = False
            else:
                return error.sys_command.action_not_implemented(u'E', regex_result.match_at, action)

            if is_ids:
                result = kwd_instance.set_pinned_by_index(target_array, pinned)
            else:
                result = kwd_instance.set_pinned_by_keyword(target_array, pinned)
            
            if result:
                return (bot.line_api_wrapper.wrap_text_message('{} 置頂屬性變更成功。'.format(expr), self._webpage_generator), shortcut_template)
            else:
                return '{} 置頂屬性變更失敗。可能是因為ID不存在或權限不足而造成。'.format(expr)
        else:
            raise RegexNotImplemented(error.sys_command.regex_not_implemented(u'E', regex_result.match_at, regex_result.regex))
        
    def _K(self, src, execute_in_gid, group_config_type, executor_permission, text):
        regex_list = [ur'小水母 前(([1-9]\d?)名)?(使用者|回覆組|使用過的)']
        
        regex_result = tool.regex_finder.find_match(regex_list, text)

        if regex_result is None:
            return

        kwd_instance = self._get_kwd_instance(src, group_config_type, execute_in_gid)
        default = self._config_manager.getint(bot.config_category.KEYWORD_DICT, bot.config_category_kw_dict.DEFAULT_RANK_RESULT_COUNT)
        
        limit = regex_result.group(2)
        # validate parameters
        if limit is not None:
            limit = ext.string_to_int(limit)
            if limit is None:
                return error.main.incorrect_param(u'參數2', u'整數，代表表示結果上限')
        else:
            limit = default
        
        if limit > 99:
            return error.main.incorrect_param(u'參數2', u'小於99的整數')

        if regex_result.match_at == 0:
            type_category = regex_result.group(3)

            if type_category == u'使用者':
                return kwd_instance.user_created_rank_string(limit, self._line_api_wrapper)
            elif type_category == u'回覆組':
                return kwd_instance.get_ranking_call_count_string(limit)
            elif type_category == u'使用過的':
                return kwd_instance.recently_called_string(limit)
            else:
                return error.sys_command.action_not_implemented(u'K', regex_result.match_at, type_category)
        else:
            raise RegexNotImplemented(error.sys_command.regex_not_implemented(u'K', regex_result.match_at, regex_result.regex))
    
    def _P(self, src, execute_in_gid, group_config_type, executor_permission, text):
        regex_list = [ur'小水母 系統訊息前(\d+)名', 
                      ur'小水母 系統(自動回覆|資訊|圖片|匯率|黑名單)']
        
        regex_result = tool.regex_finder.find_match(regex_list, text)

        if regex_result is None:
            return

        if regex_result.match_at == 0:
            limit = ext.string_to_int(regex_result.group(1))

            if limit is None:
                limit = self._config_manager.getint(bot.config.config_category.KEYWORD_DICT, bot.config.config_category_kw_dict.MAX_MESSAGE_TRACK_OUTPUT_COUNT)
        
            tracking_string_obj = db.group_manager.message_track_string(self._group_manager.order_by_recorded_msg_count(limit), limit, [u'【訊息流量統計】(前{}名)'.format(limit)], error.main.miscellaneous(u'沒有訊息量追蹤紀錄。'), True, True, self._group_manager.message_sum())
        
            return u'為避免訊息過長洗板，請點此察看結果:\n{}'.format(self._webpage_generator.rec_webpage(tracking_string_obj.full, db.webpage_content_type.TEXT))
        elif regex_result.match_at == 1:
            type_category = regex_result.group(1)

            if type_category == u'自動回覆':
                kwd_instance = self._get_kwd_instance(src, group_config_type, execute_in_gid)
                instance_type = u'{}回覆組資料庫'.format(unicode(kwd_instance.available_range))
                return u'【{}相關統計資料】\n'.format(instance_type) + kwd_instance.get_statistics_string()
            elif type_category == u'資訊':
                text = u'【系統統計資料】\n'
                text += u'開機時間: {} (UTC+8)\n\n'.format(self._system_data.boot_up)
                text += self._system_stats.get_statistics()

                return text
            elif type_category == u'圖片':
                import socket
                ip_address = socket.gethostbyname(socket.getfqdn(socket.gethostname()))

                return self._imgur_api_wrapper.get_status_string(ip_address)
            elif type_category == u'匯率':
                return self._oxr_client.usage_str(self._oxr_client.get_usage_dict())
            elif type_category == u'黑名單':
                text = u'【暫時封鎖清單】\n以下使用者因洗板疑慮，已暫時封鎖指定使用者對小水母的所有操控。輸入驗證碼以解除鎖定。\n此清單將在小水母重新開啟後自動消除。\n系統開機時間: {}\n\n'.format   (self._system_data.boot_up)
                text += self._loop_prev.get_all_banned_str()

                return text
            else:
                return error.sys_command.action_not_implemented(u'P', regex_result.match_at, type_category)
        else:
            raise RegexNotImplemented(error.sys_command.regex_not_implemented(u'P', regex_result.match_at, regex_result.regex))
    
    def _P2(self, src, execute_in_gid, group_config_type, executor_permission, text):
        regex_list = [ur'小水母 使用者 ?([U]{1}[0-9a-f]{32}) ?的資料']
        
        regex_result = tool.regex_finder.find_match(regex_list, text)

        if regex_result is None:
            return

        if regex_result.match_at == 0:
            uid = regex_result.group(1)

            if bot.line_api_wrapper.is_valid_user_id(uid):
                kwd_instance = self._get_kwd_instance(src, group_config_type, execute_in_gid)

                try:
                    if execute_in_gid != bot.line_api_wrapper.source_channel_id(src):
                        source_type = bot.line_api_wrapper.determine_id_type(execute_in_gid)

                        if source_type == bot.line_event_source_type.GROUP:
                            name = self._line_api_wrapper.profile_group(execute_in_gid, uid).display_name
                        elif source_type == bot.line_event_source_type.ROOM:
                            name = self._line_api_wrapper.profile_room(execute_in_gid, uid).display_name
                        else:
                            name = self._line_api_wrapper.profile_name(uid, src)
                    else:
                        name = self._line_api_wrapper.profile_name(uid, src)
                except bot.UserProfileNotFoundError:
                    return error.main.line_account_data_not_found()

                created_id_arr = u'、'.join([str(id) for id in kwd_instance.user_created_id_array(uid)])
                owned_permission = u'\n'.join([u'{}: {}'.format(u_data.group, unicode(u_data.permission_level)) for u_data in self._group_manager.get_user_owned_permissions(uid)])

                text = u'UID:\n{}\n\n名稱:\n{}\n\n擁有權限:\n{}\n\n製作回覆組ID:\n{}'.format(uid, name, owned_permission, created_id_arr)

                return [bot.line_api_wrapper.wrap_text_message(text, self._webpage_generator), 
                        bot.line_api_wrapper.wrap_template_with_action({ u'查詢該使用者製作的回覆組': text_msg_handler.HEAD + u'找' + uid + u'做的' }, u'回覆組製作查詢快捷樣板', u'快捷查詢')]
            else:
                return error.line_bot_api.illegal_user_id(uid)
        else:
            raise RegexNotImplemented(error.sys_command.regex_not_implemented(u'P2', regex_result.match_at, regex_result.regex))

    def _G(self, src, execute_in_gid, group_config_type, executor_permission, text):
        regex_list = [ur'小水母 群組([CR]{1}[0-9a-f]{32})?的資料']
        
        regex_result = tool.regex_finder.find_match(regex_list, text)

        if regex_result is None:
            return

        if regex_result.match_at == 0:
            gid = regex_result.group(1)

            if gid is None:
                if bot.line_event_source_type.determine(src) == bot.line_event_source_type.USER:
                    return error.main.incorrect_channel(False, True, True)
                else:
                    gid = execute_in_gid

            kwd_instance = self._get_kwd_instance(src, group_config_type, gid)

            group_data = self._group_manager.get_group_by_id(gid, True)

            group_statistics = group_data.get_status_string() + u'\n【回覆組相關】\n' + kwd_instance.get_statistics_string()
            
            return (bot.line_api_wrapper.wrap_text_message(group_statistics, self._webpage_generator), 
                    bot.line_api_wrapper.wrap_template_with_action({ u'查詢群組資料庫': text_msg_handler.HEAD + u'找' + gid + u'裡面的'}, u'快速查詢群組資料庫樣板', u'相關指令'))
        else:
            raise RegexNotImplemented(error.sys_command.regex_not_implemented(u'G', regex_result.match_at, regex_result.regex))
        
    def _GA(self, src, execute_in_gid, group_config_type, executor_permission, text):
        regex_list = [ur'小水母 當(啞巴|機器人|服務員|八嘎囧)']

        regex_result = tool.regex_finder.find_match(regex_list, text)

        if regex_result is None:
            return

        if regex_result.match_at == 0:
            setter_uid = bot.line_api_wrapper.source_user_id(src)

            action = regex_result.group(1)

            if action == u'啞巴':
                cfg_type = db.config_type.SILENCE
            elif action == u'機器人':
                cfg_type = db.config_type.SYS_ONLY
            elif action == u'服務員':
                cfg_type = db.config_type.GROUP_DATABASE_ONLY
            elif action == u'八嘎囧':
                cfg_type = db.config_type.ALL
            else:
                return error.sys_command.action_not_implemented(u'GA', regex_result.match_at, action)

            change_result = self._group_manager.set_config_type(execute_in_gid, cfg_type, setter_uid)

            if change_result:
                return u'我變成{}了哦！'.format(unicode(cfg_type))
            else:
                return u'我沒辦法變成{}...'.format(change_result)
        else:
            raise RegexNotImplemented(error.sys_command.regex_not_implemented(u'GA', regex_result.match_at, regex_result.regex))

        return text
    
    def _GA2(self, src, execute_in_gid, group_config_type, executor_permission, text):
        regex_list = [ur'小水母 讓 ?([U]{1}[0-9a-f]{32}) ?變成(可憐兒|一般人|副管|管理員)']

        regex_result = tool.regex_finder.find_match(regex_list, text)

        if regex_result is None:
            return

        setter_uid = bot.line_api_wrapper.source_user_id(src)
        try:
            setter_name = self._line_api_wrapper.profile_name(setter_uid)
        except bot.UserProfileNotFoundError:
            return error.line_bot_api.unable_to_receive_user_id()

        if regex_result.match_at == 0:
            setter_uid = bot.line_api_wrapper.source_user_id(src)
            target_uid = regex_result.group(1)

            if not bot.line_api_wrapper.is_valid_user_id(target_uid):
                return error.line_bot_api.illegal_user_id(target_uid)

            try:
                target_name = self._line_api_wrapper.profile_name(target_uid)
            except bot.UserProfileNotFoundError:
                return error.main.miscellaneous(u'無法查詢權限更動目標的使用者資料。請先確保更動目標已加入小水母的好友以後再試一次。')

            action = ext.string_to_int(regex_result.group(2))

            if action == u'可憐兒':
                permission = bot.permission.RESTRICTED
            elif action == u'一般人':
                permission = bot.permission.USER
            elif action == u'副管':
                permission = bot.permission.MODERATOR
            elif action == u'管理員':
                permission = bot.permission.ADMIN
            else:
                return error.sys_command.action_not_implemented(u'GA', regex_result.match_at, action)
            
            try:
                if permission == bot.permission.USER:
                    self._group_manager.delete_permission(execute_in_gid, setter_uid, target_uid)
                    return u'權限刪除成功。\n執行者: {}\n執行者UID: {}\n目標: {}\n目標UID: {}'.format(setter_uid, setter_name, target_name, target_uid)
                else:
                    self._group_manager.set_permission(execute_in_gid, setter_uid, target_uid, permission)
                    return u'權限更改/新增成功。\n執行者: {}\n執行者UID: {}\n目標: {}\n目標UID: {}\n新權限: {}'.format(setter_uid, setter_name, target_name, target_uid, unicode(permission))
            except db.InsufficientPermissionError:
                return error.permission.restricted()
        else:
            raise RegexNotImplemented(error.sys_command.regex_not_implemented(u'GA2', regex_result.match_at, regex_result.regex))
    
    def _GA3(self, src, execute_in_gid, group_config_type, executor_permission, text):
        regex_list = [ur'小水母 啟用公用資料庫([A-Z0-9]{40})']

        regex_result = tool.regex_finder.find_match(regex_list, text)

        if regex_result is None:
            return

        if regex_result.match_at == 0:
            activate_result = self._group_manager.activate(execute_in_gid, regex_result.group(0))
            return u'公用資料庫啟用{}。'.format(u'成功' if activate_result else u'失敗')
        else:
            raise RegexNotImplemented(error.sys_command.regex_not_implemented(u'GA3', regex_result.match_at, regex_result.regex))
        
    def _H(self, src, execute_in_gid, group_config_type, executor_permission, text):
        regex_list = [ur'小水母 頻道資訊']
        
        regex_result = tool.regex_finder.find_match(regex_list, text)

        if regex_result is None:
            return
        
        if regex_result.match_at == 0:
            channel_id = bot.line_api_wrapper.source_channel_id(src)

            return [bot.line_api_wrapper.wrap_text_message(txt, self._webpage_generator) for txt in (str(bot.line_event_source_type.determine(src)), channel_id)]
        else:
            raise RegexNotImplemented(error.sys_command.regex_not_implemented(u'H', regex_result.match_at, regex_result.regex))
    
    def _SHA(self, src, execute_in_gid, group_config_type, executor_permission, text):
        regex_list = [ur'小水母 雜湊SHA ?(.*)']
        
        regex_result = tool.regex_finder.find_match(regex_list, text)

        if regex_result is None:
            return
        
        if regex_result.match_at == 0:
            target = regex_result.group(1)

            return hashlib.sha224(target.encode('utf-8')).hexdigest()
        else:
            raise RegexNotImplemented(error.sys_command.regex_not_implemented(u'SHA', regex_result.match_at, regex_result.regex))
    
    def _O(self, src, execute_in_gid, group_config_type, executor_permission, text):
        regex_list = [ur'小水母 查(\w+)']
        
        regex_result = tool.regex_finder.find_match(regex_list, text)

        if regex_result is None:
            return

        if regex_result.match_at == 0:
            voc = regex_result.group(1)

            if not self._oxford_dict.enabled:
                return error.oxford_api.disabled()
            else:
                return bot.oxford_api_wrapper.json_to_string(self._oxford_dict.get_data_json(voc))
        else:
            raise RegexNotImplemented(error.sys_command.regex_not_implemented(u'O', regex_result.match_at, regex_result.regex))
    
    def _RD(self, src, execute_in_gid, group_config_type, executor_permission, text):
        regex_list = [ur'小水母 抽 ?(([\d\.]{1,})%) ?((\d{1,6})次)?', 
                      ur'小水母 抽 ?(.+)', 
                      ur'小水母 抽 ?([\d-]+)到([\d-]+)']

        regex_result = tool.regex_finder.find_match(regex_list, text)

        if regex_result is None:
            return

        if regex_result.match_at == 0:
            probability = regex_result.group(2)
            scout_count = ext.string_to_int(regex_result.group(4))

            if scout_count is None:
                scout_count = 1

            return tool.random_drawer.draw_probability_string(probability, True, scout_count, 3)
        elif regex_result.match_at == 1:
            texts = regex_result.group(1)

            return tool.random_gen.random_drawer.draw_text_string(texts.split(self._array_separator))
        elif regex_result.match_at == 2:
            start_index = ext.string_to_int(regex_result.group(1))
            end_index = ext.string_to_int(regex_result.group(2))

            if start_index is None:
                return error.sys_command.action_not_implemented(u'RD', regex_result.match_at, start_index)

            if end_index is None:
                return error.sys_command.action_not_implemented(u'RD', regex_result.match_at, end_index)

            return tool.random_drawer.draw_number_string(start_index, end_index)
        else:
            raise RegexNotImplemented(error.sys_command.regex_not_implemented(u'RD', regex_result.match_at, regex_result.regex))
    
    def _L(self, src, execute_in_gid, group_config_type, executor_permission, text):
        regex_list = [ur'小水母 最近的(貼圖|圖片|回覆組|發送者)']

        regex_result = tool.regex_finder.find_match(regex_list, text)

        if regex_result is None:
            return

        if regex_result.match_at == 0:
            # Action detection - START
            action_dict = {
                u'貼圖': bot.system_data_category.LAST_STICKER,
                u'圖片': bot.system_data_category.LAST_PIC_SHA,
                u'回覆組': bot.system_data_category.LAST_PAIR_ID,
                u'發送者': bot.system_data_category.LAST_UID
            }

            last_action_enum = action_dict.get(regex_result.group(1))

            if last_action_enum is None:
                return error.sys_command.action_not_implemented(u'L', regex_result.match_at, action)
            # Action detection - END

            last_array = self._system_data.get(last_action_enum, execute_in_gid)

            rep_list = []

            if last_array is not None and len(last_array) > 0:
                rep_list.append(bot.line_api_wrapper.wrap_text_message(u'{} (越下面越新)\n{}'.format(unicode(last_action_enum), u'\n'.join([unicode(item) for item in last_array])), self._webpage_generator))
            else:
                return error.main.miscellaneous(u'沒有登記到本頻道的{}，有可能是因為機器人重新啟動而造成。\n\n本次開機時間: {}'.format(unicode(last_action_enum), self._system_data.boot_up))

            if last_action_enum == bot.system_data_category.LAST_STICKER:
                action_dict = {}
                for item in last_array:
                    stk_id = str(item.sticker_id)
                    pkg_id = str(item.package_id)
                    action_dict['簡潔 - {}'.format(stk_id)] = text_msg_handler.HEAD + u'找' + stk_id
                    action_dict['詳細 - {}'.format(stk_id)] = text_msg_handler.HEAD + u'詳細找' + stk_id
                    action_dict['貼圖包下載 - {}'.format(pkg_id)] = text_msg_handler.HEAD + u'下載貼圖圖包' + pkg_id
            elif last_action_enum == bot.system_data_category.LAST_PAIR_ID:
                action_dict = {}
                for item in last_array:
                    item = str(item)
                    action_dict['簡潔 - {}'.format(item)] = text_msg_handler.HEAD + u'找ID ' + item
                    action_dict['詳細 - {}'.format(item)] = text_msg_handler.HEAD + u'詳細找ID ' + item
            elif last_action_enum == bot.system_data_category.LAST_UID:
                action_dict = { 
                    '使用者{}製作'.format(uid[0:9]): text_msg_handler.HEAD + u'找' + uid + u'做的' for uid in last_array
                }
            elif last_action_enum == bot.system_data_category.LAST_PIC_SHA:
                action_dict = {}
                for sha in last_array:
                    sha = str(sha)
                    action_dict['簡潔 - {}'.format(sha)] = text_msg_handler.HEAD + u'找' + sha
                    action_dict['詳細 - {}'.format(sha)] = text_msg_handler.HEAD + u'詳細找' + sha

            rep_list.append(bot.line_api_wrapper.wrap_template_with_action(action_dict, u'{}快捷查詢樣板'.format(unicode(last_action_enum)), u'快捷指令/快速查詢'))

            return rep_list
        else:
            raise RegexNotImplemented(error.sys_command.regex_not_implemented(u'L', regex_result.match_at, regex_result.regex))
             
    def _T(self, src, execute_in_gid, group_config_type, executor_permission, text):
        from urllib import quote_plus

        regex_list = [ur'小水母 編碼(.+)']
        
        regex_result = tool.regex_finder.find_match(regex_list, text)

        if regex_result is None:
            return
        
        if regex_result.match_at == 0:
            text = regex_result.group(1)

            return quote_plus(text.encode('utf-8'))
        else:
            raise RegexNotImplemented(error.sys_command.regex_not_implemented(u'T', regex_result.match_at, regex_result.regex))
    
    # + CPI
    def _C(self, src, execute_in_gid, group_config_type, executor_permission, text):
        regex_list = [ur'小水母 匯率(可用)?', 
                      ur'小水母 匯率([A-Z ]{3,})', 
                      ur'小水母 匯率((1999|20\d{2})(0[1-9]|1[1-2])([0-2][1-9]|3[0-1]))(時的([A-Z ]{3,}))?', 
                      ur'小水母 匯率([A-Z]{3}) ([\d\.]+) ?轉成 ?([A-Z]{3})']
        
        regex_result = tool.regex_finder.find_match(regex_list, text)

        if regex_result is None:
            return
        
        if regex_result.match_at == 0:
            is_requesting_available_currencies = regex_result.group(1) is not None

            if is_requesting_available_currencies:
                return tool.curr_exc.oxr.available_currencies_str(self._oxr_client.get_available_currencies_dict())
            else:
                return tool.curr_exc.oxr.latest_str(self._oxr_client.get_latest_dict())
        elif regex_result.match_at == 1:
            currencies = regex_result.group(1)

            return tool.curr_exc.oxr.latest_str(self._oxr_client.get_latest_dict(currencies))
        elif regex_result.match_at == 2:
            historical_date = regex_result.group(2) + regex_result.group(3) + regex_result.group(4)
            currencies = regex_result.group(6)

            if currencies is not None:
                return tool.curr_exc.oxr.historical_str(self._oxr_client.get_historical_dict(historical_date, currencies))
            else:
                return tool.curr_exc.oxr.historical_str(self._oxr_client.get_historical_dict(historical_date))
        elif regex_result.match_at == 3:
            source_currency = regex_result.group(1)
            amount = regex_result.group(2)
            target_currency = regex_result.group(3)

            return self._oxr_client.convert(source_currency, target_currency, amount).formatted_string
        else:
            raise RegexNotImplemented(error.sys_command.regex_not_implemented(u'T', regex_result.match_at, regex_result.regex))
             
    def _FX(self, src, execute_in_gid, group_config_type, executor_permission, text):
        regex_list = [ur'小水母 解因式分解([!$%^&*()_+|~\-=`{}\[\]:\";\'<>\?,\./0-9A-Za-z]+)', 
                      ur'小水母 解方程式 ?(變數(.+)(?<! )) ?(方程式([!$%^&*()_+|~\-\n=`{}\[\]:\";\'<>\?,\./0-9A-Za-z和]+))']
        
        regex_result = tool.regex_finder.find_match(regex_list, text)

        if regex_result is None:
            return

        if regex_result.match_at == 0:
            formulas = regex_result.group(1)

            calc_result = self._string_calculator.calculate(formulas, self._system_config.get(db.config_data.CALCULATOR_DEBUG), True, tool.calc_type.POLYNOMIAL_FACTORIZATION)

            return self._FX_generate_result(calc_result)
        elif regex_result.match_at == 1:
            vars = regex_result.group(2)
            eq = regex_result.group(4)

            calc_result = self._string_calculator.calculate(vars + tool.text_calculator.EQUATION_VAR_FORMULA_SEPARATOR + eq, self._system_config.get(db.config_data.CALCULATOR_DEBUG), True, tool.calc_type.ALGEBRAIC_EQUATIONS)

            return self._FX_generate_result(calc_result)
        else:
            raise RegexNotImplemented(error.sys_command.regex_not_implemented(u'FX', regex_result.match_at, regex_result.regex))

    def _FX_generate_result(self, calc_result):
        result_str = calc_result.get_basic_text()
        if calc_result.over_length:
            text = u'因算式結果長度大於100字，為避免洗板，請點選網址察看結果。\n{}'.format(self._webpage_generator.rec_webpage(result_str, db.webpage_content_type.TEXT))
        else:
            text = result_str

        if calc_result.latex_avaliable:
            text += u'\nLaTeX URL:\n{}'.format(self._webpage_generator.rec_webpage(calc_result.latex, db.webpage_content_type.LATEX))

        return text
             
    def _W(self, src, execute_in_gid, group_config_type, executor_permission, text):
        regex_list = [ur'小水母 天氣ID查詢 ?(\w+)', 
                      ur'小水母 天氣(查詢|記錄|刪除) ?([\d\s]+) ?(詳|簡)? ?((\d+)小時內)? ?(每(\d+)小時)?']
        
        regex_result = tool.regex_finder.find_match(regex_list, text)

        if regex_result is None:
            return

        if regex_result.match_at == 0:
            location_keyword = regex_result.group(1)

            search_result = self._weather_id_reg.ids_for(location_keyword, None, 'like')
            search_result_count = len(search_result)
            search_result_simp = search_result[:15]
            search_desc = u'搜尋字詞: {} (共{}筆結果)'.format(location_keyword, search_result_count)
            if len(search_result) > 0:
                result_arr = [search_desc] + [u'{} - {}'.format(id, u'{}, {}'.format(city_name, country_code)) for id, city_name, country_code in search_result]
                action_dict = { str(id): text_msg_handler.HEAD + u'查詢' + str(id) for id, city_name, country_code in search_result_simp }
                return [bot.line_api_wrapper.wrap_template_with_action(action_dict, u'搜尋結果快速查詢樣板', u'快速查詢樣板，請參考搜尋結果點選'),
                        bot.line_api_wrapper.wrap_text_message(u'\n'.join(result_arr), self._webpage_generator)]
            else:
                return u'{}\n{}\n若城市名為中文，請用該城市的英文名搜尋。'.format(search_desc, error.main.no_result())
        elif regex_result.match_at == 1:
            action = regex_result.group(1)
            station_ids = ext.string_to_int(*regex_result.group(2).split(self._array_separator))
            if isinstance(station_ids, int):
                station_ids = [station_ids]

            hr_range = regex_result.group(5)
            if hr_range is None:
                hr_range = self._config_manager.getint(bot.config_category.WEATHER_REPORT, bot.config_category_weather_report.DEFAULT_DATA_RANGE_HR)

            hr_freq = regex_result.group(7)
            if hr_freq is None:
                hr_freq = self._config_manager.getint(bot.config_category.WEATHER_REPORT, bot.config_category_weather_report.DEFAULT_INTERVAL_HR)

            mode_dict = { u'簡': tool.weather.output_config.SIMPLE, u'詳': tool.weather.output_config.DETAIL }
            mode = mode_dict.get(regex_result.group(3), tool.weather.output_config.SIMPLE)

            executor_uid = bot.line_api_wrapper.source_user_id(src)

            if mode is None:
                return error.sys_command.action_not_implemented(u'W', regex_result.match_at, mode + u'(group 3)')

            if action == u'查詢':
                if len(station_ids) > self._config_manager.getint(bot.config_category.WEATHER_REPORT, bot.config_category_weather_report.MAX_BATCH_SEARCH_COUNT):
                    return error.main.invalid_thing_with_correct_format(u'批次查詢量', u'最多一次10筆', len(station_ids))

                return u'\n==========\n'.join([self._weather_reporter.get_data_by_owm_id(id, mode, hr_freq, hr_range) for id in station_ids])
            elif action == u'記錄':
                return self._weather_config.add_config(executor_uid, station_ids, mode, hr_freq, hr_range)
            elif action == u'刪除':
                return self._weather_config.del_config(executor_uid, station_ids)
            else:
                return error.sys_command.action_not_implemented(u'W', regex_result.match_at, action + u'(group 1)')

            return self._FX_generate_result(calc_result)
        else:
            raise RegexNotImplemented(error.sys_command.regex_not_implemented(u'W', regex_result.match_at, regex_result.regex))
             
    def _DL(self, src, execute_in_gid, group_config_type, executor_permission, text):
        regex_list = [ur'小水母 下載貼圖圖包 ?(\d+) ?(含聲音)?']
        
        regex_result = tool.regex_finder.find_match(regex_list, text)

        if regex_result is None:
            return

        if regex_result.match_at == 0:
            package_id = regex_result.group(1)
            including_sound = regex_result.group(2) is not None

            try:
                sticker_meta = self._sticker_dl.get_pack_meta(package_id)
            except tool.MetaNotFoundException:
                return error.main.miscellaneous(u'查無貼圖資料。(圖包ID: {})'.format(package_id))
            
            dl_result = self._sticker_dl.download_stickers(sticker_meta, including_sound)

            with self._flask_app.test_request_context():
                url = request.host_url
            
            ret = [u'貼圖圖包製作完成，請盡快下載。', u'檔案將於小水母休眠後刪除。', u'LINE內建瀏覽器無法下載檔案，請自行複製連結至手機瀏覽器。', u'若要將動態貼圖轉為gif，請點此 https://ezgif.com/apng-to-gif', u'']
            ret.append(u'圖包ID: {}'.format(sticker_meta.pack_id))
            ret.append(u'{} (由 {} 製作)'.format(sticker_meta.title, sticker_meta.author))
            ret.append(u'')
            ret.append(u'檔案下載連結: (如下)')
            ret.append(u'下載耗時 {:.3f} 秒'.format(dl_result.downloading_consumed_time))
            ret.append(u'壓縮耗時 {:.3f} 秒'.format(dl_result.compression_consumed_time))
            ret.append(u'內含貼圖 {} 張'.format(dl_result.sticker_count))

            return [bot.line_api_wrapper.wrap_text_message(txt, self._webpage_generator) for txt in (u'\n'.join(ret), url + dl_result.compressed_file_path.replace("\\", "\\\\"))]
        else:
            raise RegexNotImplemented(error.sys_command.regex_not_implemented(u'DL', regex_result.match_at, regex_result.regex))
        
    def _STK(self, src, execute_in_gid, group_config_type, executor_permission, text):
        regex_list = [ur'小水母 貼圖(圖包)?排行 ?(前(\d+)名)? ?((\d+)小時內)?', 
                      ur'小水母 貼圖(\d+)']
        
        regex_result = tool.regex_finder.find_match(regex_list, text)

        if regex_result is None:
            return

        if regex_result.match_at == 0:
            limit_count = regex_result.group(3)
            if limit_count is None:
                limit_count = self._config_manager.getint(bot.config_category.STICKER_RANKING, bot.config_category_sticker_ranking.LIMIT_COUNT)
            limit_count = ext.string_to_int(limit_count)
            if limit_count is None:
                raise RuntimeError('limit_count is not integer.')

            hour_range = regex_result.group(5)
            if hour_range is None:
                hour_range = self._config_manager.getint(bot.config_category.STICKER_RANKING, bot.config_category_sticker_ranking.HOUR_RANGE)
            hour_range = ext.string_to_int(hour_range)
            if hour_range is None:
                raise RuntimeError('hour_range is not integer.')
                
            is_package = regex_result.group(1) is not None

            if is_package:
                result = self._stk_rec.hottest_sticker_str(hour_range, limit_count)
            else:
                result = self._stk_rec.hottest_package_str(hour_range, limit_count)

            if isinstance(result, db.PackedResult):
                full_url = self._webpage_generator.rec_webpage(result.full, db.webpage_content_type.STICKER_RANKING)
                return result.limited + u'\n\n詳細資訊: ' + full_url
            else:
                return result
        elif regex_result.match_at == 1:
            sticker_id = regex_result.group(1)

            return bot.line_api_wrapper.wrap_image_message(bot.line_api_wrapper.sticker_png_url(sticker_id))
        else:
            raise RegexNotImplemented(error.sys_command.regex_not_implemented(u'STK', regex_result.match_at, regex_result.regex))

    @staticmethod
    def can_try_handle(full_text):
        return full_text.startswith(text_msg_handler.HEAD) or bot.line_api_wrapper.is_valid_room_group_id(full_text.split(text_msg_handler.REMOTE_SPLITTER)[0], True, True)

class game_msg_handler(object):
    HEAD = u'小遊戲 '
    SPLITTER = u'\n'

    def __init__(self, mongo_db_uri, line_api_wrapper):
        self._rps_holder = db.rps_holder(mongo_db_uri)
        self._line_api_wrapper = line_api_wrapper
        
    def handle_text(self, event, user_permission):
        """Return whether message has been replied"""
        token = event.reply_token
        text = unicode(event.message.text)
        src = event.source

        src_uid = bot.line_api_wrapper.source_user_id(src)

        if user_permission == bot.permission.RESTRICTED:
            self._line_api_wrapper.reply_message_text(token, error.permission.user_is_resticted())
            return True

        cmd_data = None
        for cmd_kw, cmd_obj in bot.game_cmd_dict.iteritems():
            if text.startswith(game_msg_handler.HEAD + cmd_kw):
                cmd_data = cmd_obj
                break

        if cmd_data is None:
            print 'Called an not existed command.'
            return False

        cmd_function = getattr(self, '_{}'.format(cmd_data.function_code))

        handle_result = cmd_function(src, user_permission, text)
        if handle_result is None:
            return self._line_api_wrapper.reply_message_text(token, error.sys_command.syntax_error(cmd_data.function_code))
        else:
            if isinstance(handle_result, (str, unicode)):
                self._line_api_wrapper.reply_message_text(token, handle_result)
                return True
            else:
                self._line_api_wrapper.reply_message(token, handle_result)
                return True

        return False
    
    def _RPS(self, src, executor_permission, text):
        regex_list = [ur'小遊戲 猜拳(狀況|啟用|停用|重設|註冊|結束)',
                      ur'小遊戲 猜拳開始 ?(\d+) (\d+) (\d+)',
                      ur'小遊戲 猜拳代表 ?(剪刀|石頭|布) ?((貼圖) ?(\d+)|(\w+))']
        
        regex_result = tool.regex_finder.find_match(regex_list, text)

        if regex_result is None:
            return
        
        executor_cid = bot.line_api_wrapper.source_channel_id(src)
        executor_uid = bot.line_api_wrapper.source_user_id(src)

        if regex_result.match_at == 0:
            action = regex_result.group(1)

            if action == u'狀況':
                return self._rps_holder.game_statistics(executor_cid)
            elif action == u'啟用':
                return self._rps_holder.set_enabled(executor_cid, True)
            elif action == u'停用':
                return self._rps_holder.set_enabled(executor_cid, True)
            elif action == u'重設':
                return self._rps_holder.reset_statistics(executor_cid)
            elif action == u'結束':
                return self._rps_holder.delete_game(executor_cid)
            elif action == u'註冊':
                try:
                    player_name = self._line_api_wrapper.profile_name(executor_uid)
                except bot.UserProfileNotFoundError:
                    return error.line_bot_api.unable_to_receive_user_id()

                if bot.line_api_wrapper.is_valid_user_id(executor_uid):
                    return self._rps_holder.register_player(executor_cid, executor_uid, player_name)
                else:
                    return error.line_bot_api.unable_to_receive_user_id()
            else:
                return error.sys_command.action_not_implemented(u'RPS', regex_result.match_at, action)
        elif regex_result.match_at == 1:
            scissor = regex_result.group(1)
            rock = regex_result.group(2)
            paper = regex_result.group(3)

            try:
                creator_name = self._line_api_wrapper.profile_name(executor_uid)
            except bot.UserProfileNotFoundError:
                return error.line_bot_api.unable_to_receive_user_id()

            return self._rps_holder.create_game(executor_cid, executor_uid, creator_name, rock, paper, scissor)
        elif regex_result.match_at == 2:
            repr_dict = { u'剪刀': db.battle_item.SCISSOR, u'石頭': db.battle_item.ROCK, u'布': db.battle_item.PAPER }
            repr = repr_dict.get(regex_result.group(1))
            if repr is None:
                return error.sys_command.action_not_implemented(u'RPS', regex_result.match_at, repr)

            is_sticker = regex_result.group(3) is not None

            if is_sticker:
                repr_content = regex_result.group(4)
            else:
                repr_content = regex_result.group(5)
                
            return self._rps_holder.register_battleitem(executor_cid, repr_content, is_sticker, repr)
        else:
            raise RegexNotImplemented(error.sys_command.regex_not_implemented(u'RPS', regex_result.match_at, regex_result.regex))

    @staticmethod
    def can_try_handle(full_text):
        return full_text.startswith(game_msg_handler.HEAD)
 
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

class ActionNotImplemented(Exception):
    def __init__(self, *args):
        return super(ActionNotImplemented, self).__init__(*args)

class RegexNotImplemented(Exception):
    def __init__(self, *args):
        return super(RegexNotImplemented, self).__init__(*args)