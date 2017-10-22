# -*- coding: utf-8 -*-

import numpy
from enum import IntEnum

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

def object_to_json(o, indent=4, space=" ", newline="\n", level=0):
    ret = ""
    if isinstance(o, dict):
        ret += "{" + newline
        comma = ""
        for k,v in o.iteritems():
            ret += comma
            comma = ",\n"
            ret += space * indent * (level+1)
            ret += '"' + str(k) + '":' + space
            ret += object_to_json(v, level + 1)

        ret += newline + space * indent * level + "}"
    elif isinstance(o, basestring):
        ret += '"' + o + '"'
    elif isinstance(o, list):
        ret += "[" + ",".join([object_to_json(e, level+1) for e in o]) + "]"
    elif isinstance(o, bool):
        ret += "true" if o else "false"
    elif isinstance(o, (int, long)):
        ret += str(o)
    elif isinstance(o, float):
        ret += '%.7g' % o
    elif isinstance(o, numpy.ndarray) and numpy.issubdtype(o.dtype, numpy.integer):
        ret += "[" + ','.join(map(str, o.flatten().tolist())) + "]"
    elif isinstance(o, numpy.ndarray) and numpy.issubdtype(o.dtype, numpy.inexact):
        ret += "[" + ','.join(map(lambda x: '%.7g' % x, o.flatten().tolist())) + "]"
    elif o is None:
        ret += 'null'
    else:
        raise TypeError("Unknown type '%s' for json serialization" % str(type(o)))
    return ret