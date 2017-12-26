# -*- coding: utf-8 -*-

import ast
import re

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

    from bot import config_manager

    ARRAY_SEPARATOR = config_manager('SystemConfig.ini').get(bot.config_category.KEYWORD_DICT, bot.config_category_kw_dict.ARRAY_SEPARATOR)

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

        if re.match(ur'[0-9a-fA-F]{56}', obj):
            return param_validator.conv_unicode(obj, allow_null)
        else:
            return param_validation_result(error.sys_command.must_sha(obj), False)

    @staticmethod
    def conv_int(obj, allow_null):
        base = param_validator.base_null(obj, allow_null)
        if base is not None:
            return base

        new_int = ext.to_int(obj)

        if new_int is not None:
            return param_validation_result(new_int, True)
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
            return param_validation_result(new_int, False)
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
    def is_not_null(obj, allow_null):
        return param_validation_result(obj is not None, True)

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
            elif param_validator.conv_int(obj, allow_null).valid:
                ret = db.word_type.STICKER
            elif param_validator.conv_unicode(obj, allow_null).valid:
                ret = db.word_type.TEXT
            else:
                return param_validation_result(u'Object cannot be determined to any type. ({})'.format(obj), False)

            return param_validation_result(ret, True)

    class line_bot_api(object):
        @staticmethod
        def validate_uid(obj, allow_null):
            base = param_validator.base_null(obj, allow_null)
            if base is not None:
                return base

            return param_validation_result(obj, bot.line_api_wrapper.is_valid_user_id(obj))

        @staticmethod
        def validate_gid_public_global(obj, allow_null):
            base = param_validator.base_null(obj, allow_null)
            if base is not None:
                return base
            
            return param_validation_result(obj, bot.line_api_wrapper.is_valid_room_group_id(obj, True, True))

class param_validation_result(ext.action_result):
    def __init__(self, ret, valid):
        super(param_validation_result, self).__init__(ret, valid)

    @property
    def ret(self):
        return self._result

    @property
    def valid(self):
        return self._success

class UndefinedCommandCategoryException(Exception):
    def __init__(self, *args):
        return super(UndefinedCommandCategoryException, self).__init__(*args)

class UndefinedParameterException(Exception):
    def __init__(self, *args):
        return super(UndefinedParameterException, self).__init__(*args)

class UndefinedPackedStatusException(Exception):
    def __init__(self, *args):
        return super(UndefinedPackedStatusException, self).__init__(*args)
