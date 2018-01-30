# -*- coding: utf-8 -*-

import db, bot, tool

class special_text_handler(object):
    def __init__(self, mongo_db_uri, line_api_wrapper, weather_reporter):
        self._line_api_wrapper = line_api_wrapper
        self._weather_reporter = weather_reporter
        self._weather_config = db.weather_report_config(mongo_db_uri)
        self._system_stats = db.system_statistics(mongo_db_uri)

        self._special_keyword = {
            u'天氣': (self._handle_text_spec_weather, (False,)),
            u'詳細天氣': (self._handle_text_spec_weather, (True,))
        }

    def handle_text(self, event):
        """Return replied or not."""
        token = event.reply_token
        msg_text = event.message.text

        uid = bot.line_api_wrapper.source_user_id(event.source)

        spec = self._special_keyword.get(msg_text, None)
        
        if spec is not None:
            spec_func, spec_param = spec
            rep_text = spec_func(*(spec_param + (uid,)))

            if isinstance(rep_text, (str, unicode)):
                self._line_api_wrapper.reply_message_text(token, rep_text)
            else:
                self._line_api_wrapper.reply_message(token, rep_text)

            return True

        return False

    def _handle_text_spec_weather(self, detailed, uid):
        self._system_stats.extend_function_used(db.extend_function_category.REQUEST_WEATHER_REPORT)

        config_data = self._weather_config.get_config(uid) 
        if config_data is not None and len(config_data.config) > 0:
            ret = [self._weather_reporter.get_data_by_owm_id(cfg.city_id, tool.weather.output_type(cfg.mode), cfg.interval, cfg.data_range) for cfg in config_data.config]

            return u'\n===========================\n'.join(ret)
        else:
            command_head = bot.msg_handler.text_msg_handler.CH_HEAD + u'天氣查詢 '

            template_title = u'快速天氣查詢'
            template_title_alt = u'快速天氣查詢樣板，請使用手機查看。'
            template_actions = { 
                tool.weather.owm.DEFAULT_TAICHUNG.name: command_head + str(tool.weather.owm.DEFAULT_TAICHUNG.id),
                tool.weather.owm.DEFAULT_TAIPEI.name: command_head + str(tool.weather.owm.DEFAULT_TAIPEI.id),
                tool.weather.owm.DEFAULT_KAOHSIUNG.name: command_head + str(tool.weather.owm.DEFAULT_KAOHSIUNG.id),
                tool.weather.owm.DEFAULT_HONG_KONG.name: command_head + str(tool.weather.owm.DEFAULT_HONG_KONG.id),
                tool.weather.owm.DEFAULT_KUALA_LUMPER.name: command_head + str(tool.weather.owm.DEFAULT_KUALA_LUMPER.id),
                tool.weather.owm.DEFAULT_MACAU.name: command_head + str(tool.weather.owm.DEFAULT_MACAU.id)
            }

            if detailed:
                template_actions = { k: v + (u'詳' if detailed else u'簡') for k, v in template_actions.iteritems() }

            return bot.line_api_wrapper.wrap_template_with_action(template_actions, template_title_alt, template_title)