# -*- coding: utf-8 -*-

import os, sys
import error

import urlparse
import psycopg2
from sqlalchemy.exc import IntegrityError
import hashlib
from enum import Enum, IntEnum
import pymongo
import tool

from bot.commands import permission
from .base import db_base, dict_like_mapping
from .misc import FormattedStringResult

class EnumWithName(Enum):
    def __new__(cls, value, name):
        member = object.__new__(cls)
        member._value_ = value
        member._name = name
        return member

    def __int__(self):
        return self.value

    def __str__(self):
        return self._name

    def __unicode__(self):
        return unicode(self._name.decode('utf-8'))

############
### ENUM ###
############

class config_type(EnumWithName):
    SILENCE = 0, '全靜音'
    SYS_ONLY = 1, '限指令'
    GROUP_DATABASE_ONLY = 2, '限群組庫'
    ALL = 3, '無限制'

    def __gt__(a, b):
        return int(a) > int(b)

    def __ge__(a, b):
        return int(a) >= int(b)

    def __ne__(a, b):
        return int(a) != int(b)

    def __eq__(a, b):
        return int(a) == int(b)

    def __le__(a, b):
        return int(a) <= int(b)

    def __lt__(a, b):
        return int(a) < int(b)

class msg_type(EnumWithName):
    UNKNOWN = -1, '不明'
    TEXT = 0, '文字'
    STICKER = 1, '貼圖'
    PICTURE = 2, '圖片'
    VIDEO = 3, '影片'
    AUDIO = 4, '音訊'
    LOCATION = 5, '位置'

###############################
### GROUP MANAGING INSTANCE ###
###############################

class group_manager(db_base):
    ID_LENGTH = 33
    GROUP_DB_NAME = 'group'

    def __init__(self, mongo_db_uri):
        super(group_manager, self).__init__(mongo_db_uri, group_manager.GROUP_DB_NAME, self.__class__.__name__, False, [group_data.GROUP_ID])

        self._activator = group_activator(mongo_db_uri)
        self._permission_manager = user_data_manager(mongo_db_uri)

        self._cache_config = {}
        self._cache_permission = {}

        self._ADMIN_UID = os.getenv('ADMIN_UID', None)
        if self._ADMIN_UID is None:
            print 'Specify bot admin uid as environment variable "ADMIN_UID".'
            sys.exit(1)

    # utilities - misc
    def new_data(self, gid, config=config_type.GROUP_DATABASE_ONLY):
        """Return result none if creation failed, else return token to activate accepting public database if config is not set to public."""
        if len(gid) != group_manager.ID_LENGTH:
            return
        else:
            try:
                data = group_data.init_by_field(gid, config)
                self.insert_one(data)
                self._permission_manager.new_data(gid, self._ADMIN_UID, self._ADMIN_UID, permission.BOT_ADMIN)
                return self._activator.new_data(gid)
            except pymongo.errors.DuplicateKeyError as ex:
                return

    def activate(self, gid, token):
        """Return boolean to indicate activation result."""
        group_activated = self._activator.del_data(gid, token)
        if group_activated:
            self.find_one_and_update({ group_data.GROUP_ID: gid }, { '$set': { group_data.CONFIG_TYPE: config_type.ALL } })

        return group_activated
            
    # utilities - group settings related
    def get_group_by_id(self, gid, including_member_data=False):
        """Return None if nothing found"""
        if len(gid) != group_manager.ID_LENGTH:
            return None
        
        try:
            result = self.find_one({ group_data.GROUP_ID: gid })
            if result is None:
                return None
            else:
                g_data = group_data(result)
                if including_member_data:
                    admins_list = self._permission_manager.get_data_by_permission(gid, permission.ADMIN)
                    mods_list = self._permission_manager.get_data_by_permission(gid, permission.MODERATOR)
                    restricts_list = self._permission_manager.get_data_by_permission(gid, permission.RESTRICTED)
                    g_data.set_members_data(admins_list, mods_list, restricts_list)

                return g_data
        except pymongo.errors.PyMongoError as ex:
            print ex
            raise ex

    def set_config_type(self, gid, config_type, uid):
        """Return true if success, else return error message in string."""
        if len(gid) != group_manager.ID_LENGTH:
            return None

        setup_result = self.find_one_and_update({
            { '$or': [{ group_data.SPECIAL_USER + '.' + group_data.ADMINS: uid },
                      { group_data.SPECIAL_USER + '.' + group_data.MODERATORS: { '$elemMatch': { '$eq': [uid] } } }] },
                      { group_data.GROUP_ID: gid }},
            { '$set': { group_data.CONFIG_TYPE: config_type } }, None, None, False, pymongo.ReturnDocument.AFTER)

        if setup_result is not None:
            return True
        else:
            return error.error.main.incorrect_password_or_insufficient_permission()
        
    # utilities - group permission related
    def set_permission(self, gid, setter_uid, target_uid, permission_lv):
        """Raise InsufficientPermissionError if action is not allowed."""
        self._permission_manager.set_permission(gid, setter_uid, target_uid, permission_lv)

    def delete_permission(self, gid, setter_uid, target_uid):
        """Raise InsufficientPermissionError if action is not allowed."""
        self._permission_manager.del_data(gid, setter_uid, target_uid)

    def get_group_config_type(self, gid):
        cfg_type = self._get_cache_config(gid)
        if cfg_type is not None:
            return cfg_type
        else:
            group = self.get_group_by_id(gid)
            if group is not None:
                cfg_type = group.config_type
                self._set_cache_config(gid, group.config_type)
                return cfg_type
            else:
                raise ValueError(error.error.main.miscellaneous(u'群組資料未登錄。').encode('utf-8'))

    def get_user_permission(self, gid, uid):
        permission = self._get_cache_config(gid. uid)
        if permission is not None:
            return permission
        else:
            user_data = self._permission_manager.get_user_data(gid, uid)
            if user_data is not None:
                permission = user_data.permission_level
            else:
                permission = permission.USER
            self._set_cache_permission(gid, uid, permission)
            return permission
        
    # utilities - activity tracking
    def log_message_activity(self, chat_instance_id, rcv_type_enum, rep_type_enum=None, rcv_count=1, rep_count=1):
        if len(chat_instance_id) != group_manager.ID_LENGTH:
            raise ValueError(error.error.main.incorrect_thing_with_correct_format(u'頻道ID', u'33字元長度', chat_instance_id))
        else:
            inc_dict = {}
            if rep_type_enum is not None:
                inc_dict[group_data.MESSAGE_RECORDS + '.' + msg_stats_data.REPLY + '.' + str(rep_type_enum)] = rep_count
                triggered = True
            else:
                triggered = False

            inc_dict[group_data.MESSAGE_RECORDS + '.' + msg_stats_data.RECEIVE + '.' + str(rcv_type_enum) + '.' + (msg_stats_pair.TRIGGERED if triggered else msg_stats_pair.NOT_TRIGGERED)] = rcv_count 

            result = self.update_one({ group_data.GROUP_ID: chat_instance_id },
                                     { '$inc': inc_dict }, False)
            if result.matched_count < 1:
                raise ValueError(error.error.main.miscellaneous(u'Group data not registered.').encode('utf-8'))

    # statistics - message track
    def message_sum(self):
        group_dict = { '_id': None }
        for type_enum in list(msg_type):
            for k in (msg_stats_pair.TRIGGERED, msg_stats_pair.NOT_TRIGGERED):
                group_dict[msg_stats_data.RECEIVE + '_' + str(type_enum) + '_' + k] = { '$sum': '$' + group_data.MESSAGE_RECORDS + '.' + msg_stats_data.RECEIVE + '.' + str(type_enum) + '.' + k }
            group_dict[msg_stats_data.REPLY + '_' + str(type_enum)] = { '$sum': '$' + group_data.MESSAGE_RECORDS + '.' + msg_stats_data.REPLY + '.' + str(type_enum) }

        project_dict = {
            msg_stats_data.RECEIVE: { str(type_enum): { k: '$' + msg_stats_data.RECEIVE + '_' + str(type_enum) + '_' + k for k in (msg_stats_pair.TRIGGERED, msg_stats_pair.NOT_TRIGGERED) } for type_enum in list(msg_type) },
            msg_stats_data.REPLY: { str(type_enum): '$' + msg_stats_data.REPLY + '_' + str(type_enum) for type_enum in list(msg_type) }
        }

        aggr_result = list(self.aggregate([
            { '$group': group_dict },
            { '$project': project_dict }
        ]))
        if len(aggr_result) > 0:
            return msg_stats_data(aggr_result[0])
        else:
            return msg_stats_data.empty_init()
        
    def order_by_recorded_msg_count(self, limit=None):
        """Sort by COUNT OF RECEIVED MESSAGES"""

        RECEIVED_MESSAGES = 'rcv_sum'

        aggr_pipeline = [
            { '$addFields': { group_data.MESSAGE_RECORDS + '.' + RECEIVED_MESSAGES: { '$sum': [ '$' + group_data.MESSAGE_RECORDS + '.' + msg_stats_data.RECEIVE + '.' + str(type_enum) + '.' + k for k in (msg_stats_pair.TRIGGERED, msg_stats_pair.NOT_TRIGGERED) for type_enum in list(msg_type) ] },
                              group_data.MESSAGE_RECORDS + '.' + msg_stats_data.CHAT_INSTANCE_ID: '$' + group_data.GROUP_ID} }, 
            { '$replaceRoot': { 'newRoot': '$' + group_data.MESSAGE_RECORDS } },
            { '$sort': { RECEIVED_MESSAGES: pymongo.DESCENDING } }
        ]

        if limit is not None and isinstance(limit, (int, long)):
            aggr_pipeline.append({ '$limit': limit })

        aggr_result = list(self.aggregate(aggr_pipeline))
        if len(aggr_result) > 0:
            return [msg_stats_data(data) for data in aggr_result]
        else:
            return []

    # private
    def _set_cache_config(self, gid, cfg_type):
        self._cache_config[gid] = cfg_type
    
    def _get_cache_config(self, gid):
        """Return none if key not exists"""
        return self._cache_config.get(gid, None)

    def _set_cache_permission(self, gid, uid, permission):
        group_permission_data = self._cache_permission.get(gid, None)
        if group_permission_data is None:
            self._cache_permission[gid] = { uid: permission }
        else:
            self._cache_permission[gid][uid] = permission
    
    def _get_cache_permission(self, gid, uid):
        """Return none if key not exists"""
        group_permission_data = self._cache_permission.get(gid, None)
        if group_permission_data is None:
            return None
        else:
            return group_permission_data.get(uid, None)
        
    @staticmethod
    def message_track_string(group_data_or_list, limit=None, append_first_list=None, no_result_text=None):
        if group_data_or_list is not None and len(group_data_or_list) > 0:
            if not isinstance(group_data_or_list, list):
                group_data_or_list = [group_data_or_list]

            def format_string(data):
                data = group_data(data)
                gid = data.group_id

                if group_manager is not None:
                    if gid.startswith('U'):
                        activation_status = u'私訊頻道'
                    else:
                        activation_status = unicode(data.config_type)
                else:
                    activation_status = u'N/A'

                text = u'頻道ID: {} 【{}】'.format(gid, activation_status)
                text += u'\n收到:\n{}'.format('\n'.join(u'{} - {}(觸發{})'.format(type_string, pair.not_triggered, pair.triggered) for type_string, pair in data.message_track_record.received.iteritems()))
                text += u'\n回覆:\n{}'.format('\n'.join(u'{} - {}(觸發{})'.format(type_string, pair.not_triggered, pair.triggered) for type_string, pair in data.message_track_record.reply.iteritems()))
                return text

            return FormattedStringResult.init_by_field(group_data_or_list, format_string, limit, append_first_list, no_result_text)
        else:
            err = error.main.miscellaneous(u'沒有輸入群組資料。')
            return FormattedStringResult([err], [err])

class group_data(dict_like_mapping):
    """
    {
        group_id: STRING - INDEX,
        config_type: CONFIG_TYPE
        message_records: {
            receive: {
                (MSG_TYPE): MSG_STATS_PAIR
                ...
                ...
            },
            reply: {
                (MSG_TYPE): INTEGER
                ...
                ...
            }
        },
        ===NO DATA ON INIT===
        mem: {
            admin: [ STRING, STRING, STRING... ],
            moderators: [ STRING, STRING, STRING... ],
            restricts: [ STRING, STRING, STRING... ]
        }
    }
    """
    GROUP_ID = 'group_id'

    SPECIAL_USER = 'mem'
    ADMINS = 'admins'
    MODERATORS = 'mods'
    RESTRICTS = 'rst'

    CONFIG_TYPE = 'config_type'

    MESSAGE_RECORDS = 'msg_rec'

    @staticmethod
    def init_by_field(gid, config_type):
        if mod_user_data_list is None:
            mod_user_data_list = []

        init_dict = {
            group_data.GROUP_ID: gid,
            group_data.CONFIG_TYPE: int(config_type),
            group_data.MESSAGE_RECORDS: msg_stats_data.empty_init()
        }

        return group_data(init_dict)

    def __init__(self, org_dict):
        if org_dict is not None:
            if not all(k in org_dict for k in (group_data.GROUP_ID, group_data.SPECIAL_USER, group_data.CONFIG_TYPE)):
                raise ValueError('Invalid group data dictionary.')
            if org_dict[group_data.SPECIAL_USER].get(group_data.ADMINS, None) is None:
                raise ValueError('Admin data is null in group data dictionary.')

            org_dict[group_data.MESSAGE_RECORDS] = msg_stats_data(org_dict[group_data.MESSAGE_RECORDS])
        else:
            raise ValueError('Dictionary is None.')

        self._members_data_set = False
        return super(group_data, self).__init__(org_dict)

    def set_members_data(self, admins_list, mods_list, restricts_list):
        self._members_data_set = True
        self[group_data.SPECIAL_USER][group_data.ADMINS] = admins_list
        self[group_data.SPECIAL_USER][group_data.MODERATORS] = mods_list
        self[group_data.SPECIAL_USER][group_data.RESTRICTS] = restricts_list

    @property
    def has_member_data(self):
        return self._members_data_set

    def get_status_string(self):
        message_track_string = group_manager.message_track_string(self).full
        admins_string = self.get_group_members_string()

        text = u'房間/群組ID: {}\n'.format(self.group_id)
        text += u'自動回覆設定: {}\n'.format(unicode(self.config_type))
        text += u'【訊息量紀錄】\n{}\n'.format(message_track_string)
        text += u'【管理員列表】\n{}'.format(admins_string)

        return text

    def get_group_members_string(self):
        if not self._members_data_set:
            return error.error.main.miscellaneous(u'未寫入群組非一般用戶使用者資料。')
        text = u'管理員:\n{}'.format(self[group_data.SPECIAL_USER][group_data.ADMINS])
        text += u'副管:\n{}'.format('\n'.join(self[group_data.SPECIAL_USER][group_data.MODERATORS]))
        text += u'限制用戶:\n{}'.format('\n'.join(self[group_data.SPECIAL_USER][group_data.RESTRICTS]))

        return text

    @property
    def group_id(self):
        return self[group_data.GROUP_ID]

    @property
    def config_type(self):
        return config_type(self[group_data.CONFIG_TYPE])
        
    @property
    def message_track_record(self):
        return self[group_data.MESSAGE_RECORDS]

########################
### TOKEN ACTIVATION ###
########################

class group_activator(db_base):
    ID_LENGTH = 33
    ACTIVATE_TOKEN_LENGTH = 40
    DATA_EXPIRE_SECS = 24 * 60 * 60

    def __init__(self, mongo_db_uri):
        super(group_activator, self).__init__(mongo_db_uri, group_manager.GROUP_DB_NAME, self.__class__.__name__, False, [group_data.GROUP_ID])
        self.create_index([(group_activation_data.TOKEN, pymongo.DESCENDING)], expireAfterSeconds=group_activator.DATA_EXPIRE_SECS)

    def new_data(self, group_id):
        """Return token string."""
        new_token = tool.random_drawer.generate_random_string(group_activator.ACTIVATE_TOKEN_LENGTH)
        self.insert_one(group_activation_data.init_by_field(group_id, new_token))
        return new_token

    def del_data(self, group_id, token):
        """Return data deleted count > 0"""
        return self.delete_many({ group_data.GROUP_ID: group_id, group_activation_data.TOKEN: token }).deleted_count > 0

class group_activation_data(dict_like_mapping):
    """
    {
        group_id: STRING - INDEX,
        token: STRING
    }
    """
    TOKEN = 'token'

    @staticmethod
    def init_by_field(group_id, token):
        init_dict = {
            group_data.GROUP_ID: group_id,
            group_activation_data.TOKEN: token
        }
        
    def __init__(self, org_dict):
        if not all(k in org_dict for k in (group_data.GROUP_ID, group_activation_data.TOKEN)):
            raise ValueError('Incomplete user data.')
        
        super(group_activation_data, self).__init__(org_dict)

    @property
    def token(self):
        return self[group_activation_data.TOKEN]

    @property
    def group_id(self):
        return self[group_activation_data.GROUP_ID]

##########################
### MESSAGE STATISTICS ###
##########################

class msg_stats_data(dict_like_mapping):
    """
    {
        receive: {
            (MSG_TYPE): MSG_STATS_PAIR
            ...
            ...
        },
        reply: {
            (MSG_TYPE): INTEGER
            ...
            ...
        }
    }
    """
    RECEIVE = 'rcv'
    REPLY = 'rpl'
    CHAT_INSTANCE_ID = 'cid'

    @staticmethod
    def empty_init():
        init_dict = {
            msg_stats_data.RECEIVE: {str(msg_type_iter): msg_stats_pair.empty_init() for msg_type_iter in list(msg_type)},
            msg_stats_data.REPLY: {str(msg_type_iter): 0 for msg_type_iter in list(msg_type)}
        }

        return msg_stats_data(init_dict)

    def __init__(self, org_dict):
        if org_dict is not None:
            key_check_list = [msg_stats_data.RECEIVE, msg_stats_data.REPLY]
            
            if not msg_stats_data.RECEIVE in org_dict:
                org_dict[msg_stats_data.RECEIVE] = {str(msg_type_iter): msg_stats_pair.empty_init() for msg_type_iter in list(msg_type)}

            if not msg_stats_data.REPLY in org_dict:
                org_dict[msg_stats_data.REPLY] = {str(msg_type_iter): 0 for msg_type_iter in list(msg_type)}
        else:
            raise ValueError('Dictionary is none.')

        return super(msg_stats_data, self).__init__(org_dict)

    @property
    def reply(self):
        return self[msg_stats_data.REPLY]
        
    @property
    def received(self):
        return { key: msg_stats_pair(data) for key, data in self[msg_stats_data.RECEIVE].iteritems() } 
        
    @property
    def chat_instance_id(self):
        return self.get(msg_stats_data.CHAT_INSTANCE_ID, None)

    def get_string(self):
        text = u'\n收到:\n{}'.format('\n'.join(u'{} - {} (觸發{})'.format(type_string, pair.not_triggered, pair.triggered) for type_string, pair in self.received.iteritems()))
        text += u'\n回覆:\n{}'.format('\n'.join(u'{} - {}'.format(type_string, count) for type_string, count in self.reply.iteritems()))
        return text

class msg_stats_pair(dict_like_mapping):
    """
    {
        triggered: INTEGER,
        not_triggered: INTEGER
    }
    """
    TRIGGERED = 'trig'
    NOT_TRIGGERED = 'xtrig'

    @staticmethod
    def empty_init():
        init_dict = {
            msg_stats_pair.TRIGGERED: 0, 
            msg_stats_pair.NOT_TRIGGERED: 0
        }
        return msg_stats_pair(init_dict)

    def __init__(self, org_dict):
        if org_dict is not None:
            if all(k in org_dict for k in (msg_stats_pair.TRIGGERED, msg_stats_pair.NOT_TRIGGERED)):
                pass
            else:
                raise ValueError('Incomplete data.')
        else:
            raise ValueError('Dictionary is none.')

        super(msg_stats_pair, self).__init__(org_dict)

    @property
    def triggered(self):
        return self[msg_stats_pair.TRIGGERED]

    @property
    def not_triggered(self):
        return self[msg_stats_pair.NOT_TRIGGERED]

##########################
### PERMISSION RELATED ###
##########################

class user_data_manager(db_base):
    COLLECTION_NAME = 'user_data'

    def __init__(self, mongo_db_uri):
        super(user_data_manager, self).__init__(mongo_db_uri, SYSTEM_DATABASE_NAME, user_data_manager.COLLECTION_NAME, False, [user_data.USER_ID])
        self._ADMIN_UID = os.getenv('ADMIN_UID', None)
        if self._ADMIN_UID is None:
            print 'Specify bot admin uid as environment variable "ADMIN_UID".'
            sys.exit(1)
        self._set_cache()

    def new_data(self, group_id, setter_uid, target_uid, target_permission_lv):
        """
        Set setter_uid and target_uid to exact same to bypass permission check.

        Raise InsufficientPermissionError if action is not allowed.
        """
        if setter_uid == target_uid and self._check_action_is_allowed(setter_uid, group_id, target_permission_lv):
            self.insert_one(user_data.init_by_field(target_uid, group_id, target_permission_lv))
            self._set_cache()
        else:
            raise InsufficientPermissionError()

    def del_data(self, group_id, setter_uid, target_uid):
        """
        Raise InsufficientPermissionError if action is not allowed.
        """
        target_data = self.get_user_data(group_id, target_uid)
        if target_data is not None:
            target_permission_lv = target_data.permission_level
        else:
            target_permission_lv = permission.USER

        if self._check_action_is_allowed(setter_uid, group_id, target_permission_lv):
            self.delete_one({ user_data.USER_ID: target_uid, user_data.GROUP: group_id })
            self._set_cache()
        else:
            raise InsufficientPermissionError()

    def set_permission(self, group_id, setter_uid, target_uid, new_lv):
        """Raise InsufficientPermissionError if action is not allowed."""
        if self._check_action_is_allowed(setter_uid, group_id, new_lv):
            self.update_one({ user_data.USER_ID: target_uid, user_data.GROUP: group_id },
                            { user_data.PERMISSION_LEVEL: new_lv }, True)
            self._set_cache()
        else:
            raise InsufficientPermissionError()

    def get_user_data(self, group_id, uid):
        """Return None if nothing found."""
        result = next((item for item in self._cache if item[user_data.USER_ID] == uid and item[user_data.GROUP] == group_id), None) 
        if result is None:
            return None
        else:
            return user_data(result)

    def get_data_by_permission(self, group_id, permission_lv):
        return list(user_data(item) for item in self._cache if item.permission_level == permission_lv and item.group == group_id)

    def _check_action_is_allowed(self, uid, group_id, action_permission):
        if uid == self._ADMIN_UID:
            return True

        u_data = next((item for item in self._cache if item[user_data.USER_ID] == uid and item[user_data.GROUP] == group_id), None) 
        if u_data is not None:
            u_data = user_data(u_data)

            # Need moderator+ to set restricted
            if action_permission < permission.USER:
                return u_data.permission_level >= permission.MODERATOR
            else:
                return u_data.permission_level >= action_permission
        else:
            return False

    def _set_cache():
        self._cache = [user_data(data) for data in self.find()]

class user_data(dict_like_mapping):
    """
    {
        user_id: STRING - INDEX,
        group: STRING,
        permission_level: INTEGER
    }
    """
    USER_ID = 'uid'
    GROUP = 'grp'
    PERMISSION_LEVEL = 'perm'

    @staticmethod
    def init_by_field(uid, group_id, permission_lv):
        init_dict = {
            user_data.USER_ID: uid,
            user_data.GROUP: group_id,
            user_data.PERMISSION_LEVEL: permission_lv
        }
        return user_data(init_dict)

    def __init__(self, org_dict):
        if org_dict is not None:
            if not all(k in org_dict for k in (user_data.USER_ID, user_data.PERMISSION_LEVEL, user_data.GROUP)):
                raise ValueError(u'Incomplete user data.')
        else:
            raise ValueError(u'Dict is none.')

        return super(user_data, self).__init__(org_dict)

    @property
    def user_id(self):
        return self[user_data.USER_ID]

    @property
    def permission_level(self):
        return self[user_data.PERMISSION_LEVEL]

    @property
    def group(self):
        return self[user_data.GROUP]

class InsufficientPermissionError(Exception):
    def __init__(self, *args):
        return super(InsufficientPermissionError, self).__init__(*args)