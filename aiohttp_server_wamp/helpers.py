import re

sub_first_cap = re.compile('(.)([A-Z][a-z]+)').sub
sub_all_caps = re.compile('([a-z0-9])([A-Z])').sub


def camel_to_snake(name):
    # Based on https://stackoverflow.com/a/1176023/1843865
    s1 = sub_first_cap(r'\1_\2', name)
    return sub_all_caps(r'\1_\2', s1).lower()
