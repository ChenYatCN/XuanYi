"""Guarded text filling; the user chooses the game's channel and sends there."""
import asyncio
import ctypes
import time

from .api import TranslationError
from .window_text import read_control_text
from loguru import logger

async def _chat_edit(client):
    node = client.root_window
    for name in ('WorldView', 'WizardChatBox', 'chatContainer', 'chatEditContainer', 'chatEdit'):
        node = await node.get_child_by_name(name)
        if not await node.is_visible():
            if name in ('chatEditContainer', 'chatEdit'):
                raise RuntimeError(f'{name} 不可见，请先在游戏里展开聊天输入栏（只显示聊天记录不够）')
            raise RuntimeError(f'{name} 不可见，请先展开聊天框')
    if await node.maybe_read_type_name() != 'ControlFreeChat':
        raise RuntimeError('聊天输入控件类型不符')
    return node

async def _chat_readback(client, edit, text):
    current = await _chat_edit(client)
    address = await current.read_base_address()
    expected_address = await edit.read_base_address()
    actual = await read_control_text(current)
    # Do not issue /s or touch chatEditPrefix: preserve the selected channel
    # and private recipient. This proves filling only, never sending.
    matched = address == expected_address and actual == text
    logger.debug('聊天填入回读：{}，地址={}，原地址={}，期望={!r}，实际={!r}，匹配={}',
                 client.title, address, expected_address, text, actual, matched)
    return matched

async def _type_chat(client, text):
    # WM_CHAR goes to this client's HWND only, never the foreground keyboard.
    send = ctypes.windll.user32.SendMessageTimeoutW
    send.argtypes = [ctypes.c_void_p, ctypes.c_uint, ctypes.c_size_t,
                     ctypes.c_ssize_t, ctypes.c_uint, ctypes.c_uint,
                     ctypes.POINTER(ctypes.c_size_t)]
    send.restype = ctypes.c_ssize_t
    for char in text:
        if not client.is_running():
            raise RuntimeError('输入期间客户端离线')
        response = ctypes.c_size_t()
        if not send(client.window_handle, 0x102, ord(char), 0, 2, 100,
                    ctypes.byref(response)):
            raise RuntimeError('目标窗口未及时处理字符；未发送')
        await asyncio.sleep(.01)


def has_chinese(text):
    return any('\u3400' <= char <= '\u9fff' or '\uf900' <= char <= '\ufaff' for char in text)


def validate_message(text, *, english=False):
    if (not isinstance(text, str) or not text.strip() or len(text) > 80 or any(
            not char.isprintable() or ord(char) > 0xFFFF or 0xD800 <= ord(char) <= 0xDFFF
            for char in text) or (english and has_chinese(text))):
        raise TranslationError('消息须为 1–80 个可打印字符，不支持换行或 emoji；英文译文不可含中文。')
    return text


async def chat_ready(client):
    if not client.is_running():
        raise RuntimeError('客户端已关闭。')
    # These checks use root UI only, not player/duel/teleport hooks.
    if await client.is_loading() or await client.is_in_dialog():
        raise RuntimeError('正在加载或与 NPC 对话；未发送。')
    world = await client.root_window.get_child_by_name('WorldView')
    if not await world.is_visible():
        raise RuntimeError('尚未进入角色界面；未发送。')
    return (client.window_handle, await client.root_window.read_base_address(),
            await world.read_base_address())


async def send_once(reader, text, api, active, publish):
    """One user action -> one body fill, no channel command and no Enter."""
    validate_message(text)
    client = reader.client
    if client is None or not active():
        raise RuntimeError('请先开始读取并选择目标客户端。')
    if not reader.owned_hook:
        raise RuntimeError('正在复用其他工具的连接；为避免输入冲突，请退出其他工具后停止并重新开始读取。')
    await chat_ready(client)
    if has_chinese(text):
        if api is None:
            raise TranslationError('请先配置 API Key；中文原文不会直接输入游戏。')
        publish({'status': '正在将中文翻译为英文；尚未输入游戏。'})
        try:
            translated = await asyncio.to_thread(api.translate, text, target_language='en')
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            safe = str(exc) if isinstance(exc, TranslationError) else '翻译失败；未输入中文原文。'
            raise TranslationError(safe) from None
        validate_message(translated, english=True)
        if not active():
            raise RuntimeError('翻译期间配置或客户端发生变化；未输入、未发送。')
        text = translated
        publish({'status': '英文：' + text, 'translation': text})
    async with asyncio.timeout(8):
        stage = await chat_ready(client)
        edit = await _chat_edit(client)
        if await read_control_text(edit):
            raise RuntimeError('游戏聊天框已有草稿，未覆盖、未发送。')
        # Same controls as the existing manual flow; only coordinate support.
        await reader.prepare_send()
        if not active() or await chat_ready(client) != stage:
            raise RuntimeError('客户端状态发生变化；未输入、未发送。')
        current = await _chat_edit(client)
        if await current.read_base_address() != await edit.read_base_address() or await read_control_text(current):
            raise RuntimeError('聊天控件或草稿发生变化；未覆盖、未发送。')
        async with client.mouse_handler:
            await client.mouse_handler.click_window(edit)
        if not active() or await read_control_text(edit):
            raise RuntimeError('点击后状态或草稿发生变化；未发送。')
        await _type_chat(client, text)
        deadline = time.monotonic() + 1
        while not await _chat_readback(client, edit, text):
            if not active():
                raise RuntimeError('操作已取消；请检查游戏草稿，未继续发送。')
            if time.monotonic() >= deadline:
                raise RuntimeError('输入回读不一致；未自动发送，请检查游戏草稿。')
            await asyncio.sleep(.05)
        if not active() or await chat_ready(client) != stage or not await _chat_readback(client, edit, text):
            raise RuntimeError('填入后状态或正文发生变化；未自动发送，请检查游戏草稿。')
        return {'status': '英文已填入；请在游戏里确认频道和收件人后发送。',
                'filled': True, 'invoked': False, 'message': text}

