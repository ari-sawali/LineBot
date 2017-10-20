# -*- coding: utf-8 -*-

# TODO: print error message -> field

import pymongo
from .base import db_base, dict_like_mapping, SYSTEM_DATABASE_NAME

class system_config(db_base):
    COLLECTION_NAME = 'config'

    def __init__(self, mongo_db_uri):
        super(system_config, self).__init__(mongo_db_uri, SYSTEM_DATABASE_NAME, system_config.COLLECTION_NAME, False)
        self._cache = None

    def set(self, field_var, setting_bool):
        """Return changed data."""
        if self._cache is None:
            self._set_cache()

        self._cache.set(field_var, setting_bool)
        print field_var
        print setting_bool
        print self._cache
        return config_data(self.find_one_and_update({}, { '$set': self._cache }, None, None, True, pymongo.ReturnDocument.AFTER))

    def get(self, field_var):
        if self._cache is None:
            self._set_cache()

        return self._cache.get(field_var)

    def _set_cache(self):
        self._cache = config_data(self.find_one())

class config_data(dict_like_mapping):
    """
    {
        silence: BOOLEAN,
        intercept: BOOLEAN,
        calculator_debug: BOOLEAN,
        reply_error: BOOLEAN
    }
    """
    SILENCE = 'mute'
    INTERCEPT = 'itc'
    CALCULATOR_DEBUG = 'calc_dbg'
    REPLY_ERROR = 'rep_err'

    def __init__(self, org_dict):
        if org_dict is None:
            org_dict = {
                config_data.SILENCE: False,
                config_data.INTERCEPT: True,
                config_data.CALCULATOR_DEBUG: False,
                config_data.REPLY_ERROR: False
            }

        if not all(k in org_dict for k in (config_data.SILENCE, config_data.INTERCEPT, config_data.CALCULATOR_DEBUG, config_data.REPLY_ERROR)):
            raise ValueError(u'Incomplete config data.')

        return super(config_data, self).__init__(org_dict)

    def get(self, field):
        return self[field]

    def set(self, field, value):
        self[field] = value


