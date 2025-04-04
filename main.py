from astrbot.api.all import *
import re
import aiohttp
import json
import os
from pathlib import Path
from astrbot.api.event import filter, AstrMessageEvent

@register("nodetest", "Jason.Joestar", "一个伪造转发消息的插件", "1.0.0", "插件仓库URL")
class NodeTestPlugin(Star):
    def __init__(self, context: Context):
        super().__init__(context)
        logger.debug("伪造转发消息插件已初始化")
    
    async def get_qq_nickname(self, qq_number):
        """获取QQ昵称"""
        url = f"http://api.mmp.cc/api/qqname?qq={qq_number}"
        
        async with aiohttp.ClientSession() as session:
            async with session.get(url) as response:
                if response.status == 200:
                    try:
                        data = await response.json()
                        logger.debug(f"QQ昵称API返回: {data}")
                        
                        if data.get("code") == 200 and "data" in data and "name" in data["data"]:
                            nickname = data["data"]["name"]
                            logger.debug(f"成功提取昵称: {nickname}")
                            if nickname:
                                return nickname
                    except Exception as e:
                        logger.debug(f"解析昵称出错: {str(e)}")
        
        return f"用户{qq_number}"
    
    async def parse_message_components(self, message_obj):
        """按顺序解析消息组件，将图片正确分配到对应的消息段"""
        segments = []
        current_segment = {"text": "", "images": []}
        segment_started = False
        
        try:
            prefix_skipped = False
            
            if hasattr(message_obj, 'message'):
                for comp in message_obj.message:
                    if isinstance(comp, Plain):
                        text = comp.text
                        
                        if not prefix_skipped and "伪造消息" in text:
                            prefix_pos = text.find("伪造消息")
                            text = text[prefix_pos + len("伪造消息"):].lstrip()
                            prefix_skipped = True
                        
                        if "|" in text:
                            parts = text.split("|")
                            
                            current_segment["text"] += parts[0]
                            segment_started = True
                            
                            if current_segment["text"].strip():
                                segments.append(current_segment)
                            
                            for i in range(1, len(parts)-1):
                                segments.append({"text": parts[i], "images": []})
                            
                            if len(parts) > 1:
                                current_segment = {"text": parts[-1], "images": []}
                                segment_started = True
                        else:
                            current_segment["text"] += text
                            segment_started = True
                    
                    elif isinstance(comp, Image) and hasattr(comp, 'url') and comp.url:
                        if segment_started:
                            current_segment["images"].append(comp.url)
                            logger.debug(f"将图片 {comp.url} 添加到当前段落")
                
                if current_segment["text"].strip():
                    segments.append(current_segment)
            
            logger.debug(f"解析完成，共有 {len(segments)} 个段落")
            
            for i, seg in enumerate(segments):
                img_count = len(seg["images"])
                logger.debug(f"段落 {i+1}: 文本长度={len(seg['text'])}, 图片数量={img_count}")
                if img_count > 0:
                    logger.debug(f"段落 {i+1} 包含的图片: {seg['images']}")
        
        except Exception as e:
            logger.error(f"解析消息组件出错: {str(e)}")
            segments = []
        
        return segments
    
    @event_message_type(EventMessageType.ALL)
    async def on_all_message(self, event: AstrMessageEvent):
        '''监听所有消息并检测伪造消息请求'''
        from astrbot.api.message_components import Node, Plain, Nodes, Image as CompImage
        
        message_text = event.message_str
        
        if not message_text.startswith("伪造消息"):
            return
        
        segments = await self.parse_message_components(event.message_obj)
        
        if not segments:
            pattern = r'伪造消息((?:\s+\d+\s+[^|]+\|)+)'
            match = re.search(pattern, message_text)
            
            if not match:
                yield event.plain_result("格式错误，请使用：伪造消息 QQ号 内容 | QQ号 内容 | ...")
                return
                
            content = match.group(1).strip()
            text_segments = content.split('|')
            
            segments = [{"text": seg.strip(), "images": []} for seg in text_segments if seg.strip()]
        
        nodes_list = []
        
        for segment in segments:
            text = segment["text"]
            images = segment["images"]
            
            match = re.match(r'^\s*(\d+)\s+(.*)', text)
            if not match:
                logger.debug(f"段落格式错误，跳过: {text}")
                continue
                
            qq_number, content = match.group(1), match.group(2).strip()
            
            nickname = await self.get_qq_nickname(qq_number)
            
            node_content = [Plain(content)]
            
            for img_url in images:
                try:
                    node_content.append(CompImage.fromURL(img_url))
                    logger.debug(f"为QQ {qq_number} 添加图片: {img_url}")
                except Exception as e:
                    logger.debug(f"添加图片到节点失败: {e}")
            
            node = Node(
                uin=int(qq_number),
                name=nickname,
                content=node_content
            )
            nodes_list.append(node)
        
        if nodes_list:
            nodes = Nodes(nodes=nodes_list)
            yield event.chain_result([nodes])
        else:
            yield event.plain_result("未能解析出任何有效的消息节点")
    
    @filter.command("伪造帮助")
    async def help_command(self, event: AstrMessageEvent):
        """显示插件帮助信息"""
        help_text = """📱 伪造转发消息插件使用说明 📱

【基本格式】
伪造消息 QQ号 消息内容 | QQ号 消息内容 | ...

【带图片的格式】
- 在任意消息段中添加图片，图片将只出现在它所在的消息段
- 例如: 伪造消息 123456 看我的照片[图片] | 654321 好漂亮啊
- 在这个例子中，图片只会出现在第一个人的消息中

【注意事项】
- 每个消息段之间用"|"分隔
- 每个消息段的格式必须是"QQ号 消息内容"
- 图片会根据它在消息中的位置分配到对应的消息段
"""
        yield event.plain_result(help_text)
            
    async def terminate(self):
        '''插件被卸载/停用时调用'''
        pass
