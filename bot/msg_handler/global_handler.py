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
        self._game_data = db.game_object_holder(mongo_db_uri)

        self._txt_handle = txt_handle
        self._game_handle = game_handle
        self._img_handle = img_handle

        self._group_manager = self._txt_handle._group_manager 
        self._webpage_generator = self._txt_handle._webpage_generator 
        self._system_stats = self._txt_handle._system_stats 
        self._system_data = self._txt_handle._system_data 
        self._string_calculator = self._txt_handle._string_calculator 
        self._get_kwd_instance = self._txt_handle._get_kwd_instance 

        self._intercept_key = os.getenv('COMMAND_INTERCEPT', None)
        if self._intercept_key is None:
            print 'Define COMMAND_INTERCEPT in environment variable to switch message interception.'
            sys.exit(1)

        self._silence_key = os.getenv('ADMIN_SHA', None)
        if self._silence_key is None:
            print 'Define ADMIN_SHA in environment variable to switch text message handling.'
            sys.exit(1)

        self._calc_debug_key = os.getenv('COMMAND_CALC_DEBUG', None)
        if self._calc_debug_key is None:
            print 'Define COMMAND_CALC_DEBUG in environment variable to switch string calculator debugging.'
            sys.exit(1)

        self._rep_error_key = os.getenv('COMMAND_REPLY_ERROR', None)
        if self._rep_error_key is None:
            print 'Define COMMAND_REPLY_ERROR in environment variable to switch report on error occurred.'
            sys.exit(1)

    ##############
    ### GLOBAL ###
    ##############

    def _terminate(self):
        return self._system_config.get(db.config_data.SILENCE)

    def _handle_auto_reply(self, event, reply_data):
        """THIS WILL LOG MESSAGE ACTIVITY INSIDE METHOD IF MESSAGE HAS BEEN REPLIED."""
        self._system_data.set_last_pair(bot.line_api_wrapper.source_channel_id(event.source), reply_data.seq_id)
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

        if rep_att is not None:
            rep_list.append(bot.line_api_wrapper.wrap_text_message(rep_att, self._webpage_generator))

        if rep_link is not None:
            # Max label text length is 20. Ref: https://developers.line.me/en/docs/messaging-api/reference/#template-action
            action_dict = { db.simplified_string(word, 12): word for word in rep_link }
            alt_text = u'相關字詞: {}'.format(u'、'.join(word for word in rep_link))

            rep_list.append(bot.line_api_wrapper.wrap_template_with_action(action_dict, alt_text, '相關回覆組'))
        
        self._line_api_wrapper.reply_message(token, rep_list) 

    def _print_intercepted(self, event):
        intercept = self._system_config.get(db.config_data.INTERCEPT)
        if intercept:
            src = event.source
            uid = bot.line_api_wrapper.source_user_id(src)

            try:
                user_name = self._line_api_wrapper.profile_name(uid, src)
                if user_name is None:
                    user_name = 'Empty'
            except bot.UserProfileNotFoundError:
                user_name = 'Unknown'

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

    def _minigame_rps_capturing(rps_obj, is_sticker, content, uid):
        if rps_obj is not None and bot.line_api_wrapper.is_valid_user_id(uid) and rps_obj.get_player_by_uid(uid) is not None:
            if rps_obj.enabled:
                battle_item = rps_obj.find_battle_item(is_sticker, content)
                if battle_item is not None:
                    result = rps_obj.play(battle_item, uid)
                    if result is not None:
                        return result
                    else:
                        if rps_obj.is_waiting_next:
                            return u'等待下一個玩家出拳中...'
                        if rps_obj.result_generated:
                            return rps_obj.result_text()

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

        if full_text == self._silence_key:
            new_setting = self._system_config.set(db.config_data.SILENCE, not self._system_config.get(db.config_data.SILENCE)).get(db.config_data.SILENCE)
            self._line_api_wrapper.reply_message_text(event.reply_token, 'BOT SILENCE: {}'.format('ENABLED' if new_setting else 'DISABLED'))
            return True

        if full_text == self._intercept_key:
            new_setting = self._system_config.set(db.config_data.INTERCEPT, not self._system_config.get(db.config_data.INTERCEPT)).get(db.config_data.INTERCEPT)
            self._line_api_wrapper.reply_message_text(event.reply_token, 'MESSAGE INTERCEPTION: {}'.format('ENABLED' if new_setting else 'DISABLED'))
            return True
        
        if full_text == self._calc_debug_key:
            new_setting = self._system_config.set(db.config_data.CALCULATOR_DEBUG, not self._system_config.get(db.config_data.CALCULATOR_DEBUG)).get(db.config_data.CALCULATOR_DEBUG)
            self._line_api_wrapper.reply_message_text(event.reply_token, 'CALCULATOR DEBUG: {}'.format('ENABLED' if new_setting else 'DISABLED'))
            return True
        
        if full_text == self._rep_error_key:
            new_setting = self._system_config.set(db.config_data.REPLY_ERROR, not self._system_config.get(db.config_data.REPLY_ERROR)).get(db.config_data.REPLY_ERROR)
            self._line_api_wrapper.reply_message_text(event.reply_token, 'REPLY ON ERROR: {}'.format('ENABLED' if new_setting else 'DISABLED'))
            return True

        return False

    def _handle_text_sys_command(self, event, user_permission):
        """Return whether message has been replied."""
        full_text = event.message.text
        if bot.msg_handler.global_msg_handle.SPLITTER in text:
            head, content = split(full_text, global_msg_handle.SPLITTER, 2)

            if head == text_msg_handler.HEAD:
                return self._txt_handle.handle_text(event, content, user_permission)
            elif head == game_msg_handler.HEAD:
                return self._game_handle.handle_text(event, content, user_permission)

        return False

    def _handle_text_rps(self, event):
        """Return whether message has been replied."""
        full_text = event.message.text
        src = event.source

        rps_obj = self._game_data.get_data(bot.line_api_wrapper.source_channel_id(src))

        if rps_obj is not None:
            rps_text = self._minigame_rps_capturing(rps_obj, False, full_text, bot.line_api_wrapper.source_user_id(src))
            if rps_text is not None:
                self._line_api_wrapper.reply_message_text(event.reply_token, rps_text)
                return True

        return False

    def _handle_text_auto_reply(self, event, config):
        """Return whether message has been replied. THIS WILL LOG MESSAGE ACTIVITY INSIDE METHOD IF MESSAGE HAS BEEN REPLIED."""
        full_text = event.message.text
        reply_data = self._get_kwd_instance(src, config).get_reply_data(full_text)
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
                
            self._line_api_wrapper.reply_message(token, text) 
            return True

        return False

    ############################
    ### HANDLE TEXT - PUBLIC ###
    ############################

    def handle_text(self, event):
        self._print_intercepted(event)

        if full_text == 'ERRORERRORERRORERROR':
            raise Exception('THIS ERROR IS CREATED FOR TESTING PURPOSE.')

        src = event.source
        token = event.reply_token
        full_text = event.message.text

        group_config = self._get_group_config(bot.line_api_wrapper.source_channel_id(src))
        user_permission = self._get_user_permission(src)

        #########################################################
        ### TERMINATE CHECK - MAIN SYSTEM CONFIG CHANGING KEY ###
        #########################################################

        terminate_0 = self._handle_text_sys_config(event, full_text)

        if terminate_0:
            self._group_manager.log_message_activity(bot.line_api_wrapper.source_channel_id(src), db.msg_type.TEXT, db.msg_type.TEXT)
            return

        ####################################################
        ### TERMINATE CHECK - SILENCE CONFIG FROM SYSTEM ###
        ####################################################

        terminate_1 = self._terminate()
        
        if terminate_1 or group_config == db.config_type.SILENCE:
            self._group_manager.log_message_activity(bot.line_api_wrapper.source_channel_id(src), db.msg_type.TEXT)
            return

        ########################################
        ### TERMINATE CHECK - SYSTEM COMMAND ###
        ########################################

        terminate_2 = self._handle_text_sys_command(event, full_text)

        if terminate_2:
            self._group_manager.log_message_activity(bot.line_api_wrapper.source_channel_id(src), db.msg_type.TEXT, None)
            return

        ####################################
        ### TERMINATE CHECK - GAME (RPS) ###
        ####################################
        
        terminate_3 = self._handle_text_rps(event, full_text)

        if terminate_3 or group_config == db.config_type.SYS_ONLY or user_permission == bot.permission.RESTRICTED:
            self._group_manager.log_message_activity(bot.line_api_wrapper.source_channel_id(src), db.msg_type.TEXT, db.msg_type.TEXT)
            return

        ####################################
        ### TERMINATE CHECK - AUTO REPLY ###
        ####################################
        
        terminate_4 = self._handle_text_auto_reply(event, full_text, group_config)
             
        if terminate_4:
            return

        #########################################
        ### TERMINATE CHECK - TEXT CALCULATOR ###
        #########################################

        terminate_5 = self._handle_text_str_calc(event, full_text)

        if terminate_5:
            self._group_manager.log_message_activity(bot.line_api_wrapper.source_channel_id(src), db.msg_type.TEXT, db.msg_type.TEXT)
            return 

        self._group_manager.log_message_activity(bot.line_api_wrapper.source_channel_id(src), db.msg_type.TEXT)

    ################################
    ### HANDLE STICKER - PRIVATE ###
    ################################

    def _handle_sticker_rps(self, event, sticker_id):
        """Return whether message has been replied."""
        src = event.source

        rps_obj = self._game_data.get_rps(bot.line_api_wrapper.source_channel_id(src))

        if rps_obj is not None:
            rps_text = self._minigame_rps_capturing(rps_obj, True, sticker_id, bot.line_api_wrapper.source_user_id(src))
            if rps_text is not None:
                self._line_api_wrapper.reply_message_text(event.reply_token, rps_text)
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
        reply_data = self._get_kwd_instance(src, config).get_reply_data(full_text, db.word_type.STICKER)
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
        
        group_config = self._get_group_config(bot.line_api_wrapper.source_channel_id(src))
        
        self._print_intercepted(event)
        self._system_data.set_last_sticker(cid, sticker_id)
        
        ####################################################
        ### TERMINATE CHECK - SILENCE CONFIG FROM SYSTEM ###
        ####################################################
        
        terminate_0 = self._terminate()
        
        if terminate_0:
            self._group_manager.log_message_activity(bot.line_api_wrapper.source_channel_id(src), db.msg_type.STICKER)
            return

        ####################################
        ### TERMINATE CHECK - GAME (RPS) ###
        ####################################

        terminate_1 = self._handle_sticker_rps(event, sticker_id)
        if terminate_1 and group_config == db.config_type.SYS_ONLY:
            self._group_manager.log_message_activity(bot.line_api_wrapper.source_channel_id(src), db.msg_type.STICKER, db.msg_type.TEXT)
            return 

        ######################################
        ### TERMINATE CHECK - STICKER DATA ###
        ######################################

        terminate_2 = self._handle_sticker_data(event)
        if terminate_2:
            self._group_manager.log_message_activity(bot.line_api_wrapper.source_channel_id(src), db.msg_type.STICKER, db.msg_type.TEXT)
            return 

        ####################################
        ### TERMINATE CHECK - AUTO REPLY ###
        ####################################

        terminate_3 = self._handle_sticker_auto_reply(event, group_config)
        if terminate_3:
            return 

        self._group_manager.log_message_activity(cid, db.msg_type.STICKER)

    ##############################
    ### HANDLE IMAGE - PRIVATE ###
    ##############################

    def _handle_image_upload(self, event, image_sha):
        if bot.line_event_source_type.determine(event.source) == bot.line_event_source_type.USER:
            upload_result = self._img_handle.upload_imgur(event.message)

            rep_list = [bot.line_api_wrapper.wrap_text_message(u'檔案雜湊碼(SHA224)'), 
                        bot.line_api_wrapper.wrap_text_message(image_sha)]

            if upload_result.image_url is not None:
                rep_list.append(bot.line_api_wrapper.wrap_text_message(upload_result.result_string))
                rep_list.append(bot.line_api_wrapper.wrap_text_message(upload_result.image_url))

            self._line_api_wrapper.reply_message(event.reply_token, rep_list)
            return True

        return False

    def _handle_image_auto_reply(self, image_sha, config):
        """Return whether message has been replied. THIS WILL LOG MESSAGE ACTIVITY INSIDE METHOD IF MESSAGE HAS BEEN REPLIED."""
        reply_data = self._get_kwd_instance(src, config).get_reply_data(image_sha, db.word_type.PICTURE)
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
        
        group_config = self._get_group_config(bot.line_api_wrapper.source_channel_id(src))

        ####################################################
        ### TERMINATE CHECK - SILENCE CONFIG FROM SYSTEM ###
        ####################################################
        
        terminate_0 = self._terminate()
        
        if terminate_0:
            self._group_manager.log_message_activity(bot.line_api_wrapper.source_channel_id(src), db.msg_type.PICTURE)
            return

        ############################################
        ######## ASSIGN NECESSARY VARIABLES ########
        ############################################
        
        image_sha = self._img_handle.image_sha224_of_message(event.message)
        self._system_data.set_last_pic_sha(bot.line_api_wrapper.source_channel_id(event.source), image_sha)

        ######################################
        ### TERMINATE CHECK - UPLOAD IMAGE ###
        ######################################
        
        terminate_1 = self._handle_image_upload(event, image_sha)
        
        if terminate_1:
            self._group_manager.log_message_activity(bot.line_api_wrapper.source_channel_id(src), db.msg_type.PICTURE, db.msg_type.TEXT, 1, 4)
            return

        ####################################
        ### TERMINATE CHECK - AUTO REPLY ###
        ####################################
        
        terminate_2 = self._handle_image_auto_reply(event, image_sha, group_config)
             
        if terminate_2:
            return

        self._group_manager.log_message_activity(bot.line_api_wrapper.source_channel_id(src), db.msg_type.PICTURE)