# -*- coding: utf-8 -*-
import os, sys
from linebot.models import (
    TextMessage, StickerMessage, ImageMessage, VideoMessage, AudioMessage, LocationMessage
)

from .text_msg import text_msg_handler, game_msg_handler, split
import db, bot, error

class global_msg_handle(object):
    SPLITTER = '\n'

    def __init__(self, line_api_wrapper, system_config, mongo_db_uri, txt_handle, game_handle, img_handle):
        self._mongo_uri = mongo_db_uri
        self._line_api_wrapper = line_api_wrapper
        self._system_config = system_config
        self._loop_preventer = bot.infinite_loop_preventer()

        self._txt_handle = txt_handle
        self._game_handle = game_handle
        self._img_handle = img_handle

        self._group_manager = self._txt_handle._group_manager 
        self._webpage_generator = self._txt_handle._webpage_generator 
        self._system_stats = self._txt_handle._system_stats 
        self._system_data = self._txt_handle._system_data 
        self._string_calculator = self._txt_handle._string_calculator 
        self._get_kwd_instance = self._txt_handle._get_kwd_instance 
        
        self._rps_data = self._game_handle._rps_holder

        self._intercept_key = os.getenv('COMMAND_INTERCEPT', None)
        if self._intercept_key is None:
            print 'Define COMMAND_INTERCEPT in environment variable to switch message interception.'
            sys.exit(1)

        self._silence_key = os.getenv('COMMAND_SILENCE', None)
        if self._silence_key is None:
            print 'Define COMMAND_SILENCE in environment variable to switch text message handling.'
            sys.exit(1)

        self._calc_debug_key = os.getenv('COMMAND_CALC_DEBUG', None)
        if self._calc_debug_key is None:
            print 'Define COMMAND_CALC_DEBUG in environment variable to switch string calculator debugging.'
            sys.exit(1)

        self._rep_error_key = os.getenv('COMMAND_REPLY_ERROR', None)
        if self._rep_error_key is None:
            print 'Define COMMAND_REPLY_ERROR in environment variable to switch report on error occurred.'
            sys.exit(1)

        self._intercept_display_name_key = os.getenv('COMMAND_INTERCEPT_DISPLAY_NAME', None)
        if self._intercept_display_name_key is None:
            print 'Define COMMAND_INTERCEPT_DISPLAY_NAME in environment variable to switch report on error occurred.'
            sys.exit(1)

    ##############
    ### GLOBAL ###
    ##############

    def _terminate(self):
        return self._system_config.get(db.config_data.SILENCE)

    def _handle_auto_reply(self, event, reply_data):
        """THIS WILL LOG MESSAGE ACTIVITY INSIDE METHOD IF MESSAGE HAS BEEN REPLIED."""
        self._system_data.set(bot.system_data_category.LAST_PAIR_ID, bot.line_api_wrapper.source_channel_id(event.source), reply_data.seq_id)
        src = event.source
        msg = event.message

        if isinstance(msg, TextMessage):
            recv_msg_type = db.msg_type.TEXT
        elif isinstance(msg, StickerMessage):
            recv_msg_type = db.msg_type.STICKER
        elif isinstance(msg, ImageMessage):
            recv_msg_type = db.msg_type.PICTURE
        else:
            raise NotImplementedError()

        token = event.reply_token

        rep_type = reply_data.reply_type
        rep_content = reply_data.reply
        rep_att = reply_data.reply_attach_text
        rep_link = reply_data.linked_words

        rep_list = []

        if rep_type == db.word_type.TEXT:
            rep_list.append(bot.line_api_wrapper.wrap_text_message(rep_content, self._webpage_generator))

            self._group_manager.log_message_activity(bot.line_api_wrapper.source_channel_id(src), recv_msg_type, db.msg_type.TEXT)
        elif rep_type == db.word_type.STICKER:
            rep_list.append(bot.line_api_wrapper.wrap_image_message(db.sticker_png_url(rep_content)))

            self._group_manager.log_message_activity(bot.line_api_wrapper.source_channel_id(src), recv_msg_type, db.msg_type.STICKER)
        elif rep_type == db.word_type.PICTURE:
            rep_list.append(bot.line_api_wrapper.wrap_image_message(rep_content))
            
            self._group_manager.log_message_activity(bot.line_api_wrapper.source_channel_id(src), recv_msg_type, db.msg_type.PICTURE)
        else:
            raise ValueError(error.error.main.miscellaneous(u'Unknown word type for reply.'))

        if rep_att is not None and (rep_type == db.word_type.STICKER or rep_type == db.word_type.PICTURE):
            rep_list.append(bot.line_api_wrapper.wrap_text_message(rep_att, self._webpage_generator))

        if len(rep_link) > 0:
            # Max label text length is 20. Ref: https://developers.line.me/en/docs/messaging-api/reference/#template-action
            action_dict = { db.simplified_string(word, 12): word for word in rep_link }
            alt_text = u'相關字詞: {}'.format(u'、'.join(word for word in rep_link))

            rep_list.append(bot.line_api_wrapper.wrap_template_with_action(action_dict, alt_text, u'相關回覆組'))
        
        self._line_api_wrapper.reply_message(token, rep_list) 

    def _print_intercepted(self, event, display_user_name=False):
        intercept = self._system_config.get(db.config_data.INTERCEPT)
        intercept_display_name = self._system_config.get(db.config_data.INTERCEPT_DISPLAY_NAME)
        if intercept:
            src = event.source
            uid = bot.line_api_wrapper.source_user_id(src)

            if intercept_display_name:
                try:
                    user_name = self._line_api_wrapper.profile_name(uid)
                    if user_name is None:
                        user_name = 'Empty'
                except bot.UserProfileNotFoundError:
                    user_name = 'Unknown'
            else:
                user_name = '(Set to not to display.)'

            print '==========================================='
            print 'From Channel ID \'{}\''.format(bot.line_api_wrapper.source_channel_id(src))
            print 'From User ID \'{}\' ({})'.format(uid, user_name.encode('utf-8'))
            if isinstance(event.message, TextMessage):
                print 'Message \'{}\''.format(event.message.text.encode('utf-8'))
            elif isinstance(event.message, StickerMessage):
                print 'Sticker ID: {} Package ID: {}'.format(event.message.sticker_id, event.message.package_id)
            else:
                print '(not implemented intercept output.)'
                print event.message
            print '=================================================================='

    def _get_group_config(self, cid):
        return self._group_manager.get_group_config_type(cid)

    def _get_user_permission(self, src):
        src_gid = bot.line_api_wrapper.source_channel_id(src)
        src_uid = bot.line_api_wrapper.source_user_id(src)
        return self._group_manager.get_user_permission(src_gid, src_uid)

    #############################
    ### HANDLE TEXT - PRIVATE ###
    #############################

    def _handle_text_sys_config(self, event):
        """Return whether message has been replied."""
        full_text = event.message.text

        # IMPORTANT: make dict

        action_dict = { self._silence_key: (db.config_data.SILENCE, 'BOT SILENCE: {}'),
                        self._intercept_key: (db.config_data.INTERCEPT, 'MESSAGE INTERCEPTION: {}'),
                        self._intercept_display_name_key: (db.config_data.INTERCEPT_DISPLAY_NAME, 'DISPLAY NAME IN MESSAGE INTERCEPTION: {}'),
                        self._calc_debug_key: (db.config_data.CALCULATOR_DEBUG, 'CALCULATOR DEBUG: {}'),
                        self._rep_error_key: (db.config_data.REPLY_ERROR, 'REPLY ON ERROR: {}') }

        action = action_dict.get(full_text, None)
        if action is not None:
            new_setting = self._system_config.set(action[0], not self._system_config.get(action[0])).get(action[0])
            self._line_api_wrapper.reply_message_text(event.reply_token, action[1].format('ENABLED' if new_setting else 'DISABLED'))

        return False

    def _handle_text_sys_command(self, event, user_permission, group_config_type):
        """Return whether message has been replied."""
        full_text = event.message.text
        if bot.msg_handler.global_msg_handle.SPLITTER in full_text:
            head, content = split(full_text, global_msg_handle.SPLITTER, 2)

            if head == text_msg_handler.HEAD:
                return self._txt_handle.handle_text(event, content, user_permission, group_config_type)
            elif head == game_msg_handler.HEAD:
                return self._game_handle.handle_text(event, content, user_permission)

        return False

    def _handle_text_rps(self, event):
        """Return whether message has been replied."""
        content = event.message.text
        src = event.source
        src_cid = bot.line_api_wrapper.source_channel_id(src)
        src_uid = bot.line_api_wrapper.source_user_id(src)

        rps_result = self._rps_data.play(src_cid, src_uid, content, False)

        if rps_result is not None and not any(rps_result != res_str for res_str in (db.rps_message.error.game_instance_not_exist(), db.rps_message.error.game_is_not_enabled(), db.rps_message.error.player_data_not_found())):
            self._line_api_wrapper.reply_message_text(event.reply_token, rps_result)
            return True  

        return False

    def _handle_text_auto_reply(self, event, config):
        """Return whether message has been replied. THIS WILL LOG MESSAGE ACTIVITY INSIDE METHOD IF MESSAGE HAS BEEN REPLIED."""
        full_text = event.message.text
        reply_data = self._get_kwd_instance(event.source, config).get_reply_data(full_text)
        if reply_data is not None:
            self._handle_auto_reply(event, reply_data)
            return True

        return False

    def _handle_text_str_calc(self, event):
        """Return whether message has been replied."""
        full_text = event.message.text
        calc_result = self._string_calculator.calculate(full_text, self._system_config.get(db.config_data.CALCULATOR_DEBUG))
        if calc_result.success or calc_result.timeout:
            self._system_stats.command_called('FX')

            result_str = calc_result.get_basic_text()

            if calc_result.over_length:
                text = u'因算式結果長度大於100字，為避免洗板，請點選網址察看結果。\n{}'.format(self._webpage_generator.rec_webpage(result_str, db.webpage_content_type.TEXT))
            else:
                text = result_str
                
            self._line_api_wrapper.reply_message_text(event.reply_token, text) 
            return True

        return False

    ############################
    ### HANDLE TEXT - PUBLIC ###
    ############################

    def handle_text(self, event):
        self._print_intercepted(event)

        src = event.source
        token = event.reply_token
        full_text = event.message.text

        if full_text == 'ERRORERRORERRORERROR':
            raise Exception('THIS ERROR IS CREATED FOR TESTING PURPOSE.')

        #########################################################
        ### TERMINATE CHECK - MAIN SYSTEM CONFIG CHANGING KEY ###
        #########################################################

        terminate_0 = self._handle_text_sys_config(event)

        if terminate_0:
            print 'terminate 0'
            self._group_manager.log_message_activity(bot.line_api_wrapper.source_channel_id(src), db.msg_type.TEXT, db.msg_type.TEXT)
            return

        ####################################################
        ### TERMINATE CHECK - SILENCE CONFIG FROM SYSTEM ###
        ####################################################

        terminate_1 = self._terminate()
        if terminate_1 and not full_text.startswith(text_msg_handler.HEAD + text_msg_handler.SPLITTER + 'GA'):
            print 'terminate 1'
            self._group_manager.log_message_activity(bot.line_api_wrapper.source_channel_id(src), db.msg_type.TEXT)
            return

        ##############################################
        ######## ASSIGN NECESSARY VARIABLES 1 ########
        ##############################################

        cid = bot.line_api_wrapper.source_channel_id(src)
        uid = bot.line_api_wrapper.source_user_id(src)

        #####################################
        ### TERMINATE CHECK - LOOP TO BAN ###
        #####################################

        terminate_2 = self._loop_preventer.rec_last_content_and_get_status(uid, full_text)

        if terminate_2:
            print 'terminate 2'
            return

        ##############################################
        ######## ASSIGN NECESSARY VARIABLES 2 ########
        ##############################################

        group_config = self._get_group_config(cid)
        user_permission = self._get_user_permission(src)
        self._system_data.set(bot.system_data_category.LAST_UID, cid, uid)

        #######################################################
        ### TERMINATE CHECK - GROUP CONFIG IS SILENCE CHECK ###
        #######################################################

        terminate_3 = group_config <= db.config_type.SILENCE or user_permission == bot.permission.RESTRICTED

        if terminate_3:
            print 'terminate 3'
            return

        #########################################
        ### TERMINATE CHECK - TEXT CALCULATOR ###
        #########################################

        terminate_4 = self._handle_text_str_calc(event)

        if terminate_4:
            print 'terminate 4'
            self._group_manager.log_message_activity(bot.line_api_wrapper.source_channel_id(src), db.msg_type.TEXT, db.msg_type.TEXT)
            return

        ####################################
        ### TERMINATE CHECK - GAME (RPS) ###
        ####################################
        
        terminate_5 = self._handle_text_rps(event)

        if terminate_5:
            print 'terminate 5'
            self._group_manager.log_message_activity(bot.line_api_wrapper.source_channel_id(src), db.msg_type.TEXT, db.msg_type.TEXT)
            return

        ########################################
        ### TERMINATE CHECK - SYSTEM COMMAND ###
        ########################################

        terminate_6 = self._handle_text_sys_command(event, user_permission, group_config)

        if terminate_6 or group_config <= db.config_type.SYS_ONLY:
            print 'terminate 6'
            self._group_manager.log_message_activity(bot.line_api_wrapper.source_channel_id(src), db.msg_type.TEXT, db.msg_type.TEXT)
            return

        ####################################
        ### TERMINATE CHECK - AUTO REPLY ###
        ####################################
        
        terminate_7 = self._handle_text_auto_reply(event, group_config)
             
        if terminate_7:
            print 'terminate 7'
            return

        self._group_manager.log_message_activity(bot.line_api_wrapper.source_channel_id(src), db.msg_type.TEXT)

    ################################
    ### HANDLE STICKER - PRIVATE ###
    ################################

    def _handle_sticker_rps(self, event, sticker_id):
        """Return whether message has been replied."""
        content = event.message.sticker_id
        src = event.source
        src_cid = bot.line_api_wrapper.source_channel_id(src)
        src_uid = bot.line_api_wrapper.source_user_id(src)

        rps_result = self._rps_data.play(src_cid, src_uid, content, True)

        print rps_result

        if rps_result is not None and not any(rps_result != res_str for res_str in (db.rps_message.error.game_instance_not_exist(), db.rps_message.error.game_is_not_enabled(), db.rps_message.error.player_data_not_found())):
            self._line_api_wrapper.reply_message_text(event.reply_token, rps_result)
            return True  

        return False

    def _handle_sticker_data(self, event):
        """Return whether message has been replied."""
        if bot.line_event_source_type.determine(event.source) == bot.line_event_source_type.USER:
            sticker_id = event.message.sticker_id
            package_id = event.message.package_id

            self._line_api_wrapper.reply_message_text(event.reply_token, u'貼圖圖包ID: {}\n貼圖圖片ID: {}'.format(package_id, sticker_id))
            return True
        
        return False

    def _handle_sticker_auto_reply(self, event, config):
        """Return whether message has been replied. THIS WILL LOG MESSAGE ACTIVITY INSIDE METHOD IF MESSAGE HAS BEEN REPLIED."""
        full_text = event.message.sticker_id
        reply_data = self._get_kwd_instance(event.source, config).get_reply_data(full_text, db.word_type.STICKER)
        if reply_data is not None:
            self._handle_auto_reply(event, reply_data)
            return True

        return False

    ###############################
    ### HANDLE STICKER - PUBLIC ###
    ###############################

    def handle_sticker(self, event):
        sticker_id = event.message.sticker_id
        token = event.reply_token
        src = event.source
        cid = bot.line_api_wrapper.source_channel_id(src)
        
        self._print_intercepted(event)
        
        ####################################################
        ### TERMINATE CHECK - SILENCE CONFIG FROM SYSTEM ###
        ####################################################
        
        terminate_0 = self._terminate()
        
        if terminate_0:
            print 'terminate 0'
            self._group_manager.log_message_activity(bot.line_api_wrapper.source_channel_id(src), db.msg_type.STICKER)
            return

        ############################################
        ######## ASSIGN NECESSARY VARIABLES ########
        ############################################

        group_config = self._get_group_config(bot.line_api_wrapper.source_channel_id(src))
        user_permission = self._get_user_permission(src)

        self._system_data.set(bot.system_data_category.LAST_STICKER, cid, sticker_id)

        #######################################################
        ### TERMINATE CHECK - GROUP CONFIG IS SILENCE CHECK ###
        #######################################################

        terminate_1 = group_config <= db.config_type.SILENCE or user_permission == bot.permission.RESTRICTED

        if terminate_1:
            print 'terminate 1'
            return

        ####################################
        ### TERMINATE CHECK - GAME (RPS) ###
        ####################################

        terminate_2 = self._handle_sticker_rps(event, sticker_id)

        if terminate_2 or group_config <= db.config_type.SYS_ONLY:
            print 'terminate 2'
            self._group_manager.log_message_activity(bot.line_api_wrapper.source_channel_id(src), db.msg_type.STICKER, db.msg_type.TEXT)
            return

        ######################################
        ### TERMINATE CHECK - STICKER DATA ###
        ######################################

        terminate_3 = self._handle_sticker_data(event)

        if terminate_3:
            print 'terminate 3'
            self._group_manager.log_message_activity(bot.line_api_wrapper.source_channel_id(src), db.msg_type.STICKER, db.msg_type.TEXT)
            return

        ####################################
        ### TERMINATE CHECK - AUTO REPLY ###
        ####################################

        terminate_4 = self._handle_sticker_auto_reply(event, group_config)

        if terminate_4:
            print 'terminate 4'
            return

        self._group_manager.log_message_activity(cid, db.msg_type.STICKER)

    ##############################
    ### HANDLE IMAGE - PRIVATE ###
    ##############################

    def _handle_image_upload(self, event, image_sha):
        if bot.line_event_source_type.determine(event.source) == bot.line_event_source_type.USER:
            upload_result = self._img_handle.upload_imgur(event.message)

            rep_list = [bot.line_api_wrapper.wrap_text_message(u'檔案雜湊碼(SHA224)', self._webpage_generator), 
                        bot.line_api_wrapper.wrap_text_message(image_sha, self._webpage_generator)]

            if upload_result.image_url is not None:
                rep_list.append(bot.line_api_wrapper.wrap_text_message(upload_result.result_string, self._webpage_generator))
                rep_list.append(bot.line_api_wrapper.wrap_text_message(upload_result.image_url, self._webpage_generator))

            self._line_api_wrapper.reply_message(event.reply_token, rep_list)
            return True

        return False

    def _handle_image_auto_reply(self, event, image_sha, config):
        """Return whether message has been replied. THIS WILL LOG MESSAGE ACTIVITY INSIDE METHOD IF MESSAGE HAS BEEN REPLIED."""
        reply_data = self._get_kwd_instance(event.source, config).get_reply_data(image_sha, db.word_type.PICTURE)
        if reply_data is not None:
            self._handle_auto_reply(event, reply_data)
            return True

        return False

    #############################
    ### HANDLE IMAGE - PUBLIC ###
    #############################

    def handle_image(self, event):
        src = event.source
        token = event.reply_token
        cid = bot.line_api_wrapper.source_channel_id(src)

        ####################################################
        ### TERMINATE CHECK - SILENCE CONFIG FROM SYSTEM ###
        ####################################################
        
        terminate_0 = self._terminate()
        
        if terminate_0:
            print 'terminate 0'
            self._group_manager.log_message_activity(bot.line_api_wrapper.source_channel_id(src), db.msg_type.PICTURE)
            return

        ############################################
        ######## ASSIGN NECESSARY VARIABLES ########
        ############################################

        group_config = self._get_group_config(cid)
        user_permission = self._get_user_permission(src)
        image_sha = self._img_handle.image_sha224_of_message(event.message)
        
        self._system_data.set(bot.system_data_category.LAST_PIC_SHA, cid, image_sha)

        #######################################################
        ### TERMINATE CHECK - GROUP CONFIG IS SILENCE CHECK ###
        #######################################################

        terminate_1 = group_config <= db.config_type.SYS_ONLY or user_permission == bot.permission.RESTRICTED

        if terminate_1:
            print 'terminate 1'
            return

        ######################################
        ### TERMINATE CHECK - UPLOAD IMAGE ###
        ######################################
        
        terminate_2 = self._handle_image_upload(event, image_sha)
        
        if terminate_2:
            print 'terminate 2'
            self._group_manager.log_message_activity(bot.line_api_wrapper.source_channel_id(src), db.msg_type.PICTURE, db.msg_type.TEXT, 1, 4)
            return

        ####################################
        ### TERMINATE CHECK - AUTO REPLY ###
        ####################################
        
        terminate_3 = self._handle_image_auto_reply(event, image_sha, group_config)
             
        if terminate_3:
            print 'pass 3'
            return

        self._group_manager.log_message_activity(bot.line_api_wrapper.source_channel_id(src), db.msg_type.PICTURE)