# -*- coding: utf-8 -*-

import os, sys
from datetime import datetime, timedelta
from collections import defaultdict
from linebot import exceptions
import hashlib
import operator
import traceback
import error

from linebot.models import (
    SourceGroup, SourceRoom, SourceUser,
    TextSendMessage, ImageSendMessage, TemplateSendMessage,
    CarouselTemplate, ButtonsTemplate, CarouselColumn, MessageTemplateAction, URITemplateAction
)

import db
import ext

class system_data(object):
    def __init__(self):
        self._boot_up = datetime.now() + timedelta(hours=8)
        self._last_sticker = defaultdict(str)
        self._last_pic_sha = defaultdict(str)
        self._last_pair = defaultdict(str)

    def set_last_sticker(self, cid, stk_id):
        self._last_sticker[cid] = stk_id

    def get_last_sticker(self, cid):
        return self._last_sticker.get(cid)

    def set_last_pic_sha(self, cid, sha):
        self._last_pic_sha[cid] = sha

    def get_last_pic_sha(self, cid):
        return self._last_pic_sha.get(cid)

    def set_last_pair(self, cid, pair_id):
        self._last_pair[cid] = pair_id

    def get_last_pair(self, cid):
        return self._last_pair.get(cid)

    @property
    def boot_up(self):
        return self._boot_up

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
            if src is None:
                return self._line_api.get_profile(uid)
            else:
                source_type = line_event_source_type.determine(src)
                if source_type == line_event_source_type.USER:
                    return self.profile(uid, None)
                elif source_type == line_event_source_type.GROUP:
                    return self.profile_group(line_api_wrapper.source_channel_id(src), uid)
                elif source_type == line_event_source_type.ROOM:
                    return self.profile_room(line_api_wrapper.source_channel_id(src), uid)
                else:
                    raise ValueError('Instance not defined.')
        except exceptions.LineBotApiError as ex:
            if ex.status_code == 404:
                return None

    def profile_name(self, uid):
        """Raise UserProfileNotFoundError if user name is unreachable."""
        prof = self.profile(uid)
        if prof is None:
            raise UserProfileNotFoundError()
        else:
            return prof.display_name

    def profile_group(self, gid, uid):
        try:
            return self._line_api.get_group_member_profile(gid, uid)
        except exceptions.LineBotApiError as ex:
            if ex.status_code == 404:
                return None

    def profile_room(self, rid, uid):
        try:
            return self._line_api.get_room_member_profile(rid, uid)
        except exceptions.LineBotApiError as ex:
            if ex.status_code == 404:
                return None

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
    def is_valid_room_group_id(gid):
        return gid is not None and len(gid) == 33 and (gid.startswith('C') or gid.startswith('R'))

    @staticmethod
    def wrap_template_with_action(data_dict, alt_text, title):
        """
        data_dict should follow the format below, and the length of dict must less than or equals to 15. Result may be unexpected if the format is invalid.

        title will display as "{title} {index}", index is the index of carousel.
        title should be str type.

        Return TemplateSendMessage.
        """
        MAX_ACTIONS = 15
        MAX_ACTIONS_IN_CAROUSEL = 3
        if isinstance(title, str):
            title = title.decode('utf-8')

        data_dict = [(key, value) for key, value in data_dict.iteritems()]

        length_action_dict = len(data_dict)

        if length_action_dict > MAX_ACTIONS:
            raise ValueError(error.error.main.miscellaneous(u'Length of data dict must less than or equals to {}.'.format(MAX_ACTIONS)))

        column_list = []
        for i in range(0, length_action_dict, MAX_ACTIONS_IN_CAROUSEL):
            d = data_dict[i:MAX_ACTIONS_IN_CAROUSEL]

            title = u'{} {}'.format(title, i / MAX_ACTIONS_IN_CAROUSEL + 1)
            explain_text = u'#{} ~ {}'.format(i + 1, i + MAX_ACTIONS_IN_CAROUSEL)
            action_list = [MessageTemplateAction(label=repr_text, text=action_text) for repr_text, action_text in d]

            column_list.append(CarouselColumn(text=explain_text, title=title, actions=action_list))

        return TemplateSendMessage(alt_text='相關回覆組快捷樣板.\n{}'.format(alt_text), template=CarouselTemplate(columns=column_list))
    
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
                text += u'IP積分重設時間: {} (UTC+8)\n\n'.format((self.user_reset + timedelta(hours=9)).strftime('%Y-%m-%d %H:%M:%S'))

            text += u'目前API擁有額度: {} ({:.2%})\n'.format(self.client_remaining, float(self.client_remaining) / float(self.client_limit))
            text += u'今日API上限額度: {}'.format(self.client_limit)
        except ValueError:
            import json
            text = json.dump(self._imgur_api.credits)

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

class UserProfileNotFoundError(Exception):
    def __init__(self, *args):
        super(UserProfileNotFoundError, self).__init__(*args)
    

