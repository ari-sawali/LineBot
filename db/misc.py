# -*- coding: utf-8 -*-

import error

class FormattedStringResult(object):
    def __init__(self, limited_list, full_list):
        self._limited = '\n'.join(limited_list)
        self._full = '\n'.join(full_list)
        self._has_result = False

    @staticmethod
    def init_by_field(data_list, string_format_function, limit=None, append_first_list=None, no_result_text=None):
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
            self._has_result = True
            _list_full.append(u'共有{}筆結果\n'.format(count))
            
            if limit is not None:
                _limited_data_list = data_list[:limit]
            else:
                _limited_data_list = data_list

            _list_limited.extend([string_format_function(data) for data in _limited_data_list])
            _list_full.extend([string_format_function(data) for data in data_list])

            if limit is not None:
                data_left = count - limit
            else:
                data_left = -1

            if data_left > 0:
                _list_limited.append(u'...(還有{}筆)'.format(data_left))

        print data_list

        return FormattedStringResult(_list_limited, _list_full)

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
