# -*- coding: utf-8 -*-
import os, sys
import json
from datetime import datetime, timedelta
import hashlib

from flask import request, url_for
import pymongo
import ast
from linebot.models import TextSendMessage

import tool
from error import error
import bot, db, ext

class text_msg_handler(object):
    HEAD = 'JC'
    SPLITTER = '\n'

    def __init__(self, command_manager, flask_app, config_manager, line_api_wrapper, mongo_db_uri, oxford_api, system_data, webpage_generator, imgur_api_wrapper, oxr_client, string_calculator):
        self._mongo_uri = mongo_db_uri
        self._flask_app = flask_app
        self._config_manager = config_manager

        self._array_separator = self._config_manager.get(bot.config_category.KEYWORD_DICT, bot.config_category_kw_dict.ARRAY_SEPARATOR)

        self._system_data = system_data
        self._system_config = db.system_config(mongo_db_uri)
        self._system_stats = db.system_statistics(mongo_db_uri)
        self._command_manager = command_manager
        self._stk_rec = db.sticker_recorder(mongo_db_uri)

        self._kwd_public = db.group_dict_manager(mongo_db_uri, config_manager.getint(bot.config_category.KEYWORD_DICT, bot.config_category_kw_dict.CREATE_DUPLICATE), config_manager.getint(bot.config_category.KEYWORD_DICT, bot.config_category_kw_dict.REPEAT_CALL))
        self._kwd_global = db.word_dict_global(mongo_db_uri)
        self._group_manager = db.group_manager(mongo_db_uri)
        self._oxford_dict = oxford_api
        self._line_api_wrapper = line_api_wrapper
        self._webpage_generator = webpage_generator
        self._imgur_api_wrapper = imgur_api_wrapper
        self._oxr_client = oxr_client
        self._string_calculator = string_calculator
        
        self._pymongo_client = None

    def handle_text(self, event, full_org_text_without_head, user_permission, group_config_type):
        """Return whether message has been replied"""
        token = event.reply_token
        text = event.message.text
        src = event.source
        src_gid = bot.line_api_wrapper.source_channel_id(src)
        src_uid = bot.line_api_wrapper.source_user_id(src)

        cmd, oth = split(full_org_text_without_head, text_msg_handler.SPLITTER, 2)
        cmd = cmd.replace(' ', '')
        params = self.split_verify(cmd, text_msg_handler.SPLITTER, oth)

        if isinstance(params, unicode):
            self._line_api_wrapper.reply_message_text(token, params)
            return True
        else:
            # log statistics
            self._system_stats.command_called(cmd)

            # assign command data
            cmd_data = self._command_manager.get_command_data(cmd)

            # get function
            cmd_function = getattr(self, '_{}'.format(cmd))

            # check if command is remote
            if cmd_data.remotable and bot.line_api_wrapper.is_valid_room_group_id(params[1], cmd_data.allow_gid_public):
                user_permission = self._group_manager.get_user_permission(params[1], src_uid)

            # check permission
            low_perm = cmd_data.lowest_permission
            if user_permission == bot.permission.RESTRICTED:
                self._line_api_wrapper.reply_message_text(token, error.permission.user_is_resticted())
                return True
            elif user_permission < low_perm:
                self._line_api_wrapper.reply_message_text(token, error.main.restricted(low_perm))
                return True

            # handle command
            handle_result = cmd_function(src, params, user_permission, group_config_type)

            # reply handle result
            if isinstance(handle_result, (str, unicode)):
                self._line_api_wrapper.reply_message_text(token, handle_result)
                return True
            else:
                self._line_api_wrapper.reply_message(token, handle_result)
                return True
            
        return False

    def _get_remote_gid(self, params, default=None, allow_pop_public=False, allow_pop_global=False):
        """Return gid. gid will be none if params[1] is not legal gid. if gid is not None, params is popped. If default is not None, all None returns will be default."""
        if bot.line_api_wrapper.is_valid_room_group_id(params[1], allow_pop_public, allow_pop_global):
            return params.pop(1)

        return default

    def _get_kwd_instance(self, src, config, params=None, spec_gid=None, allow_global=False):
        """Return kwd instance. Will pop param if params[1] is remote. Specify (spec_gid) group id will use the parameter as remote gid directly. Set allow_global to enable GLOBAL popping in params. Set spec_gid to GLOBAL and allow global to directly get global range instance.
        
        Priority(H to L):
        allow_global -> Range = GLOBAL
        spec_gid -> Range = +GROUP
        """

        if spec_gid is None and params is not None:
            remote_gid = self._get_remote_gid(params, None, False, allow_global)
        else:
            remote_gid = spec_gid

        if bot.line_api_wrapper.is_valid_room_group_id(remote_gid):
            config = self._group_manager.get_group_config_type(remote_gid)

        if config is not None and config == db.config_type.ALL:
            manager_range = db.group_dict_manager_range.GROUP_AND_PUBLIC
        else:
            manager_range = db.group_dict_manager_range.GROUP_ONLY

        if remote_gid == db.group_dict_manager.CODE_OF_GLOBAL_RANGE:
            return self._kwd_public.clone_instance(self._mongo_uri, db.PUBLIC_GROUP_ID, db.group_dict_manager_range.GLOBAL)
        elif remote_gid is not None:
            kwd_instance = self._kwd_public.clone_instance(self._mongo_uri, remote_gid, manager_range)
        else:
            source_type = bot.line_event_source_type.determine(src)
            if source_type == bot.line_event_source_type.USER:
                kwd_instance = self._kwd_public
            elif source_type == bot.line_event_source_type.GROUP or source_type == bot.line_event_source_type.ROOM:
                kwd_instance = self._kwd_public.clone_instance(self._mongo_uri, bot.line_api_wrapper.source_channel_id(src), manager_range)
            else:
                raise ValueError(error.main.miscellaneous(u'Unknown source type.'))

        return kwd_instance

    def _get_query_result(self, params, kwd_instance, exact_same):
        if params[2] is not None:
            if bot.string_can_be_int(params[1]) and bot.string_can_be_int(params[2]):
                begin_index = int(params[1])
                end_index = int(params[2])
                title = u'範圍: 【回覆組ID】介於【{}】和【{}】之間的回覆組。\n'.format(begin_index, end_index)

                if end_index - begin_index < 0:
                    return error.main.incorrect_param(u'參數2', u'大於參數1的數字')
                else:
                    result_data = kwd_instance.search_pair_by_index(begin_index, end_index)
            else:
                action = params[1]
                if action == 'UID':
                    uid = params[2]
                    title = u'範圍: 【回覆組製作者UID】為【{}】的回覆組。\n'.format(uid)
                    if bot.line_api_wrapper.is_valid_user_id(uid):
                        result_data = kwd_instance.search_pair_by_creator(uid)
                    else:
                        return error.line_bot_api.illegal_user_id(uid)
                elif action == 'GID':
                    gid = params[2]
                    title = u'範圍: 隸屬於【群組ID】為【{}】的回覆組。\n'.format(gid)
                    if bot.line_api_wrapper.is_valid_room_group_id(gid):
                        result_data = self._kwd_global.get_pairs_by_group_id(gid, True)
                    else:
                        return error.line_bot_api.illegal_room_group_id(gid)
                elif action == 'ID':
                    ids = params[2]
                    id_list = ids.split(self._array_separator)
                    title = u'範圍: 【回覆組ID】為【{}】的回覆組。\n'.format(u'、'.join(id_list))
                    if bot.string_can_be_int(ids.replace(self._array_separator, '')):
                        result_data = kwd_instance.search_pair_by_index(id_list)
                    else:
                        return error.main.incorrect_param(u'參數2', u'整數數字，或指定字元分隔的數字陣列')
                else:
                    return error.main.incorrect_param(u'參數1', u'ID、UID(使用者)或GID(群組隸屬資料)')
        elif params[1] is not None:
            kw = params[1]
            title = u'範圍: 【關鍵字】或【回覆】{}【{}】的回覆組。\n'.format(u'為' if exact_same else u'包含', kw)

            result_data = kwd_instance.search_pair_by_keyword(kw, exact_same)
        else:
            title = u'範圍: 可用回覆組。\n'

            result_data = kwd_instance.search_all_available_pair()

        return result_data, title

    def _S(self, src, params, key_permission_lv, group_config_type):
        if self._pymongo_client is None:
            self._pymongo_client = pymongo.MongoClient(self._mongo_uri)

        if params[4] is not None:
            db_name = params[1]
            command = params[2]
            command_parameter = params[3]

            shell_cmd_dict = params[4]
            try:
                shell_cmd_dict = ast.literal_eval(shell_cmd_dict)
            except ValueError:
                return error.main.miscellaneous(u'參數4字串型別分析失敗。')

            if not isinstance(shell_cmd_dict, dict):
                return error.main.miscellaneous(u'輸入參數必須是合法dictionary型別。')
            
            text = u'目標資料庫:\n{}\n'.format(db_name)
            text += u'資料庫主指令:\n{}\n'.format(command)
            text += u'資料庫主指令參數:\n{}\n'.format(command_parameter)
            text += u'資料庫副指令:\n{}\n\n'.format(shell_cmd_dict)

            try:
                result = self._pymongo_client.get_database(db_name).command(command, command_parameter, **shell_cmd_dict)

                text += ext.object_to_json(result)
            except pymongo.errors.OperationFailure as ex:
                text += u'資料庫指令執行失敗。\n錯誤碼: {}\n錯誤訊息: {}'.format(ex.code, ex.message)
        else:
            text = error.sys_command.lack_of_parameters([1, 2, 3])

        return text

    def _A(self, src, params, key_permission_lv, group_config_type, pinned=False):
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
        kwd_instance = self._get_kwd_instance(src, group_config_type, params)
        
        flags = params[1]
        kw = params[2]
        if kw is not None:
            kw = kw.replace('\\n', '\n')
        else:
            return error.main.invalid_thing(u'參數2', u'非空字串')
        rep = params[3]
        if rep is not None:
            rep = rep.replace('\\n', '\n')
        else:
            return error.main.invalid_thing(u'參數3', u'非空字串')
        linked = params[4]
        rep_att = params[5]
        if rep_att is not None:
            rep_att = rep_att.replace('\\n', '\n')

        # checking flags is legal
        if len(flags) != 2:
            return error.auto_reply.illegal_flags(flags)

        # checking type of keyword and reply
        try:
            kw_type = db.word_type.determine_by_flag(flags[0])
            rep_type = db.word_type.determine_by_flag(flags[1])
        except db.UnknownFlagError:
            return error.auto_reply.illegal_flags(flags)

        source_type = bot.line_event_source_type.determine(src)

        if kw_type == db.word_type.STICKER and not bot.string_can_be_int(kw):
            return error.main.invalid_thing_with_correct_format(u'關鍵字', u'貼圖ID', kw)
        
        if kw_type == db.word_type.PICTURE and not len(kw) == db.pair_data.HASH_LENGTH:
            return error.main.invalid_thing_with_correct_format(u'關鍵字', u'共{}字元的{}雜湊'.format(db.pair_data.HASH_LENGTH, db.pair_data.HASH_TYPE), kw)

        if rep_type == db.word_type.STICKER and not bot.string_can_be_int(rep):
            return error.main.invalid_thing_with_correct_format(u'回覆', u'貼圖ID', rep)

        if rep_type == db.word_type.PICTURE and not rep.startswith('https://'):
            return error.main.invalid_thing_with_correct_format(u'回覆', u'使用HTTPS通訊協定的圖片網址', rep)

        if linked is not None and len(linked) > 0:
            linked = linked.split(self._array_separator)

        if rep_att is not None and not (rep_type == db.word_type.PICTURE or rep_type == db.word_type.STICKER):
            return error.main.miscellaneous(u'附加回覆只可以在回覆種類為圖片或貼圖時使用。')
        
        # create and write
        result = kwd_instance.insert_keyword(kw, rep, new_profile_uid, pinned, kw_type, rep_type, linked, rep_att)

        # check whether success
        if isinstance(result, (str, unicode)):
            return result
        elif isinstance(result, db.pair_data):
            return u'回覆組新增成功。\n' + result.basic_text(True)
        else:
            raise ValueError('Unknown type of return result.')

    def _M(self, src, params, key_permission_lv, group_config_type):
        # check whether profile data is reachable
        try:
            new_profile_uid = bot.line_api_wrapper.source_user_id(src)
            self._line_api_wrapper.profile_name(new_profile_uid)
        except bot.UserProfileNotFoundError as ex:
            return error.line_bot_api.unable_to_receive_user_id()

        # check whether user id is legal
        if not bot.line_api_wrapper.is_valid_user_id(new_profile_uid):
            return error.line_bot_api.illegal_user_id(new_profile_uid)

        return self._A(src, params, key_permission_lv, group_config_type, True)

    def _D(self, src, params, key_permission_lv, group_config_type, pinned=False):
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
        kwd_instance = self._get_kwd_instance(src, group_config_type, params)

        # disable keyword
        if params[2] is not None:
            action = params[1]
        
            if action == 'ID':
                pair_ids = params[2]

                if bot.string_can_be_int(pair_ids.replace(self._array_separator, '')):
                    if self._array_separator in pair_ids:
                        pair_ids = pair_ids.split(self._array_separator)

                    disable_result_id_list = kwd_instance.disable_keyword_by_id(pair_ids, del_profile_uid, pinned)
                else:
                    return error.main.incorrect_param(u'參數2', u'整數數字，或指定字元分隔的數字陣列')
            else:
                return error.main.incorrect_param(u'參數1', u'ID')
        elif params[1] is not None:
            kw = params[1]
            disable_result_id_list = kwd_instance.disable_keyword(kw, del_profile_uid, pinned)
        else:
            return error.main.lack_of_thing(u'參數')
        
        # process action result
        if len(disable_result_id_list) > 0:
            text = u'回覆組刪除成功。\n'
            text += '\n'.join([data.basic_text(True) for data in disable_result_id_list])
            return text
        else:
            if bot.string_can_be_int(params[1]):
                return error.main.miscellaneous(u'偵測到參數1是整數。若欲使用ID作為刪除根據，請參閱小水母使用說明。')
            else:
                return error.main.pair_not_exist_or_insuffieicnt_permission()

    def _R(self, src, params, key_permission_lv, group_config_type):
        # check whether profile data is reachable
        try:
            disabler_uid = bot.line_api_wrapper.source_user_id(src)
            self._line_api_wrapper.profile_name(disabler_uid)
        except bot.UserProfileNotFoundError as ex:
            return error.line_bot_api.unable_to_receive_user_id()

        # check whether user id is legal
        if not bot.line_api_wrapper.is_valid_user_id(disabler_uid):
            return error.line_bot_api.illegal_user_id(disabler_uid)

        return self._D(src, params, key_permission_lv, group_config_type, True)

    def _Q(self, src, params, key_permission_lv, group_config_type):
        # assign keyword instance
        kwd_instance = self._get_kwd_instance(src, group_config_type, params, None, True)

        # create query result
        query_result = self._get_query_result(params, kwd_instance, False)
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

    def _I(self, src, params, key_permission_lv, group_config_type):
        # assign keyword instance
        kwd_instance = self._get_kwd_instance(src, group_config_type, params, None, True)

        # create query result
        query_result = self._get_query_result(params, kwd_instance, True)
        if isinstance(query_result[0], (str, unicode)):
            return query_result
        
        # process output
        max_count = self._config_manager.getint(bot.config.config_category.KEYWORD_DICT, bot.config.config_category_kw_dict.MAX_INFO_OUTPUT_COUNT)
        output = db.keyword_dict.group_dict_manager.list_keyword_info(query_result[0], kwd_instance, self._line_api_wrapper, max_count, query_result[1].replace('\n', ''), error.main.no_result())

        text = output.limited
        if output.has_result:
            text += u'\n\n完整結果: {}'.format(self._webpage_generator.rec_webpage(output.full, db.webpage_content_type.INFO))
        return text

    def _X(self, src, params, key_permission_lv, group_config_type):
        low_perm = self._command_manager.get_command_data('X').lowest_permission

        target_gid = self._get_remote_gid(params, bot.line_api_wrapper.source_channel_id(src), True)
        uid = bot.line_api_wrapper.source_user_id(src)

        if params[2] is not None:
            if key_permission_lv < bot.permission.MODERATOR:
                return error.main.restricted(bot.permission.MODERATOR)
            flags = params[1]
            source_gid = params[2]

            if bot.line_api_wrapper.is_valid_room_group_id(source_gid) or source_gid == db.word_dict_global.CODE_OF_PUBLIC_GROUP:
                result_ids = self._kwd_global.clone_from_group(source_gid, target_gid, uid, 'D' in flags, 'P' in flags)
            else:
                return error.main.invalid_thing_with_correct_format(u'參數2', u'合法的群組/房間ID 或 "PUBLIC"(公用資料庫)', source_gid)
        elif params[1] is not None:
            if bot.string_can_be_int(params[1].replace(self._array_separator, '')):
                ids = params[1]
                result_ids = self._kwd_global.clone_by_id(ids.split(self._array_separator), target_gid, uid, True, key_permission_lv >= low_perm)
            elif hashlib.sha224('clear').hexdigest() == params[1]:
                if key_permission_lv < bot.permission.ADMIN:
                    return error.main.restricted(bot.permission.ADMIN)

                try:
                    clear_count = self._kwd_global.clear(target_gid, uid)
                except db.ActionNotAllowed as ex:
                    return ex.message

                if clear_count > 0:
                    return u'已刪除群組所屬回覆組(共{}組)。'.format(clear_count)
                else:
                    return u'沒有刪除任何回覆組。'
            else:
                return error.main.invalid_thing_with_correct_format(u'參數1', u'"clear"的SHA雜湊(可藉由JC SHA獲取) 或 要複製的回覆組ID/ID陣列', params[1])
        else:
            return error.main.lack_of_thing(u'參數')

        if len(result_ids) > 0:
            first_id_str = str(result_ids[0])
            last_id_str = str(result_ids[-1])
            return [bot.line_api_wrapper.wrap_text_message(u'回覆組複製完畢。\n新建回覆組ID: {}'.format(u'、'.join([u'#{}'.format(id) for id in result_ids])), self._webpage_generator),
                    bot.line_api_wrapper.wrap_template_with_action({
                        u'回覆組資料查詢(簡略)': text_msg_handler.HEAD + text_msg_handler.SPLITTER + 'Q' + text_msg_handler.SPLITTER + first_id_str + text_msg_handler.SPLITTER + last_id_str,
                        u'回覆組資料查詢(詳細)': text_msg_handler.HEAD + text_msg_handler.SPLITTER + 'I' + text_msg_handler.SPLITTER + first_id_str + text_msg_handler.SPLITTER + last_id_str} ,u'新建回覆組相關指令樣板', u'相關指令')]
        else:
            return u'回覆組複製失敗。回覆組來源沒有符合條件的回覆組可供複製。'

    def _E(self, src, params, key_permission_lv, group_config_type):
        low_perm = self._command_manager.get_command_data('E').lowest_permission
        
        # assign keyword instance
        kwd_instance = self._get_kwd_instance(src, group_config_type, params)

        action = params[1]
        id = params[2]

        if not bot.string_can_be_int(id):
            return error.main.invalid_thing_with_correct_format(u'參數2', u'正整數', id)
        else:
            id = int(id)

        shortcut_template = bot.line_api_wrapper.wrap_template_with_action({ '查看回覆組詳細資訊': text_msg_handler.HEAD + text_msg_handler.SPLITTER + 'I' + text_msg_handler.SPLITTER + 'ID' + text_msg_handler.SPLITTER + str(id) }, u'更動回覆組ID: {}'.format(id), u'相關指令')
        
        # edit linked keyword pair
        if params[3] is not None:
            word_list = params[3].split(self._array_separator)

            # 0 will be able to modify 1

            if action == 'A':
                result = kwd_instance.add_linked_word(id, word_list, key_permission_lv >= low_perm)
            elif action == 'D':
                result = kwd_instance.del_linked_word(id, word_list, key_permission_lv >= low_perm)
            else:
                return error.main.invalid_thing_with_correct_format(u'參數1', u'A(新增)或D(刪除)', action)

            if result:
                return (bot.line_api_wrapper.wrap_text_message('#{} 相關回覆組變更成功。'.format(id), self._webpage_generator), shortcut_template)
            else:
                return '#{} 相關回覆組變更失敗。可能是因為ID不存在或權限不足而造成。'.format(id)
        # edit pinned property
        elif params[2] is not None:
            if key_permission_lv > low_perm:
                action_dict = {'P': True, 'U': False}
                pinned = action_dict.get(action, None)

                if pinned is None:
                    return error.main.invalid_thing_with_correct_format(u'參數1', u'P(置頂)或U(取消置頂)', action)

                result = kwd_instance.set_pinned_by_index(id, pinned)
                if result:
                    return (bot.line_api_wrapper.wrap_text_message('#{} 置頂屬性變更成功。'.format(id), self._webpage_generator), shortcut_template)
                else:
                    return '#{} 置頂屬性變更失敗。'.format(id)
            else:
                return error.main.restricted(low_perm)
        else:
            return error.main.lack_of_thing(u'參數')

    def _K(self, src, params, key_permission_lv, group_config_type):
        # assign keyword instance
        kwd_instance = self._get_kwd_instance(src, group_config_type, params, None, True)

        # assign parameters
        ranking_type = params[1]

        default = self._config_manager.getint(bot.config_category.KEYWORD_DICT, bot.config_category_kw_dict.DEFAULT_RANK_RESULT_COUNT)
        limit = default if params[2] is None else int(params[2])

        # validate parameters
        if not bot.string_can_be_int(limit):
            return error.main.incorrect_param(u'參數2(數量)', u'整數')
        
        if limit > 50:
            return error.main.incorrect_param(u'參數2(數量)', u'小於50的整數')

        # get ranking result
        if ranking_type == 'USER':
            text = kwd_instance.user_created_rank_string(limit, self._line_api_wrapper)
        elif ranking_type == 'KW':
            text = kwd_instance.get_ranking_call_count_string(limit)
        elif ranking_type == 'KWRC':
            text = kwd_instance.recently_called_string(limit)
        else:
            return error.main.incorrect_param(u'參數1(種類)', u'USER(使用者排行)、KW(關鍵字排行)或KWRC(呼叫時間排行)')

        # append full url
        # with self._flask_app.test_request_context():
        #     text += u'\n\n完整使用者排名: {}\n完整關鍵字排名: {}\n完整最新呼叫表: {}'.format(
        #         request.url_root + url_for('full_ranking', type='user')[1:],
        #         request.url_root + url_for('full_ranking', type='used')[1:],
        #         request.url_root + url_for('full_ranking', type='called')[1:])

        return text

    def _P(self, src, params, key_permission_lv, group_config_type):
        wrong_param1 = error.main.invalid_thing_with_correct_format(u'參數1', u'MSG、KW、IMG、SYS、EXC或合法使用者ID', params[1])

        default_target_gid = bot.line_api_wrapper.source_channel_id(src)
        target_gid = self._get_remote_gid(params, default_target_gid, False, True)

        category = params[1]
        gid = params[2]

        if category == 'MSG':
            if gid is not None and bot.string_can_be_int(gid):
                limit = int(gid)
            else:
                limit = self._config_manager.getint(bot.config.config_category.KEYWORD_DICT, bot.config.config_category_kw_dict.MAX_MESSAGE_TRACK_OUTPUT_COUNT)
        
            tracking_string_obj = db.group_manager.message_track_string(self._group_manager.order_by_recorded_msg_count(limit), limit, [u'【訊息流量統計】(前{}名)'.format(limit)], error.main.miscellaneous(u'沒有訊息量追蹤紀錄。'), True, True)
        
            text = u'為避免訊息過長洗板，請點此察看結果:\n{}'.format(self._webpage_generator.rec_webpage(tracking_string_obj.full, db.webpage_content_type.TEXT))
        elif category == 'KW':
            kwd_instance = self._get_kwd_instance(src, group_config_type, params, target_gid, True)

            instance_type = u'{}回覆組資料庫'.format(unicode(kwd_instance.available_range))
                
            text = u'【{}相關統計資料】\n'.format(instance_type)
            text += kwd_instance.get_statistics_string()
        elif category == 'SYS':
            text = u'【系統統計資料】\n'
            text += u'開機時間: {} (UTC+8)\n'.format(self._system_data.boot_up)
            text += self._system_stats.get_statistics()
        elif category == 'IMG':
            import socket
            ip_address = socket.gethostbyname(socket.getfqdn(socket.gethostname()))

            text = self._imgur_api_wrapper.get_status_string(ip_address)
        elif category == 'EXC':
            usage_dict = self._oxr_client.get_usage_dict()
            text = self._oxr_client.usage_str(usage_dict)
        else:
            uid = category

            if bot.line_api_wrapper.is_valid_user_id(uid):
                kwd_instance = self._get_kwd_instance(src, group_config_type, params, target_gid)

                try:
                    if target_gid != default_target_gid:
                        source_type = bot.line_api_wrapper.determine_id_type(target_gid)

                        if source_type == bot.line_event_source_type.GROUP:
                            name = self._line_api_wrapper.profile_group(target_gid, uid).display_name
                        elif source_type == bot.line_event_source_type.ROOM:
                            name = self._line_api_wrapper.profile_room(target_gid, uid).display_name
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
                        bot.line_api_wrapper.wrap_template_with_action({ '查詢該使用者製作的回覆組': text_msg_handler.HEAD + text_msg_handler.SPLITTER + 'Q' + text_msg_handler.SPLITTER + 'UID' + text_msg_handler.SPLITTER + uid }, u'回覆組製作查詢快捷樣板', u'快捷查詢')]
            else:
                return wrong_param1

        return text

    def _G(self, src, params, key_permission_lv, group_config_type):
        if params[1] is None and bot.line_event_source_type.determine(src) == bot.line_event_source_type.USER:
            return error.main.incorrect_channel(False, True, True)

        gid = self._get_remote_gid(params, bot.line_api_wrapper.source_channel_id(src))
        kwd_instance = self._get_kwd_instance(src, group_config_type, params, gid, True)

        group_data = self._group_manager.get_group_by_id(gid, True)

        group_statistics = group_data.get_status_string() + u'\n【回覆組相關】\n' + kwd_instance.get_statistics_string()
        
        return (bot.line_api_wrapper.wrap_text_message(group_statistics, self._webpage_generator), 
                bot.line_api_wrapper.wrap_template_with_action({ u'查詢群組資料庫': text_msg_handler.HEAD + text_msg_handler.SPLITTER + 'Q' + text_msg_handler.SPLITTER + 'GID' + text_msg_handler.SPLITTER + gid }, u'快速查詢群組資料庫樣板', u'相關指令'))

    def _GA(self, src, params, key_permission_lv, group_config_type):
        gid = self._get_remote_gid(params, bot.line_api_wrapper.source_channel_id(src))
        setter_uid = bot.line_api_wrapper.source_user_id(src)
        try:
            setter_name = self._line_api_wrapper.profile_name(setter_uid)
        except bot.UserProfileNotFoundError:
            return error.line_bot_api.unable_to_receive_user_id()

        if params[3] is not None:
            action = params[1]
            target_uid = params[2]
            permission = params[3]

            if action == 'S':
                if not bot.line_api_wrapper.is_valid_user_id(target_uid):
                    return error.line_bot_api.illegal_user_id(target_uid)

                try:
                    target_name = self._line_api_wrapper.profile_name(target_uid)
                except bot.UserProfileNotFoundError:
                    return error.line_bot_api.unable_to_receive_user_id()
                
                try:
                    permission = bot.permission(int(permission))
                except ValueError:
                    return error.main.invalid_thing_with_correct_format(u'參數3', u'權限等級(整數)', unicode(permission))

                if permission > bot.permission.ADMIN:
                    return error.main.miscellaneous(u'最高可設定權限為【群組管理員】(等級2)。')

                try:
                    self._group_manager.set_permission(gid, setter_uid, target_uid, permission)
                    
                    text = u'成員權限更改/新增成功。\n執行者: {}\n執行者UID: {}\n目標: {}\n目標UID: {}\n新權限: {}'.format(setter_uid, setter_name, target_name, target_uid, unicode(permission))
                except db.InsufficientPermissionError:
                    text = error.main.restricted()
            else:
                text = error.main.incorrect_param(u'參數1', u'S(更改權限)')
        elif params[2] is not None:
            action = params[1]
        
            if action == 'ACTIVATE':
                token = params[2]
                activate_result = self._group_manager.activate(gid, token)
                text = u'公用資料庫啟用{}。'.format(u'成功' if activate_result else u'失敗')
            elif action == 'D':
                if bot.line_api_wrapper.is_valid_user_id(params[2]):
                    target_uid = params[2]
                    try:
                        target_name = self._line_api_wrapper.profile_name(target_uid)
                    except bot.UserProfileNotFoundError:
                        return error.main.miscellaneous(u'無法查詢權限更動目標的使用者資料。請先確保更動目標已加入小水母的好友以後再試一次。')

                    try:
                        self._group_manager.delete_permission(gid, setter_uid, target_uid)
                        
                        text = u'成員權限刪除成功。\n執行者: {}\n執行者UID: {}\n目標: {}\n目標UID: {}'.format(setter_uid, setter_name, target_name, target_uid)
                    except db.InsufficientPermissionError:
                        text = error.main.restricted()
                else:
                    text = error.main.incorrect_param(u'參數2', u'合法使用者ID')
            else:
                text = error.main.incorrect_param(u'參數1', u'ACTIVATE(啟用)、D(刪除權限)')
        elif params[1] is not None:
            cfg_type = params[1]
        
            if not bot.string_can_be_int(cfg_type):
                return error.main.invalid_thing_with_correct_format(u'參數1', u'群組設定代碼(整數)', cfg_type)
        
            try:
                cfg_type = db.config_type(int(cfg_type))
            except ValueError:
                return error.main.miscellaneous(u'群組設定代碼不合法，請確認代碼有效後重試。')

            change_result = self._group_manager.set_config_type(gid, cfg_type, setter_uid)

            if change_result:
                text = u'群組自動回覆設定已更改為【{}】。'.format(unicode(cfg_type))
            else:
                text = u'群組自動回覆設定更改失敗。\n{}'.format(change_result)
        else:
            text = error.main.lack_of_thing(u'參數')

        return text

    def _H(self, src, params, key_permission_lv, group_config_type):
        channel_id = bot.line_api_wrapper.source_channel_id(src)

        return [bot.line_api_wrapper.wrap_text_message(text, self._webpage_generator) for text in (str(bot.line_event_source_type.determine(src)), channel_id)]

    def _SHA(self, src, params, key_permission_lv, group_config_type):
        target = params[1]

        if target is not None:
            text = hashlib.sha224(target.encode('utf-8')).hexdigest()
        else:
            text = error.main.incorrect_param(u'參數1', u'非空參數')

        return text

    def _O(self, src, params, key_permission_lv, group_config_type):
        voc = params[1]

        if not self._oxford_dict.enabled:
            text = error.main.miscellaneous(u'牛津字典功能已停用。可能是因為超過單月查詢次數或無效的API密鑰。')
        else:
            j = self._oxford_dict.get_data_json(voc)

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

    def _RD(self, src, params, key_permission_lv, group_config_type):
        if params[2] is not None:
            if params[1].endswith('%') and params[1].count('%') == 1:
                probability = params[1].replace('%', '')
                scout_count = params[2]

                if not bot.string_can_be_float(probability):
                    text = error.main.incorrect_param(u'參數1(機率)', u'百分比加上符號%')
                elif not bot.string_can_be_int(scout_count):
                    text = error.main.incorrect_param(u'參數2(抽籤次數)', u'整數')
                elif int(scout_count) > 999999:
                    text = error.main.invalid_thing_with_correct_format(u'參數2(抽籤次數)', u'小於999999的整數', scout_count)
                else:
                    text = tool.random_drawer.draw_probability_string(probability, True, scout_count, 3)
            else:
                start_index = params[1]
                end_index = params[2]
                if not bot.string_can_be_int(start_index):
                    text = error.main.invalid_thing_with_correct_format(u'起始抽籤數字', u'整數', start_index)
                elif not bot.string_can_be_int(end_index):
                    text = error.main.invalid_thing_with_correct_format(u'終止抽籤數字', u'整數', start_index)
                else:
                    text = tool.random_drawer.draw_number_string(start_index, end_index)
        elif params[1] is not None:
            if self._array_separator in params[1]:
                texts = params[1]

                text = tool.random_gen.random_drawer.draw_text_string(texts.split(self._array_separator))
            elif params[1].endswith('%') and params[1].count('%') == 1:
                probability = params[1].replace('%', '')

                text = tool.random_drawer.draw_probability_string(probability, True, 1, 1)
            else:
                text = error.main.invalid_thing(u'參數1', params[1])
        else:
            text = error.main.lack_of_thing(u'參數')

        return text

    def _L(self, src, params, key_permission_lv, group_config_type):
        target_gid = self._get_remote_gid(params, bot.line_api_wrapper.source_channel_id(src))

        if params[1] is not None:
            category = params[1]

            category_dict = {
                'S': bot.system_data_category.LAST_STICKER,
                'P': bot.system_data_category.LAST_PIC_SHA,
                'R': bot.system_data_category.LAST_PAIR_ID,
                'U': bot.system_data_category.LAST_UID
            }

            last_item_cat = category_dict.get(category)

            if last_item_cat is None:
                return error.main.invalid_thing_with_correct_format(u'參數1', u'S(最後貼圖)、P(最後圖片)、U(最後UID)或R(最後回覆組)', category)

            last_array = self._system_data.get(last_item_cat, target_gid)

            rep_list = []

            if last_array is not None and len(last_array) > 0:
                rep_list.append(bot.line_api_wrapper.wrap_text_message(u'{}\n{}。'.format(unicode(last_item_cat), u'、'.join([str(item) for item in last_array])), self._webpage_generator))
            else:
                return error.main.miscellaneous(u'沒有登記到本頻道的{}，有可能是因為機器人重新啟動而造成。\n\n本次開機時間: {}'.format(unicode(last_item_cat), self._system_data.boot_up))

            if any(last_item_cat == type_cat for type_cat in (bot.system_data_category.LAST_STICKER, bot.system_data_category.LAST_PAIR_ID, bot.system_data_category.LAST_PIC_SHA)):
                action_dict = { 
                    '相關回覆組(簡潔)': text_msg_handler.HEAD + text_msg_handler.SPLITTER + 'Q' + text_msg_handler.SPLITTER + self._array_separator.join([str(item) for item in last_array]),
                    '相關回覆組(詳細)': text_msg_handler.HEAD + text_msg_handler.SPLITTER + 'I' + text_msg_handler.SPLITTER + self._array_separator.join([str(item) for item in last_array])
                }
            elif last_item_cat == bot.system_data_category.LAST_UID:
                action_dict = { 
                    '使用者{}製作'.format(uid[0:8]): text_msg_handler.HEAD + text_msg_handler.SPLITTER + 'Q' + text_msg_handler.SPLITTER + 'UID' + text_msg_handler.SPLITTER + uid for uid in last_array
                }

            rep_list.append(bot.line_api_wrapper.wrap_template_with_action(action_dict, u'{}快捷查詢樣板'.format(unicode(last_item_cat)), u'快速查詢'))

            return rep_list
        else:
            return error.main.lack_of_thing(u'參數')
             
    def _T(self, src, params, key_permission_lv, group_config_type):
        from urllib import quote

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
        
        return quote(text)

    def _C(self, src, params, key_permission_lv, group_config_type):
        if params[3] is not None:
            amount = params[1]
            source_currency = params[2]
            target_currency = params[3]

            if not bot.string_can_be_float(amount):
                text = error.main.invalid_thing_with_correct_format(u'轉換值', u'整數或小數', amount)
            elif not tool.curr_exc.oxr.is_legal_symbol_text(source_currency):
                text = error.main.invalid_thing_with_correct_format(u'原始值貨幣', u'3英文字元的貨幣代號', source_currency)
            elif not tool.curr_exc.oxr.is_legal_symbol_text(target_currency):
                text = error.main.invalid_thing_with_correct_format(u'目標值貨幣', u'3英文字元的貨幣代號', target_currency)
            else:
                text = self._oxr_client.convert(source_currency, target_currency, amount).formatted_string
        elif params[2] is not None:
            historical_date = params[1]
            target_symbol = params[2]

            if not bot.string_can_be_int(historical_date) and not len(historical_date) == 8:
                text = error.main.invalid_thing_with_correct_format(u'日期', u'8位數整數，代表(年年年年月月日日)', historical_date)
            elif not tool.curr_exc.oxr.is_legal_symbol_text(target_symbol):
                text = error.main.invalid_thing_with_correct_format(u'貨幣單位', u'3字元貨幣代號，多貨幣時以空格分隔', target_symbol)
            else:
                data_dict = self._oxr_client.get_historical_dict(historical_date, target_symbol)
                text = tool.curr_exc.oxr.historical_str(data_dict)
        elif params[1] is not None:
            param = params[1]
            if param == '$':
                available_currencies_dict = self._oxr_client.get_available_currencies_dict()
                text = tool.curr_exc.oxr.available_currencies_str(available_currencies_dict)
            elif bot.string_can_be_int(param) and len(param) == 8:
                historical_all_dict = self._oxr_client.get_historical_dict(param)
                text = tool.curr_exc.oxr.historical_str(historical_all_dict)
            elif tool.curr_exc.oxr.is_legal_symbol_text(param):
                latset_dict = self._oxr_client.get_latest_dict(param)
                text = tool.curr_exc.oxr.latest_str(latset_dict)
            else:
                text = error.main.incorrect_param(u'參數1', u'貨幣符號($)、希望幣種(NTD, USD) 或 希望歷史時間(20170505)')
        else:
            latset_dict = self._oxr_client.get_latest_dict()
            text = tool.curr_exc.oxr.latest_str(latset_dict)

        return text
             
    def _FX(self, src, params, key_permission_lv, group_config_type):
        if params[2] is not None:
            vars = params[1]
            eq = params[2]

            calc_result = self._string_calculator.calculate(vars + text_msg_handler.SPLITTER + eq, self._system_config.get(db.config_data.CALCULATOR_DEBUG), True, tool.calc_type.ALGEBRAIC_EQUATIONS)
        elif params[1] is not None:
            formula = params[1]

            calc_result = self._string_calculator.calculate(formula, self._system_config.get(db.config_data.CALCULATOR_DEBUG), True, tool.calc_type.POLYNOMIAL_FACTORIZATION)
        else:
            return error.main.unable_to_determine()

        result_str = calc_result.get_basic_text()
        if calc_result.over_length:
            text = u'因算式結果長度大於100字，為避免洗板，請點選網址察看結果。\n{}'.format(self._webpage_generator.rec_webpage(result_str, db.webpage_content_type.TEXT))
        else:
            text = result_str

        if calc_result.latex_avaliable:
            text += u'\nLaTeX URL:\n{}'.format(self._webpage_generator.rec_webpage(calc_result.latex, db.webpage_content_type.LATEX))

        return text
             
    def _N(self, src, params, key_permission_lv, group_config_type):
        if params[1] is not None:
            texts = params[1]
            
            return texts.replace('\n', '\\n')
        else:
            text = error.main.lack_of_thing(u'參數')

    def _STK(self, src, params, key_permission_lv, group_config_type):
        category = params[1]
        hour_range = params[2]
        limit_count = params[3]

        category_action_dict = { 'STK': self._stk_rec.hottest_sticker, 'PKG': self._stk_rec.hottest_package_str }

        if category not in category_action_dict:
            return error.main.invalid_thing_with_correct_format(u'參數1', u'STK(貼圖排行)或PKG(圖包排行)', category)

        if hour_range is None and limit_count is None:
            hour_range = self._config_manager.getint(bot.config_category.STICKER_RANKING, bot.config_category_sticker_ranking.HOUR_RANGE)
            limit_count = self._config_manager.getint(bot.config_category.STICKER_RANKING, bot.config_category_sticker_ranking.LIMIT_COUNT)

        if hour_range is not None and hour_range != '' and not bot.string_can_be_int(hour_range):
            return error.main.invalid_thing_with_correct_format(u'參數1(小時範圍)', u'整數', limit_count)

        if limit_count is not None and limit_count != '' and not bot.string_can_be_int(limit_count):
            return error.main.invalid_thing_with_correct_format(u'參數2(結果數量)', u'正整數', limit_count)

        hour_range = None if hour_range is None or hour_range == '' else int(hour_range)
        limit_count = None if limit_count is None or hour_range == '' else int(limit_count)

        result = category_action_dict[category](hour_range, limit_count)

        if isinstance(result, db.PackedResult):
            full_url = self._webpage_generator.rec_webpage(result.full, db.webpage_content_type.STICKER_RANKING)
            return result.limited + u'\n\n詳細資訊: ' + full_url
        else:
            return result

    def split_verify(self, cmd, splitter, param_text):
        if not self._command_manager.is_command_exist(cmd):
            return error.main.invalid_thing(u'指令', cmd)

        cmd_obj = self._command_manager.get_command_data(cmd)
        if cmd_obj.category == bot.cmd_category.GAME:
            return error.main.miscellaneous(u'此指令為遊戲指令，請將標頭之"JC"替換為"G"。')

        max_prm = cmd_obj.split_max
        min_prm = cmd_obj.split_min
        params = split(param_text, text_msg_handler.SPLITTER, max_prm)

        if min_prm > len(params) - params.count(None):
            return error.main.lack_of_thing(u'參數')

        params.insert(0, None)
        return params

class game_msg_handler(object):
    HEAD = 'G'
    SPLITTER = '\n'

    def __init__(self, mongo_db_uri, line_api_wrapper, command_manager):
        self._rps_holder = db.rps_holder(mongo_db_uri)
        self._line_api_wrapper = line_api_wrapper

        self._command_manager = command_manager

    def handle_text(self, event, full_org_text_without_head, user_permission):
        """Return whether message has been replied"""
        token = event.reply_token
        text = event.message.text
        src = event.source
        src_uid = bot.line_api_wrapper.source_user_id(src)

        cmd, oth = split(full_org_text_without_head, game_msg_handler.SPLITTER, 2)
        cmd = cmd.replace(' ', '')
        params = self.split_verify(cmd, text_msg_handler.SPLITTER, oth)

        if isinstance(params, unicode):
            self._line_api_wrapper.reply_message_text(token, params)
            return True
        else:
            cmd_function = getattr(self, '_{}'.format(cmd))

            if user_permission is bot.permission.RESTRICTED:
                self._line_api_wrapper.reply_message_text(token, error.permission.user_is_resticted())
                return True

            handle_result = cmd_function(src, params)
            if isinstance(handle_result, (str, unicode)):
                self._line_api_wrapper.reply_message_text(token, handle_result)
                return True
            else:
                self._line_api_wrapper.reply_message(token, handle_result)
                return True

        return False

    def _RPS(self, src, params):
        cid = bot.line_api_wrapper.source_channel_id(src)
        uid = bot.line_api_wrapper.source_user_id(src)

        battle_item_dict = { 'R': db.battle_item.ROCK, 'P': db.battle_item.PAPER, 'S': db.battle_item.SCISSOR }

        if params[4] is not None:
            action = params[1]
            item_enum_code = params[2]
            type_code = params[3]
            content = params[4]

            type_dict = { 'STK': True, 'TXT': False }

            if item_enum_code not in battle_item_dict:
                return db.rps_message.error.unknown_battle_item()

            if type_code not in type_dict:
                return db.rps_message.error.unknown_content_type()

            text = self._rps_holder.register_battleitem(cid, content, type_dict[type_code], battle_item_dict[item_enum_code])
        elif params[3] is not None:
            scissor = params[1]
            rock = params[2]
            paper = params[3]

            try:
                creator_name = self._line_api_wrapper.profile_name(uid)
            except bot.UserProfileNotFoundError:
                return error.line_bot_api.unable_to_receive_user_id()

            if not bot.string_can_be_int(scissor, rock, paper):
                return error.main.miscellaneous(u'初次建立遊戲時，各拳代表必須是貼圖ID。')

            text = self._rps_holder.create_game(cid, uid, creator_name, rock, paper, scissor)
        elif params[1] is not None:
            action = params[1]

            action_dict = {
                'SW': self._rps_holder.switch_enabled,
                'RST': self._rps_holder.reset_statistics,
                'DEL': self._rps_holder.delete_game,
            }

            if action == 'PLAY':
                try:
                    player_name = self._line_api_wrapper.profile(uid).display_name
                except bot.UserProfileNotFoundError:
                    return error.line_bot_api.unable_to_receive_user_id()

                if bot.line_api_wrapper.is_valid_user_id(uid):
                    text = self._rps_holder.register_player(cid, uid, player_name)
                else:
                    text = error.line_bot_api.unable_to_receive_user_id()
            elif action in action_dict:
                text = action_dict[action](cid)
            else:
                text = error.main.unable_to_determine()
        else:
            text = self._rps_holder.game_statistics(cid)

        return text

    def split_verify(self, cmd, splitter, param_text):
        if not self._command_manager.is_command_exist(cmd):
            return error.main.invalid_thing(u'指令', cmd)

        cmd_obj = self._command_manager.get_command_data(cmd)
        max_prm = cmd_obj.split_max
        min_prm = cmd_obj.split_min
        params = split(param_text, text_msg_handler.SPLITTER, max_prm)

        if min_prm > len(params) - params.count(None):
            return error.main.lack_of_thing(u'參數')

        params.insert(0, None)
        return params
 
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

