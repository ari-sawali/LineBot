# -*- coding: utf-8 -*-
import os, sys
import json
from datetime import datetime, timedelta
import hashlib
import re

from flask import request, url_for
import pymongo

import tool
from error import error
import bot, db, ext

from .misc import *
from .text_msg_param import *

class text_msg_handler(object):
    # TODO: Modulize each command

    CH_HEAD = u'小水母 '
    EN_HEAD = u'JC\n'

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
        self._pli = tool.currency.pypli()
        self._ctyccy = tool.currency.countries_and_currencies()
        
        self._pymongo_client = None
        
    # TODO: Modulize this
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
            text = text

        cmd_data = self._get_cmd_data(text)

        # terminate if set to silence
        if group_config_type <= db.config_type.SILENCE and cmd_data.function_code != 'GA':
            print 'Terminate because the group is set to silence and function code is not GA.'
            return False

        if cmd_data is None:
            print 'Called an not existed command.'
            return False

        # log statistics
        self._system_stats.command_called(cmd_data.function_code)

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

    def _get_cmd_data(self, text):
        for cmd_obj in bot.sys_cmd_dict.itervalues():
            for header in cmd_obj.headers:
                if text.startswith(text_msg_handler.CH_HEAD + header) or text.startswith(text_msg_handler.EN_HEAD + header):
                    return cmd_obj

    def _get_kwd_instance(self, src, config, execute_remote_gid=None):
        cid = bot.line_api_wrapper.source_channel_id(src)

        if bot.line_api_wrapper.is_valid_room_group_id(execute_remote_gid, True, True):
            config = self._group_manager.get_group_config_type(execute_remote_gid)
        else:
            config = self._group_manager.get_group_config_type(cid)
            execute_remote_gid = None

        if config is not None and config == db.config_type.ALL:
            manager_range = db.group_dict_manager_range.GROUP_AND_PUBLIC
        else:
            manager_range = db.group_dict_manager_range.GROUP_ONLY

        if execute_remote_gid == bot.remote.GLOBAL_TOKEN():
            kwd_instance = self._kwd_public.clone_instance(self._mongo_uri, db.PUBLIC_GROUP_ID, db.group_dict_manager_range.GLOBAL)
        elif execute_remote_gid == bot.remote.PUBLIC_TOKEN():
            kwd_instance = self._kwd_public.clone_instance(self._mongo_uri, db.PUBLIC_GROUP_ID)
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

    def _get_query_result(self, pack_result, execute_in_gid, kwd_instance, exact_same):
        cmd_cat = pack_result.command_category
        prm_dict = pack_result.result

        if cmd_cat == param_packer.func_Q.command_category.BY_AVAILABLE:
            if prm_dict[param_packer.func_Q.param_category.GLOBAL]:
                expr = u'搜尋範圍: 全域回覆組'
                result_data = self._kwd_global.get_pairs_by_group_id(bot.remote.GLOBAL_TOKEN(), True)
            elif prm_dict[param_packer.func_Q.param_category.AVAILABLE]:
                expr = u'搜尋範圍: 本頻道( {} )可用的回覆組'.format(execute_in_gid)
                result_data = kwd_instance.search_all_available_pair()
            else:
                return ext.action_result(UndefinedParameterException(), False)
        elif cmd_cat == param_packer.func_Q.command_category.BY_ID_RANGE:
            expr = u'搜尋範圍: ID介於【{}】~【{}】之間的回覆組'.format(prm_dict[param_packer.func_Q.param_category.START_ID], 
                                                                     prm_dict[param_packer.func_Q.param_category.END_ID])
            result_data = kwd_instance.search_pair_by_index(prm_dict[param_packer.func_Q.param_category.START_ID], 
                                                            prm_dict[param_packer.func_Q.param_category.END_ID])
        elif cmd_cat == param_packer.func_Q.command_category.BY_GID:
            expr = u'搜尋範圍: 群組ID {} 內專屬的回覆組'.format(prm_dict[param_packer.func_Q.param_category.GID])
            result_data = self._kwd_global.get_pairs_by_group_id(prm_dict[param_packer.func_Q.param_category.GID], True)
        elif cmd_cat == param_packer.func_Q.command_category.BY_UID:
            get_name_result = self._get_user_name(prm_dict[param_packer.func_Q.param_category.UID])

            expr = u'搜尋範圍: 由 {} ({}) 製作的回覆組'.format(get_name_result.result, prm_dict[param_packer.func_Q.param_category.UID])
            result_data = kwd_instance.search_pair_by_creator(prm_dict[param_packer.func_Q.param_category.UID])
        elif cmd_cat == param_packer.func_Q.command_category.BY_KEY:
            if prm_dict[param_packer.func_Q.param_category.IS_ID]:
                search_source = prm_dict[param_packer.func_Q.param_category.ID]

                expr = u'搜尋範圍: ID為【{}】的回覆組'.format(u'、'.join([str(id) for id in search_source]))
                result_data = kwd_instance.search_pair_by_index(search_source)
            else:
                search_source = prm_dict[param_packer.func_Q.param_category.KEYWORD]

                expr = u'搜尋範圍: 關鍵字 或 回覆 {}【{}】的回覆組'.format(u'為' if exact_same else u'含', search_source)
                result_data = kwd_instance.search_pair_by_keyword(search_source, exact_same)
        else:
            raise UndefinedCommandCategoryException()

        return ext.action_result([expr, result_data], True)

    def _get_executor_uid(self, src):
        # try to get complete profile
        try:
            uid = bot.line_api_wrapper.source_user_id(src)
            self._line_api_wrapper.profile_name(uid)
        except bot.UserProfileNotFoundError as ex:
            return ext.action_result(error.line_bot_api.unable_to_receive_user_id(), False)

        # verify uid structure
        if not bot.line_api_wrapper.is_valid_user_id(uid):
            return ext.action_result(error.line_bot_api.illegal_user_id(uid), False)

        return ext.action_result(uid, True)

    def _get_user_name(self, uid):
        try:
            return ext.action_result(self._line_api_wrapper.profile_name(uid), True)
        except bot.UserProfileNotFoundError:
            return ext.action_result(error.main.line_account_data_not_found(), False)

    def _replace_newline(self, text):
        if isinstance(text, unicode):
            return text.replace(u'\\n', u'\n')
        elif isinstance(text, str):
            return text.replace('\\n', '\n')
        elif isinstance(text, list):
            return [t.replace(u'\\n', u'\n') for t in text]
        else:
            return text

    def _reg_mongo(self):
        if self._pymongo_client is None:
            self._pymongo_client = pymongo.MongoClient(self._mongo_uri)

    def _S(self, src, execute_in_gid, group_config_type, executor_permission, text, pinned=False):
        packer_list = packer_factory._S
        
        for packer in packer_list:
            packing_result = packer.pack(text)
            if packing_result.status == param_packing_result_status.ALL_PASS:
                self._reg_mongo()

                param_dict = packing_result.result

                text = self._S_generate_output_head(param_dict)
                try:
                    text += self._S_generate_output_mongo_result(param_dict)
                except pymongo.errors.OperationFailure as ex:
                    text += error.mongo_db.op_fail(ex)

                return text
            elif packing_result.status == param_packing_result_status.ERROR_IN_PARAM:
                return unicode(packing_result.result)
            elif packing_result.status == param_packing_result_status.NO_MATCH:
                pass
            else:
                raise UndefinedPackedStatusException(unicode(packing_result.status))

    def _S_generate_output_head(self, param_dict):
        text = u'目標資料庫:\n{}\n'.format(param_dict[param_packer.func_S.param_category.DB_NAME])
        text += u'資料庫主指令:\n{}\n'.format(param_dict[param_packer.func_S.param_category.MAIN_CMD])
        text += u'資料庫主指令參數:\n{}\n'.format(param_dict[param_packer.func_S.param_category.MAIN_PRM])
        text += u'資料庫副指令:\n{}\n\n'.format(param_dict[param_packer.func_S.param_category.OTHER_PRM])

        return text

    def _S_generate_output_mongo_result(self, param_dict):
        return ext.object_to_json(self._S_execute_mongo_shell(param_dict))

    def _S_execute_mongo_shell(self, param_dict):
        return self._pymongo_client.get_database(param_dict[param_packer.func_S.param_category.DB_NAME]) \
                                   .command(param_dict[param_packer.func_S.param_category.MAIN_CMD], 
                                            param_dict[param_packer.func_S.param_category.MAIN_PRM], 
                                            **param_dict[param_packer.func_S.param_category.OTHER_PRM])
    
    def _A(self, src, execute_in_gid, group_config_type, executor_permission, text, pinned=False):
        if pinned:
            packer_list = packer_factory._M
        else:
            packer_list = packer_factory._A

        for packer in packer_list:
            packing_result = packer.pack(text)
            if packing_result.status == param_packing_result_status.ALL_PASS:
                get_uid_result = self._get_executor_uid(src)
                if not get_uid_result.success:
                    return get_uid_result.result

                kwd_instance = self._get_kwd_instance(src, group_config_type, execute_in_gid)
                kwd_add_result = self._A_add_kw(kwd_instance, packing_result, pinned, get_uid_result.result)

                return self._A_generate_output(kwd_add_result)
            elif packing_result.status == param_packing_result_status.ERROR_IN_PARAM:
                return unicode(packing_result.result)
            elif packing_result.status == param_packing_result_status.NO_MATCH:
                pass
            else:
                raise UndefinedPackedStatusException(unicode(packing_result.status))

    def _A_add_kw(self, kwd_instance, packing_result, pinned, adder_uid):
        param_dict = packing_result.result

        rcv_type_result = self._A_get_rcv_type(packing_result)
        rcv_content = self._A_get_rcv_content(packing_result)
        rep_type_result = self._A_get_rep_type(packing_result)
        rep_content = self._A_get_rep_content(packing_result)

        if not rcv_type_result.success:
            return rcv_type_result.result

        if not rep_type_result.success:
            return rep_type_result.result

        # create and write
        result = kwd_instance.insert_keyword(rcv_content, rep_content, adder_uid, pinned, rcv_type_result.result, rep_type_result.result, None, param_dict[param_packer.func_A.param_category.ATTACHMENT])

        return ext.action_result(result, isinstance(result, db.pair_data))

    def _A_generate_output(self, kwd_add_result):
        if kwd_add_result.success:
            if isinstance(kwd_add_result.result, (str, unicode)):
                return result
            elif isinstance(kwd_add_result.result, db.pair_data):
                return u'回覆組新增成功。\n' + kwd_add_result.result.basic_text(True)
            else:
                raise ValueError('Unhandled type of return result. ({} - {})'.format(type(kwd_add_result.result), kwd_add_result.result))
        else:
            return u'回覆組新增失敗。\n\n{}'.format(kwd_add_result.result)

    def _A_is_auto_detect(self, packing_result):
        return any(packing_result.command_category == cat for cat in (param_packer.func_A.command_category.ADD_PAIR_AUTO_CH, param_packer.func_A.command_category.ADD_PAIR_AUTO_EN))

    def _A_get_rcv_type(self, packing_result):
        param_dict = packing_result.result
        if self._A_is_auto_detect(packing_result):
            return param_validator.keyword_dict.get_type_auto(param_dict[param_packer.func_A.param_category.RCV_CONTENT], False)
        else:
            return ext.action_result(param_dict[param_packer.func_A.param_category.RCV_TYPE], True)

    def _A_get_rep_type(self, packing_result):
        param_dict = packing_result.result
        if self._A_is_auto_detect(packing_result):
            return param_validator.keyword_dict.get_type_auto(param_dict[param_packer.func_A.param_category.REP_CONTENT], False)
        else:
            return ext.action_result(param_dict[param_packer.func_A.param_category.REP_TYPE], True)

    def _A_get_rcv_content(self, packing_result):
        param_dict = packing_result.result
        cmd_cat = packing_result.command_category

        if self._A_is_auto_detect(packing_result):
            return param_dict[param_packer.func_A.param_category.RCV_CONTENT]
        else:
            if param_dict[param_packer.func_A.param_category.RCV_TYPE] == db.word_type.TEXT:
                t = param_dict[param_packer.func_A.param_category.RCV_TXT]

                if cmd_cat == param_packer.func_A.command_category.ADD_PAIR_AUTO_EN:
                    t = self._replace_newline(t)

                return t
            elif param_dict[param_packer.func_A.param_category.RCV_TYPE] == db.word_type.STICKER:
                return param_dict[param_packer.func_A.param_category.RCV_STK]
            elif param_dict[param_packer.func_A.param_category.RCV_TYPE] == db.word_type.PICTURE:
                return param_dict[param_packer.func_A.param_category.RCV_PIC]

    def _A_get_rep_content(self, packing_result):
        param_dict = packing_result.result
        cmd_cat = packing_result.command_category

        if self._A_is_auto_detect(packing_result):
            return param_dict[param_packer.func_A.param_category.REP_CONTENT]
        else:
            if param_dict[param_packer.func_A.param_category.REP_TYPE] == db.word_type.TEXT:
                t = param_dict[param_packer.func_A.param_category.REP_TXT]

                if cmd_cat == param_packer.func_A.command_category.ADD_PAIR_AUTO_EN:
                    t = self._replace_newline(t)

                return t
            elif param_dict[param_packer.func_A.param_category.REP_TYPE] == db.word_type.STICKER:
                return param_dict[param_packer.func_A.param_category.REP_STK]
            elif param_dict[param_packer.func_A.param_category.REP_TYPE] == db.word_type.PICTURE:
                return param_dict[param_packer.func_A.param_category.REP_PIC]
        
    def _M(self, src, execute_in_gid, group_config_type, executor_permission, text):
        return self._A(src, execute_in_gid, group_config_type, executor_permission, text, True)
    
    def _D(self, src, execute_in_gid, group_config_type, executor_permission, text, pinned=False):
        if pinned:
            packer_list = packer_factory._R
        else:
            packer_list = packer_factory._D

        for packer in packer_list:
            packing_result = packer.pack(text)
            if packing_result.status == param_packing_result_status.ALL_PASS:
                get_uid_result = self._get_executor_uid(src)
                if not get_uid_result.success:
                    return get_uid_result.result

                kwd_instance = self._get_kwd_instance(src, group_config_type, execute_in_gid)
                kwd_del_result = self._D_del_kw(kwd_instance, packing_result, pinned, get_uid_result.result)

                return self._D_generate_output(kwd_del_result)
            elif packing_result.status == param_packing_result_status.ERROR_IN_PARAM:
                return unicode(packing_result.result)
            elif packing_result.status == param_packing_result_status.NO_MATCH:
                pass
            else:
                raise UndefinedPackedStatusException(unicode(packing_result.status))

    def _D_del_kw(self, kwd_instance, packing_result, pinned, exceutor_uid):
        param_dict = packing_result.result

        if param_dict[param_packer.func_D.param_category.IS_ID]:
            disabled_ids = kwd_instance.disable_keyword_by_id(param_dict[param_packer.func_D.param_category.ID], del_profile_uid, pinned)
        else:
            disabled_ids = kwd_instance.disable_keyword_by_id(self._replace_newline(param_dict[param_packer.func_D.param_category.WORD]), del_profile_uid, pinned)

        return ext.action_result(disabled_ids, len(disabled_ids) > 0)

    def _D_generate_output(self, del_result):
        if del_result.success:
            text = u'回覆組刪除成功。\n'
            text += '\n'.join([data.basic_text(True) for data in del_result.result])
            return text
        else:
            return error.main.miscellaneous(error.main.pair_not_exist_or_insuffieicnt_permission() + u'若欲使用ID作為刪除根據，請參閱小水母使用說明。')

    def _R(self, src, execute_in_gid, group_config_type, executor_permission, text):
        return self._D(src, execute_in_gid, group_config_type, executor_permission, text, True)
    
    def _Q(self, src, execute_in_gid, group_config_type, executor_permission, text):
        packer_list = packer_factory._Q

        for packer in packer_list:
            packing_result = packer.pack(text)
            if packing_result.status == param_packing_result_status.ALL_PASS:
                kwd_instance = self._get_kwd_instance(src, group_config_type, execute_in_gid)
                query_result = self._get_query_result(packing_result, execute_in_gid, kwd_instance, False)

                return self._Q_generate_output(query_result)
            elif packing_result.status == param_packing_result_status.ERROR_IN_PARAM:
                return unicode(packing_result.result)
            elif packing_result.status == param_packing_result_status.NO_MATCH:
                pass
            else:
                raise UndefinedPackedStatusException(unicode(packing_result.status))

    def _Q_generate_output(self, query_result):
        if query_result.success:
            max_count = self._config_manager.getint(bot.config.config_category.KEYWORD_DICT, bot.config.config_category_kw_dict.MAX_QUERY_OUTPUT_COUNT)
            str_length = self._config_manager.getint(bot.config.config_category.KEYWORD_DICT, bot.config.config_category_kw_dict.MAX_SIMPLE_STRING_LENGTH)

            title, data = query_result.result

            output = db.keyword_dict.group_dict_manager.list_keyword(data, max_count, title, error.main.no_result(), str_length)

            text = output.limited
            if output.has_result:
                text += u'\n\n完整結果: {}'.format(self._webpage_generator.rec_webpage(output.full, db.webpage_content_type.QUERY))
            return text
        else:
            return unicode(query_result.result)
    
    def _I(self, src, execute_in_gid, group_config_type, executor_permission, text):
        packer_list = packer_factory._I

        for packer in packer_list:
            packing_result = packer.pack(text)
            if packing_result.status == param_packing_result_status.ALL_PASS:
                kwd_instance = self._get_kwd_instance(src, group_config_type, execute_in_gid)
                query_result = self._get_query_result(packer, execute_in_gid, kwd_instance, False)

                return self._I_generate_output(query_result)
            elif packing_result.status == param_packing_result_status.ERROR_IN_PARAM:
                return unicode(packing_result.result)
            elif packing_result.status == param_packing_result_status.NO_MATCH:
                pass
            else:
                raise UndefinedPackedStatusException(unicode(packing_result.status))

        regex_list = packer_factory._I

    def _I_generate_output(self, query_result):
        if query_result.success:
            max_count = self._config_manager.getint(bot.config.config_category.KEYWORD_DICT, bot.config.config_category_kw_dict.MAX_INFO_OUTPUT_COUNT)
            
            title, data = query_result.result

            output = db.keyword_dict.group_dict_manager.list_keyword_info(data, kwd_instance, self._line_api_wrapper, max_count, title.replace('\n', ''),  error.main.no_result())

            text = output.limited
            if output.has_result:
                text += u'\n\n完整結果: {}'.format(self._webpage_generator.rec_webpage(output.full, db.webpage_content_type.INFO))
            return text
        else:
            return unicode(query_result.result)
    
    ####################
    ### UNDONE BELOW ###
    ####################

    def _X(self, src, execute_in_gid, group_config_type, executor_permission, text):
        regex_list = packer_factory._X
        
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
                source = ext.to_int(regex_result.group(3).split(self._array_separator))
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
                        u'回覆組資料查詢(簡略)': text_msg_handler.CH_HEAD + u'找ID範圍' + first_id_str + u'到' + last_id_str,
                        u'回覆組資料查詢(詳細)': text_msg_handler.CH_HEAD + u'詳細找ID範圍' + first_id_str + u'到' + last_id_str } ,u'新建回覆組相關指令樣板', u'相關指令')]
        else:
            return u'回覆組複製失敗。回覆組來源沒有符合條件的回覆組可供複製。'
        
    def _X2(self, src, execute_in_gid, group_config_type, executor_permission, text):
        regex_list = packer_factory._X2

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
        regex_list = packer_factory._E
        
        regex_result = tool.regex_finder.find_match(regex_list, text)

        if regex_result is None:
            return
        
        # assign keyword instance
        kwd_instance = self._get_kwd_instance(src, group_config_type, execute_in_gid)
        
        # validate and assign modify target array
        is_ids = regex_result.group(2) is not None
        if is_ids:
            target_array = ext.to_int(regex_result.group(3).split(self._array_separator))
        else:
            target_array = regex_result.group(1).split(self._array_separator)

        if target_array is None:
            return error.main.invalid_thing_with_correct_format(u'參數1', u'正整數、正整數陣列(代表ID)或字串、字串陣列(代表關鍵字)', regex_result.group(1))

        # create template of target item
        if is_ids:
            expr = u'、'.join([u'#{}'.format(str(id)) for id in target_array])

            shortcut_template = bot.line_api_wrapper.wrap_template_with_action({ '回覆組詳細資訊(#{})'.format(id): text_msg_handler.CH_HEAD + u'詳細找ID {}'.format(id) for id in target_array }, u'更動回覆組ID: {}'.format(expr), u'相關指令')
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
        regex_list = packer_factory._K
        
        regex_result = tool.regex_finder.find_match(regex_list, text)

        if regex_result is None:
            return

        kwd_instance = self._get_kwd_instance(src, group_config_type, execute_in_gid)
        default = self._config_manager.getint(bot.config_category.KEYWORD_DICT, bot.config_category_kw_dict.DEFAULT_RANK_RESULT_COUNT)
        
        limit = regex_result.group(2)
        # validate parameters
        if limit is not None:
            limit = ext.to_int(limit)
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
        regex_list = packer_factory._P
        
        regex_result = tool.regex_finder.find_match(regex_list, text)

        if regex_result is None:
            return

        if regex_result.match_at == 0:
            limit = ext.to_int(regex_result.group(1))

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
        regex_list = packer_factory._P2
        
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
                        bot.line_api_wrapper.wrap_template_with_action({ u'查詢該使用者製作的回覆組': text_msg_handler.CH_HEAD + u'找' + uid + u'做的' }, u'回覆組製作查詢快捷樣板', u'快捷查詢')]
            else:
                return error.line_bot_api.illegal_user_id(uid)
        else:
            raise RegexNotImplemented(error.sys_command.regex_not_implemented(u'P2', regex_result.match_at, regex_result.regex))

    def _G(self, src, execute_in_gid, group_config_type, executor_permission, text):
        regex_list = packer_factory._G
        
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
                    bot.line_api_wrapper.wrap_template_with_action({ u'查詢群組資料庫': text_msg_handler.CH_HEAD + u'找' + gid + u'裡面的'}, u'快速查詢群組資料庫樣板', u'相關指令'))
        else:
            raise RegexNotImplemented(error.sys_command.regex_not_implemented(u'G', regex_result.match_at, regex_result.regex))
        
    def _GA(self, src, execute_in_gid, group_config_type, executor_permission, text):
        regex_list = packer_factory._GA

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
        regex_list = packer_factory._GA2

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

            action = ext.to_int(regex_result.group(2))

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
        regex_list = packer_factory._GA3

        regex_result = tool.regex_finder.find_match(regex_list, text)

        if regex_result is None:
            return

        if regex_result.match_at == 0:
            activate_result = self._group_manager.activate(execute_in_gid, regex_result.group(0))
            return u'公用資料庫啟用{}。'.format(u'成功' if activate_result else u'失敗')
        else:
            raise RegexNotImplemented(error.sys_command.regex_not_implemented(u'GA3', regex_result.match_at, regex_result.regex))
        
    def _H(self, src, execute_in_gid, group_config_type, executor_permission, text):
        regex_list = packer_factory._H
        
        regex_result = tool.regex_finder.find_match(regex_list, text)

        if regex_result is None:
            return
        
        if regex_result.match_at == 0:
            channel_id = bot.line_api_wrapper.source_channel_id(src)

            return [bot.line_api_wrapper.wrap_text_message(txt, self._webpage_generator) for txt in (str(bot.line_event_source_type.determine(src)), channel_id)]
        else:
            raise RegexNotImplemented(error.sys_command.regex_not_implemented(u'H', regex_result.match_at, regex_result.regex))
    
    def _SHA(self, src, execute_in_gid, group_config_type, executor_permission, text):
        regex_list = packer_factory._SHA
        
        regex_result = tool.regex_finder.find_match(regex_list, text)

        if regex_result is None:
            return
        
        if regex_result.match_at == 0:
            target = regex_result.group(1)

            return hashlib.sha224(target.encode('utf-8')).hexdigest()
        else:
            raise RegexNotImplemented(error.sys_command.regex_not_implemented(u'SHA', regex_result.match_at, regex_result.regex))
    
    def _O(self, src, execute_in_gid, group_config_type, executor_permission, text):
        regex_list = packer_factory._O
        
        regex_result = tool.regex_finder.find_match(regex_list, text)

        if regex_result is None:
            return

        if regex_result.match_at == 0:
            voc = regex_result.group(1)

            if not self._oxford_dict.enabled:
                return error.oxford_api.disabled()
            else:
                return bot.oxford_api_wrapper.json_to_string(voc, self._oxford_dict.get_data_json(voc))
        else:
            raise RegexNotImplemented(error.sys_command.regex_not_implemented(u'O', regex_result.match_at, regex_result.regex))
    
    def _RD(self, src, execute_in_gid, group_config_type, executor_permission, text):
        regex_list = packer_factory._RD

        regex_result = tool.regex_finder.find_match(regex_list, text)

        if regex_result is None:
            return

        if regex_result.match_at == 0:
            probability = regex_result.group(2)
            scout_count = ext.to_int(regex_result.group(4))

            if scout_count is None:
                scout_count = 1

            return tool.random_drawer.draw_probability_string(probability, True, scout_count, 3)
        elif regex_result.match_at == 1:
            times = ext.to_int(regex_result.group(2))
            texts = regex_result.group(3)

            if times is None:
                times = 1

            return tool.random_gen.random_drawer.draw_text_string(texts.split(self._array_separator), times)
        elif regex_result.match_at == 2:
            start_index = ext.to_int(regex_result.group(1))
            end_index = ext.to_int(regex_result.group(2))

            if start_index is None:
                return error.sys_command.action_not_implemented(u'RD', regex_result.match_at, start_index)

            if end_index is None:
                return error.sys_command.action_not_implemented(u'RD', regex_result.match_at, end_index)

            return tool.random_drawer.draw_number_string(start_index, end_index)
        else:
            raise RegexNotImplemented(error.sys_command.regex_not_implemented(u'RD', regex_result.match_at, regex_result.regex))
    
    def _L(self, src, execute_in_gid, group_config_type, executor_permission, text):
        regex_list = packer_factory._L

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
                    action_dict['簡潔 - {}'.format(stk_id)] = text_msg_handler.CH_HEAD + u'找' + stk_id
                    action_dict['詳細 - {}'.format(stk_id)] = text_msg_handler.CH_HEAD + u'詳細找' + stk_id
                    action_dict['貼圖包下載 - {}'.format(pkg_id)] = text_msg_handler.CH_HEAD + u'下載貼圖圖包' + pkg_id
            elif last_action_enum == bot.system_data_category.LAST_PAIR_ID:
                action_dict = {}
                for item in last_array:
                    item = str(item)
                    action_dict['簡潔 - {}'.format(item)] = text_msg_handler.CH_HEAD + u'找ID ' + item
                    action_dict['詳細 - {}'.format(item)] = text_msg_handler.CH_HEAD + u'詳細找ID ' + item
            elif last_action_enum == bot.system_data_category.LAST_UID:
                action_dict = { 
                    '使用者{}製作'.format(uid[0:9]): text_msg_handler.CH_HEAD + u'找' + uid + u'做的' for uid in last_array
                }
            elif last_action_enum == bot.system_data_category.LAST_PIC_SHA:
                action_dict = {}
                for sha in last_array:
                    sha = str(sha)
                    action_dict['簡潔 - {}'.format(sha)] = text_msg_handler.CH_HEAD + u'找' + sha
                    action_dict['詳細 - {}'.format(sha)] = text_msg_handler.CH_HEAD + u'詳細找' + sha

            rep_list.append(bot.line_api_wrapper.wrap_template_with_action(action_dict, u'{}快捷查詢樣板'.format(unicode(last_action_enum)), u'快捷指令/快速查詢'))

            return rep_list
        else:
            raise RegexNotImplemented(error.sys_command.regex_not_implemented(u'L', regex_result.match_at, regex_result.regex))
             
    def _T(self, src, execute_in_gid, group_config_type, executor_permission, text):
        from urllib import quote_plus

        regex_list = packer_factory._T
        
        regex_result = tool.regex_finder.find_match(regex_list, text)

        if regex_result is None:
            return
        
        if regex_result.match_at == 0:
            text = regex_result.group(1)

            return quote_plus(text.encode('utf-8'))
        else:
            raise RegexNotImplemented(error.sys_command.regex_not_implemented(u'T', regex_result.match_at, regex_result.regex))
    
    def _C(self, src, execute_in_gid, group_config_type, executor_permission, text):
        regex_list = packer_factory._C
        
        regex_result = tool.regex_finder.find_match(regex_list, text)

        if regex_result is None:
            return
        
        if regex_result.match_at == 0:
            is_requesting_available_currencies = regex_result.group(1) is not None

            if is_requesting_available_currencies:
                return tool.currency.oxr.available_currencies_str(self._oxr_client.get_available_currencies_dict())
            else:
                return tool.currency.oxr.latest_str(self._oxr_client.get_latest_dict())
        elif regex_result.match_at == 1:
            currencies = regex_result.group(1)

            return tool.currency.oxr.latest_str(self._oxr_client.get_latest_dict(currencies))
        elif regex_result.match_at == 2:
            historical_date = regex_result.group(2) + regex_result.group(3) + regex_result.group(4)
            currencies = regex_result.group(6)

            if currencies is not None:
                return tool.currency.oxr.historical_str(self._oxr_client.get_historical_dict(historical_date, currencies))
            else:
                return tool.currency.oxr.historical_str(self._oxr_client.get_historical_dict(historical_date))
        elif regex_result.match_at == 3:
            source_currency = regex_result.group(1)
            amount = regex_result.group(2)
            target_currency = regex_result.group(3)

            ret = []

            conv_result = self._oxr_client.convert(source_currency, target_currency, amount)
            ret.append(conv_result.formatted_string)
            ret.append(u'')
            ret.append(u'物價水平(PLI)補正計算(使用指令PLI可獲得完整資訊):')

            country_entries_source = self._ctyccy.get_country_entry(currency_codes=source_currency)
            country_entries_target = self._ctyccy.get_country_entry(currency_codes=target_currency)
            plis_source = self._pli.get_pli(country_codes=[ce_s.get_data(tool.currency.country_entry_column.CountryCode) for ce_s in country_entries_source])
            plis_target = self._pli.get_pli(country_codes=[ce_t.get_data(tool.currency.country_entry_column.CountryCode) for ce_t in country_entries_target])

            for pli_s in plis_source:
                for pli_t in plis_target:
                    ret.append(u'於{} (使用{})換算至{} (使用{})'.format(pli_s.get_data(tool.currency.pli_category.CountryName), source_currency, pli_t.get_data(tool.currency.pli_category.CountryName), target_currency))
                    cat_to_calc = [tool.currency.pli_category.Health, tool.currency.pli_category.Transport, tool.currency.pli_category.Education]
                    
                    for cat in cat_to_calc:
                        pli_comp = pli_t.get_data(cat) / pli_s.get_data(cat)
                        actual_amount = conv_result.result * pli_comp
                        actual_amount_trans = (1 / conv_result.rate) * actual_amount
                        
                        ret.append(u'{}: 約{} {:.2f} ({} {:.2f})'.format(unicode(cat), source_currency, actual_amount_trans, target_currency, actual_amount))

            return u'\n'.join(ret)
        else:
            raise RegexNotImplemented(error.sys_command.regex_not_implemented(u'T', regex_result.match_at, regex_result.regex))
             
    def _FX(self, src, execute_in_gid, group_config_type, executor_permission, text):
        regex_list = packer_factory._FX
        
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
        regex_list = packer_factory._W
        
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
                action_dict = { str(id): text_msg_handler.CH_HEAD + u'天氣查詢ID ' + str(id) for id, city_name, country_code in search_result_simp }
                return [bot.line_api_wrapper.wrap_template_with_action(action_dict, u'搜尋結果快速查詢樣板', u'快速查詢樣板，請參考搜尋結果點選'),
                        bot.line_api_wrapper.wrap_text_message(u'\n'.join(result_arr), self._webpage_generator)]
            else:
                return u'{}\n{}\n若城市名為中文，請用該城市的英文名搜尋。'.format(search_desc, error.main.no_result())
        elif regex_result.match_at == 1:
            action = regex_result.group(1)
            station_ids = ext.to_int(regex_result.group(2).split(self._array_separator))

            hr_range = ext.to_int(regex_result.group(5))
            if hr_range is None:
                hr_range = self._config_manager.getint(bot.config_category.WEATHER_REPORT, bot.config_category_weather_report.DEFAULT_DATA_RANGE_HR)

            hr_freq = ext.to_int(regex_result.group(7))
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
        regex_list = packer_factory._DL
        
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
        regex_list = packer_factory._STK
        
        regex_result = tool.regex_finder.find_match(regex_list, text)

        if regex_result is None:
            return

        if regex_result.match_at == 0:
            limit_count = regex_result.group(3)
            if limit_count is None:
                limit_count = self._config_manager.getint(bot.config_category.STICKER_RANKING, bot.config_category_sticker_ranking.LIMIT_COUNT)
            limit_count = ext.to_int(limit_count)
            if limit_count is None:
                raise RuntimeError('limit_count is not integer.')

            hour_range = regex_result.group(5)
            if hour_range is None:
                hour_range = self._config_manager.getint(bot.config_category.STICKER_RANKING, bot.config_category_sticker_ranking.HOUR_RANGE)
            hour_range = ext.to_int(hour_range)
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

    # UNDONE, try to get complete pli data
    def _PLI(self, src, execute_in_gid, group_config_type, executor_permission, text):
        pass

    @staticmethod
    def can_try_handle(full_text):
        return full_text.startswith(text_msg_handler.CH_HEAD) or \
               full_text.startswith(text_msg_handler.EN_HEAD) or \
               bot.line_api_wrapper.is_valid_room_group_id(full_text.split(text_msg_handler.REMOTE_SPLITTER)[0], True, True)

class param_packer(object):
    class func_S(param_packer_base):
        class command_category(ext.EnumWithName):
            DB_COMMAND = 1, '資料庫指令'

        class param_category(ext.EnumWithName):
            DB_NAME = 1, '資料庫名稱'
            MAIN_CMD = 2, '主指令'
            MAIN_PRM = 3, '主參數'
            OTHER_PRM = 4, '其餘參數'

        def __init__(self, command_category, CH_regex=None, EN_regex=None):
            prm_objs = self._get_prm_objs(command_category)

            super(param_packer.func_S, self).__init__(command_category, prm_objs, CH_regex, EN_regex)

        def _get_prm_objs(self, command_category):
            if command_category == param_packer.func_S.command_category.DB_COMMAND:
                prm_objs = [parameter(param_packer.func_S.param_category.DB_NAME, param_validator.conv_unicode), 
                            parameter(param_packer.func_S.param_category.MAIN_CMD, param_validator.conv_unicode), 
                            parameter(param_packer.func_S.param_category.MAIN_PRM, param_validator.conv_unicode), 
                            parameter(param_packer.func_S.param_category.OTHER_PRM, param_validator.check_dict)]
            else:
                raise UndefinedCommandCategoryException()

            return prm_objs
    
    class func_A(param_packer_base):
        class command_category(ext.EnumWithName):
            ADD_PAIR_CH = 1, '新增回覆組(中文)'
            ADD_PAIR_EN = 2, '新增回覆組(英文)'
            ADD_PAIR_AUTO_CH = 3, '新增回覆組(自動偵測，中文)'
            ADD_PAIR_AUTO_EN = 4, '新增回覆組(自動偵測，英文)'

        class param_category(ext.EnumWithName):
            ATTACHMENT = 2, '附加回覆內容'
            RCV_TYPE = 3, '接收(種類)'
            RCV_TXT = 4, '接收(文字)'
            RCV_STK = 5, '接收(貼圖)'
            RCV_PIC = 6, '接收(圖片)'
            REP_TYPE = 7, '回覆(種類)'
            REP_TXT = 8, '回覆(文字)'
            REP_STK = 9, '回覆(貼圖)'
            REP_PIC = 10, '回覆(圖片)'
            RCV_CONTENT = 11, '接收(內容)'
            REP_CONTENT = 12, '回覆(內容)'

        def __init__(self, command_category, CH_regex=None, EN_regex=None):
            prm_objs = self._get_prm_objs(command_category)

            super(param_packer.func_A, self).__init__(command_category, prm_objs, CH_regex, EN_regex)

        def _get_prm_objs(self, command_category):
            if command_category == param_packer.func_A.command_category.ADD_PAIR_CH:
                prm_objs = [parameter(param_packer.func_A.param_category.ATTACHMENT, param_validator.conv_unicode, True),
                            parameter(param_packer.func_A.param_category.RCV_TYPE, param_validator.keyword_dict.conv_pair_type_from_org),  
                            parameter(param_packer.func_A.param_category.RCV_TXT, param_validator.conv_unicode, True),  
                            parameter(param_packer.func_A.param_category.RCV_PIC, param_validator.validate_sha224, True),  
                            parameter(param_packer.func_A.param_category.RCV_STK, param_validator.valid_int, True),  
                            parameter(param_packer.func_A.param_category.REP_TYPE, param_validator.keyword_dict.conv_pair_type_from_org), 
                            parameter(param_packer.func_A.param_category.REP_TXT, param_validator.conv_unicode, True), 
                            parameter(param_packer.func_A.param_category.REP_PIC, param_validator.validate_https, True), 
                            parameter(param_packer.func_A.param_category.REP_STK, param_validator.valid_int, True)]
            elif command_category == param_packer.func_A.command_category.ADD_PAIR_EN:
                prm_objs = [parameter(param_packer.func_A.param_category.RCV_TYPE, param_validator.keyword_dict.conv_pair_type_from_org),  
                            parameter(param_packer.func_A.param_category.RCV_TXT, param_validator.conv_unicode, True),  
                            parameter(param_packer.func_A.param_category.RCV_STK, param_validator.valid_int, True),  
                            parameter(param_packer.func_A.param_category.RCV_PIC, param_validator.validate_sha224, True),  
                            parameter(param_packer.func_A.param_category.REP_TYPE, param_validator.keyword_dict.conv_pair_type_from_org), 
                            parameter(param_packer.func_A.param_category.REP_TXT, param_validator.conv_unicode, True), 
                            parameter(param_packer.func_A.param_category.REP_STK, param_validator.valid_int, True), 
                            parameter(param_packer.func_A.param_category.REP_PIC, param_validator.validate_https, True), 
                            parameter(param_packer.func_A.param_category.ATTACHMENT, param_validator.conv_unicode, True)]
            elif command_category == param_packer.func_A.command_category.ADD_PAIR_AUTO_CH:
                prm_objs = [parameter(param_packer.func_A.param_category.ATTACHMENT, param_validator.conv_unicode, True),  
                            parameter(param_packer.func_A.param_category.RCV_CONTENT, param_validator.conv_unicode),  
                            parameter(param_packer.func_A.param_category.REP_CONTENT, param_validator.conv_unicode)]
            elif command_category == param_packer.func_A.command_category.ADD_PAIR_AUTO_EN:
                prm_objs = [parameter(param_packer.func_A.param_category.RCV_CONTENT, param_validator.conv_unicode),  
                            parameter(param_packer.func_A.param_category.REP_CONTENT, param_validator.conv_unicode),
                            parameter(param_packer.func_A.param_category.ATTACHMENT, param_validator.conv_unicode, True)]
            else:
                raise UndefinedCommandCategoryException()

            return prm_objs
    
    class func_D(param_packer_base):
        class command_category(ext.EnumWithName):
            DEL_PAIR = 1, '刪除回覆組'

        class param_category(ext.EnumWithName):
            IS_ID = 1, '根據ID?'
            ID = 2, 'ID'
            WORD = 3, '關鍵字'

        def __init__(self, command_category, CH_regex=None, EN_regex=None):
            prm_objs = self._get_prm_objs(command_category)

            super(param_packer.func_D, self).__init__(command_category, prm_objs, CH_regex, EN_regex)

        def _get_prm_objs(self, command_category):
            if command_category == param_packer.func_D.command_category.DEL_PAIR:
                prm_objs = [parameter(param_packer.func_D.param_category.IS_ID, param_validator.is_not_null, True),  
                            parameter(param_packer.func_D.param_category.ID, param_validator.conv_int_arr, True),  
                            parameter(param_packer.func_D.param_category.WORD, param_validator.conv_unicode_arr, True)]
            else:
                raise UndefinedCommandCategoryException()

            return prm_objs
    
    class func_Q(param_packer_base):
        class command_category(ext.EnumWithName):
            BY_AVAILABLE = 1, '根據可用範圍'
            BY_ID_RANGE = 2, '根據ID範圍'
            BY_UID = 3, '根據製作者'
            BY_GID = 4, '根據群組'
            BY_KEY = 5, '根據關鍵'

        class param_category(ext.EnumWithName):
            AVAILABLE = 1, '可用的'
            GLOBAL = 2, '全域'
            START_ID = 3, '起始ID'
            END_ID = 4, '終止ID'
            UID = 5, '製作者ID'
            GID = 6, '群組ID'
            IS_ID = 7, '根據ID?'
            KEYWORD = 8, '關鍵字'
            ID = 9, 'ID'

        def __init__(self, command_category, CH_regex=None, EN_regex=None):
            prm_objs = self._get_prm_objs(command_category)

            super(param_packer.func_Q, self).__init__(command_category, prm_objs, CH_regex, EN_regex)

        def _get_prm_objs(self, command_category):
            if command_category == param_packer.func_Q.command_category.BY_AVAILABLE:
                prm_objs = [parameter(param_packer.func_Q.param_category.GLOBAL, param_validator.is_not_null, True),
                            parameter(param_packer.func_Q.param_category.AVAILABLE, param_validator.is_not_null, True)]
            elif command_category == param_packer.func_Q.command_category.BY_ID_RANGE:
                prm_objs = [parameter(param_packer.func_Q.param_category.START_ID, param_validator.conv_int),  
                            parameter(param_packer.func_Q.param_category.END_ID, param_validator.conv_int)]
            elif command_category == param_packer.func_Q.command_category.BY_UID:
                prm_objs = [parameter(param_packer.func_Q.param_category.UID, param_validator.line_bot_api.validate_uid)]
            elif command_category == param_packer.func_Q.command_category.BY_GID:
                prm_objs = [parameter(param_packer.func_Q.param_category.GID, param_validator.line_bot_api.validate_gid_public_global)]
            elif command_category == param_packer.func_Q.command_category.BY_KEY:
                prm_objs = [parameter(param_packer.func_Q.param_category.IS_ID, param_validator.is_not_null, True),  
                            parameter(param_packer.func_Q.param_category.ID, param_validator.conv_int_arr, True),  
                            parameter(param_packer.func_Q.param_category.KEYWORD, param_validator.conv_unicode, True)]
            else:
                raise UndefinedCommandCategoryException()

            return prm_objs

class packer_factory(object):
    _S = [param_packer.func_S(command_category=param_packer.func_S.command_category.DB_COMMAND,
                              CH_regex=ur'小水母 DB ?資料庫((?:.|\n)+)(?<! ) ?主指令((?:.|\n)+)(?<! ) ?主參數((?:.|\n)+)(?<! ) ?參數((?:.|\n)+)(?<! )', 
                              EN_regex=ur'JC\nS\n(.+(?<! ))\n(.+(?<! ))\n(.+(?<! ))\n(.+(?<! ))')]

    _M = [param_packer.func_A(command_category=param_packer.func_A.command_category.ADD_PAIR_CH,
                              CH_regex=ur'小水母 置頂 ?(?:\s|附加((?:.|\n)+)(?<! ))? ?(收到 ?((?:.|\n)+)(?<! )|看到 ?([0-9a-f]{56})|被貼 ?(\d+)) ?(回答 ?((?:.|\n)+)(?<! )|回圖 ?(https://(?:.|\n)+)|回貼 ?(\d+))'),
          param_packer.func_A(command_category=param_packer.func_A.command_category.ADD_PAIR_EN,
                              EN_regex=ur'JC\nM\n(T\n(.+)|S\n(\d+)|P\n([0-9a-f]{56}))\n(T\n(.+)|S\n(\d+)|P\n(https://.+))(?:\n(.+))?'),
          param_packer.func_A(command_category=param_packer.func_A.command_category.ADD_PAIR_AUTO_CH,
                              CH_regex=ur'小水母 置頂 ?(?:\s|附加((?:.|\n)+)(?<! ))? ?(?:入 ?((?:.|\n)+)(?<! )) ?(?:出 ?((?:.|\n)+)(?<! ))'),
          param_packer.func_A(command_category=param_packer.func_A.command_category.ADD_PAIR_AUTO_EN,
                              EN_regex=ur'JC\nMM\n(.+)\n(.+)(?:\n(.+))?')]

    _A = [param_packer.func_A(command_category=param_packer.func_A.command_category.ADD_PAIR_CH,
                              CH_regex=ur'小水母 記住 ?(?:\s|附加((?:.|\n)+)(?<! ))? ?(收到 ?((?:.|\n)+)(?<! )|看到 ?([0-9a-f]{56})|被貼 ?(\d+)) ?(回答 ?((?:.|\n)+)(?<! )|回圖 ?(https://(?:.|\n)+)|回貼 ?(\d+))'),
          param_packer.func_A(command_category=param_packer.func_A.command_category.ADD_PAIR_EN,
                              EN_regex=ur'JC\nA\n(T\n(.+)|S\n(\d+)|P\n([0-9a-f]{56}))\n(T\n(.+)|S\n(\d+)|P\n(https://.+))(?:\n(.+))?'),
          param_packer.func_A(command_category=param_packer.func_A.command_category.ADD_PAIR_AUTO_CH,
                              CH_regex=ur'小水母 記住 ?(?:\s|附加((?:.|\n)+)(?<! ))? ?(?:入 ?((?:.|\n)+)(?<! )) ?(?:出 ?((?:.|\n)+)(?<! ))'),
          param_packer.func_A(command_category=param_packer.func_A.command_category.ADD_PAIR_AUTO_EN,
                              EN_regex=ur'JC\nAA\n(.+)\n(.+)(?:\n(.+))?')]

    _R = [param_packer.func_D(command_category=param_packer.func_D.command_category.DEL_PAIR,
                              CH_regex=ur'小水母 忘記置頂的 ?((ID ?)(\d{1}[\d\s]*)|(?:.|\n)+)', 
                              EN_regex=ur'JC\nR\n?(?:(ID\n)(\d{1}[\d\s]*)|(.+))')]

    _D = [param_packer.func_D(command_category=param_packer.func_D.command_category.DEL_PAIR,
                              CH_regex=ur'小水母 忘記 ?((ID ?)(\d{1}[\d\s]*)|(?:.|\n)+)', 
                              EN_regex=ur'JC\nD\n?(?:(ID\n)(\d{1}[\d\s]*)|(.+))')]

    _Q = [param_packer.func_Q(command_category=param_packer.func_Q.command_category.BY_AVAILABLE,
                              CH_regex=ur'小水母 找 ?(?:(全部)|(可以用的))',
                              EN_regex=ur'JC\n(?:(Q\nALL)|(Q))'),
          param_packer.func_Q(command_category=param_packer.func_Q.command_category.BY_ID_RANGE,
                              CH_regex=ur'小水母 找 ?ID範圍 ?(\d+)(?:到|~)(\d+)',
                              EN_regex=ur'JC\nQ\nID\n(\d+)\n(\d+)'),
          param_packer.func_Q(command_category=param_packer.func_Q.command_category.BY_UID,
                              CH_regex=ur'小水母 找 ?([U]{1}[0-9a-f]{32}) ?做的',
                              EN_regex=ur'JC\nQ\nUID\n([U]{1}[0-9a-f]{32})'),
          param_packer.func_Q(command_category=param_packer.func_Q.command_category.BY_GID,
                              CH_regex=ur'小水母 找 ?([CR]{1}[0-9a-f]{32}|PUBLIC|GLOBAL) ?裡面的',
                              EN_regex=ur'JC\nQ\nGID\n([CR]{1}[0-9a-f]{32}|PUBLIC|GLOBAL)'),
          param_packer.func_Q(command_category=param_packer.func_Q.command_category.BY_KEY,
                              CH_regex=ur'小水母 找 ?((ID ?)(\d{1}[\d\s]*)|(?:.|\n)+)',
                              EN_regex=ur'JC\nQ\n(?:(ID\n)(\d{1}[\d\s]*)|(.+))')]

    _I = [param_packer.func_Q(command_category=param_packer.func_Q.command_category.BY_AVAILABLE,
                              CH_regex=ur'小水母 詳細找 ?(?:(全部)|(可以用的))',
                              EN_regex=ur'JC\n(?:(I\nALL)|(I))'),
          param_packer.func_Q(command_category=param_packer.func_Q.command_category.BY_ID_RANGE,
                              CH_regex=ur'小水母 詳細找 ?ID範圍 ?(\d+)(?:到|~)(\d+)',
                              EN_regex=ur'JC\nI\nID\n(\d+)\n(\d+)'),
          param_packer.func_Q(command_category=param_packer.func_Q.command_category.BY_UID,
                              CH_regex=ur'小水母 詳細找 ?([U]{1}[0-9a-f]{32}) ?做的',
                              EN_regex=ur'JC\nI\nUID\n([U]{1}[0-9a-f]{32})'),
          param_packer.func_Q(command_category=param_packer.func_Q.command_category.BY_GID,
                              CH_regex=ur'小水母 詳細找 ?([CR]{1}[0-9a-f]{32}|PUBLIC|GLOBAL) ?裡面的',
                              EN_regex=ur'JC\nI\nGID\n([CR]{1}[0-9a-f]{32}|PUBLIC|GLOBAL)'),
          param_packer.func_Q(command_category=param_packer.func_Q.command_category.BY_KEY,
                              CH_regex=ur'小水母 詳細找 ?((ID ?)(\d{1}[\d\s]*)|(?:.|\n)+)',
                              EN_regex=ur'JC\nI\n(?:(ID\n)(\d{1}[\d\s]*)|(.+))')]

    _X = [ur'小水母 複製 ?((ID ?)(\d{1}[\d\s]*)|(?:.|\n)+)(?:到([CR]{1}[0-9a-f]{32}|PUBLIC))?', 
          ur'小水母 複製群組([CR]{1}[0-9a-f]{32})?裡面的( 包含置頂)?(?:到([CR]{1}[0-9a-f]{32}|PUBLIC))?']

    _X2 = [ur'小水母 清除(於([CR]{1}[0-9a-f]{32})中)?所有的回覆組571a95ae875a9ae315fad8cdf814858d9441c5ec671f0fb373b5f340']

    _E = [ur'小水母 修改 ?((ID ?)(\d{1}[\d\s]*)|(?:.|\n)+)跟((?:.|\n)+)(無|有)關', 
          ur'小水母 修改 ?((ID ?)(\d{1}[\d\s]*)|(?:.|\n)+)(不)?置頂']

    _K = [ur'小水母 前(([1-9]\d?)名)?(使用者|回覆組|使用過的)']

    _P = [ur'小水母 系統訊息前(\d+)名', 
          ur'小水母 系統(自動回覆|資訊|圖片|匯率|黑名單)']

    _P2 = [ur'小水母 使用者 ?([U]{1}[0-9a-f]{32}) ?的資料']

    _G = [ur'小水母 群組([CR]{1}[0-9a-f]{32})?的資料']

    _GA = [ur'小水母 當(啞巴|機器人|服務員|八嘎囧)']

    _GA2 = [ur'小水母 讓 ?([U]{1}[0-9a-f]{32}) ?變成(可憐兒|一般人|副管|管理員)']

    _GA3 = [ur'小水母 啟用公用資料庫([A-Z0-9]{40})']

    _H = [ur'小水母 頻道資訊']

    _SHA = [ur'小水母 雜湊SHA ?(.*)']

    _O = [ur'小水母 查 ?(\w+)']

    _RD = [ur'小水母 抽 ?(([\d\.]{1,})%) ?((\d{1,6})次)?', 
           ur'小水母 抽 ?((\d{1,6})次)? ?((?:.|\n)+)', 
           ur'小水母 抽 ?(\d+)(到|~)(\d+)']

    _L = [ur'小水母 最近的(貼圖|圖片|回覆組|發送者)']

    _T = [ur'小水母 編碼((?:.|\n)+)']

    _C = [ur'小水母 匯率(可用)?', 
          ur'小水母 匯率([A-Z ]{3,})', 
          ur'小水母 匯率((1999|20\d{2})(0[1-9]|1[1-2])([0-2][1-9]|3[0-1]))(時的([A-Z ]{3,}))?', 
          ur'小水母 匯率([A-Z]{3}) ([\d\.]+) ?轉成 ?([A-Z]{3})']

    _FX = [ur'小水母 解因式分解 ?([!$%^&*()_+|~\-=`{}\[\]:\";\'<>\?,\./0-9A-Za-z]+)', 
           ur'小水母 解方程式 ?(變數((?:.|\n)+)(?<! )) ?(方程式([!$%^&*()_+|~\-\n=`{}\[\]:\";\'<>\?,\./0-9A-Za-z和]+))']

    _W = [ur'小水母 天氣ID查詢 ?(\w+)', 
          ur'小水母 天氣(查詢|記錄|刪除) ?([\d\s]+) ?(詳|簡)? ?((\d+)小時內)? ?(每(\d+)小時)?']

    _DL = [ur'小水母 下載貼圖圖包 ?(\d+) ?(含聲音)?']

    _STK = [ur'小水母 貼圖(圖包)?排行 ?(前(\d+)名)? ?((\d+)小時內)?', 
            ur'小水母 貼圖(\d+)']