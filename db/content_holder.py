# -*- coding: utf-8 -*-
import time
import enum
from datetime import datetime, timedelta
import pymongo
from collections import defaultdict

from .base import db_base, dict_like_mapping
import error
from tool import random_gen
import bot
import ext

CONTENT_HOLDER_DB_NAME = 'content'

###############
### WEBPAGE ###
###############

class webpage_content_type(ext.EnumWithName):
    ERROR = 0, '詳細錯誤紀錄'
    QUERY = 1, '資料查詢紀錄(簡略)'
    INFO = 2, '資料查詢紀錄(詳細)'
    TEXT = 3, '文字'
    LATEX = 4, 'LaTeX (數學)'

class webpage_content_holder(db_base):
    COLLECTION_NAME = 'webpage'

    DATA_EXPIRE_SECS = 15 * 24 * 60 * 60

    def __init__(self, mongo_db_uri):
        return super(webpage_content_holder, self).__init__(mongo_db_uri, CONTENT_HOLDER_DB_NAME, webpage_content_holder.COLLECTION_NAME, True)
        self.create_index([(webpage_data.TIMESTAMP, pymongo.DESCENDING)], webpage_content_holder=system_statistics.DATA_EXPIRE_SECS)

    def _get_timestamp_in_datetime(self):
        return datetime.now() + timedelta(hours=8)

    def rec_data(self, content, type, short_description=None):
        """Return sequence id of recorded content document."""
        timestamp = self._get_timestamp_in_datetime()
        return self.insert_one(webpage_data.init_by_field(timestamp, type, content, short_description)).inserted_seq_id

    def get_data(self, id):
        """Return None if nothing found."""
        page_data = self.find_one({ webpage_data.SEQUENCE_ID: id })
        if page_data is not None:
            data = webpage_data(page_data)
            
            if data.content_type == webpage_content_type.LATEX:
                data.content += bot.webpage_manager.LATEX_SPLITTER

            data.content += u'\n\n網頁內容將在{}後清除。'.format((data.timestamp + timedelta(seconds=webpage_content_holder.DATA_EXPIRE_SECS)).strftime('%Y-%m-%d %H:%M:%S'))
            data.content += u'\n\n網頁紀錄時間: {}'.format(data.timestamp.strftime('%Y-%m-%d %H:%M:%S'))
            data.content += u'\n網頁種類: {}'.format(unicode(data.content_type))

            return data
        else:
            return None

    def get_error_page_list(self, limit=None):
        """Return list of webpage_data of error message webpage"""
        find_cursor = self.find({ webpage_data.TYPE: webpage_content_type.ERROR }, sort=[(webpage_data.SEQUENCE_ID, pymongo.DESCENDING)])
        find_cursor = self.cursor_limit(find_cursor, limit)
        data_list = list(find_cursor)
        return [webpage_data(page) for page in data_list]

class webpage_data(dict_like_mapping):
    """
    {
        seq_id: INTEGER,
        timestamp: DATETIME,
        type: WEBPAGE_CONTENT_TYPE,
        content: STRING
    }
    """
    SEQUENCE_ID = '_seq'
    TIMESTAMP = 'time'
    TYPE = 'type'
    SHORT_DESCRIPTION = 'desc'
    CONTENT = 'cont'

    @staticmethod
    def init_by_field(time, type, content, short_description):
        init_dict = {
            webpage_data.TIMESTAMP: time,
            webpage_data.TYPE: type,
            webpage_data.CONTENT: content,
            webpage_data.SHORT_DESCRIPTION: short_description
        }
        return webpage_data(init_dict)

    @staticmethod
    def no_content_template():
        init_dict = {
            webpage_data.TIMESTAMP: time.time(),
            webpage_data.TYPE: webpage_content_type.ERROR,
            webpage_data.CONTENT: error.error.webpage.no_content(),
            webpage_data.SHORT_DESCRIPTION: error.error.webpage.no_content()
        }
        return webpage_data(init_dict)

    def __init__(self, org_dict):
        if org_dict is None:
            raise ValueError(error.error.main.miscellaneous(u'Dict is None.'))

        if not all(k in org_dict for k in (webpage_data.CONTENT, webpage_data.TIMESTAMP, webpage_data.TIMESTAMP)):
            raise ValueError(error.error.main.miscellaneous(u'Incomplete webpage data keys.'))

        if webpage_data.SHORT_DESCRIPTION not in org_dict:
            org_dict[webpage_data.SHORT_DESCRIPTION] = None

        return super(webpage_data, self).__init__(org_dict)

    @property
    def seq_id(self):
        return self[webpage_data.SEQUENCE_ID]

    @property
    def timestamp(self):
        return self[webpage_data.TIMESTAMP]

    @property
    def content_type(self):
        return webpage_content_type(self[webpage_data.TYPE])

    @property
    def content(self):
        return self[webpage_data.CONTENT]

    @content.setter
    def content(self, value):
        self[webpage_data.CONTENT] = value

    @property
    def short_description(self):
        return self[webpage_data.SHORT_DESCRIPTION]

#################################
### GAME - ROCK-PAPER-SCISSOR ###
#################################

class game_object_holder(db_base):
    COLLECTION_NAME = 'game'

    def __init__(self, mongo_db_uri):
        super(game_object_holder, self).__init__(mongo_db_uri, CONTENT_HOLDER_DB_NAME, game_object_holder.COLLECTION_NAME, False, [rps.CHAT_INSTANCE_ID])
        self._cache_exist = {}

    def update_data(self, chat_instance_id, new_data):
        self._set_cache_object_exist(chat_instance_id, True)
        self.find_one_and_replace({ rps.CHAT_INSTANCE_ID: chat_instance_id }, new_data)
        
    def delete_data(self, chat_instance_id):
        self._set_cache_object_exist(chat_instance_id, False)
        self.delete_one({ rps.CHAT_INSTANCE_ID: chat_instance_id })

    def create_data(self, chat_instance_id, creator_id, creator_name, rock, paper, scissor):
        """Return false if game is exists, else return true."""
        is_bot = bot.line_api_wrapper.is_valid_user_id(chat_instance_id)

        try:
            self.insert_one(rps.init_by_field(chat_instance_id, creator_id, creator_name, is_bot, rock, paper, scissor))
            self._set_cache_object_exist(chat_instance_id, True)
            return True
        except pymongo.errors.DuplicateKeyError:
            return False

    def get_data(self, chat_instance_id):
        """Return None if data not exists."""
        exist = self._get_cache_object_exist(chat_instance_id)
        if exist:
            find_result = self.find_one({ rps.CHAT_INSTANCE_ID: chat_instance_id })
            if find_result is not None:
                return rps(find_result)
            else:
                self._set_cache_object_exist(chat_instance_id, False)
                return None
        else:
            return None

    def _set_cache_object_exist(self, gid, exist):
        self._cache_exist[gid] = exist

    def _get_cache_object_exist(self, gid):
        return self._cache_exist.get(gid, False)

class battle_item(ext.EnumWithName):
    __order__ = 'SCISSOR ROCK PAPER'
    ROCK = 1, '石頭'
    PAPER = 2, '布'
    SCISSOR = 3, '剪刀'

class battle_item_representative(dict_like_mapping):
    """
    { 
        battle_item: BATTLE_ITEM,
        is_sticker: BOOLEAN,
        content: STRING
    }
    """
    BATTLE_ITEM = 'bi'
    IS_STICKER = 'stk'
    CONTENT = 'cont'

    def __init__(self, battle_item, is_sticker, content):
        init_dict = {
            battle_item_representative.BATTLE_ITEM: battle_item,
            battle_item_representative.IS_STICKER: is_sticker,
            battle_item_representative.CONTENT: content
        }
        super(battle_item_representative, self).__init__(init_dict)

    @property
    def is_sticker(self):
        return self[battle_item_representative.IS_STICKER]

    @property
    def content(self):
        return self[battle_item_representative.CONTENT]

    @property
    def battle_item(self):
        return self[battle_item_representative.BATTLE_ITEM]

class battle_result(enum.IntEnum):
    UNDEFINED = -1
    TIED = 0
    PLAYER1_WIN = 1
    PLAYER2_WIN = 2

class battle_player(dict_like_mapping):
    """
    {
        name: STRING,
        uid: STRING,
        win: INTEGER,
        lose: INTEGER,
        tied: INTEGER,
        last_item: BATTLE_ITEM,
        consecutive_winning: BOOLEAN,
        consecutive_count: BOOLEAN,
        consecutive_win: INTEGER,
        consecutive_lose: INTEGER
    }
    """
    NAME = 'name'
    UID = 'uid'

    WIN = 'w'
    LOSE = 'l'
    TIED = 't'

    LAST_ITEM = 'last'
    CONSECUTIVE_WINNING = 'cw'
    CONSECUTIVE_COUNT = 'cc'
    CONSECUTIVE_WIN = 'max_cw'
    CONSECUTIVE_LOSE = 'max_cl'

    @staticmethod
    def init_by_field(name, uid):
        init_dict = {
            battle_player.NAME: name,
            battle_player.UID: uid
        }
        return battle_player(init_dict, False)

    def __init__(self, org_dict, by_pass_statistics_init=True):
        if not all(k in org_dict for k in (battle_player.NAME, battle_player.UID)):
            raise ValueError(error.error.main.miscellaneous(u'Incomplete player data.'))

        super(battle_player, self).__init__(org_dict)
        if not by_pass_statistics_init:
            self.reset_statistics()

    def win(self):
        self[battle_player.CONSECUTIVE_WIN] += 1
        if self[battle_player.CONSECUTIVE_WINNING]:
            self[battle_player.CONSECUTIVE_COUNT] += 1
        else:
            self[battle_player.CONSECUTIVE_COUNT] = 1
        if self[battle_player.CONSECUTIVE_COUNT] > self[battle_player.CONSECUTIVE_WIN]:
            self[battle_player.CONSECUTIVE_WIN] = self[battle_player.CONSECUTIVE_COUNT]
        self[battle_player.CONSECUTIVE_WINNING] = True
        
    def lose(self):
        self[battle_player.LOSE] += 1
        if not self[battle_player.CONSECUTIVE_WINNING]:
            self[battle_player.CONSECUTIVE_COUNT] += 1
        else:
            self[battle_player.CONSECUTIVE_COUNT] = 1
        if self[battle_player.CONSECUTIVE_COUNT] > self[battle_player.CONSECUTIVE_LOSE]:
            self[battle_player.CONSECUTIVE_LOSE] = self[battle_player.CONSECUTIVE_COUNT]
        self[battle_player.CONSECUTIVE_WINNING] = False
        
    def tied(self):
        self[battle_player.TIED] += 1

    def reset_statistics(self):
        self[battle_player.WIN] = 0
        self[battle_player.LOSE] = 0
        self[battle_player.TIED] = 0
        self[battle_player.LAST_ITEM] = None
        self[battle_player.CONSECUTIVE_WINNING] = False
        self[battle_player.CONSECUTIVE_COUNT] = 0
        self[battle_player.CONSECUTIVE_WIN] = 0
        self[battle_player.CONSECUTIVE_LOSE] = 0

    def is_same_uid(self, uid):
        return self[battle_player.UID] == uid

    @property
    def name(self):
        return self[battle_player.NAME]
    
    @property
    def win_count(self):
        return self[battle_player.WIN]
    
    @property
    def lose_count(self):
        return self[battle_player.LOSE]
    
    @property
    def tied_count(self):
        return self[battle_player.TIED]

    @property
    def total_played(self):
        return self[battle_player.WIN] + self[battle_player.LOSE] + self[battle_player.TIED]

    @property
    def consecutive_type(self):
        """True=Win, False=Lose"""
        return self[battle_player.CONSECUTIVE_WINNING]

    @property
    def consecutive_count(self):
        return self[battle_player.CONSECUTIVE_COUNT]

    @property
    def longest_consecutive_win(self):
        return self[battle_player.CONSECUTIVE_WIN]

    @property
    def longest_consecutive_lose(self):
        return self[battle_player.CONSECUTIVE_LOSE]

    @property
    def winning_rate(self):
        try:
            return self[battle_player.WIN] / float(self[battle_player.WIN] + self[battle_player.LOSE])
        except ZeroDivisionError:
            return 1.0 if self._win > 0 else 0.0
    
    @property
    def last_item(self):
        return self[battle_player.LAST_ITEM]

    @last_item.setter
    def last_item(self, value):
        self[battle_player.LAST_ITEM] = value

class rps(dict_like_mapping):
    """
    Game of Rock-Paper-Scissors
    
    {
        chat_instance_id: STRING,
        representatives: {
            rock: [],
            paper: [],
            scissor: []
        },
        players: {
            player_uid: PLAYER, player_uid: PLAYER, player_uid: PLAYER...
        },
        properties: {
            enabled: BOOLEAN,,
            is_vs_bot: BOOLEAN
            result_generated: BOOLEAN,
            play_begin: FLOAT (TIME),
            gap_time: FLOAT (TIME)
        },
        player_temp1: PLAYER,
        player_temp2: PLAYER
    }
    """
    _BOT_UID = 'U--------------------------------'

    CHAT_INSTANCE_ID = 'cid'
    IS_VS_BOT = 'vs_bot'

    REPRESENTATIVES = 'repr'
    ROCK = 'rck'
    PAPER = 'ppr'
    SCISSOR = 'scr'

    PROPERTIES = 'prop'
    ENABLED = 'en'
    RESULT_GENERATED = 'gen'
    PLAY_BEGIN = 'begin_t'
    GAP_TIME = 'gap'
    BATTLE_RESULT = 'res'

    PLAYERS = 'plyr'
    PLAYER_TEMP1 = 'temp1'
    PLAYER_TEMP2 = 'temp2'
    
    @staticmethod
    def init_by_field(chat_instance_id, creator_id, creator_name, vs_bot, rock, paper, scissor):
        """rps object is content only, set default to sticker id."""
        if vs_bot:
            player_dict = {rps._BOT_UID: battle_player.init_by_field(u'(電腦)', rps._BOT_UID)}
        else:
            player_dict = {}

        player_dict[creator_id] = battle_player.init_by_field(creator_name, creator_id)

        init_dict = {
            rps.CHAT_INSTANCE_ID: chat_instance_id,
            rps.REPRESENTATIVES: {
                rps.ROCK: [battle_item_representative(battle_item.ROCK, True, rock)],
                rps.PAPER: [battle_item_representative(battle_item.PAPER, True, paper)],
                rps.SCISSOR: [battle_item_representative(battle_item.SCISSOR, True, scissor)]
            },
            rps.PLAYERS: player_dict,
            rps.PROPERTIES: {
                rps.ENABLED: True,
                rps.IS_VS_BOT: vs_bot,
                rps.RESULT_GENERATED: False,
                rps.PLAY_BEGIN: -1,
                rps.GAP_TIME: -1
            },
            rps.PLAYER_TEMP1: None,
            rps.PLAYER_TEMP2: None
        }
        return rps(init_dict)

    def __init__(self, org_dict):
        super(rps, self).__init__(org_dict)

    def register_battle_item(self, item, is_sticker, content):
        field = self._battle_item_to_repr_key(item)
        self[rps.REPRESENTATIVES][field].append(battle_item_representative(item, is_sticker, content))

    def register_player(self, name, uid):
        if self.get_player_by_uid(uid) is None:
            self[rps.PLAYERS][uid] = battle_player.init_by_field(name, uid)
            return True
        else:
            return False
        
    def play(self, item, player_uid):
        """
        return not void if error occurred.
        No action if player not exist.
        """
        if self[rps.ENABLED]:
            player_count = len(self[rps.PLAYERS])
            if player_count < 2:
                return error.error.main.miscellaneous(u'玩家人數不足，需要先註冊2名玩家以後方可遊玩。目前已註冊玩家{}名。\n已註冊玩家: {}'.format(
                    player_count, '、'.join([player[battle_player.NAME] for player in self[rps.PLAYERS].itervalues()])))
            else:
                if self[rps.PLAYER_TEMP1] is not None:
                    if self[rps.PLAYER_TEMP1][battle_player.UID] == player_uid:
                        return error.error.main.miscellaneous(u'同一玩家不可重複出拳。')
                    else:
                        self._play2(item, player_uid)
                else:
                    self._play1(item, player_uid)
        else:
            return error.error.main.miscellaneous(u'遊戲暫停中...')

    def result_text(self):
        """
        Player object will be released after calling this method.
        """
        result_enum = self[rps.BATTLE_RESULT]
        if result_enum == battle_result.TIED:
            text = u'【平手】'
        elif result_enum == battle_result.PLAYER1_WIN:
            text = u'【勝利 - {}】'.format(self[rps.PLAYER_TEMP1][battle_player.NAME])
            text += u'\n【敗北 - {}】'.format(self[rps.PLAYER_TEMP2][battle_player.NAME])
        elif result_enum == battle_result.PLAYER2_WIN:
            text = u'【勝利 - {}】'.format(self[rps.PLAYER_TEMP2][battle_player.NAME])
            text += u'\n【敗北 - {}】'.format(self[rps.PLAYER_TEMP1][battle_player.NAME])
        elif result_enum == battle_result.UNDEFINED:
            text = u'【尚未猜拳】'
        else:
            raise ValueError(error.error.main.invalid_thing(u'猜拳結果', result_enum))
        
        text += u'\n本次猜拳兩拳間格時間(包含程式處理時間) {:.3f} 秒'.format(self[rps.GAP_TIME])
        text += u'\n\n'
        text += rps.player_stats_text(self[rps.PLAYERS])

        self._reset()
        return text

    def battle_item_dict_text(self, item=None):
        if item is None:
            text = u'【剪刀石頭布代表物件】\n'
            text += u'\n'.join([self._battle_item_dict_text(item) for item in battle_item])
            return text
        else:
            return self._battle_item_dict_text(item)

    def reset_statistics(self):
        for player in self[rps.PLAYERS].itervalues():
            player = battle_player(player)
            player.reset_statistics() 

    def find_battle_item(self, is_sticker, content):
        for battle_item_key, representatives in self[rps.REPRESENTATIVES].iteritems():
            for representative in representatives:
                if representative[battle_item_representative.IS_STICKER] == is_sticker and representative[battle_item_representative.CONTENT] == content:
                    return self._repr_key_to_battle_item(battle_item_key)

        return None

    def clear_battle_item(self):
        for k in self[rps.REPRESENTATIVES].keys():
            self[rps.REPRESENTATIVES][k] = []

    def _play1(self, item, player_uid):
        player_obj = self.get_player_by_uid(player_uid)
        if player_obj is not None:
            self[rps.PLAYER_TEMP1] = player_obj
            self[rps.PLAYER_TEMP1][battle_player.LAST_ITEM] = item
            self[rps.PLAY_BEGIN] = time.time()

            if self[rps.IS_VS_BOT]:
                self._play2(random_gen.random_drawer.draw_from_list(list(battle_item)), rps._BOT_UID)

    def _play2(self, item, player_uid):
        player_obj = self.get_player_by_uid(player_uid)
        if player_obj is not None or player_uid == rps._BOT_UID:
            self[rps.PLAYER_TEMP2] = player_obj
            self[rps.PLAYER_TEMP2][battle_player.LAST_ITEM] = item
            self[rps.GAP_TIME] = time.time() - self[rps.PLAY_BEGIN]
            self._calculate_result()

    def _calculate_result(self):
        result = (int(self[rps.PLAYER_TEMP1][battle_player.LAST_ITEM]) - int(self[rps.PLAYER_TEMP2][battle_player.LAST_ITEM])) % 3
        result_enum = battle_result(result)
        player1 = self[rps.PLAYER_TEMP1]
        player2 = self[rps.PLAYER_TEMP2]
        if result_enum == battle_result.PLAYER1_WIN:
            player1.win()
            player2.lose()
        elif result_enum == battle_result.PLAYER2_WIN:
            player2.win()
            player1.lose()
        elif result_enum == battle_result.TIED:
            player1.tied()
            player2.tied()
        self[rps.RESULT_GENERATED] = True
            
    def _reset(self):
        self[rps.RESULT_GENERATED] = False
        self[rps.PLAY_BEGIN] = -1
        self[rps.PLAYER_TEMP1] = None
        self[rps.PLAYER_TEMP2] = None

    def _battle_item_dict_text(self, item):
        key_repr_key = self._battle_item_to_repr_key(item)

        text = u'【{}】\n'.format(unicode(item))
        text += u', '.join([u'(貼圖ID {})'.format(item[battle_item_representative.CONTENT]) if item[battle_item_representative.IS_STICKER] else unicode(item[battle_item_representative.CONTENT]) for item in self[rps.REPRESENTATIVES][key_repr_key]])

        return text

    def _battle_item_to_repr_key(self, item):
        key_repr_dict = { battle_item.SCISSOR: rps.SCISSOR,
                          battle_item.PAPER: rps.PAPER,
                          battle_item.ROCK: rps.ROCK}
        return key_repr_dict[item]

    def _repr_key_to_battle_item(self, key):
        repr_key_dict = { rps.SCISSOR: battle_item.SCISSOR,
                          rps.PAPER: battle_item.PAPER,
                          rps.ROCK: battle_item.ROCK }
        return repr_key_dict[key]
        
    def get_player_by_uid(self, uid):
        """Return None if nothing found. IMMUTABLE."""
        obj = next((item for item in self[rps.PLAYERS] if item[rps.USER_ID] == uid), None)
        if obj is not None:
            return battle_player(obj)
        else:
            return None

    @property
    def gap_time(self):
		return self[rps.GAP_TIME]

    @property
    def vs_bot(self):
        return self[rps.IS_VS_BOT]

    @property
    def battle_dict(self):
        return self[rps.REPRESENTATIVES]

    @property
    def player_dict(self):
        return self[rps.PLAYERS]

    @property
    def is_waiting_next(self):
        return self[rps.PLAYER_TEMP1] is not None and self[rps.PLAYER_TEMP2] is None

    @property
    def result_generated(self):
        return self[rps.RESULT_GENERATED]

    @property
    def enabled(self):
        return self[rps.ENABLED]

    @enabled.setter
    def enabled(self, value):
        self[rps.ENABLED] = value

    @staticmethod
    def player_stats_text(player_dict):
        texts_to_join = []
        for player in sorted(player_dict.values(), reverse=True):
            player = battle_player(player)
            texts_to_join.append(u'{}\n{}戰 勝率{:.3f} {}勝 {}敗 {}平 {}連{}中 最長{}連勝、{}連敗'.format(
                player.name, player.total_played, player.winning_rate, player.win_count, player.lose_count, player.tied_count, 
                player.consecutive_count, u'勝' if player.consecutive_type else u'敗', player.longest_consecutive_win, player.longest_consecutive_lose))

        text = u'【玩家戰績】\n'
        text += u'\n\n'.join(texts_to_join)
        return text






