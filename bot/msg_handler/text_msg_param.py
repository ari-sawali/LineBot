# -*- coding: utf-8 -*-

import ast

from error import error
import ext
import tool, db, bot

class param_packer_base(object):
    def __init__(self, command_category, param_objs, CH_regex=None, EN_regex=None):
        """
        Parameters:
            CH_regex: chinese regex to check.
            EN_regex: english regex to check.
            command_category: category of the command.
            param_field: enum of parameter object in list.
        """
        self._CH = CH_regex
        self._EN = EN_regex

        if self._CH is None and self._EN is None:
            raise ValueError('Must specify at least one regex.')

        self._cat = command_category
        self._param_objs = param_objs

    @property
    def CH(self):
        return self._CH

    @property
    def EN(self):
        return self._EN

    @property
    def command_category(self):
        return self._cat

    def pack(self, text):
        """
        Parameters:
            text: text to try to match the provided regex.

        Return:
            param_packing_result.
        """
        regex_result = tool.regex_finder.find_match([self._CH, self._EN], text)

        if regex_result is not None:
            p_dict = {}
            for i, param in enumerate(self._param_objs, start=1):
                validate_result = param.validate(regex_result.group(i))
                if validate_result.valid:
                    p_dict[param.field_enum] = validate_result.ret
                else:
                    return param_packing_result(validate_result.ret, param_packing_result_status.ERROR_IN_PARAM, self._cat)

            return param_packing_result(p_dict, param_packing_result_status.ALL_PASS, self._cat)
        else:
            return param_packing_result(None, param_packing_result_status.NO_MATCH, self._cat)

class param_packing_result_status(ext.EnumWithName):
    ALL_PASS = 1, '全通過'
    ERROR_IN_PARAM = 2, '參數有誤'
    NO_MATCH = 3, '無符合'

class param_packing_result(object):
    def __init__(self, result, status, command_category):
        self._result = result
        self._status = status
        self._cmd_cat = command_category

    @property
    def command_category(self):
        return self._cmd_cat

    @property
    def result(self):
        """
        Returns:
            Status=ALL_PASS -> Parameter dictionary.
            Status=ERROR_IN_PARAM -> Error message of parameter.
            Status=NO_MATCH -> None.
        """
        return self._result

    @property
    def status(self):
        return self._status

class parameter(object):
    def __init__(self, field_enum, validator_method, allow_null=False):
        """
        Parameter:
            field_enum: Enum that represents this field.
            validator_method: Method to validate the parameter. If the method is not come from param_validator, the action may be unexpected.
            allow_null: Allow this field to be null.
        """
        self._field_enum = field_enum
        self._validator = validator_method
        self._allow_null = allow_null

    @property
    def field_enum(self):
        return self._field_enum

    def validate(self, content):
        """
        Parameter:
            content: Parameter to validate.

        Returns:
            return param_validation_result.
        """
        return self._validator(content, self._allow_null)

class param_validator(object):
    """
    Meta:
        Must be @staticmethod.

    Input:
        obj: parameter object (usually string) to validate.
        allow_null: allow parameter pass the validation if the parameter is null.

    Returns:
        param_check_result. Ret of result may be an error message, or processed parameter.
    """

    ARRAY_SEPARATOR = "  "

    @staticmethod
    def base_null(obj, allow_null):
        if allow_null and obj is None:
            return param_validation_result(obj, True)

    @staticmethod
    def check_dict(obj, allow_null):
        base = param_validator.base_null(obj, allow_null)
        if base is not None:
            return base

        try:
            obj = ast.literal_eval(obj)

            if not isinstance(obj, dict):
                return param_validation_result(error.main.miscellaneous(u'輸入參數必須是合法dictionary型別。({})'.format(type(obj))), False)

            return param_validation_result(obj, True)
        except ValueError as ex:
            return param_validation_result(error.main.miscellaneous(u'字串型別分析失敗。\n{}\n\n訊息: {}'.format(obj, ex.message)), False)

    @staticmethod
    def conv_unicode(obj, allow_null):
        base = param_validator.base_null(obj, allow_null)
        if base is not None:
            return base

        try:
            return param_validation_result(unicode(obj), True)
        except Exception as ex:
            return param_validation_result(u'{} - {}'.format(type(ex), ex.message), False)

    @staticmethod
    def conv_unicode_lower(obj, allow_null):
        base = param_validator.base_null(obj, allow_null)
        if base is not None:
            return base

        try:
            return param_validation_result(unicode(obj).lower(), True)
        except Exception as ex:
            return param_validation_result(u'{} - {}'.format(type(ex), ex.message), False)

    @staticmethod
    def conv_unicode_arr(obj, allow_null):
        base = param_validator.base_null(obj, allow_null)
        if base is not None:
            return base

        try:
            return param_validation_result([unicode(o) for o in ext.to_list(obj.split(param_validator.ARRAY_SEPARATOR))], True)
        except Exception as ex:
            return param_validation_result(u'{} - {}'.format(type(ex), ex.message), False)

    @staticmethod
    def validate_https(obj, allow_null):
        base = param_validator.base_null(obj, allow_null)
        if base is not None:
            return base

        if obj.startswith('https://'):
            return param_validator.conv_unicode(obj, allow_null)
        else:
            return param_validation_result(error.sys_command.must_https(obj), False)

    @staticmethod
    def validate_sha224(obj, allow_null):
        base = param_validator.base_null(obj, allow_null)
        if base is not None:
            return base

        try:
            obj = unicode(obj)
        except UnicodeDecodeError:
            obj = obj.decode('utf-8')
        except UnicodeEncodeError:
            obj = obj.encode('utf-8')

        if tool.regex.regex_finder.find_match(ur'.*(?:[0-9a-fA-F]{56}).*', obj) is not None:
            return param_validator.conv_unicode(obj, allow_null)
        else:
            return param_validation_result(error.sys_command.must_sha(obj), False)

    @staticmethod
    def conv_int_gt_0(obj, allow_null):
        base = param_validator.base_null(obj, allow_null)
        if base is not None:
            return base

        new_int = ext.to_int(obj)

        if new_int is not None:
            return param_validation_result(new_int, True)
        elif new_int < 1:
            return param_validation_result(error.sys_command.must_gt_0(obj), False)
        else:
            return param_validation_result(error.sys_command.must_int(obj), False)

    @staticmethod
    def valid_int(obj, allow_null):
        base = param_validator.base_null(obj, allow_null)
        if base is not None:
            return base

        new_int = ext.to_int(obj)

        if new_int is not None:
            return param_validation_result(obj, True)
        else:
            return param_validation_result(error.sys_command.must_int(obj), False)

    @staticmethod
    def conv_int_arr(obj, allow_null):
        base = param_validator.base_null(obj, allow_null)
        if base is not None:
            return base

        new_int = ext.to_int(ext.to_list(obj.split(param_validator.ARRAY_SEPARATOR)))

        if new_int is not None:
            return param_validation_result(new_int, True)
        else:
            return param_validation_result(error.sys_command.must_int(obj), False)

    @staticmethod
    def valid_int_arr(obj, allow_null):
        base = param_validator.base_null(obj, allow_null)
        if base is not None:
            return base

        sp = ext.to_list(obj.split(param_validator.ARRAY_SEPARATOR))
        new_int = ext.to_int(sp)

        if new_int is not None:
            return param_validation_result(sp, True)
        else:
            return param_validation_result(error.sys_command.must_int(obj), False)

    @staticmethod
    def conv_int_lt_1m(obj, allow_null):
        base = param_validator.base_null(obj, allow_null)
        if base is not None:
            return base

        res = param_validator.conv_int_gt_0(obj, allow_null)

        if res.success:
            sp_for_check = res.result
            if isinstance(obj, (list, tuple)):
                sp_for_check = [int(i) for i in sp_for_check]
            return param_validation_result(res.result, all(num < 1000000 for num in sp_for_check))
        else:
            return param_validation_result(error.sys_command.must_int(obj), False)

    @staticmethod
    def is_not_null(obj, allow_null):
        return param_validation_result(obj is not None, True)

    @staticmethod
    def text_to_bool(obj, allow_null):
        base = param_validator.base_null(obj, allow_null)
        if base is not None:
            return base

        if any(cond == obj for cond in (u'有', '有', 'O', u'O')):
            return param_validation_result(True, True)
        elif any(cond == obj for cond in (u'無', '無', 'X', u'X')):
            return param_validation_result(False, True)
        else:
            raise UndefinedTextException(obj)

    @staticmethod
    def conv_float(obj, allow_null):
        base = param_validator.base_null(obj, allow_null)
        if base is not None:
            return base

        res = ext.string_to_float(obj)

        if res is not None:
            return param_validation_result(res, True)
        else:
            return param_validation_result(obj, False)

    class keyword_dict(object):
        @staticmethod
        def conv_pair_type_from_org(obj, allow_null):
            base = param_validator.base_null(obj, allow_null)
            if base is not None:
                return base

            if any(obj.startswith(w) for w in (u'收到', u'回答', u'T')):
                ret = db.word_type.TEXT
            elif any(obj.startswith(w) for w in (u'看到', u'回圖', u'P')):
                ret = db.word_type.PICTURE
            elif any(obj.startswith(w) for w in (u'被貼', u'回貼', u'S')):
                ret = db.word_type.STICKER
            else:
                return param_validation_result(u'{} - {}'.format(type(ex), ex.message), False)

            return param_validation_result(ret, True)

        @staticmethod
        def get_type_auto(obj, allow_null):
            base = param_validator.base_null(obj, allow_null)
            if base is not None:
                return base

            if param_validator.validate_https(obj, allow_null).valid or param_validator.validate_sha224(obj, allow_null).valid:
                ret = db.word_type.PICTURE
            elif param_validator.conv_int_gt_0(obj, allow_null).valid:
                ret = db.word_type.STICKER
            elif param_validator.conv_unicode(obj, allow_null).valid:
                ret = db.word_type.TEXT
            else:
                return param_validation_result(u'Object cannot be determined to any type. ({})'.format(obj), False)

            return param_validation_result(ret, True)

    class line_bot_api(object):
        @staticmethod
        def validate_cid(obj, allow_null):
            base = param_validator.base_null(obj, allow_null)
            if base is not None:
                return base

            return param_validation_result(obj, bot.line_api_wrapper.is_valid_user_id(obj) and bot.line_api_wrapper.is_valid_room_group_id(obj))

        @staticmethod
        def validate_uid(obj, allow_null):
            base = param_validator.base_null(obj, allow_null)
            if base is not None:
                return base

            return param_validation_result(obj, bot.line_api_wrapper.is_valid_user_id(obj))

        @staticmethod
        def validate_gid(obj, allow_null):
            base = param_validator.base_null(obj, allow_null)
            if base is not None:
                return base
            
            return param_validation_result(obj, bot.line_api_wrapper.is_valid_room_group_id(obj))

        @staticmethod
        def validate_gid_public_global(obj, allow_null):
            base = param_validator.base_null(obj, allow_null)
            if base is not None:
                return base
            
            return param_validation_result(obj, bot.line_api_wrapper.is_valid_room_group_id(obj, True, True))

    class special_category(object):
        @staticmethod
        def K_ranking_category(obj, allow_null):
            base = param_validator.base_null(obj, allow_null)
            if base is not None:
                return base

            err = error.sys_command.unknown_func_K_ranking_category(obj)
            t = err

            if obj == u'使用者' or obj == u'USER':
                t = special_param.func_K.ranking_category.USER
            elif obj == u'使用過的' or obj == u'KWRC':
                t = special_param.func_K.ranking_category.RECENTLY_USED
            elif obj == u'回覆組' or obj == u'KW':
                t = special_param.func_K.ranking_category.KEYWORD

            return param_validation_result(t, t != err)

        @staticmethod
        def P_record_category(obj, allow_null):
            base = param_validator.base_null(obj, allow_null)
            if base is not None:
                return base

            err = error.sys_command.unknown_func_K_ranking_category(obj)
            t = err

            if obj == u'自動回覆' or obj == u'KW':
                t = special_param.func_P.record_category.AUTO_REPLY
            elif obj == u'資訊' or obj == u'SYS':
                t = special_param.func_P.record_category.SYS_INFO
            elif obj == u'圖片' or obj == u'IMG':
                t = special_param.func_P.record_category.IMGUR_API
            elif obj == u'匯率' or obj == u'EXC':
                t = special_param.func_P.record_category.EXCHANGE_RATE
            elif obj == u'黑名單' or obj == u'BAN':
                t = special_param.func_P.record_category.BAN_LIST

            return param_validation_result(t, t != err)

        @staticmethod
        def GA_group_range(obj, allow_null):
            base = param_validator.base_null(obj, allow_null)
            if base is not None:
                return base

            err = error.sys_command.unknown_func_GA_group_config(obj)
            t = err

            if obj == u'啞巴' or obj == u'0':
                t = db.group_data_range.SILENCE
            elif obj == u'機器人' or obj == u'1':
                t = db.group_data_range.SYS_ONLY
            elif obj == u'服務員' or obj == u'2':
                t = db.group_data_range.GROUP_DATABASE_ONLY
            elif obj == u'八嘎囧' or obj == u'3':
                t = db.group_data_range.ALL

            return param_validation_result(t, t != err)

        @staticmethod
        def GA2_permission(obj, allow_null):
            base = param_validator.base_null(obj, allow_null)
            if base is not None:
                return base

            err = error.sys_command.unknown_func_GA2_permission(obj)
            t = err

            if obj == u'可憐兒' or obj == u'0':
                t = bot.permission.RESTRICTED
            elif obj == u'一般人' or obj == u'1':
                t = bot.permission.USER
            elif obj == u'副管' or obj == u'2':
                t = bot.permission.MODERATOR
            elif obj == u'管理員' or obj == u'3':
                t = bot.permission.ADMIN

            return param_validation_result(t, t != err)
        
        @staticmethod
        def GA3_validate_token(obj, allow_null):
            base = param_validator.base_null(obj, allow_null)
            if base is not None:
                return base

            return param_validation_result(obj, tool.regex.regex_finder.find_match(ur'.*(?:[A-Z0-9]{40}).*', obj) is None)

        @staticmethod
        def L_category(obj, allow_null):
            base = param_validator.base_null(obj, allow_null)
            if base is not None:
                return base

            err = error.sys_command.unknown_func_L_category(obj)
            t = err

            if obj == u'貼圖' or obj == u'S':
                t = bot.system_data_category.LAST_STICKER
            elif obj == u'圖片' or obj == u'P':
                t = bot.system_data_category.LAST_PIC_SHA
            elif obj == u'回覆組' or obj == u'R':
                t = bot.system_data_category.LAST_PAIR_ID
            elif obj == u'發送者' or obj == u'U':
                t = bot.system_data_category.LAST_UID
            elif obj == u'訊息' or obj == u'M':
                t = bot.system_data_category.LAST_MESSAGE

            return param_validation_result(t, t != err)

        @staticmethod
        def C_validate_currency_symbols(obj, allow_null):
            base = param_validator.base_null(obj, allow_null)
            if base is not None:
                return base

            l = len(obj)
            regex_valid = tool.regex.regex_finder.find_match(ur'([A-Z ]{3, })', obj) is not None

            if regex_valid and (l == 3 or (l >= 3 and l % 3 == 2)):
                return param_validator.conv_unicode_arr(obj, allow_null)
            else:
                return param_validation_result(error.sys_command.func_C_currency_symbol_unrecognizable(obj), False)

        @staticmethod
        def C_validate_currency_symbol(obj, allow_null):
            base = param_validator.base_null(obj, allow_null)
            if base is not None:
                return base

            if tool.regex.regex_finder.find_match(ur'([A-Z]{3})', obj) is not None:
                return param_validator.conv_unicode_arr(obj, allow_null)
            else:
                return param_validation_result(error.sys_command.func_C_currency_symbol_unrecognizable(obj), False)

        @staticmethod
        def C_validate_date(obj, allow_null):
            base = param_validator.base_null(obj, allow_null)
            if base is not None:
                return base

            return param_validation_result(obj, tool.regex.regex_finder.find_match(ur'(?:(?:1999|20\d{2})(?:0[1-9]|1[1-2])(?:[0-2][1-9]|3[0-1]))', obj) is not None)

        @staticmethod
        def FX_validate_formulas(obj, allow_null):
            base = param_validator.base_null(obj, allow_null)
            if base is not None:
                return base

            if tool.regex.regex_finder.find_match(ur'([!^*()_+|~\-=<>/0-9A-Za-z&]+)', obj) is not None:
                return param_validation_result(obj.split('&'), True)
            else:
                return param_validation_result(obj, False)

        @staticmethod
        def W_output_type(obj, allow_null):
            base = param_validator.base_null(obj, allow_null)
            if base is not None:
                return base

            err = error.sys_command.unknown_func_W_output_type(obj)
            t = err

            if obj == u'詳細' or obj == u'詳' or obj == u'D':
                t = tool.weather.output_type.DETAIL
            elif obj == u'簡潔' or obj == u'簡' or obj == u'S':
                t = tool.weather.output_type.SIMPLE

            return param_validation_result(t, t != err)

        @staticmethod
        def W_action(obj, allow_null):
            base = param_validator.base_null(obj, allow_null)
            if base is not None:
                return base

            err = error.sys_command.unknown_func_W_action(obj)
            t = err

            if obj == u'新增' or obj == u'A':
                t = func_W.action_category.ADD_TRACK
            elif obj == u'刪除' or obj == u'D':
                t = func_W.action_category.DEL_TRACK
            elif obj == u'查詢' or obj == u'ID':
                t = func_W.action_category.GET_DATA

            return param_validation_result(t, t != err)

        @staticmethod
        def STK_action_category(obj, allow_null):
            base = param_validator.base_null(obj, allow_null)
            if base is not None:
                return base

            err = error.sys_command.unknown_func_STK_ranking_category(obj)
            t = err

            if obj == u'貼圖圖包' or obj == u'PKG':
                t = db.ranking_category.PACKAGE
            elif obj == u'貼圖' or obj == u'STK':
                t = db.ranking_category.STICKER

            return param_validation_result(t, t != err)

class param_validation_result(ext.action_result):
    def __init__(self, ret, valid):
        super(param_validation_result, self).__init__(ret, valid)

    @property
    def ret(self):
        return self._result

    @property
    def valid(self):
        return self._success

class special_param(object):
    class func_K(object):
        class ranking_category(ext.EnumWithName):
            KEYWORD = 1, '關鍵字排名'
            RECENTLY_USED = 2, '最近使用'
            USER = 3, '使用者'

    class func_P(object):
        class record_category(ext.EnumWithName):
            AUTO_REPLY = 1, '關鍵字排名'
            SYS_INFO = 2, '最近使用'
            IMGUR_API = 3, '使用者'
            EXCHANGE_RATE = 4, '匯率轉換'
            BAN_LIST = 5, '黑名單'

    class func_W(object):
        class action_category(ext.EnumWithName):
            ADD_TRACK = 0, '新增追蹤項目'
            DEL_TRACK = 1, '刪除追蹤項目'
            GET_DATA = 2, '獲取資料'

class param_packer(object): 
    class func_S(param_packer_base):
        class command_category(ext.EnumWithName):
            DB_COMMAND = 1, '資料庫指令'

        class param_category(ext.EnumWithName):
            DB_NAME = 1, '資料庫名稱'
            MAIN_CMD = 2, '主指令'
            MAIN_PRM = 3, '主參數'
            OTHER_PRM = 4, '其餘參數'

        def __init__(self, command_category, CH_regex=None, EN_regex=None):
            prm_objs = self._get_prm_objs(command_category)

            super(param_packer.func_S, self).__init__(command_category, prm_objs, CH_regex, EN_regex)

        def _get_prm_objs(self, command_category):
            if command_category == param_packer.func_S.command_category.DB_COMMAND:
                prm_objs = [parameter(param_packer.func_S.param_category.DB_NAME, param_validator.conv_unicode), 
                            parameter(param_packer.func_S.param_category.MAIN_CMD, param_validator.conv_unicode), 
                            parameter(param_packer.func_S.param_category.MAIN_PRM, param_validator.conv_unicode), 
                            parameter(param_packer.func_S.param_category.OTHER_PRM, param_validator.check_dict)]
            else:
                raise UndefinedCommandCategoryException()

            return prm_objs
    
    class func_A(param_packer_base):
        class command_category(ext.EnumWithName):
            ADD_PAIR_CH = 1, '新增回覆組(中文)'
            ADD_PAIR_EN = 2, '新增回覆組(英文)'
            ADD_PAIR_AUTO_CH = 3, '新增回覆組(自動偵測，中文)'
            ADD_PAIR_AUTO_EN = 4, '新增回覆組(自動偵測，英文)'

        class param_category(ext.EnumWithName):
            ATTACHMENT = 2, '附加回覆內容'
            RCV_TYPE = 3, '接收(種類)'
            RCV_TXT = 4, '接收(文字)'
            RCV_STK = 5, '接收(貼圖)'
            RCV_PIC = 6, '接收(圖片)'
            REP_TYPE = 7, '回覆(種類)'
            REP_TXT = 8, '回覆(文字)'
            REP_STK = 9, '回覆(貼圖)'
            REP_PIC = 10, '回覆(圖片)'
            RCV_CONTENT = 11, '接收(內容)'
            REP_CONTENT = 12, '回覆(內容)'

        def __init__(self, command_category, CH_regex=None, EN_regex=None):
            prm_objs = self._get_prm_objs(command_category)

            super(param_packer.func_A, self).__init__(command_category, prm_objs, CH_regex, EN_regex)

        def _get_prm_objs(self, command_category):
            if command_category == param_packer.func_A.command_category.ADD_PAIR_CH:
                prm_objs = [parameter(param_packer.func_A.param_category.ATTACHMENT, param_validator.conv_unicode, True),
                            parameter(param_packer.func_A.param_category.RCV_TYPE, param_validator.keyword_dict.conv_pair_type_from_org),  
                            parameter(param_packer.func_A.param_category.RCV_TXT, param_validator.conv_unicode, True),  
                            parameter(param_packer.func_A.param_category.RCV_PIC, param_validator.validate_sha224, True),  
                            parameter(param_packer.func_A.param_category.RCV_STK, param_validator.valid_int, True),  
                            parameter(param_packer.func_A.param_category.REP_TYPE, param_validator.keyword_dict.conv_pair_type_from_org), 
                            parameter(param_packer.func_A.param_category.REP_TXT, param_validator.conv_unicode, True), 
                            parameter(param_packer.func_A.param_category.REP_PIC, param_validator.validate_https, True), 
                            parameter(param_packer.func_A.param_category.REP_STK, param_validator.valid_int, True)]
            elif command_category == param_packer.func_A.command_category.ADD_PAIR_EN:
                prm_objs = [parameter(param_packer.func_A.param_category.RCV_TYPE, param_validator.keyword_dict.conv_pair_type_from_org),  
                            parameter(param_packer.func_A.param_category.RCV_TXT, param_validator.conv_unicode, True),  
                            parameter(param_packer.func_A.param_category.RCV_STK, param_validator.valid_int, True),  
                            parameter(param_packer.func_A.param_category.RCV_PIC, param_validator.validate_sha224, True),  
                            parameter(param_packer.func_A.param_category.REP_TYPE, param_validator.keyword_dict.conv_pair_type_from_org), 
                            parameter(param_packer.func_A.param_category.REP_TXT, param_validator.conv_unicode, True), 
                            parameter(param_packer.func_A.param_category.REP_STK, param_validator.valid_int, True), 
                            parameter(param_packer.func_A.param_category.REP_PIC, param_validator.validate_https, True), 
                            parameter(param_packer.func_A.param_category.ATTACHMENT, param_validator.conv_unicode, True)]
            elif command_category == param_packer.func_A.command_category.ADD_PAIR_AUTO_CH:
                prm_objs = [parameter(param_packer.func_A.param_category.ATTACHMENT, param_validator.conv_unicode, True),  
                            parameter(param_packer.func_A.param_category.RCV_CONTENT, param_validator.conv_unicode),  
                            parameter(param_packer.func_A.param_category.REP_CONTENT, param_validator.conv_unicode)]
            elif command_category == param_packer.func_A.command_category.ADD_PAIR_AUTO_EN:
                prm_objs = [parameter(param_packer.func_A.param_category.RCV_CONTENT, param_validator.conv_unicode),  
                            parameter(param_packer.func_A.param_category.REP_CONTENT, param_validator.conv_unicode),
                            parameter(param_packer.func_A.param_category.ATTACHMENT, param_validator.conv_unicode, True)]
            else:
                raise UndefinedCommandCategoryException()

            return prm_objs
    
    class func_D(param_packer_base):
        class command_category(ext.EnumWithName):
            DEL_PAIR = 1, '刪除回覆組'

        class param_category(ext.EnumWithName):
            IS_ID = 1, '根據ID?'
            ID = 2, 'ID'
            WORD = 3, '關鍵字'

        def __init__(self, command_category, CH_regex=None, EN_regex=None):
            prm_objs = self._get_prm_objs(command_category)

            super(param_packer.func_D, self).__init__(command_category, prm_objs, CH_regex, EN_regex)

        def _get_prm_objs(self, command_category):
            if command_category == param_packer.func_D.command_category.DEL_PAIR:
                prm_objs = [parameter(param_packer.func_D.param_category.IS_ID, param_validator.is_not_null, True),  
                            parameter(param_packer.func_D.param_category.ID, param_validator.conv_int_arr, True),  
                            parameter(param_packer.func_D.param_category.WORD, param_validator.conv_unicode_arr, True)]
            else:
                raise UndefinedCommandCategoryException()

            return prm_objs
    
    class func_Q(param_packer_base):
        class command_category(ext.EnumWithName):
            BY_AVAILABLE = 1, '根據可用範圍'
            BY_ID_RANGE = 2, '根據ID範圍'
            BY_UID = 3, '根據製作者'
            BY_GID = 4, '根據群組'
            BY_KEY = 5, '根據關鍵'

        class param_category(ext.EnumWithName):
            AVAILABLE = 1, '可用的'
            GLOBAL = 2, '全域'
            START_ID = 3, '起始ID'
            END_ID = 4, '終止ID'
            UID = 5, '製作者ID'
            GID = 6, '群組ID'
            IS_ID = 7, '根據ID?'
            KEYWORD = 8, '關鍵字'
            ID = 9, 'ID'

        def __init__(self, command_category, CH_regex=None, EN_regex=None):
            prm_objs = self._get_prm_objs(command_category)

            super(param_packer.func_Q, self).__init__(command_category, prm_objs, CH_regex, EN_regex)

        def _get_prm_objs(self, command_category):
            if command_category == param_packer.func_Q.command_category.BY_AVAILABLE:
                prm_objs = [parameter(param_packer.func_Q.param_category.GLOBAL, param_validator.is_not_null, True),
                            parameter(param_packer.func_Q.param_category.AVAILABLE, param_validator.is_not_null, True)]
            elif command_category == param_packer.func_Q.command_category.BY_ID_RANGE:
                prm_objs = [parameter(param_packer.func_Q.param_category.START_ID, param_validator.conv_int_gt_0),  
                            parameter(param_packer.func_Q.param_category.END_ID, param_validator.conv_int_gt_0)]
            elif command_category == param_packer.func_Q.command_category.BY_UID:
                prm_objs = [parameter(param_packer.func_Q.param_category.UID, param_validator.line_bot_api.validate_uid)]
            elif command_category == param_packer.func_Q.command_category.BY_GID:
                prm_objs = [parameter(param_packer.func_Q.param_category.GID, param_validator.line_bot_api.validate_gid_public_global)]
            elif command_category == param_packer.func_Q.command_category.BY_KEY:
                prm_objs = [parameter(param_packer.func_Q.param_category.IS_ID, param_validator.is_not_null, True),  
                            parameter(param_packer.func_Q.param_category.ID, param_validator.conv_int_arr, True),  
                            parameter(param_packer.func_Q.param_category.KEYWORD, param_validator.conv_unicode, True)]
            else:
                raise UndefinedCommandCategoryException()

            return prm_objs
    
    class func_X(param_packer_base):
        class command_category(ext.EnumWithName):
            BY_ID_WORD = 1, '根據ID/字'
            BY_GID = 2, '根據群組'

        class param_category(ext.EnumWithName):
            IS_ID = 1, '根據ID?'
            SOURCE_GID = 2, '來源群組ID'
            TARGET_GID = 3, '目標群組ID'
            ID = 4, '回覆組ID'
            KEYWORD = 5, '關鍵字'
            WITH_PINNED = 6, '包含置頂'

        def __init__(self, command_category, CH_regex=None, EN_regex=None):
            prm_objs = self._get_prm_objs(command_category)

            super(param_packer.func_X, self).__init__(command_category, prm_objs, CH_regex, EN_regex)

        def _get_prm_objs(self, command_category):
            if command_category == param_packer.func_X.command_category.BY_ID_WORD:
                prm_objs = [parameter(param_packer.func_X.param_category.WITH_PINNED, param_validator.is_not_null, True),
                            parameter(param_packer.func_X.param_category.IS_ID, param_validator.is_not_null, True),
                            parameter(param_packer.func_X.param_category.ID, param_validator.conv_int_arr, True),
                            parameter(param_packer.func_X.param_category.KEYWORD, param_validator.conv_unicode_arr, True)]
            elif command_category == param_packer.func_X.command_category.BY_GID:
                prm_objs = [parameter(param_packer.func_X.param_category.SOURCE_GID, param_validator.line_bot_api.validate_gid),
                            parameter(param_packer.func_X.param_category.WITH_PINNED, param_validator.is_not_null, True)]
            else:
                raise UndefinedCommandCategoryException()

            return prm_objs

    class func_X2(param_packer_base):
        class command_category(ext.EnumWithName):
            CLEAR_DATA = 1, '清除關鍵字'

        class param_category(ext.EnumWithName):
            GID = 1, '群組ID'

        def __init__(self, command_category, CH_regex=None, EN_regex=None):
            prm_objs = self._get_prm_objs(command_category)

            super(param_packer.func_X2, self).__init__(command_category, prm_objs, CH_regex, EN_regex)

        def _get_prm_objs(self, command_category):
            if command_category == param_packer.func_X2.command_category.CLEAR_DATA:
                prm_objs = []
            else:
                raise UndefinedCommandCategoryException()

            return prm_objs

    class func_E(param_packer_base):
        class command_category(ext.EnumWithName):
            MOD_LINKED = 1, '修改相關關鍵字'
            MOD_PINNED = 2, '修改置頂'

        class param_category(ext.EnumWithName):
            IS_ID = 1, '根據ID?'
            ID = 2, 'ID陣列'
            KEYWORD = 3, '關鍵字'
            LINKED = 4, '相關關鍵字'
            HAS_LINK = 5, '有/無關'
            NOT_PIN = 6, '不置頂'

        def __init__(self, command_category, CH_regex=None, EN_regex=None):
            prm_objs = self._get_prm_objs(command_category)

            super(param_packer.func_E, self).__init__(command_category, prm_objs, CH_regex, EN_regex)

        def _get_prm_objs(self, command_category):
            if command_category == param_packer.func_E.command_category.MOD_LINKED:
                prm_objs = [parameter(param_packer.func_E.param_category.IS_ID, param_validator.is_not_null, True),
                            parameter(param_packer.func_E.param_category.ID, param_validator.conv_int_arr, True),
                            parameter(param_packer.func_E.param_category.KEYWORD, param_validator.conv_unicode_arr, True),
                            parameter(param_packer.func_E.param_category.LINKED, param_validator.conv_unicode_arr),
                            parameter(param_packer.func_E.param_category.HAS_LINK, param_validator.text_to_bool)]
            elif command_category == param_packer.func_E.command_category.MOD_PINNED:
                prm_objs = [parameter(param_packer.func_E.param_category.IS_ID, param_validator.is_not_null, True),
                            parameter(param_packer.func_E.param_category.ID, param_validator.conv_int_arr, True),
                            parameter(param_packer.func_E.param_category.KEYWORD, param_validator.conv_unicode_arr, True),
                            parameter(param_packer.func_E.param_category.NOT_PIN, param_validator.is_not_null)]
            else:
                raise UndefinedCommandCategoryException()

            return prm_objs

    class func_K(param_packer_base):
        class command_category(ext.EnumWithName):
            RANKING = 1, '排名'

        class param_category(ext.EnumWithName):
            CATEGORY = 1, '種類'
            COUNT = 2, '結果數量'

        def __init__(self, command_category, CH_regex=None, EN_regex=None):
            prm_objs = self._get_prm_objs(command_category)

            super(param_packer.func_K, self).__init__(command_category, prm_objs, CH_regex, EN_regex)

        def _get_prm_objs(self, command_category):
            if command_category == param_packer.func_K.command_category.RANKING:
                prm_objs = [parameter(param_packer.func_K.param_category.CATEGORY, param_validator.special_category.K_ranking_category),
                            parameter(param_packer.func_K.param_category.COUNT, param_validator.conv_int_gt_0, True)]
            else:
                raise UndefinedCommandCategoryException()

            return prm_objs

    class func_P(param_packer_base):
        class command_category(ext.EnumWithName):
            SYSTEM_RECORD = 1, '系統紀錄'
            MESSAGE_RECORD = 2, '訊息量紀錄'

        class param_category(ext.EnumWithName):
            CATEGORY = 1, '種類'
            COUNT = 2, '結果數量'

        def __init__(self, command_category, CH_regex=None, EN_regex=None):
            prm_objs = self._get_prm_objs(command_category)

            super(param_packer.func_P, self).__init__(command_category, prm_objs, CH_regex, EN_regex)

        def _get_prm_objs(self, command_category):
            if command_category == param_packer.func_P.command_category.SYSTEM_RECORD:
                prm_objs = [parameter(param_packer.func_P.param_category.CATEGORY, param_validator.special_category.P_record_category)]
            elif command_category == param_packer.func_P.command_category.MESSAGE_RECORD:
                prm_objs = [parameter(param_packer.func_P.param_category.COUNT, param_validator.conv_int_gt_0, True)]
            else:
                raise UndefinedCommandCategoryException()

            return prm_objs

    class func_P2(param_packer_base):
        class command_category(ext.EnumWithName):
            FIND_PROFILE = 1, '查詢使用者資料'

        class param_category(ext.EnumWithName):
            UID = 1, '使用者ID'

        def __init__(self, command_category, CH_regex=None, EN_regex=None):
            prm_objs = self._get_prm_objs(command_category)

            super(param_packer.func_P2, self).__init__(command_category, prm_objs, CH_regex, EN_regex)

        def _get_prm_objs(self, command_category):
            if command_category == param_packer.func_P2.command_category.FIND_PROFILE:
                prm_objs = [parameter(param_packer.func_P2.param_category.UID, param_validator.line_bot_api.validate_uid)]
            else:
                raise UndefinedCommandCategoryException()

            return prm_objs

    class func_G(param_packer_base):
        class command_category(ext.EnumWithName):
            GROUP_PROFILE = 1, '查詢群組資料'

        class param_category(ext.EnumWithName):
            GID = 1, '群組ID'

        def __init__(self, command_category, CH_regex=None, EN_regex=None):
            prm_objs = self._get_prm_objs(command_category)

            super(param_packer.func_G, self).__init__(command_category, prm_objs, CH_regex, EN_regex)

        def _get_prm_objs(self, command_category):
            if command_category == param_packer.func_G.command_category.GROUP_PROFILE:
                prm_objs = [parameter(param_packer.func_G.param_category.GID, param_validator.line_bot_api.validate_gid)]
            else:
                raise UndefinedCommandCategoryException()

            return prm_objs

    class func_GA(param_packer_base):
        class command_category(ext.EnumWithName):
            SET_RANGE = 1, '設定群組資料範圍'

        class param_category(ext.EnumWithName):
            RANGE = 1, '範圍'

        def __init__(self, command_category, CH_regex=None, EN_regex=None):
            prm_objs = self._get_prm_objs(command_category)

            super(param_packer.func_GA, self).__init__(command_category, prm_objs, CH_regex, EN_regex)

        def _get_prm_objs(self, command_category):
            if command_category == param_packer.func_GA.command_category.SET_RANGE:
                prm_objs = [parameter(param_packer.func_GA.param_category.RANGE, param_validator.line_bot_api.validate_gid)]
            else:
                raise UndefinedCommandCategoryException()

            return prm_objs

    class func_GA2(param_packer_base):
        class command_category(ext.EnumWithName):
            SET_PERMISSION = 1, '設定權限'

        class param_category(ext.EnumWithName):
            UID = 1, '使用者ID'
            PERMISSION = 2, '權限'

        def __init__(self, command_category, CH_regex=None, EN_regex=None):
            prm_objs = self._get_prm_objs(command_category)

            super(param_packer.func_GA2, self).__init__(command_category, prm_objs, CH_regex, EN_regex)

        def _get_prm_objs(self, command_category):
            if command_category == param_packer.func_GA2.command_category.SET_PERMISSION:
                prm_objs = [parameter(param_packer.func_GA2.param_category.UID, param_validator.line_bot_api.validate_uid),
                            parameter(param_packer.func_GA2.param_category.PERMISSION, param_validator.special_category.GA2_permission)]
            else:
                raise UndefinedCommandCategoryException()

            return prm_objs

    class func_GA3(param_packer_base):
        class command_category(ext.EnumWithName):
            ACTIVATE_PUBLIC_DATA = 1, '啟用公用資料庫'

        class param_category(ext.EnumWithName):
            ACTIVATE_TOKEN = 1, '密鑰'

        def __init__(self, command_category, CH_regex=None, EN_regex=None):
            prm_objs = self._get_prm_objs(command_category)

            super(param_packer.func_GA3, self).__init__(command_category, prm_objs, CH_regex, EN_regex)

        def _get_prm_objs(self, command_category):
            if command_category == param_packer.func_GA3.command_category.ACTIVATE_PUBLIC_DATA:
                prm_objs = [parameter(param_packer.func_GA3.param_category.ACTIVATE_TOKEN, param_validator.special_category.GA3_validate_token)]
            else:
                raise UndefinedCommandCategoryException()

            return prm_objs

    class func_H(param_packer_base):
        class command_category(ext.EnumWithName):
            CHANNEL_DATA = 1, '查詢頻道資料'

        class param_category(ext.EnumWithName):
            CHANNEL_ID = 1, '頻道ID'

        def __init__(self, command_category, CH_regex=None, EN_regex=None):
            prm_objs = self._get_prm_objs(command_category)

            super(param_packer.func_H, self).__init__(command_category, prm_objs, CH_regex, EN_regex)

        def _get_prm_objs(self, command_category):
            if command_category == param_packer.func_H.command_category.CHANNEL_DATA:
                prm_objs = [parameter(param_packer.func_H.param_category.CHANNEL_ID, param_validator.line_bot_api.validate_cid, True)]
            else:
                raise UndefinedCommandCategoryException()

            return prm_objs

    class func_SHA(param_packer_base):
        class command_category(ext.EnumWithName):
            CALCULATE_SHA224 = 1, '計算SHA224'

        class param_category(ext.EnumWithName):
            TARGET = 1, '計算目標'

        def __init__(self, command_category, CH_regex=None, EN_regex=None):
            prm_objs = self._get_prm_objs(command_category)

            super(param_packer.func_SHA, self).__init__(command_category, prm_objs, CH_regex, EN_regex)

        def _get_prm_objs(self, command_category):
            if command_category == param_packer.func_SHA.command_category.CALCULATE_SHA224:
                prm_objs = [parameter(param_packer.func_SHA.param_category.TARGET, param_validator.conv_unicode)]
            else:
                raise UndefinedCommandCategoryException()

            return prm_objs

    class func_O(param_packer_base):
        class command_category(ext.EnumWithName):
            OXFORD = 1, '牛津字典'

        class param_category(ext.EnumWithName):
            VOCABULARY = 1, '單字'

        def __init__(self, command_category, CH_regex=None, EN_regex=None):
            prm_objs = self._get_prm_objs(command_category)

            super(param_packer.func_O, self).__init__(command_category, prm_objs, CH_regex, EN_regex)

        def _get_prm_objs(self, command_category):
            if command_category == param_packer.func_O.command_category.OXFORD:
                prm_objs = [parameter(param_packer.func_O.param_category.VOCABULARY, param_validator.conv_unicode_lower)]
            else:
                raise UndefinedCommandCategoryException()

            return prm_objs

    class func_RD(param_packer_base):
        class command_category(ext.EnumWithName):
            TEXT = 1, '文字'
            PROBABILITY = 2, '機率'
            NUM_RANGE = 3, '數字範圍'

        class param_category(ext.EnumWithName):
            COUNT = 1, '次數'
            PROBABILITY = 2, '機率'
            TEXT = 3, '文字'
            START_NUM = 4, '起始數字'
            END_NUM = 5, '終止數字'

        def __init__(self, command_category, CH_regex=None, EN_regex=None):
            prm_objs = self._get_prm_objs(command_category)

            super(param_packer.func_RD, self).__init__(command_category, prm_objs, CH_regex, EN_regex)

        def _get_prm_objs(self, command_category):
            if command_category == param_packer.func_RD.command_category.TEXT:
                prm_objs = [parameter(param_packer.func_RD.param_category.COUNT, param_validator.conv_int_lt_1m, True),
                            parameter(param_packer.func_RD.param_category.TEXT, param_validator.conv_unicode_arr)]
            elif command_category == param_packer.func_RD.command_category.PROBABILITY:
                prm_objs = [parameter(param_packer.func_RD.param_category.PROBABILITY, param_validator.conv_float),
                            parameter(param_packer.func_RD.param_category.COUNT, param_validator.conv_int_lt_1m, True)]
            elif command_category == param_packer.func_RD.command_category.NUM_RANGE:
                prm_objs = [parameter(param_packer.func_RD.param_category.START_NUM, param_validator.conv_int_gt_0),
                            parameter(param_packer.func_RD.param_category.END_NUM, param_validator.conv_int_gt_0),
                            parameter(param_packer.func_RD.param_category.COUNT, param_validator.conv_int_lt_1m, True)]
            else:
                raise UndefinedCommandCategoryException()

            return prm_objs

    class func_L(param_packer_base):
        class command_category(ext.EnumWithName):
            RECENT_DATA = 1, '最近紀錄'

        class param_category(ext.EnumWithName):
            CATEGORY = 1, '種類'

        def __init__(self, command_category, CH_regex=None, EN_regex=None):
            prm_objs = self._get_prm_objs(command_category)

            super(param_packer.func_L, self).__init__(command_category, prm_objs, CH_regex, EN_regex)

        def _get_prm_objs(self, command_category):
            if command_category == param_packer.func_L.command_category.RECENT_DATA:
                prm_objs = [parameter(param_packer.func_L.param_category.CATEGORY, param_validator.special_category.L_category)]
            else:
                raise UndefinedCommandCategoryException()

            return prm_objs

    class func_T(param_packer_base):
        class command_category(ext.EnumWithName):
            ENCODE = 1, '編碼(UTF-8)'

        class param_category(ext.EnumWithName):
            TARGET = 1, '編碼對象'

        def __init__(self, command_category, CH_regex=None, EN_regex=None):
            prm_objs = self._get_prm_objs(command_category)

            super(param_packer.func_T, self).__init__(command_category, prm_objs, CH_regex, EN_regex)

        def _get_prm_objs(self, command_category):
            if command_category == param_packer.func_T.command_category.ENCODE:
                prm_objs = [parameter(param_packer.func_T.param_category.TARGET, param_validator.conv_unicode)]
            else:
                raise UndefinedCommandCategoryException()

            return prm_objs

    class func_C(param_packer_base):
        class command_category(ext.EnumWithName):
            AVAILABLE = 1, '可用'
            CURRENT = 2, '目前匯率'
            HISTORIC = 3, '歷史匯率'
            COVNERT = 4, '匯率轉換'

        class param_category(ext.EnumWithName):
            CURRENCY_SYMBOLS = 1, '貨幣種類'
            DATE = 2, '日期'
            BASE_CURRENCY = 3, '基底貨幣'
            TARGET_CURRENCY = 4, '目標貨幣'
            AMOUNT = 5, '金額'

        def __init__(self, command_category, CH_regex=None, EN_regex=None):
            prm_objs = self._get_prm_objs(command_category)

            super(param_packer.func_C, self).__init__(command_category, prm_objs, CH_regex, EN_regex)

        def _get_prm_objs(self, command_category):
            if command_category == param_packer.func_C.command_category.AVAILABLE:
                prm_objs = []
            elif command_category == param_packer.func_C.command_category.CURRENT:
                prm_objs = [parameter(param_packer.func_C.param_category.CURRENCY_SYMBOLS, param_validator.special_category.C_validate_currency_symbols)]
            elif command_category == param_packer.func_C.command_category.HISTORIC:
                prm_objs = [parameter(param_packer.func_C.param_category.DATE, param_validator.special_category.C_validate_date),
                            parameter(param_packer.func_C.param_category.CURRENCY_SYMBOLS, param_validator.special_category.C_validate_currency_symbols, True)]
            elif command_category == param_packer.func_C.command_category.COVNERT:
                prm_objs = [parameter(param_packer.func_C.param_category.BASE_CURRENCY, param_validator.special_category.C_validate_currency_symbol),
                            parameter(param_packer.func_C.param_category.AMOUNT, param_validator.conv_int_gt_0, True),
                            parameter(param_packer.func_C.param_category.TARGET_CURRENCY, param_validator.special_category.C_validate_currency_symbol)]
            else:
                raise UndefinedCommandCategoryException()

            return prm_objs

    class func_FX(param_packer_base):
        class command_category(ext.EnumWithName):
            POLYNOMIAL_FACTORIZATION = 1, '因式分解'
            SOLVE = 2, '解方程式'

        class param_category(ext.EnumWithName):
            FORMULA = 1, '方程'
            VARIABLE = 2, '變數'

        def __init__(self, command_category, CH_regex=None, EN_regex=None):
            prm_objs = self._get_prm_objs(command_category)

            super(param_packer.func_FX, self).__init__(command_category, prm_objs, CH_regex, EN_regex)

        def _get_prm_objs(self, command_category):
            if command_category == param_packer.func_FX.command_category.POLYNOMIAL_FACTORIZATION:
                prm_objs = [parameter(param_packer.func_FX.param_category.FORMULA, param_validator.special_category.FX_validate_formulas)]
            elif command_category == param_packer.func_FX.command_category.SOLVE:
                prm_objs = [parameter(param_packer.func_FX.param_category.FORMULA, param_validator.special_category.FX_validate_formulas),
                            parameter(param_packer.func_FX.param_category.VARIABLE, param_validator.conv_unicode)]
            else:
                raise UndefinedCommandCategoryException()

            return prm_objs

    class func_W(param_packer_base):
        class command_category(ext.EnumWithName):
            DATA_CONTROL = 1, '資料控制'
            ID_SEARCH = 2, '搜尋ID'

        class param_category(ext.EnumWithName):
            KEYWORD = 1, '城市關鍵字'
            CITY_ID = 2, '城市ID'
            OUTPUT_TYPE = 3, '輸出資料種類'
            HOUR_RANGE = 4, '範圍(小時)'
            FREQUENCY = 5, '頻率(小時)'
            ACTION = 6, '動作'

        def __init__(self, command_category, CH_regex=None, EN_regex=None):
            prm_objs = self._get_prm_objs(command_category)

            super(param_packer.func_W, self).__init__(command_category, prm_objs, CH_regex, EN_regex)

        def _get_prm_objs(self, command_category):
            if command_category == param_packer.func_W.command_category.DATA_CONTROL:
                prm_objs = [parameter(param_packer.func_W.param_category.ACTION, param_validator.special_category.W_action),
                            parameter(param_packer.func_W.param_category.CITY_ID, param_validator.conv_int_arr),
                            parameter(param_packer.func_W.param_category.OUTPUT_TYPE, param_validator.special_category.W_output_type),
                            parameter(param_packer.func_W.param_category.HOUR_RANGE, param_validator.conv_int_gt_0),
                            parameter(param_packer.func_W.param_category.FREQUENCY, param_validator.conv_int_gt_0)]
            elif command_category == param_packer.func_W.command_category.ID_SEARCH:
                prm_objs = [parameter(param_packer.func_W.param_category.KEYWORD, param_validator.conv_unicode)]
            else:
                raise UndefinedCommandCategoryException()

            return prm_objs

    class func_DL(param_packer_base):
        class command_category(ext.EnumWithName):
            DOWNLOAD_STICKER_PACKAGE = 1, '下載貼圖圖包'

        class param_category(ext.EnumWithName):
            PACKAGE_ID = 1, '圖包ID'
            INCLUDE_SOUND = 2, '含聲音'

        def __init__(self, command_category, CH_regex=None, EN_regex=None):
            prm_objs = self._get_prm_objs(command_category)

            super(param_packer.func_DL, self).__init__(command_category, prm_objs, CH_regex, EN_regex)

        def _get_prm_objs(self, command_category):
            if command_category == param_packer.func_DL.command_category.DOWNLOAD_STICKER_PACKAGE:
                prm_objs = [parameter(param_packer.func_DL.param_category.PACKAGE_ID, param_validator.valid_int),
                            parameter(param_packer.func_DL.param_category.INCLUDE_SOUND, param_validator.is_not_null)]
            else:
                raise UndefinedCommandCategoryException()

            return prm_objs

    class func_STK(param_packer_base):
        class command_category(ext.EnumWithName):
            RANKING = 1, '排行'
            STICKER_LOOKUP = 2, '貼圖圖片'

        class param_category(ext.EnumWithName):
            CATEGORY = 1, '種類'
            HOUR_RANGE = 2, '範圍(小時)'
            COUNT = 3, '範圍(名次)'
            STICKER_ID = 4, '貼圖ID'

        def __init__(self, command_category, CH_regex=None, EN_regex=None):
            prm_objs = self._get_prm_objs(command_category)

            super(param_packer.func_STK, self).__init__(command_category, prm_objs, CH_regex, EN_regex)

        def _get_prm_objs(self, command_category):
            if command_category == param_packer.func_STK.command_category.RANKING:
                prm_objs = [parameter(param_packer.func_STK.param_category.CATEGORY, param_validator.special_category.STK_action_category),
                            parameter(param_packer.func_STK.param_category.HOUR_RANGE, param_validator.conv_int_gt_0),
                            parameter(param_packer.func_STK.param_category.COUNT, param_validator.conv_int_gt_0)]
            elif command_category == param_packer.func_STK.command_category.STICKER_LOOKUP:
                prm_objs = [parameter(param_packer.func_STK.param_category.STICKER_ID, param_validator.valid_int)]
            else:
                raise UndefinedCommandCategoryException()

            return prm_objs

class packer_factory(object):
    _S = [param_packer.func_S(command_category=param_packer.func_S.command_category.DB_COMMAND,
                              CH_regex=ur'小水母 DB ?資料庫((?:.|\n)+)(?<! ) ?主指令((?:.|\n)+)(?<! ) ?主參數((?:.|\n)+)(?<! ) ?參數((?:.|\n)+)(?<! )', 
                              EN_regex=ur'JC\nS\n(.+(?<! ))\n(.+(?<! ))\n(.+(?<! ))\n(.+(?<! ))')]

    _M = [param_packer.func_A(command_category=param_packer.func_A.command_category.ADD_PAIR_CH,
                              CH_regex=ur'小水母 置頂 ?(?:\s|附加((?:.|\n)+)(?<! ))? ?(收到 ?((?:.|\n)+)(?<! )|看到 ?([0-9a-f]{56})|被貼 ?(\d+)) ?(回答 ?((?:.|\n)+)(?<! )|回圖 ?(https://(?:.|\n)+)|回貼 ?(\d+))'),
          param_packer.func_A(command_category=param_packer.func_A.command_category.ADD_PAIR_EN,
                              EN_regex=ur'JC\nM\n(T\n(.+)|S\n(\d+)|P\n([0-9a-f]{56}))\n(T\n(.+)|S\n(\d+)|P\n(https://.+))(?:\n(.+))?'),
          param_packer.func_A(command_category=param_packer.func_A.command_category.ADD_PAIR_AUTO_CH,
                              CH_regex=ur'小水母 置頂 ?(?:\s|附加((?:.|\n)+)(?<! ))? ?(?:入 ?((?:.|\n)+)(?<! )) ?(?:出 ?((?:.|\n)+)(?<! ))'),
          param_packer.func_A(command_category=param_packer.func_A.command_category.ADD_PAIR_AUTO_EN,
                              EN_regex=ur'JC\nMM\n(.+)\n(.+)(?:\n(.+))?')]

    _A = [param_packer.func_A(command_category=param_packer.func_A.command_category.ADD_PAIR_CH,
                              CH_regex=ur'小水母 記住 ?(?:\s|附加((?:.|\n)+)(?<! ))? ?(收到 ?((?:.|\n)+)(?<! )|看到 ?([0-9a-f]{56})|被貼 ?(\d+)) ?(回答 ?((?:.|\n)+)(?<! )|回圖 ?(https://(?:.|\n)+)|回貼 ?(\d+))'),
          param_packer.func_A(command_category=param_packer.func_A.command_category.ADD_PAIR_EN,
                              EN_regex=ur'JC\nA\n(T\n(.+)|S\n(\d+)|P\n([0-9a-f]{56}))\n(T\n(.+)|S\n(\d+)|P\n(https://.+))(?:\n(.+))?'),
          param_packer.func_A(command_category=param_packer.func_A.command_category.ADD_PAIR_AUTO_CH,
                              CH_regex=ur'小水母 記住 ?(?:\s|附加((?:.|\n)+)(?<! ))? ?(?:入 ?((?:.|\n)+)(?<! )) ?(?:出 ?((?:.|\n)+)(?<! ))'),
          param_packer.func_A(command_category=param_packer.func_A.command_category.ADD_PAIR_AUTO_EN,
                              EN_regex=ur'JC\nAA\n(.+)\n(.+)(?:\n(.+))?')]

    _R = [param_packer.func_D(command_category=param_packer.func_D.command_category.DEL_PAIR,
                              CH_regex=ur'小水母 忘記置頂的 ?(?:(ID ?)(\d{1}[\d\s]*)|((?:.|\n)+))', 
                              EN_regex=ur'JC\nR\n?(?:(ID\n)(\d{1}[\d\s]*)|(.+))')]

    _D = [param_packer.func_D(command_category=param_packer.func_D.command_category.DEL_PAIR,
                              CH_regex=ur'小水母 忘記 ?(?:(ID ?)(\d{1}[\d\s]*)|((?:.|\n)+))', 
                              EN_regex=ur'JC\nD\n?(?:(ID\n)(\d{1}[\d\s]*)|(.+))')]

    _Q = [param_packer.func_Q(command_category=param_packer.func_Q.command_category.BY_AVAILABLE,
                              CH_regex=ur'小水母 找 ?(?:(全部)|(可以用的))',
                              EN_regex=ur'JC\n(?:(Q\nALL)|(Q))'),
          param_packer.func_Q(command_category=param_packer.func_Q.command_category.BY_ID_RANGE,
                              CH_regex=ur'小水母 找 ?ID範圍 ?(\d+)(?:到|~)(\d+)',
                              EN_regex=ur'JC\nQ\nID\n(\d+)\n(\d+)'),
          param_packer.func_Q(command_category=param_packer.func_Q.command_category.BY_UID,
                              CH_regex=ur'小水母 找 ?([U]{1}[0-9a-f]{32}) ?做的',
                              EN_regex=ur'JC\nQ\nUID\n([U]{1}[0-9a-f]{32})'),
          param_packer.func_Q(command_category=param_packer.func_Q.command_category.BY_GID,
                              CH_regex=ur'小水母 找 ?([CR]{1}[0-9a-f]{32}|PUBLIC|GLOBAL) ?裡面的',
                              EN_regex=ur'JC\nQ\nGID\n([CR]{1}[0-9a-f]{32}|PUBLIC|GLOBAL)'),
          param_packer.func_Q(command_category=param_packer.func_Q.command_category.BY_KEY,
                              CH_regex=ur'小水母 找 ?(?:(ID ?)(\d{1}[\d\s]*)|((?:.|\n)+))',
                              EN_regex=ur'JC\nQ\n(?:(ID\n)(\d{1}[\d\s]*)|(.+))')]

    _I = [param_packer.func_Q(command_category=param_packer.func_Q.command_category.BY_AVAILABLE,
                              CH_regex=ur'小水母 詳細找 ?(?:(全部)|(可以用的))',
                              EN_regex=ur'JC\n(?:(I\nALL)|(I))'),
          param_packer.func_Q(command_category=param_packer.func_Q.command_category.BY_ID_RANGE,
                              CH_regex=ur'小水母 詳細找 ?ID範圍 ?(\d+)(?:到|~)(\d+)',
                              EN_regex=ur'JC\nI\nID\n(\d+)\n(\d+)'),
          param_packer.func_Q(command_category=param_packer.func_Q.command_category.BY_UID,
                              CH_regex=ur'小水母 詳細找 ?([U]{1}[0-9a-f]{32}) ?做的',
                              EN_regex=ur'JC\nI\nUID\n([U]{1}[0-9a-f]{32})'),
          param_packer.func_Q(command_category=param_packer.func_Q.command_category.BY_GID,
                              CH_regex=ur'小水母 詳細找 ?([CR]{1}[0-9a-f]{32}|PUBLIC|GLOBAL) ?裡面的',
                              EN_regex=ur'JC\nI\nGID\n([CR]{1}[0-9a-f]{32}|PUBLIC|GLOBAL)'),
          param_packer.func_Q(command_category=param_packer.func_Q.command_category.BY_KEY,
                              CH_regex=ur'小水母 詳細找 ?(?:(ID ?)(\d{1}[\d\s]*)|((?:.|\n)+))',
                              EN_regex=ur'JC\nI\n(?:(ID\n)(\d{1}[\d\s]*)|(.+))')]

    _X = [param_packer.func_X(command_category=param_packer.func_X.command_category.BY_ID_WORD,
                              CH_regex=ur'小水母 複製 ?( ?包含置頂)? ?(?:(ID ?)(\d{1}[\d\s]*)|((?:.|\n)+))',
                              EN_regex=ur'JC\nX\n(?:(P)\n)?(?:(ID)\n(\d{1}[\d\s]*)|(.+))'),
          param_packer.func_X(command_category=param_packer.func_X.command_category.BY_ID_WORD,
                              CH_regex=ur'小水母 複製群組([CR]{1}[0-9a-f]{32})?裡面的( ?包含置頂)?',
                              EN_regex=ur'JC\nX\nGID\n([CR]{1}[0-9a-f]{32})\n?(P)?')]

    _X2 = [param_packer.func_X2(command_category=param_packer.func_X2.command_category.CLEAR_DATA,
                                CH_regex=ur'小水母 清除所有回覆組571a95ae875a9ae315fad8cdf814858d9441c5ec671f0fb373b5f340',
                                EN_regex=ur'JC\nX2\n571a95ae875a9ae315fad8cdf814858d9441c5ec671f0fb373b5f340')]

    _E = [param_packer.func_E(command_category=param_packer.func_E.command_category.MOD_LINKED,
                              CH_regex=ur'小水母 修改 ?(?:(ID ?)(\d{1}[\d\s]*)|((?:.|\n)+))跟((?:.|\n)+)(無|有)關',
                              EN_regex=ur'JC\nE\n(?:(ID)\n(\d{1}[\d\s]*)|((?:.|\n)+))\n((?:.|\n)+)\n(O|X)'),
          param_packer.func_E(command_category=param_packer.func_E.command_category.MOD_PINNED,
                              CH_regex=ur'小水母 修改 ?(?:(ID ?)(\d{1}[\d\s]*)|((?:.|\n)+))(不)?置頂',
                              EN_regex=ur'JC\nE\n(?:(ID)\n(\d{1}[\d\s]*)|((?:.|\n)+))\n(N)?P')]

    _K = [param_packer.func_K(command_category=param_packer.func_K.command_category.RANKING,
                              CH_regex=ur'小水母 排名(使用者|回覆組|使用過的) ?(?:前([1-9]\d?)名)?',
                              EN_regex=ur'JC\nK\n(USER|KWRC|KW)(?:\n?([1-9]\d?))?')]

    _P = [param_packer.func_P(command_category=param_packer.func_P.command_category.MESSAGE_RECORD,
                              CH_regex=ur'小水母 系統訊息前([1-9]\d?)名',
                              EN_regex=ur'JC\nP\nMSG(?:\n([1-9]\d?))?'),
          param_packer.func_P(command_category=param_packer.func_P.command_category.SYSTEM_RECORD,
                              CH_regex=ur'小水母 系統(自動回覆|資訊|圖片|匯率|黑名單)',
                              EN_regex=ur'JC\nP\n(KW|SYS|IMG|EXC|BAN)')]

    _P2 = [ur'小水母 使用者 ?([U]{1}[0-9a-f]{32}) ?的資料']

    _G = [ur'小水母 群組([CR]{1}[0-9a-f]{32})?的資料']

    _GA = [ur'小水母 當(啞巴|機器人|服務員|八嘎囧)']

    _GA2 = [ur'小水母 讓 ?([U]{1}[0-9a-f]{32}) ?變成(可憐兒|一般人|副管|管理員)']

    _GA3 = [(ur'小水母 啟用公用資料庫([A-Z0-9]{40})', ur'JC\nGA3\n([A-Z0-9]{40})')]

    _H = [(ur'小水母 頻道資訊', ur'JC\nH')]

    _SHA = [(ur'小水母 雜湊SHA ?(.*)', ur'JC\nSHA\n(.*)')]

    _O = [param_packer.func_O(command_category=param_packer.func_O.command_category.OXFORD,
                              CH_regex=ur'小水母 查 ?([\w\s]+)',
                              EN_regex=ur'JC\nO\n([\w\s]+)')]

    _RD = [(ur'小水母 抽 ?(([\d\.]{1,})%) ?((\d{1,6})次)?', ur'JC\nRD\n(([\d\.]{1,})%)(\n(\d{1,6}))?'), 
           (ur'小水母 抽 ?((\d{1,6})次)? ?((?:.|\n)+)', ur'JC\nRD(\n(\d{1,6}))?\n((?:.|\n)+)'),
           ur'小水母 抽 ?(\d+)(到|~)(\d+)']

    _L = [(ur'小水母 最近的(貼圖|圖片|回覆組|發送者|訊息)', ur'JC\nL\n(S|P|R|U|M)')]

    _T = [(ur'小水母 編碼((?:.|\n)+)', ur'JC\nT\n((?:.|\n)+)')]

    _C = [ur'小水母 匯率(可用)?', 
          ur'小水母 匯率([A-Z ]{3,})', 
          ur'小水母 匯率((1999|20\d{2})(0[1-9]|1[1-2])([0-2][1-9]|3[0-1]))(時的([A-Z ]{3,}))?', 
          (ur'小水母 匯率([A-Z]{3}) ([\d\.]+) ?轉成 ?([A-Z]{3})', ur'JC\nC\n([A-Z]{3})\n([\d\.]+)\n([A-Z]{3})')]

    _FX = [ur'小水母 解因式分解 ?([!$%^&*()_+|~\-=`{}\[\]:\";\'<>\?,\./0-9A-Za-z]+)', 
           ur'小水母 解方程式 ?(變數((?:.|\n)+)(?<! )) ?(方程式([!$%^&*()_+|~\-\n=`{}\[\]:\";\'<>\?,\./0-9A-Za-z和]+))']

    _W = [ur'小水母 天氣ID查詢 ?([\w\s]+)', 
          ur'小水母 天氣(查詢|記錄|刪除) ?([\d\s]+) ?(詳|簡)? ?((\d+)小時內)? ?(每(\d+)小時)?']

    _DL = [(ur'小水母 下載貼圖圖包 ?(\d+) ?(含聲音)?', ur'JC\nDL\n(\d+)(S)?')]

    _STK = [ur'小水母 貼圖(圖包)?排行 ?(前(\d+)名)? ?((\d+)小時內)?', 
            (ur'小水母 貼圖(\d+)', ur'JC\nSTK\n(\d+)')]

class UndefinedCommandCategoryException(Exception):
    def __init__(self, *args):
        return super(UndefinedCommandCategoryException, self).__init__(*args)

class UndefinedParameterException(Exception):
    def __init__(self, *args):
        return super(UndefinedParameterException, self).__init__(*args)

class UndefinedPackedStatusException(Exception):
    def __init__(self, *args):
        return super(UndefinedPackedStatusException, self).__init__(*args)

class UndefinedTextException(Exception):
    def __init__(self, *args):
        return super(UndefinedTextException, self).__init__(*args)