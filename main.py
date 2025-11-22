from astrbot.api.all import *
import re
import aiohttp
import asyncio
from astrbot.api.event import filter, AstrMessageEvent
from astrbot.api.message_components import Node, Plain, Nodes, Image as CompImage, Image

@register("SessionFaker", "Jason.Joestar", "一个伪造转发消息的插件", "1.2.4", "https://github.com/advent259141/astrbot_plugin_SessionFaker")
class SessionFakerPlugin(Star):
    def __init__(self, context: Context):
        super().__init__(context)
        self.nickname_cache = {} 
        self._session = None
        self.headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        }
        logger.info("SessionFaker v1.2.4 (诊断版) 已加载")

    async def _get_session(self):
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession(headers=self.headers)
        return self._session

    async def get_qq_nickname(self, qq_number: str) -> str:
        if qq_number in self.nickname_cache:
            return self.nickname_cache[qq_number]

        # 使用更稳定的接口，并增加容错
        apis = [
            f"https://api.usuuu.com/qq/{qq_number}",
            f"http://api.mmp.cc/api/qqname?qq={qq_number}",
        ]

        session = await self._get_session()
        for url in apis:
            try:
                async with session.get(url, timeout=2) as response:
                    if response.status == 200:
                        data = await response.json(content_type=None) # 忽略 content-type
                        name = ""
                        if isinstance(data, dict):
                            if data.get("code") == 200:
                                name = data.get("data", {}).get("name")
                        if name:
                            self.nickname_cache[qq_number] = name
                            return name
            except Exception:
                continue
        
        return f"用户{qq_number}"

    @filter.command("伪造测试")
    async def test_fake(self, event: AstrMessageEvent):
        '''
        诊断指令：发送一条硬编码的伪造消息。
        如果这条消息显示的还是Bot头像，说明是协议端问题，不是插件问题。
        '''
        logger.info("执行诊断指令...")
        node1 = Node(uin=10001, name="测试员A", content=[Plain("这是硬编码测试 A")])
        node2 = Node(uin=10002, name="测试员B", content=[Plain("这是硬编码测试 B")])
        
        yield event.chain_result([Nodes(nodes=[node1, node2])])

    @filter.command("伪造消息")
    async def fake_message(self, event: AstrMessageEvent):
        '''格式: 伪造消息 QQ 内容 | QQ 内容'''
        
        # --- 1. 暴力获取纯文本 ---
        raw_text = event.message_str
        # 移除指令部分，无论它长什么样
        # 匹配 "伪造消息" 及其左边的所有字符
        raw_text = re.sub(r'^.*?伪造消息', '', raw_text, flags=re.IGNORECASE).strip()
        
        if not raw_text:
            yield event.plain_result("未检测到内容。请使用：/伪造消息 QQ 内容 | QQ 内容")
            return

        # --- 2. 分割与解析 ---
        raw_segments = raw_text.split('|')
        processed_segments = []
        
        # 图片提取比较复杂，为了诊断核心问题，v1.2.4 暂时简化图片逻辑：
        # 如果段落里有图片，会尝试从 event.message_obj 对应位置找（这里简化为纯文本逻辑优先）
        # 只要解决了“变成Bot”的问题，图片以后好加。

        for seg_text in raw_segments:
            seg_text = seg_text.strip()
            if not seg_text: continue

            # 暴力正则：只要发现 数字+空格+内容 就捕获
            # 不再要求必须在开头 (^)
            match = re.search(r'(\d+)(?:\s*\((.*?)\))?\s+(.+)', seg_text, re.DOTALL)
            
            if match:
                qq = match.group(1)
                nick = match.group(2)
                content = match.group(3)
                processed_segments.append({
                    "qq": qq,
                    "nick": nick,
                    "content": content
                })
            else:
                # 没匹配到，记录日志帮助排查
                logger.warning(f"丢弃无法解析的片段: [{seg_text}]")

        if not processed_segments:
            yield event.plain_result(f"解析失败。插件看到的文本是：\n{raw_text}\n请确保 QQ号和内容之间有空格。")
            return

        # --- 3. 获取昵称 ---
        unique_qqs = list(set([s["qq"] for s in processed_segments if not s["nick"]]))
        if unique_qqs:
            # 无论API成不成功，都不要阻塞太久
            try:
                await asyncio.wait_for(
                    asyncio.gather(*[self.get_qq_nickname(qq) for qq in unique_qqs]), 
                    timeout=5.0
                )
            except asyncio.TimeoutError:
                logger.warning("昵称获取超时，将使用默认格式")

        # --- 4. 构建节点 ---
        nodes_list = []
        for seg in processed_segments:
            final_nick = seg["nick"]
            if not final_nick:
                final_nick = self.nickname_cache.get(seg["qq"], f"用户{seg['qq']}")
            
            # 调试日志
            logger.info(f"构建节点 -> UIN:{seg['qq']} Name:{final_nick} Content:{seg['content']}")

            nodes_list.append(Node(
                uin=int(seg["qq"]), # 确保是 int
                name=str(final_nick),
                content=[Plain(str(seg["content"]))]
            ))

        yield event.chain_result([Nodes(nodes=nodes_list)])

    async def terminate(self):
        if self._session and not self._session.closed:
            await self._session.close()
