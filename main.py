from astrbot.api.all import *
import re
import aiohttp
import asyncio
from astrbot.api.event import filter, AstrMessageEvent
from astrbot.api.message_components import Node, Plain, Nodes, Image as CompImage, Image

@register("RosaSessionFaker", "ReedSein", "一个伪造转发消息的插件", "1.2.2", "https://github.com/ReedSein/astrbot_plugin_SessionFaker")
class SessionFakerPlugin(Star):
    def __init__(self, context: Context):
        super().__init__(context)
        self.nickname_cache = {} # 内存缓存
        self._session = None
        logger.debug("伪造转发消息插件(v1.2.2 修复版)已初始化")

    async def _get_session(self):
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession()
        return self._session

    async def get_qq_nickname(self, qq_number: str) -> str:
        if qq_number in self.nickname_cache:
            return self.nickname_cache[qq_number]

        url = f"http://api.mmp.cc/api/qqname?qq={qq_number}"
        try:
            session = await self._get_session()
            async with session.get(url, timeout=5) as response:
                if response.status == 200:
                    data = await response.json()
                    if data.get("code") == 200 and data.get("data", {}).get("name"):
                        nickname = data["data"]["name"]
                        if nickname:
                            self.nickname_cache[qq_number] = nickname
                            return nickname
        except Exception as e:
            logger.warning(f"获取QQ {qq_number} 昵称失败: {str(e)}")
        
        return f"用户{qq_number}"

    async def parse_message_components(self, message_obj):
        """解析消息组件"""
        segments = []
        current_segment = {"text": "", "images": []}
        
        # 1. 获取原始消息链列表 (修复 'not iterable' 错误)
        if hasattr(message_obj, "message") and isinstance(message_obj.message, list):
            chain = message_obj.message
        elif isinstance(message_obj, list):
            chain = message_obj
        else:
            chain = []

        # 2. 预处理：移除指令前缀 "伪造消息"
        # 我们构建一个新的临时链来处理，避免修改原始对象
        processed_chain = []
        first_processed = False
        
        for comp in chain:
            if not first_processed and isinstance(comp, Plain):
                # 只在第一个文本节点处理前缀
                text = comp.text
                if "伪造消息" in text:
                    # 替换一次，并去除首尾空格
                    text = text.replace("伪造消息", "", 1).lstrip()
                processed_chain.append(Plain(text))
                first_processed = True
            else:
                processed_chain.append(comp)

        # 3. 开始分段解析
        for comp in processed_chain:
            if isinstance(comp, Plain):
                # 使用 | 分割
                parts = comp.text.split("|")
                current_segment["text"] += parts[0]
                
                if len(parts) > 1:
                    # 保存当前段落
                    if current_segment["text"].strip() or current_segment["images"]:
                        segments.append(current_segment)
                    
                    # 处理中间的段落（纯文本）
                    for i in range(1, len(parts) - 1):
                        segments.append({"text": parts[i], "images": []})
                    
                    # 开始新段落
                    current_segment = {"text": parts[-1], "images": []}
            
            elif isinstance(comp, Image) and hasattr(comp, 'url') and comp.url:
                current_segment["images"].append(comp.url)
        
        # 保存最后一个段落
        if current_segment["text"].strip() or current_segment["images"]:
            segments.append(current_segment)
            
        return segments

    @filter.command("伪造消息")
    async def fake_message(self, event: AstrMessageEvent):
        '''创建伪造转发消息。
        格式: 伪造消息 QQ(昵称) 内容 | QQ 内容
        '''
        segments = await self.parse_message_components(event.message_obj)
        if not segments:
            yield event.plain_result('未能解析出任何消息内容。')
            return

        processed_segments = []

        # --- 解析阶段 ---
        for segment in segments:
            text = segment["text"].strip()
            if not text: continue

            # 正则匹配：QQ号 (可选昵称) 内容
            match = re.match(r'^\s*(\d+)(?:\s*\(([^)]*)\))?\s+(.*)', text, re.DOTALL)
            if not match: 
                logger.warning(f"忽略无法解析的段落: {text[:20]}...")
                continue

            qq_number = match.group(1)
            custom_nickname = match.group(2)
            content = match.group(3).strip()
            
            # 调试日志：确认提取到的 QQ 号
            logger.debug(f"解析成功 -> QQ: {qq_number}, 昵称: {custom_nickname}, 内容: {content[:10]}...")

            processed_segments.append({
                "qq": qq_number,
                "custom_nick": custom_nickname,
                "content": content,
                "images": segment["images"]
            })

        if not processed_segments:
            yield event.plain_result('格式错误：未找到有效的 [QQ号 内容] 格式。请检查是否忘记加空格。')
            return

        # --- 并发获取昵称 ---
        unique_qqs = list(set([s["qq"] for s in processed_segments if not s["custom_nick"]]))
        if unique_qqs:
            await asyncio.gather(*[self.get_qq_nickname(qq) for qq in unique_qqs])

        # --- 构建节点 ---
        nodes_list = []
        for seg in processed_segments:
            nickname = seg["custom_nick"]
            if not nickname:
                nickname = self.nickname_cache.get(seg["qq"], f"用户{seg['qq']}")
            
            node_content = []
            if seg["content"]:
                node_content.append(Plain(seg["content"]))
            
            for img_url in seg["images"]:
                try:
                    node_content.append(CompImage.fromURL(img_url))
                except:
                    pass
            
            if node_content:
                # 关键点：确保 uin 是整数。
                # 如果这里解析正确，但依然显示 Bot 头像，说明是底层协议端(OneBot)的问题，而不是插件的问题。
                target_uin = int(seg["qq"])
                nodes_list.append(Node(
                    uin=target_uin,
                    name=nickname,
                    content=node_content
                ))

        if nodes_list:
            yield event.chain_result([Nodes(nodes=nodes_list)])
        else:
            yield event.plain_result("生成失败，无有效节点。")

    async def terminate(self):
        if self._session and not self._session.closed:
            await self._session.close()
