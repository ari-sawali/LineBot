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
    def __init__(self, min_split, max_split, cmd_category, lowest_permission_req=permission.USER):
        self._split_max = max_split
        self._split_min = min_split
        self._count = 0
        self._lowest_permission_required = lowest_permission_req

    @property
    def split_max(self):
        """Maximum split count."""
        return self._split_max

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
    def lowest_permission(self):
        """Required Permission"""
        return self._lowest_permission_required

# MAX_PARAM_COUNT includes parameter which will be popped
cmd_dict = { 'S': command_object(2, 2, cmd_category.MAIN, permission.BOT_ADMIN), 
             'A': command_object(3, 5, cmd_category.MAIN), 
             'M': command_object(3, 5, cmd_category.MAIN, permission.MODERATOR), 
             'D': command_object(1, 2, cmd_category.MAIN), 
             'R': command_object(1, 2, cmd_category.MAIN, permission.MODERATOR), 
             'E': command_object(2, 3, cmd_category.MAIN, permission.MODERATOR), 
             'X': command_object(1, 3, cmd_category.MAIN, permission.MODERATOR), 
             'Q': command_object(0, 2, cmd_category.MAIN), 
             'I': command_object(1, 2, cmd_category.MAIN), 
             'K': command_object(1, 2, cmd_category.MAIN),
             'P': command_object(1, 2, cmd_category.EXTEND), 
             'G': command_object(0, 1, cmd_category.EXTEND), 
             'GA': command_object(1, 4, cmd_category.EXTEND, permission.MODERATOR),  
             'H': command_object(0, 0, cmd_category.EXTEND), 
             'SHA': command_object(1, 1, cmd_category.EXTEND), 
             'O': command_object(1, 1, cmd_category.EXTEND), 
             'RD': command_object(1, 2, cmd_category.EXTEND), 
             'L': command_object(1, 1, cmd_category.EXTEND),
             'T': command_object(1, 1, cmd_category.EXTEND),
             'C': command_object(0, 3, cmd_category.EXTEND),
             'FX': command_object(1, 2, cmd_category.EXTEND),
             'N': command_object(1, 1, cmd_category.EXTEND),
             'RPS': command_object(0, 4, cmd_category.GAME) }

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
