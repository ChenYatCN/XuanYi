import unittest
from xuanyi.chat_log import ChatLogDelta, parse_chat_log


def chat_line(message, icon='Say', name='Amber', gid=31):
    sender = f'<link;GID:{gid},{name},2>[{name}]</link>' if gid else f'[{name}]'
    return f'<color;FFFFFF><image;Art/Art_Chat_{icon}.dds;24;24;FFFFFFFF> {sender} {message}</color>'

class ChatLogTests(unittest.TestCase):
    def test_nearby_group_self_and_system_markup(self):
        raw = '\n'.join([chat_line('hi'), chat_line('team', 'Group'),
                         chat_line('mine', gid=0, name='你'),
                         chat_line('You received gold', 'System'), '[DEBUG] bad'])
        self.assertEqual(parse_chat_log(raw), [('附近', 31, 'Amber', 'hi'),
                         ('队伍', 31, 'Amber', 'team'), ('附近', 0, '你', 'mine')])

    def test_entities_and_emotes_are_preserved(self):
        self.assertEqual(parse_chat_log(chat_line('&lt;b&gt; &amp; <image;Emoticons/smile.dds;24;24>'))[0][3],
                         '<b> & :smile:')

    def test_initial_baseline_append_and_repeated_message(self):
        delta = ChatLogDelta()
        row = chat_line('hi')
        self.assertEqual(delta.update([row]), [])
        self.assertEqual(len(delta.update([row + '\n' + row])), 1)
        self.assertEqual(delta.update([row + '\n' + row]), [])

    def test_scroll_and_transient_empty_do_not_replay(self):
        delta = ChatLogDelta()
        rows = [chat_line(word) for word in ('a', 'b', 'c')]
        delta.update(['\n'.join(rows[:2])])
        self.assertEqual(delta.update(['']), [])
        self.assertEqual(delta.update(['\n'.join(rows)]), [parse_chat_log(rows[2])[0]])
        self.assertEqual(delta.update(['\n'.join(rows[1:])]), [])

    def test_group_mirror_nodes_emit_once_even_when_order_changes(self):
        delta = ChatLogDelta()
        delta.update([''])
        group = chat_line('team', 'Group')
        main = chat_line('hi') + '\n' + group
        self.assertEqual(len(delta.update([main, group])), 2)
        self.assertEqual(delta.update([group, main]), [])

    def test_view_switch_known_history_is_not_replayed(self):
        delta = ChatLogDelta()
        nearby, group = chat_line('hi'), chat_line('team', 'Group')
        delta.update([nearby])
        self.assertEqual(len(delta.update([group])), 1)
        self.assertEqual(delta.update([nearby]), [])
        self.assertEqual(delta.update([group]), [])

    def test_partially_mirrored_group_window_does_not_duplicate_shared_row(self):
        delta = ChatLogDelta()
        delta.update([''])
        shared = chat_line('shared', 'Group')
        first = chat_line('nearby') + '\n' + shared
        second = shared + '\n' + chat_line('new', 'Group')
        self.assertEqual(len(delta.update([first, second])), 3)

    def test_empty_start_captures_first_message(self):
        delta = ChatLogDelta()
        delta.update([''])
        self.assertEqual(len(delta.update([chat_line('hi')])), 1)

    def test_large_history_reset_is_absorbed(self):
        delta = ChatLogDelta()
        delta.update([''])
        self.assertEqual(delta.update(['\n'.join(chat_line(str(i)) for i in range(101))]), [])

    def test_clients_have_independent_baselines(self):
        first, second = ChatLogDelta(), ChatLogDelta()
        first.update([chat_line('old')])
        second.update([''])
        self.assertEqual(len(second.update([chat_line('old')])), 1)

    def test_bounded_seen_history_is_not_filled_by_unchanged_polls(self):
        delta = ChatLogDelta()
        for _ in range(30):
            delta.update([chat_line('hi')])
        self.assertEqual(len(delta.seen), 1)
