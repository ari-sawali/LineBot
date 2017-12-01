# -*- coding: utf-8 -*-

from collections import namedtuple

import ext
import cityids

Coordinate = namedtuple('Coordinate', ['lat', 'lng'])
class Coordinate(object):
    def __init__(self, latitude, longitude):
        self._latitude = latitude
        self._longitude = longitude

    @property
    def lat(self):
        return self._latitude

    @property
    def lng(self):
        return self._longitude

    def __str__(self):
        if self._latitude > 0:
            lat_dir = 'N'
        elif self._latitude < 0:
            lat_dir = 'S'
        else:
            lat_dir = ''

        if self._longitude > 0:
            lng_dir = 'E'
        elif self._longitude < 0:
            lng_dir = 'W'
        else:
            lng_dir = ''

        return u'{}{}, {}{}'.format(lat_dir, abs(self._latitude), lng_dir, abs(self._longitude))

class output_config(ext.EnumWithName):
    SIMPLE = 0, '簡潔'
    DETAIL = 1, '詳細'

class weather_reporter(object):
    CITY_ID_REGISTRY = cityids.CityIDRegistry('%03d-%03d.txt.gz')

    def __init__(self, owm_client, aqicn_client):
        self._owm = owm_client
        self._aqicn = aqicn_client

    def get_data_by_owm_id(self, owm_city_id, o_config=output_config.SIMPLE, interval=3, hours_within=120):
        """Return String"""
        weather_data = self._owm.get_weathers_by_id(owm_city_id, o_config, interval, hours_within)
        return self._proc_weather_data(owm_city_id, weather_data, o_config)

    def get_data_by_coord(self, coord, o_config=output_config.SIMPLE, interval=3, hours_within=120):
        """Return String"""
        weather_data = self._owm.get_weathers_by_coord(coord, o_config, interval, hours_within)
        return self._proc_weather_data(coord, weather_data, o_config)

    def _proc_weather_data(self, owm_city_id_or_coord, weather_data, o_config):
        if weather_data is not None:
            ret = []
            coord = weather_data.get_location_coordinate()
            aqi_data = self._aqicn.get_location_feed_aqi_data(coord)

            ret.append(u'位置: {}'.format(weather_data.get_location_string(o_config)))
            ret.append(u'【空氣品質相關】')
            ret.append(aqi_data.to_string(o_config))
            ret.append(u'【紫外線相關】')
            ret.append(weather_data.get_uv_string())
            ret.append(u'【天氣相關】')
            ret.append(weather_data.get_weather_string(o_config))

            return u'\n'.join(ret)
        else:
            return u'查無資料。({})'.format(owm_city_id_or_coord)