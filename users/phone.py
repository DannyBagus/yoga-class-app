"""Normalisierung von Telefonnummern auf E.164 (z. B. ``+41791234567``).

Bewusst ohne externe Library: Kundinnen sind fast ausschliesslich in der
Schweiz, Eingaben kommen in allen Varianten (``079 123 45 67``,
``0041 79 123 45 67``, ``+41 (0)79 123 45 67``, ``+49 151 ...``).
"""
import re

from django.core.exceptions import ValidationError

INVALID_PHONE = "Bitte gib eine gültige Natelnummer ein, z. B. 079 123 45 67."


def normalize_phone(raw):
    """Liefert die Nummer im Format ``+<Ländervorwahl><Nummer>`` oder wirft ValidationError."""
    value = (raw or '').strip()
    # Trennzeichen entfernen, "(0)" nach der Ländervorwahl ist ein typischer Zusatz.
    value = value.replace('(0)', '')
    value = re.sub(r'[\s\-./()]', '', value)

    if value.startswith('00'):
        value = '+' + value[2:]
    elif value.startswith('0'):
        # Nationale Schweizer Schreibweise: 079... -> +4179...
        value = '+41' + value[1:]
    elif re.fullmatch(r'7\d{8}', value):
        # Schweizer Natel ohne fuehrende 0 (typisch nach Excel-Import): 79... -> +4179...
        value = '+41' + value
    if value.startswith('+410'):
        # "+41 079 ..." -> 0 nach der Laendervorwahl entfernen
        value = '+41' + value[4:]

    if not re.fullmatch(r'\+[1-9]\d{7,14}', value):
        raise ValidationError(INVALID_PHONE)
    # Schweizer Nummern haben nach +41 genau 9 Ziffern.
    if value.startswith('+41') and len(value) != 12:
        raise ValidationError(INVALID_PHONE)
    return value
