# -*- coding: utf-8 -*-

from enum import IntEnum

# IMPORTANT: __new__

class EnumWithName(IntEnum):
    def __new__(cls, value, name):
        member = int.__new__(cls, value)
        member._value_ = value
        member._name = name
        return member

    def __int__(self):
        return self._value_

    def __str__(self):
        print 'str'
        return self._name

    def __unicode__(self):
        print 'unc'
        return unicode(self._name.decode('utf-8'))
