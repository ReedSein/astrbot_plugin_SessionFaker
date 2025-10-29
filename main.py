from astrbot.api.all import *
import re
import aiohttp
from astrbot.api.event import filter, AstrMessageEvent
from astrbot.api.message_components import Node, Plain, Nodes, Image as CompImage, Image

# @register 装饰器现在反映了更新后的版本和描述
@register(
    "SessionFaker", 
    "Jason.Joestar", 
    "一个伪造转发消息的插件，支持自定义昵称和图片。", 
    "1.1.0", # 版本已更新
    "https://github.com/advent259141/astrbot_plugin_SessionFaker"
)
class SessionFakerPlugin(Star):
    def __init__(self, context: Context):
        super().__init__(context)
        logger.debug("伪造转发消息插件已初始化")
    
    async def get_qq_nickname(self, qq_number: str) -> str:
        """通过外部 API 异步获取 QQ 昵称。"""
        url = f"http://api.mmp.cc/api/qqname?qq={qq_number}"
        
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(url) as response:
                    if response.status == 200:
                        data = await response.json()
                        logger.debug(f"QQ 昵称 API 返回: {data}")
                        
                        if data.get("code") == 200 and data.get("data", {}).get("name"):
                            nickname = data["data"]["name"]
                            logger.debug(f"成功提取昵称: {nickname}")
                            return nickname
        except Exception as e:
            logger.warning(f"获取或解析 {qq_number} 的昵称失败: {e}")
        
        # 备用昵称
        return f"用户{qq_number}"
    
    async def parse_message_segments(self, message_obj: Message) -> list[dict]:
        """
        将 Message 对象解析为按 '|' 分割的、包含文本和关联图片的段落。
        这是能够优雅处理混合内容的核心解析器。
        """
        segments = []
        current_segment = {"text": "", "images": []}
        
        # 直接从消息链中移除命令前缀
        message_chain = message_obj.lstrip_str("伪造消息").lstrip()

        for comp in message_chain:
            if isinstance(comp, Plain):
                text_parts = comp.text.split('|')
                # 将第一部分追加到当前段落的文本中
                current_segment["text"] += text_parts[0]
                
                # 如果存在多个部分，说明遇到了分隔符
                if len(text_parts) > 1:
                    # 完成并追加当前段落
                    if current_segment["text"].strip() or current_segment["images"]:
                        segments.append(current_segment)
                    
                    # 添加所有中间的、纯文本的段落
                    for part in text_parts[1:-1]:
                        segments.append({"text": part, "images": []})
                    
                    # 用最后一部分开启一个新段落
                    current_segment = {"text": text_parts[-1], "images": []}

            elif isinstance(comp, Image) and comp.url:
                current_segment["images"].append(comp.url)
        
        # 如果最后一个段落有内容，则追加它
        if current_segment["text"].strip() or current_segment["images"]:
            segments.append(current_segment)
            
        logger.debug(f"消息被解析为 {len(segments)} 个段落。")
        return segments
    
    # 架构优化：使用过滤器以提升效率。
    # 现在只有以 "伪造消息" 开头的消息才会触发此函数。
    @filter.startswith("伪造消息")
    async def on_fake_session_command(self, event: AstrMessageEvent):
        '''处理 "伪造消息" 命令'''
        
        # 逻辑简化：现在完全依赖于健壮的组件解析器。
        segments = await self.parse_message_segments(event.message_obj)
        
        if not segments:
            yield event.plain_result("未能解析出任何消息内容。请检查格式。")
            return
        
        nodes_list = []
        
        for segment in segments:
            text = segment["text"].strip()
            images = segment["images"]
            
            if not text:
                continue

            # 新功能：整合了您为自定义昵称设计的更优的正则表达式。
            match = re.match(r'^\s*(\d+)(?:\s*\(([^)]*)\))?\s*(.*)', text, re.DOTALL)
            if not match:
                logger.debug(f"段落格式错误，已跳过: '{text}'")
                continue
                
            qq_number, custom_nickname, content = match.groups()
            content = content.strip()
            
            # 新功能：优先使用自定义昵称，否则从 API 获取。
            nickname = custom_nickname if custom_nickname else await self.get_qq_nickname(qq_number)
            
            # 构建 Node 的内容
            node_content = []
            if content:
                node_content.append(Plain(content))
            
            for img_url in images:
                try:
                    node_content.append(CompImage.fromURL(img_url))
                    logger.debug(f"为 UIN {qq_number} 的节点添加了图片 {img_url}")
                except Exception as e:
                    logger.warning(f"添加图片到节点失败: {e}")
            
            # 一个节点必须有内容
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
            yield event.plain_result("未能解析出任何有效的消息节点。请检查格式，例如：\n伪造消息 12345(张三) 你好 | 67890 你好啊")
    
    @filter.command("伪造帮助")
    async def help_command(self, event: AstrMessageEvent):
        """显示插件的帮助信息"""
        # 更新帮助文本以包含新功能
        help_text = """📱 伪造转发消息插件使用说明 📱

【基本格式】
`伪造消息 QQ号 消息内容 | QQ号 消息内容`

【自定义昵称格式】
`伪造消息 QQ号(昵称) 消息内容`
如果提供了昵称，将使用你指定的昵称；否则，插件会自动尝试获取QQ昵称。

【混合示例】
`伪造消息 12345(张三) 你好！ | 67890 你好啊！`

【带图片的格式】
在任意消息段中附带图片即可。图片会自动归属到它所在的消息段。
`伪造消息 12345(张三) 看我的新头像[图片] | 67890 很好看！`

【注意事项】
- 命令头 `伪造消息` 与第一个QQ号之间需要有空格。
- 每个消息段之间用 `|` 符号分隔。
"""
        yield event.plain_result(help_text)
            
    async def terminate(self):
        '''当插件被卸载或停用时调用'''
        logger.info("伪造转发消息插件已卸载")
        pass