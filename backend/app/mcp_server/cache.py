"""Small release-aware in-process cache."""
from collections import OrderedDict
import json

_CACHE = OrderedDict()
CAP = 512


def key(tool, arguments, releases):
    return json.dumps([tool, arguments, releases], sort_keys=True, default=str, separators=(',', ':'))


def get(cache_key):
    if cache_key not in _CACHE:
        return None
    _CACHE.move_to_end(cache_key)
    return _CACHE[cache_key].model_copy(deep=True)


def put(cache_key, result):
    _CACHE[cache_key] = result.model_copy(deep=True)
    _CACHE.move_to_end(cache_key)
    if len(_CACHE) > CAP:
        _CACHE.popitem(last=False)
