"""Explicit losses for overbar labels and default-only alternate pin functions."""
from .model import SymbolParseError

PIN_NAME_POLICIES = ('reject', 'plain-overbar-with-loss')
ALTERNATE_PIN_POLICIES = ('reject', 'primary-with-loss')


def validate_pin_name_policy(value):
    if not isinstance(value, str) or value not in PIN_NAME_POLICIES:
        raise SymbolParseError('Pin name policy must be reject or plain-overbar-with-loss')


def validate_alternate_pin_policy(value):
    if not isinstance(value, str) or value not in ALTERNATE_PIN_POLICIES:
        raise SymbolParseError('Alternate pin policy must be reject or primary-with-loss')


def plain_pin_name(value, policy):
    """Remove only balanced KiCad ~{...} overbars, bounded to 16 nested groups.

    No pin number/type/geometry is changed. Superscripts, malformed/legacy tilde
    markup and nested non-overbar braces remain refusals rather than guesses.
    """
    validate_pin_name_policy(policy)
    if '~' not in value or policy == 'reject':
        return value, False
    if len(value) > 4096:
        raise SymbolParseError('Overbar pin name exceeds the 4096-character profile')
    output, depth, index, changed = [], 0, 0, False
    while index < len(value):
        if value.startswith('~{', index):
            depth += 1
            if depth > 16:
                raise SymbolParseError('Overbar pin name exceeds 16 nested groups')
            index += 2
            changed = True
            continue
        char = value[index]
        if char == '}' and depth:
            depth -= 1
        elif char == '~' or char == '^' or char == '{' and depth:
            raise SymbolParseError('Unsupported/malformed overbar pin name')
        else:
            output.append(char)
        index += 1
    result = ''.join(output)
    if depth or not result or result == '~':
        raise SymbolParseError('Unbalanced/empty overbar pin name')
    return result, changed
