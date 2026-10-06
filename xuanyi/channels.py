"""Only the verified Nearby header; extracted from XuanShu language records."""
import html
import re

TEXT_RECORDS = {'Chat_HeaderSay': ['Say:', '说:']}


def plain_text(value):
    text = html.unescape(str(value or ''))
    text = re.sub(r'<(?:br|/p)\s*/?>', ' ', text, flags=re.I)
    return re.sub(r'\s+', ' ', re.sub(r'<[^>]*>', '', text)).strip()


def _normal(value):
    return re.sub(r'[\s!！。.,，:：]', '', plain_text(value)).casefold()


def matches_text(value, *text_ids):
    reference = html.unescape(str(value or ''))
    reference = re.sub(r'</?center>', '', reference, flags=re.I).strip()
    for text_id in text_ids:
        if reference.casefold() in (text_id.casefold(), f'<string;{text_id}>'.casefold()):
            return True
        if any(text and _normal(value) == _normal(text) for text in TEXT_RECORDS[text_id]):
            return True
    return False
