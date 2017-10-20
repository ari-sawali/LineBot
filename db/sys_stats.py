# -*- coding: utf-8 -*-
import pymongo

from datetime import date, datetime
from .base import db_base, dict_like_mapping, SYSTEM_DATABASE_NAME

class system_statistics(db_base):
    COLLECTION_NAME = 'statistics'
    DATA_EXPIRE_SECS = 15 * 24 * 60 * 60

    def __init__(self, mongo_db_uri):
        super(system_statistics, self).__init__(mongo_db_uri, SYSTEM_DATABASE_NAME, system_statistics.COLLECTION_NAME, False)
        self.create_index([(system_data.RECORD_DATE, pymongo.DESCENDING)], expireAfterSeconds=system_statistics.DATA_EXPIRE_SECS)

    def _new_record(self, date):
        self.insert_one(system_data.init_by_field(date))

    def _get_today_date(self):
        return datetime.combine(date.today(), datetime.min.time())

    def command_called(self, command):
        today = self._get_today_date()
        result = self.update_one({ system_data.RECORD_DATE: today },
                                 { '$inc': { system_data.COMMAND_CALLED + '.' + command: 1 } }, True)

    def webpage_viewed(self, webpage_type_enum):
        today = self._get_today_date()
        result = self.update_one({ system_data.RECORD_DATE: today },
                                 { '$inc': { system_data.WEBPAGE_VIEWED + '.' + str(webpage_type_enum): 1 } }, True)

    # UNDONE: asked at https://stackoverflow.com/questions/46806932/how-to-sum-the-value-of-keys-in-subcollection-within-a-range
    def get_statistics(self):
        raise NotImplementedError()

    def all_data(self):
        return [system_data(data) for data in list(self.find())]

    def get_data_at_date(self, date):
        return system_data(self.find_one({ system_data.RECORD_DATE: date }))

class system_data(dict_like_mapping):
    """
    {
        date: DATE,
        command_called: {
            command: INTEGER,
            ...
            ...
        },
        webpage_viewed: {
            webpage_type: INTEGER,
            ...
            ...
        }
    }
    """
    RECORD_DATE = 'rec_date'
    COMMAND_CALLED = 'cmd'
    WEBPAGE_VIEWED = 'wp'

    @staticmethod
    def init_by_field(date=None):
        init_dict = {
            system_data.COMMAND_CALLED: {},
            system_data.WEBPAGE_VIEWED: {}
        }
        if data is not None:
            init_dict[system_data.RECORD_DATE] = date

        return system_data(init_dict, date is None)

    def __init__(self, org_dict, skip_date_check=False):
        if org_dict is not None:
            if not skip_date_check and not system_data.RECORD_DATE in org_dict:
                raise ValueError('Must have date in data')

            if not system_data.COMMAND_CALLED in org_dict:
                org_dict[system_data.COMMAND_CALLED] = {}

            if not system_data.WEBPAGE_VIEWED in org_dict:
                org_dict[system_data.WEBPAGE_VIEWED] = {}
        else:
            raise ValueError('Dictionary is none.')

        return super(system_data, self).__init__(org_dict)

    @property
    def command_called(self):
        return self[system_data.COMMAND_CALLED]

    @property
    def webpage_viewed(self):
        return self[system_data.WEBPAGE_VIEWED]

    @property
    def date(self):
        return self.get(system_data.RECORD_DATE, None)

class StatisticsResult(dict_like_mapping):
    """
    {
        command_called: {
            command: STATISTICS_DATA,
            ...
            ...
        },
        webpage_viewed: {
            webpage_type: STATISTICS_DATA,
            ...
            ...
        }
    }
    """
    def __init__(self, org_dict):
        if org_dict is not None:
            if not system_data.COMMAND_CALLED in org_dict:
                org_dict[system_data.COMMAND_CALLED] = {}

            if not system_data.WEBPAGE_VIEWED in org_dict:
                org_dict[system_data.WEBPAGE_VIEWED] = {}
        else:
            raise ValueError('Dictionary is none.')
        return super(StatisticsResult, self).__init__(org_dict)

    def __repr__(self):
        cmd_list = [u'{} - {}'.format(cmd_type, cmd_data.get_string()) for cmd_type, cmd_data in self[system_data.COMMAND_CALLED]]
        wp_list = [u'{} - {}'.format(cmd_type, cmd_data.get_string()) for cmd_type, cmd_data in self[system_data.WEBPAGE_VIEWED]]

        text = u'【指令呼叫次數】\n'
        text += u'\n'.join(cmd_list)
        text += u'【網頁瀏覽次數】\n'
        text += u'\n'.join(wp_list)

        return text

class StatisticsData(dict_like_mapping):
    """
    {
        in_1: INTEGER,
        in_3: INTEGER,
        in_7: INTEGER,
        in_15: INTEGER
    }
    """
    IN_1_DAY = 'in_1'
    IN_3_DAYS = 'in_3'
    IN_7_DAYS = 'in_7'
    IN_15_DAYS = 'in_15'

    def __init__(self, in_1_count, in_3_count, in_7_count, in_15_count):
        init_dict = {
            StatisticsData.IN_1_DAY: system_data(in_1_count, True),
            StatisticsData.IN_3_DAYS: system_data(in_3_count, True),
            StatisticsData.IN_7_DAYS: system_data(in_7_count, True),
            StatisticsData.IN_15_DAYS: system_data(in_15_count, True)
        }

        return super(StatisticsData, self).__init__(init_dict)

    def get_string(self):
        return u'1日內: {}、3日內: {}、7日內: {}、15日內: {}'.format(self[StatisticsData.IN_1_DAY], self[StatisticsData.IN_3_DAYS], self[StatisticsData.IN_7_DAYS], self[StatisticsData.IN_15_DAYS])
        pass