# -*- coding: utf-8 -*-

from .base import db_base, dict_like_mapping
import pymongo.cursor
import datetime

from .keyword_dict import pair_data, group_dict_manager

class word_dict_global(db_base):
    CLONE_TIMEOUT_SEC = 15

    def __init__(self, mongo_db_uri):
        super(word_dict_global, self).__init__(mongo_db_uri, group_dict_manager.WORD_DICT_DB_NAME, group_dict_manager.WORD_DICT_DB_NAME, True)

    def clone_by_id(self, id_or_id_list, new_gid, clone_executor, including_disabled=False, including_pinned=True):
        """Return inserted sequence id(s)"""
        if isinstance(id_or_id_list, (int, long)):
            id_or_id_list = [id_or_id_list]

        filter_dict = { pair_data.SEQUENCE: { '$in': id_or_id_list } }
        return self._clone_to_group(filter_dict, new_gid, clone_executor, including_disabled, including_pinned)

    def clone_from_group(self, org_gid, new_gid, clone_executor, including_disabled=False, including_pinned=True):
        """Return inserted sequence id(s)"""
        filter_dict = { pair_data.AFFILIATED_GROUP: org_gid }
        return self._clone_to_group(filter_dict, new_gid, clone_executor, including_disabled, including_pinned)

    # TEST: test disable duplicated keyword
    def _clone_to_group(self, filter_dict, new_gid, clone_executor, including_disabled=False, including_pinned=True):
        import time
        _start_time = time.time()
        if not including_pinned:
            filter_dict[pair_data.PROPERTIES + '.' + pair_data.PINNED] = False

        if not including_disabled:
            filter_dict[pair_data.PROPERTIES + '.' + pair_data.DISABLED] = False


        find_cursor = self.find(filter_dict, projection={ '_id': False, pair_data.SEQUENCE: False })

        data_list = []
        affected_kw_list = []
        for result_data in find_cursor:
            data = pair_data(result_data, True)
            affected_kw_list.append(data.keyword)
            data_list.append(data.clone(new_gid))

            if time.time() - _start_time > 15:
                raise RuntimeError('Clone process timeout, try another clone method, or split the condition array.')
            
        if len(data_list) > 0:
            self.update_many({ pair_data.KEYWORD: { '$in': affected_kw_list } }, 
                             { '$set': { pair_data.PROPERTIES + '.' + pair_data.DISABLED: True,
                                         pair_data.STATISTICS + '.' + pair_data.DISABLED_TIME: datetime.datetime.now(),
                                         pair_data.STATISTICS + '.' + pair_data.DISABLER: clone_executor } })

            return self.insert_many(data_list).inserted_seq_ids
        else:
            return []

    def get_pairs_by_group_id(self, gid, including_disabled=False, including_pinned=True):
        """Return EMPTY LIST when nothing found"""
        find_cursor = self.find({ pair_data.AFFILIATED_GROUP: gid })
        return list(find_cursor)
