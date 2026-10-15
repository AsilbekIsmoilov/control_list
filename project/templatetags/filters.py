from django import template
import re

register = template.Library()

@register.filter
def get_dynamic_attr(obj, attr):
    return getattr(obj, attr, "")

@register.filter
def regex_search(value, pattern):
    match = re.search(pattern, value)
    if match:
        return match.group(1)
    return None

@register.filter
def split(value, delimiter=","):
    return value.split(delimiter)



@register.filter
def get_item(dictionary, key):
    if key is None or not hasattr(dictionary, "get"):
        return None
    return dictionary.get(key)
