# -*- coding: utf-8 -*-

from ConfigParser import SafeConfigParser
import ext

class config_category(ext.EnumWithName):
    KEYWORD_DICT = 0, 'KeywordDictionary'
    TIMEOUT = 1, 'Timeout'
    STICKER_RANKING = 2, 'StickerRanking'
    SYSTEM = 3, 'System'

class config_category_kw_dict(ext.EnumWithName):
    CREATE_DUPLICATE = 0, 'PossibleDuplicateCDSeconds'
    REPEAT_CALL = 1, 'RepeatCallCDSeconds'
    ARRAY_SEPARATOR = 2, 'InLineArraySeparator'
    MAX_QUERY_OUTPUT_COUNT = 3, 'MaxQueryOutputCount'
    MAX_SIMPLE_STRING_LENGTH = 4, 'MaxSimpleStringLength'
    MAX_INFO_OUTPUT_COUNT = 5, 'MaxInfoOutputCount'
    MAX_MESSAGE_TRACK_OUTPUT_COUNT = 6, 'MaxMessageTrackOutputCount'
    DEFAULT_RANK_RESULT_COUNT = 7, 'DefaultRankResultCount'

class config_category_timeout(ext.EnumWithName):
    CALCULATOR = 0, 'Calculator'

class config_category_sticker_ranking(ext.EnumWithName):
    LIMIT_COUNT = 0, 'LimitCount'
    HOUR_RANGE = 1, 'HourRange'

class config_category_system(ext.EnumWithName):
    DUPLICATE_CONTENT_BAN_COUNT = 0, 'DuplicateContentBanCount'

class config_manager(object):
    def __init__(self, file_path):
        self._parser = SafeConfigParser()
        self._parser.read(file_path)

    def get(self, cat_enum, key_enum):
        config = self._parser.get(str(cat_enum), str(key_enum))
        if config.startswith('"') and config.endswith('"'):
            config = config[1:-1]

        return config

    def getint(self, cat_enum, key_enum):
        return self._parser.getint(str(cat_enum), str(key_enum))


