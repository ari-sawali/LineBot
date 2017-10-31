# -*- coding: utf-8 -*-

import ext

class permission(ext.EnumWithName):
    RESTRICTED = -1, '限制用戶'
    USER = 0, '一般用戶'
    MODERATOR = 1, '副管理員'
    ADMIN = 2, '管理員'
    BOT_ADMIN = 3, '機器人管理員'

class cmd_category(ext.EnumWithName):
    MAIN = 0, '主要指令'
    EXTEND = 1, '延伸指令'
    GAME = 2, '遊戲用指令'

class command_object(object):
    def __init__(self, min_split, max_split, cmd_category, remotable, group_id_allow_public, lowest_permission_req=permission.USER):
        self._split_max = max_split
        self._split_min = min_split
        self._category = cmd_category
        self._count = 0
        self._remotable = remotable
        self._gid_allow_public = group_id_allow_public
        self._lowest_permission_required = lowest_permission_req

    @property
    def split_max(self):
        """Maximum split count."""
        return self._split_max + int(self._remotable)

    @property
    def split_min(self):
        """Minimum split count."""
        return self._split_min

    @property
    def count(self):
        """Called count."""
        return self._count

    @count.setter
    def count(self, value):
        """Called count."""
        self._count = value 

    @property
    def category(self):
        return self._category

    @property
    def lowest_permission(self):
        """Required Permission"""
        return self._lowest_permission_required

    @property
    def remotable(self):
        return self._remotable

    @property
    def allow_gid_public(self):
        if self._remotable:
            return self._gid_allow_public
        else:
            return False

# Provide lowest permission requirement, if some command requires higher permission, handle inside txt msg handling function.
cmd_dict = { 'S': command_object(4, 4, cmd_category.MAIN, False, False, permission.BOT_ADMIN), 
             'A': command_object(3, 5, cmd_category.MAIN, True, True), 
             'M': command_object(3, 5, cmd_category.MAIN, True, False, permission.MODERATOR), 
             'D': command_object(1, 2, cmd_category.MAIN, True, True), 
             'R': command_object(1, 2, cmd_category.MAIN, True, False, permission.MODERATOR), 
             'E': command_object(2, 3, cmd_category.MAIN, True, True, permission.MODERATOR), 
             'X': command_object(1, 3, cmd_category.MAIN, True, True), 
             'Q': command_object(0, 2, cmd_category.MAIN, True, True), 
             'I': command_object(1, 2, cmd_category.MAIN, True, True), 
             'K': command_object(1, 2, cmd_category.MAIN, True, True),
             'P': command_object(1, 2, cmd_category.EXTEND, True, True), 
             'G': command_object(0, 1, cmd_category.EXTEND, True, False), 
             'GA': command_object(1, 4, cmd_category.EXTEND, True, True, permission.MODERATOR),  
             'H': command_object(0, 0, cmd_category.EXTEND, False, False), 
             'SHA': command_object(1, 1, cmd_category.EXTEND, False, False), 
             'O': command_object(1, 1, cmd_category.EXTEND, False, False), 
             'RD': command_object(1, 2, cmd_category.EXTEND, False, False), 
             'L': command_object(1, 1, cmd_category.EXTEND, True, False),
             'T': command_object(1, 1, cmd_category.EXTEND, False, False),
             'C': command_object(0, 3, cmd_category.EXTEND, False, False),
             'FX': command_object(1, 2, cmd_category.EXTEND, False, False),
             'N': command_object(1, 1, cmd_category.EXTEND, False, False),
             'STK': command_object(1, 3, cmd_category.EXTEND, False, False),
             'RPS': command_object(0, 4, cmd_category.GAME, False, False) }

class commands_manager(object):
    def __init__(self, cmd_dict):
        self._cmd_dict = cmd_dict

    def is_permission_required(self, cmd):
        cmd_obj = self.get_command_data(cmd)
        if cmd_obj is None:
            raise CommandNotExistException(cmd)
        else:
            return int(cmd_obj.lowest_permission) > int(permission.USER)

    def is_command_exist(self, cmd):
        cmd_obj = self.get_command_data(cmd)
        return cmd_obj is not None

    def get_command_data(self, cmd):
        return self._cmd_dict.get(cmd, None)

class CommandNotExistException(Exception):
    def __init__(self, *args):
        return super(CommandNotExistException, self).__init__(*args)
