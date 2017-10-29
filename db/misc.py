# -*- coding: utf-8 -*-

import error

class FormattedStringResult(object):
    def __init__(self, limited_list, full_list, has_result=None, separator='\n'):
        self._limited = separator.join(limited_list)
        self._full = separator.join(full_list)
        if has_result is None:
            self._has_result = len(limited_list) > 0 and len(full_list) > 0
        else:
            self._has_result = has_result

    @staticmethod
    def init_by_field(data_list, string_format_function, limit=None, append_first_list=None, no_result_text=None, separator='\n', insert_ranking=False):
        has_result = False

        _list_limited = []
        _list_full = []

        if append_first_list is not None and not isinstance(append_first_list, list):
            append_first_list = [append_first_list]

        if append_first_list is not None:
            _list_limited.extend(append_first_list)
            _list_full.extend(append_first_list)

        count = 0 if data_list is None else len(data_list)

        if count <= 0:
            if no_result_text is None:
                no_res = error.error.main.no_result()
            else:
                no_res = no_result_text

            _list_limited.append(no_res)
            _list_full.append(no_res)
        else:
            has_result = True
            _list_full.append(u'共有{}筆結果\n'.format(count))

            if limit is not None:
                _limited_data_list = data_list[:limit]
            else:
                _limited_data_list = data_list

            # increase performance (duplicate flag determination if integrate)
            if insert_ranking:
                for index, data in enumerate(data_list):
                    data = string_format_function(data)

                    if limit is None or index < limit:
                        _list_limited.append(data)

                    _list_full.append(data)
            else:
                for index, data in enumerate(data_list, start=1):
                    data = u'第{}名:\n{}'.format(index, string_format_function(data))

                    if limit is None or index < limit:
                        _list_limited.append(data)

                    _list_full.append(data)

            if limit is not None:
                data_left = count - limit
            else:
                data_left = -1

            if data_left > 0:
                _list_limited.append(u'...(還有{}筆)'.format(data_left))

        return FormattedStringResult(_list_limited, _list_full, has_result, separator)

    @property
    def limited(self):
        return self._limited

    @property
    def full(self):
        return self._full

    @property
    def has_result(self):
        return self._has_result

    def __repr__(self):
        return u'LIMITED:\n{}\n\nFULL:\n{}'.format(self._limited, self._full).encode('utf-8')
