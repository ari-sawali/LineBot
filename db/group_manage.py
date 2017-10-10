# -*- coding: utf-8 -*-

import os, sys
import error

import urlparse
import psycopg2
from sqlalchemy.exc import IntegrityError
import hashlib
import enum
from pymongo.errors import DuplicateKeyError, PyMongoError
from pymongo import ReturnDocument

from .base import db_base, dict_like_mapping

"""
{
    group_id: STRING - INDEX
    admins: {
        admin: { uid: STRING, pw_sha: STRING }
        moderators: [ 
            { uid: STRING, pw_sha: STRING }, { uid: STRING, pw_sha: STRING }...
        ]
    },
    config_type: CONFIG_TYPE
}
"""

class config_type(enum.IntEnum):
    UNKNOWN = -1
    SILENCE = 0
    SYS_ONLY = 1
    GROUP_DATABASE_ONLY = 2
    ALL = 3

class group_manager(db_base):
    ID_LENGTH = 33
    GROUP_DB_NAME = 'group'

    def __init__(self, mongo_client_uri):
        super(group_manager, self).__init__(mongo_client_uri, group_manager.GROUP_DB_NAME, self.__class__.__name__, False, [group_data.GROUP_ID])

    def new_data(self, gid, admin_uid, admin_pw, config=config_type.ALL, pw_is_sha=False):
        if len(admin_uid) != group_manager.ID_LENGTH or len(gid) != group_manager.ID_LENGTH:
            return False
        else:
            try:
                data = group_data.init_by_field(gid, admin_uid, admin_pw, config, pw_is_sha)
                self.insert(data)
                return True
            except DuplicateKeyError as ex:
                return False

    def del_data(self, gid):
        if len(gid) != group_manager.ID_LENGTH:
            return error.error.main.invalid_length(u'群組/房間ID', group_manager.ID_LENGTH)
        else:
            del_count = self.delete_many({ group_data.GROUP_ID: gid }).deleted_count
            if del_count > 0:
                return True
            else:
                return False

    def get_group_by_id(self, gid):
        if len(gid) != group_manager.ID_LENGTH:
            return None
        
        try:
            result = self.find_one({ group_data.GROUP_ID: gid })
            return None if result is None else group_data(result)
        except PyMongoError as ex:
            print ex

    def set_config_type(self, gid, config_type, pw_sha, pw_is_sha=False):
        if len(gid) != group_manager.ID_LENGTH:
            return None

        if not pw_is_sha:
            pw_sha = user_data.generate_sha(pw_sha)

        setup_result = self.find_one_and_update({
            '$and': [
                { '$or': [{ group_data.ALL_ADMIN + '.' + group_data.ADMIN_DATA + '.' + user_data.PW: pw_sha },
                          { group_data.ALL_ADMIN + '.' + group_data.ALL_MODERATORS + '.' + user_data.PW: pw_sha }] },
                { group_data.GROUP_ID: gid }
            ]},
            { '$set': { group_data.CONFIG_TYPE: config_type } }, None, None, False, ReturnDocument.AFTER)

        if setup_result is not None:
            return True
        else:
            return error.error.main.incorrect_password_or_insufficient_permission()

    def change_admin(self, gid, new_admin_uid, org_admin_pw, new_admin_pw, org_pw_is_sha=False, new_pw_is_sha=False):
        if len(new_admin_uid) != group_manager.ID_LENGTH:
            return error.error.main.invalid_length(u'管理員UID', group_manager.ID_LENGTH)
        elif len(gid) != group_manager.ID_LENGTH:
            return error.error.main.invalid_length(u'群組/房間ID 或 管理員UID', group_manager.ID_LENGTH)
        
        if not org_pw_is_sha:
            org_admin_pw = user_data.generate_sha(org_admin_pw)

        if not new_pw_is_sha:
            new_admin_pw = user_data.generate_sha(new_admin_pw)

        setup_result = self.find_one_and_update({
            '$and': [
                { group_data.ALL_ADMIN + '.' + group_data.ADMIN_DATA + '.' + user_data.PW: org_admin_pw },
                { group_data.GROUP_ID: gid }
            ]},
            { '$set': { 
                group_data.ALL_ADMIN + '.' + group_data.ADMIN_DATA: user_data.init_by_field(new_admin_uid, new_admin_pw, new_pw_is_sha)
            } }, None, None, False, ReturnDocument.AFTER)

        if setup_result is not None:
            return True
        else:
            return error.error.main.incorrect_password_or_insufficient_permission()

    def create_moderator(self, gid, admin_pw, mod_uid, mod_pw, admin_pw_is_sha=False, mod_pw_is_sha=False):
        if len(gid) != group_manager.ID_LENGTH:
            return error.error.main.invalid_length(u'群組/房間ID', group_manager.ID_LENGTH)
        elif len(mod_uid) != group_manager.ID_LENGTH:
            return error.error.main.invalid_length(u'管理員UID', group_manager.ID_LENGTH)
        
        if not admin_pw_is_sha:
            admin_pw = user_data.generate_sha(admin_pw)

        setup_result = self.find_one_and_update({
            '$and': [
                { group_data.ALL_ADMIN + '.' + group_data.ADMIN_DATA + '.' + user_data.PW: admin_pw },
                { group_data.GROUP_ID: gid }
            ]},
            { '$push': { 
                group_data.ALL_ADMIN + '.' + group_data.ALL_MODERATORS: user_data.init_by_field(mod_uid, mod_pw, mod_pw_is_sha)
            } }, None, None, False, ReturnDocument.AFTER)
        
        if setup_result is not None:
            return True
        else:
            return error.error.main.incorrect_password_or_insufficient_permission()

    def update_moderator(self, gid, admin_pw, mod_uid, mod_pw, admin_pw_is_sha=False, mod_pw_is_sha=False):
        if len(gid) != group_manager.ID_LENGTH:
            return error.error.main.invalid_length(u'群組/房間ID', group_manager.ID_LENGTH)
        elif len(mod_uid) != group_manager.ID_LENGTH:
            return error.error.main.invalid_length(u'管理員UID', group_manager.ID_LENGTH)
        
        if not admin_pw_is_sha:
            admin_pw = user_data.generate_sha(admin_pw)
            
        if not mod_pw_is_sha:
            mod_pw = user_data.generate_sha(mod_pw)

        setup_result = self.find_one_and_update({
            '$and': [
                { group_data.ALL_ADMIN + '.' + group_data.ADMIN_DATA + '.' + user_data.PW: admin_pw },
                { group_data.GROUP_ID: gid },
                { group_data.ALL_ADMIN + '.' + group_data.ALL_MODERATORS + '.' + user_data.UID : mod_uid }
            ]},
            { '$set': { 
                group_data.ALL_ADMIN + '.' + group_data.ALL_MODERATORS + '.$.' + user_data.PW : mod_pw
            } }, None, None, False, ReturnDocument.AFTER)
        
        if setup_result is not None:
            return True
        else:
            return error.error.main.incorrect_password_or_insufficient_permission()

    def delete_moderator(self, gid, admin_pw, mod_uid, admin_pw_is_sha=False):
        if len(gid) != group_manager.ID_LENGTH:
            return error.error.main.invalid_length(u'群組/房間ID', group_manager.ID_LENGTH)
        elif len(mod_uid) != group_manager.ID_LENGTH:
            return error.error.main.invalid_length(u'管理員UID', group_manager.ID_LENGTH)
        
        if not admin_pw_is_sha:
            admin_pw = user_data.generate_sha(admin_pw)

        setup_result = self.find_one_and_update({
            '$and': [
                { group_data.ALL_ADMIN + '.' + group_data.ADMIN_DATA + '.' + user_data.PW: admin_pw },
                { group_data.GROUP_ID: gid },
                { group_data.ALL_ADMIN + '.' + group_data.ALL_MODERATORS + '.' + user_data.UID : mod_uid }
            ]},
            { '$pull': { 
                group_data.ALL_ADMIN + '.' + group_data.ALL_MODERATORS : { user_data.UID : mod_uid }
            } }, None, None, False, ReturnDocument.AFTER)
        
        if setup_result > 0:
            return True
        else:
            return error.error.main.incorrect_password_or_insufficient_permission()

    def get_all_group_data(self):
        all_data = self.find({})
        return [data for data in all_data]



    def get_group_config_type(self, gid):
        group = self.get_group_by_id(gid)
        if group is not None:
            return group.config_type

class group_data(dict_like_mapping):
    GROUP_ID = 'group_id'
    ALL_ADMIN = 'admins'
    ALL_MODERATORS = 'moderators'

    CONFIG_TYPE = 'config_type'

    ADMIN_DATA = 'admin'

    @staticmethod
    def init_by_field(gid, admin_uid, admin_pw, config_type, pw_is_sha=False, mod_user_data_list=None):
        if mod_user_data_list is None:
            mod_user_data_list = []

        init_dict = {
            group_data.GROUP_ID: gid,
            group_data.ALL_ADMIN: {
                group_data.ADMIN_DATA: user_data.init_by_field(admin_uid, admin_pw, pw_is_sha), 
                group_data.ALL_MODERATORS: mod_user_data_list
            },
            group_data.CONFIG_TYPE: config_type
        }

        return group_data(init_dict)

    def __init__(self, org_dict):
        if org_dict is not None:
            if all(k in org_dict for k in (group_data.GROUP_ID, group_data.ALL_ADMIN, group_data.CONFIG_TYPE)):
                if all(k in org_dict[group_data.ALL_ADMIN] for k in (group_data.ADMIN_DATA, group_data.ALL_MODERATORS)):
                    if org_dict[group_data.ALL_ADMIN].get(group_data.ADMIN_DATA, None) is not None:
                        pass
                    else:
                        raise ValueError('Admin data is null in group data dictionary.')
                else:
                    raise ValueError('Incomplete data of admins.')
            else:
                raise ValueError('Invalid group data dictionary.')
        else:
            raise ValueError('Dictionary is None.')

        return super(group_data, self).__init__(org_dict)

    def get_admin_data(self):
        admin_data = self[group_data.ALL_ADMIN][group_data.ADMIN_DATA]
        return user_data(admin_data, True)

    def get_moderators_data(self):
        mods_data = self[group_data.ALL_ADMIN][group_data.ALL_MODERATORS]
        if len(mods_data) > 0:
            return [user_data(mod_data, True) for mod_data in mods_data]
        else:
            return None

    @property
    def group_id(self):
        return self[group_data.GROUP_ID]

    @property
    def admin_data(self):
        return self[group_data.ALL_ADMIN][group_data.ADMIN_DATA]

    @property
    def config_type(self):
        try:
            config_type_int = self[group_data.CONFIG_TYPE]
        except KeyError:
            self[group_data.CONFIG_TYPE] = config_type.UNKNOWN
        finally:
            return config_type(config_type_int)

class user_data(dict_like_mapping):
    UID = 'uid'
    PW = 'pw'

    @staticmethod
    def generate_sha(s):
        return hashlib.sha224(s).hexdigest()

    @staticmethod
    def init_by_field(uid, pw, pw_is_sha=False):
        init_dict = {
            user_data.UID: uid, user_data.PW: pw
        }

        return user_data(init_dict, pw_is_sha)

    def __init__(self, org_dict, pw_is_sha=False):
        if user_data.UID in org_dict and user_data.PW in org_dict:
            pass
        else:
            raise ValueError('Invalid user data.')
        
        super(user_data, self).__init__(org_dict)

        if not pw_is_sha:
            self[user_data.PW] = user_data.generate_sha(self[user_data.PW])

    @property
    def uid(self):
        return self[user_data.UID]

    @property
    def pw_sha(self):
        return self[user_data.PW]