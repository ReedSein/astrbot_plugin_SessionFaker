from astrbot.api.all import *
import re
import aiohttp
from astrbot.api.event import filter, AstrMessageEvent
from astrbot.api.message_components import Node, Plain, Nodes, Image as CompImage, Image

# 插件注册信息保持不变
@register("SessionFaker", "Jason.Joestar", "一个伪造转发消息的插件", "1.1.0", "插件仓库URL")
class SessionFakerPlugin(Star):
    # 修正：插件的初始化方法是 __init__，而不是 init
    def __init__(self, context: Context):
        super().__init__(context)
        logger.debug("伪造转发消息插件已初始化")

    async def get_qq_nickname(self, qq_number):
        """获取QQ昵称"""
        url = f"http://api.mmp.cc/api/qqname?qq={qq_number}"
        
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(url) as response:
                    if response.status == 200:
                        data = await response.json()
                        logger.debug(f"QQ昵称API返回: {data}")
                        
                        if data.get("code") == 200 and data.get("data", {}).get("name"):
                            nickname = data["data"]["name"]
                            if nickname:
                                logger.debug(f"成功提取昵称: {nickname}")
                                return nickname
        except Exception as e:
            logger.debug(f"解析昵称出错: {str(e)}")
        
        return f"用户{qq_number}"

    # 保持您原有的解析函数结构，不添加导致错误的类型提示
    async def parse_message_components(self, message_obj):
        """按顺序解析消息组件，将图片正确分配到对应的消息段"""
        segments = []
        current_segment = {"text": "", "images": []}
        
        # 移除命令前缀
        message_chain = message_obj.lstrip_str("伪造消息").lstrip()

        for comp in message_chain:
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
                logger.debug(f"将图片 {comp.url} 添加到当前段落")
        
        if current_segment["text"].strip() or current_segment["images"]:
            segments.append(current_segment)
        
        logger.debug(f"解析完成，共有 {len(segments)} 个段落")
        return segments

    # 保持您原有的事件监听方式
    @event_message_type(EventMessageType.ALL)
    async def on_all_message(self, event: AstrMessageEvent):
        '''监听所有消息并检测伪造消息请求'''
        message_text = event.message_str
        
        if not message_text.startswith("伪造消息"):
            return
        
        segments = await self.parse_message_components(event.message_obj)
        
        if not segments:
            yield event.plain_result('未能解析出任何消息内容。请检查格式。')
            return
            
        nodes_list = []
        
        for segment in segments:
            text = segment["text"].strip()
            images = segment["images"]
            
            if not text:
                continue
            
            # 核心修改：应用您提供的新版正则表达式和昵称处理逻辑
            match = re.match(r'^\s*(\d+)(?:\s*\(([^)]*)\))?\s+(.*)', text, re.DOTALL)
            if not match:
                logger.debug(f"段落格式错误，跳过: {text}")
                continue
                
            qq_number = match.group(1)
            custom_nickname = match.group(2)
            content = match.group(3).strip()
            
            # 核心修改：如果自定义昵称存在则使用，否则异步获取
            nickname = custom_nickname if custom_nickname else await self.get_qq_nickname(qq_number)
            
            node_content = []
            if content:
                node_content.append(Plain(content))
            
            for img_url in images:
                try:
                    node_content.append(CompImage.fromURL(img_url))
                    logger.debug(f"为QQ {qq_number} 添加图片: {img_url}")
                except Exception as e:
                    logger.debug(f"添加图片到节点失败: {e}")
            
            if not node_content:
                continue

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
        # 更新帮助文档以反映新功能
        help_text = """📱 伪造转发消息插件使用说明 📱

【基本格式】
伪造消息 QQ号 消息内容 | QQ号 消息内容 | ...

【自定义昵称】
伪造消息 QQ号(昵称) 消息内容 | QQ号(昵称) 消息内容 | ...

如不指定昵称，将自动获取QQ昵称

例如: 伪造消息 123456(张三) 你好！ | 654321(李四) 你好啊！

【带图片的格式】
在任意消息段中添加图片，图片将只出现在它所在的消息段

例如: 伪造消息 123456(张三) 看我的照片[图片] | 654321 好漂亮啊
"""
        yield event.plain_result(help_text)

    async def terminate(self):
        '''插件被卸载/停用时调用'''
        pass