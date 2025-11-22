from astrbot.api.all import *
import re
import aiohttp
import asyncio
from astrbot.api.event import filter, AstrMessageEvent
from astrbot.api.message_components import Node, Plain, Nodes, Image as CompImage, Image

@register("SessionFaker", "ReedSein", "一个伪造转发消息的插件", "1.2.3", "https://github.com/ReedSein/astrbot_plugin_SessionFaker")
class SessionFakerPlugin(Star):
    def __init__(self, context: Context):
        super().__init__(context)
        self.nickname_cache = {} 
        self._session = None
        # 设置浏览器UA，防止API被拦截
        self.headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        }
        logger.debug("伪造转发消息插件(v1.2.3 强力修复版)已初始化")

    async def _get_session(self):
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession(headers=self.headers)
        return self._session

    async def get_qq_nickname(self, qq_number: str) -> str:
        """获取QQ昵称"""
        if qq_number in self.nickname_cache:
            return self.nickname_cache[qq_number]

        # 备用API列表，提高成功率
        apis = [
            f"http://api.mmp.cc/api/qqname?qq={qq_number}",
            f"https://api.usuuu.com/qq/{qq_number}" # 备用接口
        ]

        session = await self._get_session()
        
        for url in apis:
            try:
                async with session.get(url, timeout=3) as response:
                    if response.status == 200:
                        # 根据不同API返回结构尝试解析
                        try:
                            data = await response.json()
                            name = ""
                            # 适配 mmp.cc
                            if isinstance(data, dict) and data.get("code") == 200:
                                name = data.get("data", {}).get("name")
                            # 适配 usuuu.com
                            elif isinstance(data, dict) and data.get("code") == 200:
                                name = data.get("data", {}).get("name")
                            
                            if name:
                                self.nickname_cache[qq_number] = name
                                return name
                        except:
                            pass
            except Exception:
                continue
        
        # 如果所有API都失败，返回默认值，不打印堆栈以免刷屏
        logger.debug(f"获取QQ {qq_number} 昵称失败，使用默认值")
        return f"用户{qq_number}"

    async def parse_message_components(self, message_obj):
        """解析消息组件"""
        segments = []
        current_segment = {"text": "", "images": []}
        
        # 1. 安全获取消息链
        if hasattr(message_obj, "message") and isinstance(message_obj.message, list):
            chain = message_obj.message
        elif isinstance(message_obj, list):
            chain = message_obj
        else:
            chain = []

        # 2. 预处理：强力去除指令前缀
        processed_chain = []
        first_processed = False
        
        for comp in chain:
            if not first_processed and isinstance(comp, Plain):
                text = comp.text
                # 使用正则去除 "伪造消息" 及其前面的所有字符（包括 / . 等）
                # 匹配模式：开头任意字符 + 伪造消息 + 任意空格
                text = re.sub(r'^.*?伪造消息\s*', '', text, count=1, flags=re.IGNORECASE)
                # 再次清理开头非数字的字符（防止残留的 / 或空格）
                # 只保留开头的数字，确保第一段一定是 QQ 号开头
                # 注意：这里不能把整个 text 的非数字都去掉，只能去掉开头的"垃圾"
                # 查找第一个数字的位置
                match = re.search(r'\d', text)
                if match:
                    text = text[match.start():]
                
                processed_chain.append(Plain(text))
                first_processed = True
            else:
                processed_chain.append(comp)

        # 3. 分段
        for comp in processed_chain:
            if isinstance(comp, Plain):
                parts = comp.text.split("|")
                current_segment["text"] += parts[0]
                
                if len(parts) > 1:
                    if current_segment["text"].strip() or current_segment["images"]:
                        segments.append(current_segment)
                    
                    for i in range(1, len(parts) - 1):
                        segments.append({"text": parts[i], "images": []})
                    
                    current_segment = {"text": parts[-1], "images": []}
            
            elif isinstance(comp, Image) and hasattr(comp, 'url') and comp.url:
                current_segment["images"].append(comp.url)
        
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
            yield event.plain_result('未能解析出消息内容。')
            return

        processed_segments = []
        
        # --- 解析阶段 ---
        for segment in segments:
            text = segment["text"].strip()
            if not text: continue

            # 稍微放宽正则，允许开头有极少量杂乱字符（虽然我们在parse里已经清理了）
            match = re.match(r'^\s*(\d+)(?:\s*\(([^)]*)\))?\s+(.*)', text, re.DOTALL)
            if not match: 
                # 尝试更激进的匹配：查找第一个数字串
                search_match = re.search(r'(\d+)(?:\s*\(([^)]*)\))?\s+(.*)', text, re.DOTALL)
                if search_match:
                    match = search_match
                else:
                    logger.warning(f"忽略无法解析的段落: {text[:20]}...")
                    continue

            qq_number = match.group(1)
            custom_nickname = match.group(2)
            content = match.group(3).strip()
            
            processed_segments.append({
                "qq": qq_number,
                "custom_nick": custom_nickname,
                "content": content,
                "images": segment["images"]
            })

        if not processed_segments:
            yield event.plain_result('未解析出有效节点，请检查格式是否为：QQ号 内容 | ...')
            return

        # --- 并发获取昵称 ---
        unique_qqs = list(set([s["qq"] for s in processed_segments if not s["custom_nick"]]))
        if unique_qqs:
            await asyncio.gather(*[self.get_qq_nickname(qq) for qq in unique_qqs])

        # --- 构建 ---
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
                nodes_list.append(Node(
                    uin=int(seg["qq"]),
                    name=nickname,
                    content=node_content
                ))

        if nodes_list:
            yield event.chain_result([Nodes(nodes=nodes_list)])
        else:
            yield event.plain_result("生成失败。")

    async def terminate(self):
        if self._session and not self._session.closed:
            await self._session.close()
