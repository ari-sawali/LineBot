# -*- coding: utf-8 -*-

import os, sys
import requests
from datetime import datetime, timedelta
from collections import deque
from linebot import exceptions
import hashlib
import operator
import traceback
import error, tool

from linebot.models import (
    SourceGroup, SourceRoom, SourceUser,
    TextSendMessage, ImageSendMessage, TemplateSendMessage,
    CarouselTemplate, ButtonsTemplate, CarouselColumn, MessageTemplateAction, URITemplateAction
)

import db
import ext
from .config import config_manager

class system_data_category(ext.EnumWithName):
    LAST_STICKER = 0, '末三張貼圖ID'
    LAST_PIC_SHA = 1, '末三張圖片雜湊(SHA224)'
    LAST_PAIR_ID = 2, '末三組回覆組ID'
    LAST_UID = 3, '末三則訊息傳送者(不含小水母)UID'

class system_data(object):
    MAX_LENGTH_OF_DEQUE = 3

    def __init__(self):
        self._boot_up = datetime.now() + timedelta(hours=8)
        
        self._last_sticker = {}
        self._last_pic_sha = {}
        self._last_pair = {}
        self._last_uid = {}

        self._field_dict = {
            system_data_category.LAST_STICKER: self._last_sticker,
            system_data_category.LAST_PIC_SHA: self._last_pic_sha,
            system_data_category.LAST_PAIR_ID: self._last_pair,
            system_data_category.LAST_UID: self._last_uid
        }

    def set(self, category_enum, cid, content):
        d = self._field_dict[category_enum]

        if cid not in d:
            d[cid] = deque(maxlen=system_data.MAX_LENGTH_OF_DEQUE)

        if content in d[cid]:
            return

        d[cid].append(content)
        self._field_dict[category_enum] = d

    def get(self, category_enum, cid):
        return self._field_dict[category_enum].get(cid)

    @property
    def boot_up(self):
        return self._boot_up

class infinite_loop_preventer(object):
    def __init__(self, max_loop_count, unlock_pw_length):
        self._last_message = {}
        self._max_loop_count = max_loop_count
        self._unlock_pw_length = unlock_pw_length

    def rec_last_content_and_get_status(self, uid, cid, content, msg_type):
        if uid in self._last_message:
            banned = self._last_message[uid].banned
            if banned:
                return True
            self._last_message[uid].rec_content(cid, content, msg_type)
        else:
            self._last_message[uid] = infinite_loop_prevent_data(self._max_loop_count, uid, self._unlock_pw_length, cid, content, msg_type)

        return self._last_message[uid].banned

    def get_all_banned_str(self):
        banned_dict = dict((k, v) for k, v in self._last_message.iteritems() if v.banned)
        if len(banned_dict) < 1:
            return u'(無)'
        output = []
        for k, v in banned_dict.iteritems():
            output.append(u'UUID: {}\n驗證碼: {}\n訊息紀錄:\n{}'.format(k, v.unlock_key, v.rec_content_str()))
        return u'\n==========\n'.join(output)

    def get_pw_notice_text(self, uid, line_api_wrapper):
        """Return None if pw is generated. Else, return str."""
        if uid in self._last_message:
            data = self._last_message[uid]
            data.unlock_noticed = True
            pw = data.generate_pw()
            if pw is not None:
                return u'目標: {} ({})\n\n因連續發送相同的訊息內容、訊息文字{}次，有洗板、濫用小水母之疑慮，故小水母已鎖定使用者的所有操作。請輸入驗證碼以解鎖。\n驗證碼: {}。\n\n訊息紀錄:\n{}'.format(uid, line_api_wrapper.profile_name(uid), self._max_loop_count, pw, data.rec_content_str())
        else:
            self._last_message[uid] = infinite_loop_prevent_data(self._max_loop_count, uid, self._unlock_pw_length)

    def unlock(self, uid, password):
        """Return str if unlocked. Else, return None."""
        if uid in self._last_message:
            data = self._last_message[uid]
            data.unlock_noticed = False
            unlock_result = data.unlock(password)
            if unlock_result:
                return u'使用者UUID: {}\n解鎖成功。'.format(uid)
        else:
            self._last_message[uid] = infinite_loop_prevent_data(self._max_loop_count, uid, self._unlock_pw_length)

class infinite_loop_prevent_data(object):
    CONTENT = 'cont'
    MESSAGE_TYPE = 'typ'
    CHANNEL_ID = 'cid'
    TIMESTAMP = 'ts'

    def __init__(self, max_loop_count, uid, unlock_pw_length, init_cid=None, init_content=None, init_content_type=db.msg_type.TEXT):
        self._uid = uid
        self._max_loop_count = max_loop_count
        self._repeat_count = int(init_content is not None)
        self._message_record = deque(maxlen=max_loop_count)
        if self._repeat_count == 1:
            self.rec_content(init_cid, init_content, init_content_type)

        self._unlock_noticed = False
        self._unlock_key = None
        self._unlock_key_length = unlock_pw_length

    @property
    def user_id(self):
        return self._uid

    @property
    def banned(self):
        return self._repeat_count >= self._max_loop_count

    @property
    def unlock_key(self):
        return self._unlock_key

    @property
    def unlock_noticed(self):
        return self._unlock_noticed

    @unlock_noticed.setter
    def unlock_noticed(self, value):
        self._unlock_noticed = value

    def generate_pw(self):
        """if generated, return None"""
        if self._unlock_key is None:
            self._unlock_key = tool.random_drawer.generate_random_string(self._unlock_key_length)
            return self._unlock_key

    def unlock(self, password):
        """Clear password if success. Return result of unlocking."""
        if password == self._unlock_key:
            self._repeat_count = 0
            self._unlock_key = None
            return True

        return False

    def rec_content(self, cid, content, msg_type):
        new_data = message_pack(content, cid, msg_type)

        msg_rec_count = len(self._message_record)
        if msg_rec_count > 0:
            last_data = self._message_record[msg_rec_count - 1]
        else:
            last_data = None 

        self._message_record.append(new_data)

        if new_data == last_data:
            self._repeat_count += 1
        else:
            self._repeat_count = 0

    def rec_content_str(self):
        l = [msg_pack.get_repr_str() for msg_pack in self._message_record]
        return u'\n\n'.join(l)

class message_pack(object):
    def __init__(self, content, channel_id, msg_type=db.msg_type.TEXT):
        self._content = content
        self._channel_id = channel_id
        self._msg_type = msg_type
        self._timestamp = datetime.now() + timedelta(hours=8)

    def __eq__(self, other):
        if other is None:
            return False

        def equal_dicts(d1, d2, ignore_keys):
            ignored = set(ignore_keys)
            for k1, v1 in d1.iteritems():
                if k1 not in ignored and (k1 not in d2 or d2[k1] != v1):
                    return False
            for k2, v2 in d2.iteritems():
                if k2 not in ignored and k2 not in d1:
                    return False
            return True

        return equal_dicts(self.__dict__, other.__dict__, ['_timestamp'])

    def get_repr_str(self):
        return u'發訊頻道ID: {}\n內容: {}\n訊息種類: {}\n時間: {}'.format(simplified_string(self._channel_id), simplified_string(self._content, 20), unicode(self._msg_type), self._timestamp.strftime('%Y-%m-%d %H:%M:%S.%f'))

    @property
    def content(self):
        return self._content
    
    @property
    def channel_id(self):
        return self._channel_id
    
    @property
    def msg_type(self):
        return self._msg_type
    
    @property
    def timestamp(self):
        return self._timestamp

class line_event_source_type(ext.EnumWithName):
    USER = 0, '私訊'
    GROUP = 1, '群組'
    ROOM = 2, '房間'

    @staticmethod
    def determine(event_source):
        if isinstance(event_source, SourceUser):
            return line_event_source_type.USER
        elif isinstance(event_source, SourceGroup):
            return line_event_source_type.GROUP
        elif isinstance(event_source, SourceRoom):
            return line_event_source_type.ROOM
        else:
            raise ValueError(error.error.main.miscellaneous(u'Undefined type of event source instance.'))

class line_api_wrapper(object):
    def __init__(self, line_api, webpage_generator):
        self._line_api = line_api
        self._webpage_generator = webpage_generator

    def profile(self, uid, src=None):
        try:
            profile = self.profile_friend_list(uid)

            if profile is not None:
                return profile

            if src is None:
                return profile
            else:
                source_type = line_event_source_type.determine(src)
                if source_type == line_event_source_type.USER:
                    return profile
                elif source_type == line_event_source_type.GROUP:
                    return self.profile_group(line_api_wrapper.source_channel_id(src), uid)
                elif source_type == line_event_source_type.ROOM:
                    return self.profile_room(line_api_wrapper.source_channel_id(src), uid)
                else:
                    raise ValueError('Instance not defined.')
        except exceptions.LineBotApiError as ex:
            if ex.status_code == 404:
                return None

    def profile_name(self, uid, src=None):
        """Raise UserProfileNotFoundError if user name is unreachable."""
        prof = self.profile(uid, src)
        if prof is None:
            raise UserProfileNotFoundError()
        else:
            return prof.display_name

    def profile_group(self, gid, uid):
        try:
            return self._line_api.get_group_member_profile(gid, uid)
        except exceptions.LineBotApiError as ex:
            if ex.status_code == 404:
                raise UserProfileNotFoundError()
            else:
                raise ex

    def profile_room(self, rid, uid):
        try:
            return self._line_api.get_room_member_profile(rid, uid)
        except exceptions.LineBotApiError as ex:
            if ex.status_code == 404:
                raise UserProfileNotFoundError()
            else:
                raise ex

    def profile_friend_list(self, uid):
        try:
            return self._line_api.get_profile(uid)
        except exceptions.LineBotApiError as ex:
            if ex.status_code == 404:
                raise UserProfileNotFoundError()
            else:
                raise ex

    def get_content(self, msg_id):
        return self._line_api.get_message_content(msg_id)

    def reply_message(self, reply_token, msgs):
        self._line_api.reply_message(reply_token, msgs)

    def reply_message_text(self, reply_token, msgs):
        if isinstance(msgs, (str, unicode)):
            msgs = [msgs]
        self._line_api.reply_message(reply_token, [line_api_wrapper.wrap_text_message(msg, self._webpage_generator) for msg in msgs])

    @staticmethod
    def source_channel_id(event_source):
        return event_source.sender_id
    
    @staticmethod
    def source_user_id(event_source):
        return event_source.user_id
    
    @staticmethod
    def is_valid_user_id(uid):
        return uid is not None and len(uid) == 33 and uid.startswith('U')
    
    @staticmethod
    def is_valid_room_group_id(gid, allow_public=False, allow_global=False):
        return gid is not None and (len(gid) == 33 and (gid.startswith('C') or gid.startswith('R')) or (allow_public and gid == db.word_dict_global.CODE_OF_PUBLIC_GROUP) or (allow_global and gid == db.group_dict_manager.CODE_OF_GLOBAL_RANGE))
    
    @staticmethod
    def determine_id_type(cid):
        if cid.startswith('C'):
            return line_event_source_type.GROUP
        elif cid.startswith('R'):
            return line_event_source_type.ROOM
        elif cid.startswith('U'):
            return line_event_source_type.USER

    @staticmethod
    def wrap_template_with_action(data_dict, alt_text_unicode, title_unicode):
        """
        data_dict should follow the format below, and the length of dict must less than or equals to 15. Result may be unexpected if the format is invalid.
            {label: message}

        title will display as "{title} {index}", index is the index of carousel.
        title should be str type.

        Return TemplateSendMessage.
        """
        MAX_ACTIONS = 15
        MAX_ACTIONS_IN_CAROUSEL = 3
        MAX_LABEL_TEXT_LENGTH = 17

        data_dict = [(key, value) for key, value in data_dict.iteritems()]

        length_action_dict = len(data_dict)

        if length_action_dict > MAX_ACTIONS:
            raise ValueError(error.error.main.miscellaneous(u'Length of data dict must less than or equals to {}.'.format(MAX_ACTIONS)))

        column_list = []
        for i in range(0, length_action_dict, MAX_ACTIONS_IN_CAROUSEL):
            d = data_dict[i : i + MAX_ACTIONS_IN_CAROUSEL]

            if i >= MAX_ACTIONS_IN_CAROUSEL:
                while len(d) < MAX_ACTIONS_IN_CAROUSEL:
                    d.append((u'(空)', u'小水母'))

            explain_text = u'#{} ~ {}'.format(i + 1, i + MAX_ACTIONS_IN_CAROUSEL)
            action_list = [MessageTemplateAction(label=simplified_string(repr_text, MAX_LABEL_TEXT_LENGTH), text=action_text) for repr_text, action_text in d]

            column_list.append(CarouselColumn(text=explain_text, title=title_unicode, actions=action_list))

        return TemplateSendMessage(alt_text=alt_text_unicode, template=CarouselTemplate(columns=column_list))
    
    @staticmethod
    def wrap_image_message(picture_url, preview_url=None):
        """
        Return ImageSendMessage.
        """
        MAX_URL_CHARACTER_LENGTH = 1000 # Ref: https://developers.line.me/en/docs/messaging-api/reference/#image

        if len(picture_url) > MAX_URL_CHARACTER_LENGTH:
            raise ValueError(error.error.main.miscellaneous(u'String length of picture_url must less than or equals to {}.'.format(MAX_URL_CHARACTER_LENGTH)))

        if preview_url is not None and len(preview_url) > MAX_URL_CHARACTER_LENGTH:
            raise ValueError(error.error.main.miscellaneous(u'String length of preview_url must less than or equals to {}.'.format(MAX_URL_CHARACTER_LENGTH)))

        if preview_url is None:
            preview_url = picture_url

        return ImageSendMessage(original_content_url=picture_url, preview_image_url=preview_url)

    @staticmethod
    def wrap_text_message(text, webpage_gen):
        """
        Return TextSendMessage.
        """
        MAX_CHARACTER_LENGTH = 2000 # Ref: https://developers.line.me/en/docs/messaging-api/reference/#text

        if len(text) > MAX_CHARACTER_LENGTH:
            text = error.error.main.text_length_too_long(webpage_gen.rec_webpage(text, db.webpage_content_type.TEXT))

        return TextSendMessage(text=text)

    @staticmethod
    def introduction_template():
        buttons_template = ButtonsTemplate(title=u'機器人簡介', text='歡迎使用小水母！', 
                actions=[URITemplateAction(label=u'點此開啟使用說明', uri='https://sites.google.com/view/jellybot'),
                         URITemplateAction(label=u'點此導向問題回報網址', uri='https://github.com/RaenonX/LineBot/issues'),
                         URITemplateAction(label=u'群組管理權限申請單', uri='https://goo.gl/forms/91RWtMKZNMvGrpk32')])
        return TemplateSendMessage(alt_text=u'機器人簡介', template=buttons_template)

class imgur_api_wrapper(object):
    def __init__(self, imgur_api):
        self._imgur_api = imgur_api
    
    def upload(self, content, image_name):
        config = {
	    	'album': None,
	    	'name':  image_name,
	    	'title': image_name,
	    	'description': 'Automatically uploaded by line bot.(LINE ID: @fcb0332q)'
	    }
        return self._imgur_api.upload(content, config=config, anon=False)['link']

    @property
    def user_limit(self):
        return int(self._imgur_api.credits['UserLimit'])

    @property
    def user_remaining(self):
        return int(self._imgur_api.credits['UserRemaining'])

    @property
    def user_reset(self):
        """UNIX EPOCH @UTC <Type 'datetime'>"""
        return datetime.fromtimestamp(self._imgur_api.credits['UserReset'])

    @property
    def client_limit(self):
        return int(self._imgur_api.credits['ClientLimit'])

    @property
    def client_remaining(self):
        return int(self._imgur_api.credits['ClientRemaining'])

    def get_status_string(self, ip_addr=None):
        try:
            text = u''
            if ip_addr is not None:
                text += u'連結IP: {}\n'.format(ip_addr)
                text += u'IP可用額度: {} ({:.2%})\n'.format(self.user_remaining, float(self.user_remaining) / float(self.user_limit))
                text += u'IP上限額度: {}\n'.format(self.user_limit)
                text += u'IP積分重設時間: {} (UTC+8)\n\n'.format((float(self.user_reset) + timedelta(hours=9)).strftime('%Y-%m-%d %H:%M:%S'))

            text += u'目前API擁有額度: {} ({:.2%})\n'.format(self.client_remaining, float(self.client_remaining) / float(self.client_limit))
            text += u'今日API上限額度: {}'.format(self.client_limit)
        except (ValueError, TypeError):
            import json
            text = json.dumps(self._imgur_api.credits)

        return text

class oxford_api_wrapper(object):
    def __init__(self, language):
        """
        Set environment variable "OXFORD_ID", "OXFORD_KEY" as presented api id and api key.
        """
        self._language = language
        self._id = os.getenv('OXFORD_ID', None)
        self._key = os.getenv('OXFORD_KEY', None)
        self._url = 'https://od-api.oxforddictionaries.com:443/api/v1/entries/{}/'.format(self._language)
        self._enabled = False if self._id is None or self._key is None else True

    def get_data_json(self, word):
        if self._enabled:
            url = self._url + word.lower()
            r = requests.get(url, headers = {'app_id': self._id, 'app_key': self._key})
            status_code = r.status_code

            if status_code != requests.codes.ok:
                return status_code
            else:
                return r.json()
        else:
            raise RuntimeError(error.error.main.miscellaneous(u'Oxford dictionary not enabled.').encode('utf-8'))

    @property
    def enabled(self):
        return self._enabled

    @enabled.setter
    def enabled(self, value):
        self._enabled = value

def left_alphabet(s):
    return filter(unicode.isalpha, unicode(s))

def string_can_be_int(*args):
    try:
        [int(i) for i in args]
        return True
    except ValueError:
        return False

def string_can_be_float(s):
    try:
        float(s)
        return True
    except ValueError:
        return False

def simplified_string(s, max_length=8):
    """max_length excludes ..."""
    s = s.replace('\n', '\\n')
    if len(s) > (max_length + 3):
        s = s[:max_length] + '...'
    return s


class UserProfileNotFoundError(Exception):
    def __init__(self, *args):
        super(UserProfileNotFoundError, self).__init__(*args)
    

