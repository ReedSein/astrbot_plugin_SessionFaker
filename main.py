from astrbot.api.all import *
import re
import aiohttp
import asyncio
from astrbot.api.event import filter, AstrMessageEvent
from astrbot.api.message_components import Node, Plain, Nodes, Image as CompImage, Image

@register("SessionFaker", "ReedSein", "一个伪造转发消息的插件", "1.2.0", "https://github.com/ReedSein/astrbot_plugin_SessionFaker")
class SessionFakerPlugin(Star):
    def __init__(self, context: Context):
        super().__init__(context)
        self.nickname_cache = {} # 内存缓存：{qq: nickname}，重启后自动清空
        self._session = None # 复用 HTTP Session
        logger.debug("伪造转发消息插件(优化版 v1.2.0)已初始化")

    async def _get_session(self):
        """懒加载获取 session"""
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession()
        return self._session

    async def get_qq_nickname(self, qq_number: str) -> str:
        """获取QQ昵称 (带内存缓存 + 复用Session)"""
        # 1. 查缓存 (O(1) 复杂度)
        if qq_number in self.nickname_cache:
            return self.nickname_cache[qq_number]

        url = f"http://api.mmp.cc/api/qqname?qq={qq_number}"
        try:
            session = await self._get_session()
            # 设置超时，防止 API 挂起导致整个流程卡住
            async with session.get(url, timeout=5) as response: 
                if response.status == 200:
                    data = await response.json()
                    if data.get("code") == 200 and data.get("data", {}).get("name"):
                        nickname = data["data"]["name"]
                        if nickname:
                            # 2. 写入缓存
                            self.nickname_cache[qq_number] = nickname
                            logger.debug(f"已缓存昵称: {qq_number} -> {nickname}")
                            return nickname
        except Exception as e:
            logger.warning(f"获取QQ {qq_number} 昵称失败: {str(e)}")
        
        return f"用户{qq_number}"

    async def parse_message_components(self, message_obj):
        """解析消息组件，分离文本和图片"""
        segments = []
        current_segment = {"text": "", "images": []}
        
        # 获取纯文本部分用于分割，移除指令前缀避免干扰
        # 注意：AstrBot 的 command 过滤器可能已经处理了部分前缀，这里做防御性编程
        raw_str = message_obj.message_str
        if raw_str.startswith("伪造消息"):
            raw_str = raw_str.replace("伪造消息", "", 1)
            
        # 尝试重构消息链逻辑
        # 这里沿用你原始的逻辑思路，但在处理 command 时稍微调整
        
        # 为了兼容性，我们直接遍历 message_obj
        # 如果第一个节点是纯文本且包含命令，去掉它
        iterator = iter(message_obj)
        first_node = next(iterator, None)
        
        processed_chain = []
        if first_node:
            if isinstance(first_node, Plain):
                text = first_node.text
                if text.strip().startswith("伪造消息"):
                    text = text.replace("伪造消息", "", 1).lstrip()
                processed_chain.append(Plain(text))
            else:
                processed_chain.append(first_node)
            
            # 添加剩余节点
            for node in iterator:
                processed_chain.append(node)

        # 开始解析
        for comp in processed_chain:
            if isinstance(comp, Plain):
                parts = comp.text.split("|")
                current_segment["text"] += parts[0]
                
                if len(parts) > 1:
                    # 当前段落结束，保存
                    if current_segment["text"].strip() or current_segment["images"]:
                        segments.append(current_segment)
                    
                    # 中间的段落（纯文本）
                    for i in range(1, len(parts) - 1):
                        segments.append({"text": parts[i], "images": []})
                    
                    # 开启新段落
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
        示例: 伪造消息 123456(张三) 你好 | 654321 我也好
        '''
        
        segments = await self.parse_message_components(event.message_obj)
        if not segments:
            yield event.plain_result('未能解析出任何消息内容。请检查格式。')
            return

        # --- 阶段 1: 预处理与任务分发 ---
        tasks = []
        processed_segments = []

        for segment in segments:
            text = segment["text"].strip()
            if not text: continue

            # 解析 QQ、昵称、内容
            match = re.match(r'^\s*(\d+)(?:\s*\(([^)]*)\))?\s+(.*)', text, re.DOTALL)
            if not match: continue

            qq_number = match.group(1)
            custom_nickname = match.group(2)
            content = match.group(3).strip()
            images = segment["images"]

            seg_data = {
                "qq": qq_number,
                "custom_nick": custom_nickname,
                "content": content,
                "images": images
            }
            processed_segments.append(seg_data)

            # 如果没有自定义昵称，且不在缓存中，则需要请求
            if not custom_nickname:
                # get_qq_nickname 内部会处理缓存检查，这里直接调用即可
                # 但为了 asyncio.gather 的效率，我们收集所有非自定义昵称的 task
                pass

        # --- 阶段 2: 并发网络请求 ---
        # 找出所有需要获取昵称的 QQ 号 (去重可以进一步优化，但在缓存层做也行)
        unique_qqs_to_fetch = list(set([s["qq"] for s in processed_segments if not s["custom_nick"]]))
        
        if unique_qqs_to_fetch:
            logger.debug(f"开始并发获取 {len(unique_qqs_to_fetch)} 个用户的昵称...")
            # 这里会并发执行所有网络请求，等待所有结果返回
            # 结果会自动写入 self.nickname_cache
            await asyncio.gather(*[self.get_qq_nickname(qq) for qq in unique_qqs_to_fetch])
        
        # --- 阶段 3: 组装消息链 ---
        nodes_list = []

        for seg in processed_segments:
            # 确定最终昵称：优先用自定义的，否则从缓存取（刚才的并发请求已经保证缓存里有了）
            nickname = seg["custom_nick"]
            if not nickname:
                nickname = self.nickname_cache.get(seg["qq"], f"用户{seg['qq']}")
            
            node_content = []
            if seg["content"]:
                node_content.append(Plain(seg["content"]))
            
            for img_url in seg["images"]:
                try:
                    node_content.append(CompImage.fromURL(img_url))
                except Exception as e:
                    logger.warning(f"图片加载失败: {e}")
            
            if node_content:
                nodes_list.append(Node(
                    uin=int(seg["qq"]),
                    name=nickname,
                    content=node_content
                ))

        if nodes_list:
            yield event.chain_result([Nodes(nodes=nodes_list)])
        else:
            yield event.plain_result("解析失败，未生成有效节点。")

    async def terminate(self):
        '''插件卸载时关闭 HTTP Session'''
        logger.debug("伪造消息插件正在停止，清理资源...")
        if self._session and not self._session.closed:
            await self._session.close()
