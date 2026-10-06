from collections import Counter, deque
import html
import re

def parse_chat_log(text):
    """Read player lines from chatLog markup, excluding drops/system notices."""
    messages = []
    for raw in (text or '').splitlines():
        icon = re.search(r'<image;Art/((?:Art_Chat|chat_balloon|Art_Word_Balloon)[^.;>]*)', raw, re.I)
        if not icon or icon[1].casefold().startswith('art_chat_system'):
            continue
        # Preserve image-only emotes instead of dropping their entire message.
        raw_text = re.sub(r'<image;Emoticons/([^.;>]+)\.dds[^>]*>',
                          lambda match: ':' + match[1] + ':', raw, flags=re.I)
        clean = ' '.join(html.unescape(re.sub(r'<[^>]*>', '', raw_text)).replace('\x00', ' ').split())
        sender = re.match(r'^\[([^\]]+)\]\s+(.+)$', clean)
        if not sender:
            continue
        gid = re.search(r'<link;GID:(\d+)[,;]', raw, re.I)
        channel = {'art_chat_say': '附近', 'art_chat_group': '队伍'}.get(
            icon[1].casefold(), icon[1])
        messages.append((channel, int(gid[1]) if gid else 0, sender[1], sender[2]))
    return messages

class ChatLogDelta:
    """Bounded snapshot differencing; no replay on startup or transient empties."""
    def __init__(self):
        self.previous = None
        self.seen = deque(maxlen=2048)

    def update(self, texts):
        parts = [parse_chat_log(text) for text in sorted(texts)]
        main = max(parts, key=len, default=[])
        # A floating group window can mirror the same rows in the main log.
        current = list(main)
        for part in parts:
            if part is main:
                continue
            remaining = Counter(current)
            for message in part:
                if remaining[message]:
                    remaining[message] -= 1
                else:
                    current.append(message)
        if self.previous is None:
            new = []
        elif not current:
            return []
        else:
            new = None
            for start in range(len(self.previous)):
                tail = self.previous[start:]
                if current[:len(tail)] == tail:
                    new = current[len(tail):]
                    break
            if new is None:
                known = set(self.seen)
                new = [message for message in current if message not in known]
        self.previous = current
        known = set(self.seen)
        for message in current:
            if message not in known:
                self.seen.append(message)
                known.add(message)
        # A large view replacement is not a plausible single polling burst.
        return new if len(new) <= 100 else []
