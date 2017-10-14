# -*- coding: utf-8 -*-

import time

class error(object):
    user_manual_url = 'https://sites.google.com/view/jellybot'

    class webpage(object):

        @staticmethod
        def no_content_at_time(content_type, timestamp):
            return u'在指定的時間沒有{}的紀錄。 ({})'.format(content_type, time.strftime('%Y-%m-%d %H:%M:%S (%Z)', time.localtime(timestamp)))

        @staticmethod
        def no_content():
            return u'沒有內容。.'

    class main(object):
        @staticmethod
        def incorrect_password_or_insufficient_permission():
            return u'密碼錯誤或權限不足。'

        @staticmethod
        def invalid_thing(name_of_thing, thing):
            return u'不合法的{}: {}。請查看使用說明書( {} )。'.format(name_of_thing, thing, error.user_manual_url)
        
        @staticmethod
        def invalid_thing_with_correct_format(name_of_thing, correct_format, thing):
            return u'不合法的{nt}: {t}。{nt}應為{fmt}。詳情請查看使用說明書( {um} )。'.format(nt=name_of_thing, t=thing, fmt=correct_format, um=error.user_manual_url)

        @staticmethod
        def lack_of_thing(name_of_thing):
            return u'缺少{nm}。請修正您所提供的{nm}成正確的格式。詳細說明請參閱使用說明書( {um} )'.format(nm=name_of_thing, um=error.user_manual_url)

        @staticmethod
        def no_result():
            return u'無結果。'

        @staticmethod
        def restricted(permission=None):
            return u'已限制的功能。{}'.format(
                u'\n需求權限: {}+\n\n權限相關說明請參閱使用說明書( {} )'.format(permission, error.user_manual_url) if permission is not None else u'')

        @staticmethod
        def incorrect_channel(available_in_1v1=True, available_in_room=False, available_in_group=False):
            return u'無法於此類型的頻道使用。請至下列頻道:\n{} {} {}\n詳細使用說明請參閱使用說明書( {} )'.format(
                u'[ 私訊 ]' if available_in_1v1 else u'[ - ]',
                u'[ 群組 ]' if available_in_group else u'[ - ]',
                u'[ 房間 ]' if available_in_room else u'[ - ]',
                error.user_manual_url)

        @staticmethod
        def incorrect_param(param_name, correct):
            return u'無法辨認。如果要使用這個功能，{}必須為{}。詳細使用方法請參閱使用說明書( {} )。'.format(param_name, correct, error.user_manual_url)

        @staticmethod
        def unable_to_determine():
            return u'無法判斷指令，請檢閱使用說明書( {} )。'.format(error.user_manual_url)

        @staticmethod
        def pair_not_exist_or_insuffieicnt_permission():
            return u'回覆組不存在，或字組改變權限不足。權限相關說明請參閱使用說明書( {} )。'.format(error.user_manual_url)

        @staticmethod
        def invalid_length(thing, length):
            return u'長度不符。{}的長度應為{}。'.format(thing, length)

        @staticmethod
        def unable_to_receive_user_id():
            return u'因LINE政策問題，如果要使用這個功能的話，請先將LINE更新到v7.5.0以上，或是在私訊頻道中重試。\n\n詳細說明請點此查看: https://developers.line.me/messaging-api/obtaining-user-consent'

        @staticmethod
        def line_account_data_not_found():
            return u'無對應LINE帳號資料。'

        @staticmethod
        def user_name_not_found():
            return u'找不到使用者名稱。'

        @staticmethod
        def text_length_too_long(url):
            return u'因文字內容長度超過LINE Messaging API的最大字數限制(2000字)，故無法顯示。請點下列網址查看完整內容。\n{}'.format(url)

        @staticmethod
        def miscellaneous(content):
            return u'{}\n\n小水母使用說明: {}'.format(content, error.user_manual_url)

    class string_calculator(object):
        @staticmethod
        def result_is_not_numeric(org_text=None):
            return u'計算結果為非數字型態，請重新檢查輸入的算式是否正確。{}'.format(
                '' if org_text is None else '\n資料型態: {}\n原始字串: {}'.format(type(org_text), org_text))

        @staticmethod
        def error_on_calculating(ex):
            return u'發生錯誤，計算失敗。\n錯誤訊息: {}'.format(ex.message)

        @staticmethod
        def calculation_timeout(timeout_sec, org_text=None):
            return u'因計算超時({}秒)，故終止運算。請嘗試拆解算式以後重新計算。{}'.format(
                timeout_sec,
                u'' if org_text is None else u'\n資料型態: {}\n原始字串: {}'.format(type(org_text), org_text))

        @staticmethod
        def wrong_format_to_calc_equations():
            return u'方程式計算格式錯誤。請確認輸入格式為:\n第一行 - 有使用的變數，以逗號分隔(例: x, y)\n第二行以後 - 方程式，例如:\n  2x+3y=7\n  5x+8=9'

        @staticmethod
        def overflow(org_text=None):
            return u'發生溢位。請嘗試拆解算式以後重新計算。{}'.format(
                u'' if org_text is None else u'\n原始字串: {}'.format(org_text))

        @staticmethod
        def unknown_calculate_type():
            return u'無法辨認要使用的計算項目。正確格式請參閱使用說明書( {} )'.format(error.user_manual_url)