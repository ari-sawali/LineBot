# -*- coding: utf-8 -*-

import error, bot, tool

from .base import db_base, dict_like_mapping

DB_NAME = 'sys'

class weather_report_config(db_base):
    COLLECTION_NAME = 'weather_cfg'

    def __init__(self, mongo_db_uri):
        super(weather_report_config, self).__init__(mongo_db_uri, DB_NAME, weather_report_config.COLLECTION_NAME, False)

    def add_config(self, uid, city_id, mode=tool.weather.output_config.SIMPLE, interval=3, data_range=120):
        """Return result in string"""
        if not bot.line_api_wrapper.is_valid_user_id(uid):
            return error.error.line_bot_api.illegal_user_id(uid)

        weather_report_config_data.init_by_field(uid, weather_report_child_config.init_by_field(city_id, mode, interval, data_range))

class weather_report_config_data(dict_like_mapping):
    """\
    {
        USER_ID: STRING - INDEX,
        CONFIG: [ CONFIG_DATA, CONFIG_DATA... ]
    }\
    """
    USER_ID = 'uid'
    CONFIG = 'cfg'

    @staticmethod
    def init_by_field(uid, config=None):
        init_dict = {
            weather_report_config_data.USER_ID: uid,
            weather_report_config_data.CONFIG: config if config is not None else []
        }
        
        return weather_report_config_data(init_dict)

    def __init__(self, org_dict):
        if not all(k in org_dict for k in (weather_report_config_data.USER_ID, weather_report_config_data.CONFIG)):
            raise ValueError('Incomplete dictionary. {}'.format(org_dict))

        super(weather_report_config_data, self).__init__(org_dict)

    @property
    def uid(self):
        return self[weather_report_config_data.USER_ID]

    @property
    def config(self):
        return self[weather_report_config_data.CONFIG]

class weather_report_child_config(dict_like_mapping):
    """\
    {
        CITY_ID: INTEGER, 
        MODE: OUTPUT_CONFIG,
        INTERVAL: INTEGER,
        DATA_RANGE: INTEGER
    }\
    """
    CITY_ID = 'c'
    MODE = 'm'
    INTERVAL = 'i'
    DATA_RANGE = 'r'

    @staticmethod
    def init_by_field(city_id, mode, interval, data_range_hr):
        init_dict = {
            weather_report_child_config.CITY_ID: city_id,
            weather_report_child_config.MODE: mode,
            weather_report_child_config.INTERVAL: interval,
            weather_report_child_config.DATA_RANGE: data_range_hr,
        }
        
        return weather_report_child_config(init_dict)

    def __init__(self, org_dict):
        if not all(k in org_dict for k in (weather_report_child_config.CITY_ID, weather_report_child_config.MODE, weather_report_child_config.INTERVAL, weather_report_child_config.DATA_RANGE)):
            raise ValueError('Incomplete dictionary. {}'.format(org_dict))

        super(weather_report_config_data, self).__init__(org_dict)
        
    @property
    def city_id(self):
        return self[weather_report_child_config.CITY_ID]

    @property
    def mode(self):
        return self[weather_report_child_config.MODE]

    @property
    def interval(self):
        return self[weather_report_child_config.INTERVAL]

    @property
    def data_range(self):
        return self[weather_report_child_config.DATA_RANGE]

    