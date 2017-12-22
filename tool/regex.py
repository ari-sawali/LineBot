# coding: utf-8

import re

class regex_finder(object):

    @staticmethod
    def find_match(regex_list, text):
        """
        Returns:
            Has result: RegexFindResult
            No result: None
        """
        for num, regex in enumerate(regex_list):
            pattern = ur"^" + regex + ur"$"
            match_result = re.match(pattern, text)
            if match_result is not None:
                return RegexFindResult(num, match_result, pattern)

        return None

class RegexFindResult(object):
    def __init__(self, match_at, match_obj, pattern):
        self._match_at = match_at
        self._match_obj = match_obj
        self._pattern = pattern

    @property
    def match_at(self):
        return self._match_at

    @property
    def regex(self):
        return self._pattern
    
    def group(self, index):
        return self._match_obj.group(index)