# -*- coding: utf-8 -*-

import ext

class permission(ext.EnumWithName):
    RESTRICTED = -1, '限制用戶'
    USER = 0, '一般用戶'
    MODERATOR = 1, '副管理員'
    ADMIN = 2, '管理員'
    BOT_ADMIN = 3, '機器人管理員'

class remote(ext.EnumWithName):
    NOT_AVAILABLE = 0, '不可用'
    GROUP_ID_ONLY = 1, '限群組ID'
    ALLOW_PUBLIC = 2, '可控公群'
    ALLOW_GLOBAL = 3, '可控全域'
    ALLOW_ALL = 4, '可控公群/全域'

    @staticmethod
    def PUBLIC_TOKEN():
        return 'PUBLIC'

    @staticmethod
    def GLOBAL_TOKEN():
        return 'GLOBAL'

class command_object(object):
    def __init__(self, head, function_code, remotable, lowest_permission_req=permission.USER):
        self._head = head
        self._function_code = function_code
        self._remotable = remotable
        self._lowest_permission_required = lowest_permission_req

    @property
    def head(self):
        """Head of command."""
        return self._head

    @property
    def remotable(self):
        return self._remotable

    @property
    def lowest_permission(self):
        """Required Permission"""
        return self._lowest_permission_required

    @property
    def function_code(self):
        """Code of function"""
        return self._function_code

# Provide lowest permission requirement, if some command requires higher permission, handle inside txt msg handling function.
sys_cmd_dict = { u'記住': command_object(u'記住', 'A', remote.ALLOW_ALL), 
                 u'置頂': command_object(u'置頂', 'M', remote.GROUP_ID_ONLY, permission.MODERATOR), 
                 u'忘記': command_object(u'忘記', 'D', remote.ALLOW_ALL), 
                 u'忘記置頂': command_object(u'忘記置頂', 'R', remote.ALLOW_ALL), 
                 u'找': command_object(u'找', 'Q', remote.ALLOW_ALL), 
                 u'詳細找': command_object(u'詳細找', 'I', remote.ALLOW_ALL), 
                 u'修改': command_object(u'修改', 'E', remote.ALLOW_ALL), 
                 u'複製': command_object(u'複製', 'X', remote.NOT_AVAILABLE), 
                 u'清除': command_object(u'清除', 'X2', remote.NOT_AVAILABLE, permission.ADMIN), 
                 u'群組': command_object(u'群組', 'G', remote.ALLOW_ALL), 
                 u'當': command_object(u'當', 'GA', remote.GROUP_ID_ONLY), 
                 u'讓': command_object(u'讓', 'GA2', remote.GROUP_ID_ONLY), 
                 u'啟用': command_object(u'啟用', 'GA3', remote.GROUP_ID_ONLY), 
                 u'頻道': command_object(u'頻道', 'H', remote.NOT_AVAILABLE), 
                 u'系統': command_object(u'系統', 'P', remote.ALLOW_ALL), 
                 u'使用者': command_object(u'使用者', 'P2', remote.GROUP_ID_ONLY),
                 u'前': command_object(u'前', 'K', remote.ALLOW_ALL), 
                 u'最近的': command_object(u'最近的', 'L', remote.GROUP_ID_ONLY), 
                 u'匯率': command_object(u'匯率', 'C', remote.NOT_AVAILABLE), 
                 u'雜湊': command_object(u'雜湊', 'SHA', remote.NOT_AVAILABLE), 
                 u'貼圖': command_object(u'貼圖', 'STK', remote.NOT_AVAILABLE), 
                 u'編碼': command_object(u'編碼', 'T', remote.NOT_AVAILABLE), 
                 u'查': command_object(u'查', 'O', remote.NOT_AVAILABLE), 
                 u'抽': command_object(u'抽', 'RD', remote.NOT_AVAILABLE), 
                 u'解': command_object(u'解', 'FX', remote.NOT_AVAILABLE), 
                 u'DB': command_object(u'DB', 'S', remote.NOT_AVAILABLE, permission.ADMIN), 
                 u'天氣': command_object(u'天氣', 'W', remote.NOT_AVAILABLE), 
                 u'下載': command_object(u'下載', 'DL', remote.NOT_AVAILABLE) }

game_cmd_dict = { u'猜拳': command_object(u'猜拳', 'RPS', remote.NOT_AVAILABLE) } 

class CommandNotExistException(Exception):
    def __init__(self, *args):
        return super(CommandNotExistException, self).__init__(*args)