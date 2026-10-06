import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock
from xuanyi.window_text import read_control_text

def control(text, *, kind='ControlFreeChat', capacity=None, pointer=0x40000):
    encoded = text.encode('utf-16-le')
    length = len(encoded) // 2
    capacity = (7 if length <= 7 else length + 8) if capacity is None else capacity
    address = 0x20000 + (712 if kind in ('ControlText', 'ControlList', 'ControlFreeChat') else 736)
    header = {address: pointer, address + 16: length, address + 24: capacity}

    async def typed(at, _primitive):
        return header[at]

    async def read(at, size):
        if at != (address if capacity == 7 else pointer):
            raise AssertionError(f'wrong string address: {at}')
        return encoded[:size]

    return SimpleNamespace(
        maybe_read_type_name=AsyncMock(return_value=kind),
        read_base_address=AsyncMock(return_value=0x20000),
        read_typed=AsyncMock(side_effect=typed),
        read_bytes=AsyncMock(side_effect=read),
        # Root and packaged dependencies have different maybe_text offsets.
        maybe_text=AsyncMock(side_effect=RuntimeError('Unable to read memory at address 7.')),
    )

class ChatControlTextTests(unittest.IsolatedAsyncioTestCase):
    async def test_logged_freechat_capacity_is_not_a_string_pointer(self):
        window = control('')
        base = 0x1F702224F90 - 736
        window.read_base_address.return_value = base
        # The live failure logged these fields at the old +736 header. Its
        # first value 7 belongs to the capacity at +712+24, not a pointer.
        # An empty draft at the correct header is the regression fixture;
        # the original log did not capture the actual draft length at +728.
        values = {base + 712: 0, base + 728: 0, base + 736: 7,
                  base + 752: 256, base + 760: 2160565320096}
        window.read_typed.side_effect = lambda at, _primitive: values[at]
        self.assertEqual(await read_control_text(window), '')
        self.assertEqual([call.args[0] for call in window.read_typed.await_args_list],
                         [base + 728, base + 736])
        window.read_bytes.assert_not_awaited()

    async def test_empty_draft_and_inline_text(self):
        for text in ('', 'hello', '1234567', '聊天草稿'):
            with self.subTest(text=text):
                window = control(text)
                self.assertEqual(await read_control_text(window), text)
                window.maybe_text.assert_not_awaited()

    async def test_heap_draft_uses_validated_pointer_not_dependency_fallback(self):
        for kind in ('ControlFreeChat', 'ControlText', 'ControlList', 'ControlButton'):
            with self.subTest(kind=kind):
                window = control('/s hello', kind=kind)
                self.assertEqual(await read_control_text(window), '/s hello')
                window.maybe_text.assert_not_awaited()

    async def test_invalid_small_pointer_never_dereferenced(self):
        window = control('/s hello', pointer=7)
        with self.assertRaisesRegex(RuntimeError, 'ControlFreeChat.*pointer=7'):
            await read_control_text(window)
        window.read_bytes.assert_not_awaited()
        window.maybe_text.assert_not_awaited()

    async def test_invalid_header_is_not_treated_as_empty_draft(self):
        for text, capacity in (('', 0), ('draft', 2), ('12345678', 7), ('draft', -1)):
            with self.subTest(text=text, capacity=capacity):
                window = control(text, capacity=capacity)
                with self.assertRaisesRegex(RuntimeError, 'ControlFreeChat.*length=.*capacity='):
                    await read_control_text(window)
                window.read_bytes.assert_not_awaited()
                window.maybe_text.assert_not_awaited()

    async def test_invalid_utf16_is_not_treated_as_empty_draft(self):
        window = control('x')
        window.read_bytes = AsyncMock(return_value=b'\x00\xd8')
        with self.assertRaises(UnicodeDecodeError):
            await read_control_text(window)
