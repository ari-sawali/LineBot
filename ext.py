# -*- coding: utf-8 -*-

import numpy
from enum import IntEnum
from datetime import datetime
import time
import bson
from math import log10

class EnumWithName(IntEnum):
    def __new__(cls, value, name):
        member = int.__new__(cls, value)
        member._value_ = value
        member._name = name
        return member

    def __int__(self):
        return self._value_

    def __str__(self):
        return self._name

    def __unicode__(self):
        return unicode(self._name.decode('utf-8'))

def object_to_json(o, level=0, indent=4, space=" ", newline="\n"):
    ret = ""
    if isinstance(o, dict):
        ret += "{" + newline
        comma = ""
        for k,v in o.iteritems():
            ret += comma
            comma = ",\n"
            ret += space * indent * level
            ret += '"' + str(k) + '":' + space
            ret += object_to_json(v, level + 1)

        ret += newline + space * indent * (level - 1) + "}"
    elif isinstance(o, basestring):
        ret += '"' + o + '"'
    elif isinstance(o, list):
        ret += "[" + ", ".join([object_to_json(e, level+1) for e in o]) + "]"
    elif isinstance(o, bool):
        ret += "true" if o else "false"
    elif isinstance(o, (int, long)):
        ret += str(o)
    elif isinstance(o, datetime):
        ret += o.strftime('%Y-%m-%d %H:%M:%S.%f')
    elif isinstance(o, bson.ObjectId):
        ret += 'ObjectId(%s)' % o
    elif isinstance(o, float):
        ret += '%.7g' % o
    elif isinstance(o, numpy.ndarray) and numpy.issubdtype(o.dtype, numpy.integer):
        ret += "[" + ','.join(map(str, o.flatten().tolist())) + "]"
    elif isinstance(o, numpy.ndarray) and numpy.issubdtype(o.dtype, numpy.inexact):
        ret += "[" + ','.join(map(lambda x: '%.7g' % x, o.flatten().tolist())) + "]"
    elif isinstance(o, bson.timestamp.Timestamp):
        ret += time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(int(o / 1000)))
    elif o is None:
        ret += 'null'
    else:
        raise TypeError("Unknown type '%s' for json serialization" % str(type(o)))
    return ret

levels = [(0, ''), (3, 'K'), (6, 'M'), (9, 'G'), (12, 'T'), (15, 'P'), (18, 'E'), (21, 'Z'), (24, 'Y')]

def simplify_num(value):
    if value < 1000:
        return u'{:.2f}'.format(value)

    lads = int(log10(value) / 3)

    if lads >= len(levels):
        simp_pow, simp_text = levels[-1]
    else:
        simp_pow, simp_text = levels[lads]
    
    simp = value / float(10 ** simp_pow)
    return u'{:.2f} {}'.format(simp, simp_text)