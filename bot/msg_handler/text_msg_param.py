# -*- coding: utf-8 -*-

import ast

from error import error
import ext

class param_packer_base(object):
    def __init__(self, CH_regex, EN_regex, command_category, param_objs):
        """
        Parameters:
            CH_regex: chinese regex to check.
            EN_regex: english regex to check.
            command_category: category of the command.
            param_field: enum of parameter object in list.
        """
        self._CH = CH_regex
        self._EN = EN_regex
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
                    return param_packing_result(validate_result.ret, param_packing_result_status.ERROR_IN_PARAM)

            return param_packing_result(p_dict, param_packing_result_status.ALL_PASS)
        else:
            return param_packing_result(p_dict, param_packing_result_status.NO_MATCH)

class param_packing_result_status(ext.EnumWithName):
    ALL_PASS = 1, '全通過'
    ERROR_IN_PARAM = 2, '參數有誤'
    NO_MATCH = 3, '無符合'

class param_packing_result(object):
    def __init__(self, result, status):
        self._result = result
        self._status = status

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
    def __init__(self, field_enum, validator_method):
        """
        Parameter:
            field_enum: Enum that represents this field.
            validator_method: Method to validate the parameter. If the method is not come from param_validator, the action may be unexpected.
        """
        self._field_enum = field_enum
        self._validator = validator_method

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
        return self._validator(content)

class param_validator(object):
    """
    Meta:
        Must be @staticmethod.

    Input:
        obj: parameter object (usually string) to validate.

    Returns:
        param_check_result. Ret of result may be an error message, or processed parameter.
    """

    @staticmethod
    def check_dict(obj):
        try:
            obj = ast.literal_eval(obj)

            if not isinstance(obj, dict):
                return param_validation_result(error.main.miscellaneous(u'輸入參數必須是合法dictionary型別。({})'.format(type(obj))), False)

            return param_validation_result(obj, True)
        except ValueError as ex:
            return param_validation_result(error.main.miscellaneous(u'字串型別分析失敗。\n{}\n\n訊息: {}'.format(prm_dict, ex.message)), False)

    @staticmethod
    def conv_unicode(obj):
        try:
            return param_validation_result(unicode(obj), True)
        except Exception as ex:
            return param_validation_result(u'{} - {}'.format(type(ex), ex.message), False)

class param_validation_result(object):
    def __init__(self, ret, valid):
        self._ret = ret
        self._valid = valid

    @property
    def ret(self):
        return self._ret

    @property
    def valid(self):
        return self._valid

class UndefinedCommandCategoryException(Exception):
    def __init__(self, *args):
        return super(UndefinedCommandCategoryException, self).__init__(*args)

class UndefinedPackedStatusException(Exception):
    def __init__(self, *args):
        return super(UndefinedPackedStatusException, self).__init__(*args)
