"""Accept handles only, never URLs."""
import re


def validate_handle(value):
    if not isinstance(value, str):
        raise ValueError('Enter a valid Instagram handle.')
    value = value.removeprefix('@').lower()
    if not re.fullmatch(r'[a-z0-9_](?:[a-z0-9_.]{0,28}[a-z0-9_])?', value) or '..' in value:
        raise ValueError('Enter a valid Instagram handle.')
    return value
