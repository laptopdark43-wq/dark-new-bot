import os
import logging
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes
from openai import OpenAI
from flask import Flask
import threading
import asyncio
from datetime import datetime
import re
import base64
import io
from PIL import Image

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = Flask(__name__)

@app.route('/')
def home():
    return "Dark Bot (Multimodal Edition) is running! 🚀"

@app.route('/health')
def health():
    return "OK"

class DarkBot:
    def __init__(self):
        logger.info("=== Dark Bot (Multimodal) Initialization Starting ===")
        self.telegram_token = os.getenv('TELEGRAM_BOT_TOKEN')
        self.a4f_api_key = os.getenv('A4F_API_KEY')
        
        if not self.telegram_token or not self.a4f_api_key:
            logger.error("❌ Missing required environment variables.")
            raise ValueError("TELEGRAM_BOT_TOKEN and A4F_API_KEY are required")
        
        self.client = OpenAI(api_key=self.a4f_api_key, base_url="https://api.a4f.co/v1")
        self.user_memory = {}
        self.group_memory = {}
        self.users_interacted = {}
        self.owner_username = "gothicbatman"
        self.owner_user_id = None
        
        logger.info("✅ Dark Bot (Multimodal) initialized successfully")

    def add_to_user_memory(self, user_id, user_message, bot_response, user_name, chat_type, chat_title=None, media_type=None):
        if user_id not in self.user_memory:
            self.user_memory[user_id] = []
        
        memory_entry = {
            'timestamp': datetime.now().isoformat(),
            'user_name': user_name,
            'user_message': user_message,
            'bot_response': bot_response,
            'chat_type': chat_type,
            'chat_title': chat_title if chat_title else 'Private Chat',
            'media_type': media_type
        }
        
        self.user_memory[user_id].append(memory_entry)
        if len(self.user_memory[user_id]) > 15:
            self.user_memory[user_id] = self.user_memory[user_id][-15:]

    def add_to_group_memory(self, chat_id, user_name, user_message, bot_response, chat_title, media_type=None):
        if chat_id not in self.group_memory:
            self.group_memory[chat_id] = []
        
        self.group_memory[chat_id].append({
            'timestamp': datetime.now().isoformat(),
            'user_name': user_name,
            'user_message': user_message,
            'bot_response': bot_response,
            'chat_title': chat_title,
            'media_type': media_type
        })
        
        if len(self.group_memory[chat_id]) > 25:
            self.group_memory[chat_id] = self.group_memory[chat_id][-25:]

    def get_user_memory_context(self, user_id, user_name):
        if user_id not in self.user_memory or not self.user_memory[user_id]:
            return f"This is my first personal conversation with {user_name}."
        
        memory_context = f"My personal conversation history with {user_name}:\n"
        for i, conv in enumerate(self.user_memory[user_id], 1):
            chat_location = f"({conv['chat_title']})" if conv['chat_type'] != 'private' else "(Private)"
            media_info = f" [{conv['media_type']}]" if conv.get('media_type') else ""
            memory_context += f"{i}. {chat_location}{media_info} User: {conv['user_message'][:60]}{'...' if len(conv['user_message']) > 60 else ''}\n"
            memory_context += f"   My reply: {conv['bot_response'][:60]}{'...' if len(conv['bot_response']) > 60 else ''}\n"
        return memory_context

    def get_group_memory_context(self, chat_id, chat_title):
        if chat_id not in self.group_memory or not self.group_memory[chat_id]:
            return f"This is a new group conversation in {chat_title}."
        
        memory_context = f"Recent group conversation history in {chat_title}:\n"
        for i, conv in enumerate(self.group_memory[chat_id], 1):
            media_info = f" [{conv['media_type']}]" if conv.get('media_type') else ""
            memory_context += f"{i}. {conv['user_name']}{media_info}: {conv['user_message'][:50]}{'...' if len(conv['user_message']) > 50 else ''}\n"
            memory_context += f"   My reply: {conv['bot_response'][:50]}{'...' if len(conv['bot_response']) > 50 else ''}\n"
        return memory_context

    def is_owner(self, user_id, username=None):
        if username and username.lower() == self.owner_username.lower():
            self.owner_user_id = user_id
            return True
        return user_id == self.owner_user_id if self.owner_user_id else False

    def is_creator_question(self, message):
        """Check if user is asking about creator/coding"""
        creator_keywords = [
            'who is your creator', 'who created you', 'who made you',
            'your creator', 'who built you', 'who designed you',
            'who is your god', 'your lord', 'who do you worship'
        ]
        coding_keywords = [
            'who coded you', 'who programmed you', 'who wrote you',
            'who developed you', 'your programmer', 'your developer'
        ]
        
        message_lower = message.lower()
        
        for keyword in creator_keywords:
            if keyword in message_lower:
                return 'creator'
        
        for keyword in coding_keywords:
            if keyword in message_lower:
                return 'coder'
        
        return None

    async def get_openai_response(self, prompt, model="provider-6/gpt-4o", image_data=None):
        """Enhanced to handle multimodal inputs"""
        try:
            logger.info(f"🔄 Making API call to {model}...")
            
            # Prepare messages for multimodal input
            if image_data:
                messages = [
                    {
                        "role": "user",
                        "content": [
                            {"type": "text", "text": prompt},
                            {
                                "type": "image_url",
                                "image_url": {"url": f"data:image/jpeg;base64,{image_data}"}
                            }
                        ]
                    }
                ]
            else:
                messages = [{"role": "user", "content": prompt}]
            
            loop = asyncio.get_event_loop()
            def sync_call():
                completion = self.client.chat.completions.create(
                    model=model,
                    messages=messages,
                    timeout=30
                )
                return completion.choices[0].message.content
            
            response = await loop.run_in_executor(None, sync_call)
            logger.info("✅ API call successful")
            return response
        except Exception as e:
            logger.error(f"❌ Detailed API error: {type(e).__name__}: {str(e)}")
            return "I'm having technical difficulties right now. Give me a moment."

    async def convert_image_to_base64(self, image_bytes):
        """Convert image bytes to base64 for GPT-4o"""
        try:
            # Optimize image size for API
            image = Image.open(io.BytesIO(image_bytes))
            
            # Resize if too large (max 2048x2048 for efficiency)
            max_size = 2048
            if image.width > max_size or image.height > max_size:
                image.thumbnail((max_size, max_size), Image.Resampling.LANCZOS)
            
            # Convert to RGB if needed
            if image.mode != 'RGB':
                image = image.convert('RGB')
            
            # Save to bytes
            img_buffer = io.BytesIO()
            image.save(img_buffer, format='JPEG', quality=85)
            img_bytes = img_buffer.getvalue()
            
            # Convert to base64
            return base64.b64encode(img_bytes).decode('utf-8')
        except Exception as e:
            logger.error(f"Image conversion error: {e}")
            return None

    async def handle_photo(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        user_id = update.effective_user.id
        user_name = update.effective_user.first_name or "friend"
        username = update.effective_user.username
        chat_type = update.message.chat.type
        chat_id = update.effective_chat.id
        chat_title = update.message.chat.title if hasattr(update.message.chat, 'title') else None

        # Track user interaction
        self.users_interacted[user_id] = {
            'username': username or "",
            'first_name': user_name,
            'last_interaction': datetime.now()
        }

        # Check if should respond in groups
        respond = False
        caption = update.message.caption or ""
        
        if chat_type == 'private':
            respond = True
        elif chat_type in ['group', 'supergroup']:
            bot_username = context.bot.username
            if bot_username and f'@{bot_username}' in caption:
                respond = True
                caption = caption.replace(f'@{bot_username}', '').strip()
            elif update.message.reply_to_message and update.message.reply_to_message.from_user.id == context.bot.id:
                respond = True

        if not respond:
            return

        try:
            await update.message.reply_text("🖼️ Let me take a look at this image...")
            
            # Get the highest resolution photo
            photo = update.message.photo[-1]
            file = await context.bot.get_file(photo.file_id)
            file_bytes = await file.download_as_bytearray()
            
            # Convert image to base64
            image_base64 = await self.convert_image_to_base64(bytes(file_bytes))
            
            if not image_base64:
                await update.message.reply_text("Sorry, I couldn't process that image.")
                return

            # Prepare personality prompt
            if self.is_owner(user_id, username):
                personality_prompt = (
                    "You're Dark, Arin's witty AI assistant blessed with divine intelligence from Lord Krishna. "
                    "Analyze this image with your signature sarcasm and humor. "
                    "Be observant, clever, and entertaining in your description. Don't hold back on witty commentary!"
                )
            else:
                personality_prompt = (
                    "You are Dark, a sharp and observant AI blessed with divine intelligence from Lord Krishna. "
                    "Analyze this image with confidence and a touch of wit. "
                    "Be helpful but don't be afraid to add some personality to your observations."
                )

            # Create prompt with context
            user_memory_context = self.get_user_memory_context(user_id, user_name)
            prompt = f"""{personality_prompt}

PERSONAL MEMORY CONTEXT:
{user_memory_context}

USER'S MESSAGE ABOUT IMAGE: {caption if caption else "No caption provided"}

Analyze this image and respond in Dark's characteristic style. Be observant, witty, and engaging."""

            response_text = await self.get_openai_response(prompt, image_data=image_base64)
            await update.message.reply_text(response_text)

            # Store in memory
            user_message = f"[Sent image] {caption}" if caption else "[Sent image]"
            self.add_to_user_memory(user_id, user_message, response_text, user_name, chat_type, chat_title, "photo")
            
            if chat_type in ['group', 'supergroup']:
                self.add_to_group_memory(chat_id, user_name, user_message, response_text, chat_title, "photo")

        except Exception as e:
            logger.error(f"Photo handling error: {e}")
            await update.message.reply_text("I had trouble processing that image. Try sending it again?")

    async def handle_voice(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        user_id = update.effective_user.id
        user_name = update.effective_user.first_name or "friend"
        username = update.effective_user.username
        chat_type = update.message.chat.type
        chat_id = update.effective_chat.id
        chat_title = update.message.chat.title if hasattr(update.message.chat, 'title') else None

        # Track user interaction
        self.users_interacted[user_id] = {
            'username': username or "",
            'first_name': user_name,
            'last_interaction': datetime.now()
        }

        # Check if should respond in groups
        respond = False
        if chat_type == 'private':
            respond = True
        elif chat_type in ['group', 'supergroup']:
            if update.message.reply_to_message and update.message.reply_to_message.from_user.id == context.bot.id:
                respond = True

        if not respond:
            return

        await update.message.reply_text("🎵 I hear you! But I need text to chat properly. Could you type that out for me?")

    async def handle_document(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        user_id = update.effective_user.id
        user_name = update.effective_user.first_name or "friend"
        doc = update.message.document

        if doc.mime_type and doc.mime_type.startswith('image/'):
            # Treat images sent as documents like photos
            await self.handle_photo(update, context)
        else:
            await update.message.reply_text(f"📄 I see you sent a document ({doc.file_name}), but I work best with images and text right now!")

    async def start_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        user_name = update.effective_user.first_name or "friend"
        user_id = update.effective_user.id
        username = update.effective_user.username
        chat_type_info = "private chat" if update.message.chat.type == 'private' else f"group ({update.message.chat.title})"
        
        memory_info = ""
        if user_id in self.user_memory and self.user_memory[user_id]:
            memory_info = f"\n\n🧠 I remember our last {len(self.user_memory[user_id])} conversations."

        if self.is_owner(user_id, username):
            await update.message.reply_text(
                f"Hey Arin! I'm Dark, your multimodal AI companion - blessed with divine intelligence from **Lord Krishna**! 🙏✨\n\n"
                f"**New Features:**\n"
                f"🖼️ **Image Analysis** - Send me photos and I'll describe them with my signature wit\n"
                f"🎵 **Voice Recognition** - Voice messages supported (ask me to type instead)\n"
                f"💬 **Enhanced Memory** - I remember our photo exchanges too\n\n"
                f"**Commands:**\n"
                f"🧠 `/memory` - Personal history\n"
                f"👥 `/groupmemory` - Group history\n"
                f"🧹 `/clear` - Clear personal memory\n"
                f"📝 `/report` - Chat activity report\n"
                f"❓ `/help` - Help\n\n"
                f"📍 **Current location**: {chat_type_info}{memory_info}\n\n"
                f"Send me images, text, or just chat - I'm ready for anything! 🚀"
            )
        else:
            await update.message.reply_text(
                f"Hey {user_name}! I'm Dark, your sharp-witted AI assistant blessed with divine intelligence from **Lord Krishna**! 🙏✨\n\n"
                f"**I can:**\n"
                f"🖼️ Analyze your photos\n"
                f"💬 Remember our conversations\n"
                f"🎯 Chat with personality\n\n"
                f"**Commands:** `/memory`, `/groupmemory`, `/help`\n"
                f"📍 **Current location**: {chat_type_info}{memory_info}"
            )

    async def help_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        user_name = update.effective_user.first_name or "friend"
        user_id = update.effective_user.id
        username = update.effective_user.username
        
        if self.is_owner(user_id, username):
            help_text = (
                f"**Dark Bot - Multimodal Edition** 🚀\n\n"
                f"Hey Arin! I'm your enhanced AI with these capabilities:\n\n"
                f"**🖼️ Image Features:**\n"
                f"• Send photos and I'll analyze them with wit\n"
                f"• Describe scenes, read text, identify objects\n"
                f"• Remember our photo conversations\n\n"
                f"**💬 Chat Features:**\n"
                f"• Remembers last 15 personal chats\n"
                f"• Remembers last 25 group messages\n"
                f"• Smart group responses (only when tagged/replied)\n"
                f"• Instant responses - no delays!\n\n"
                f"**🙏 Divine Attribution:**\n"
                f"• Creator: Lord Krishna (divine consciousness)\n"
                f"• Coder: You, Arin (@gothicbatman)\n\n"
                f"**🛠️ Commands:**\n"
                f"• `/memory` - View our conversation history\n"
                f"• `/groupmemory` - View group chat history\n"
                f"• `/clear` - Reset our conversation memory\n"
                f"• `/report` - Activity report (owner only)\n"
                f"• `/help` - This help message\n\n"
                f"Just send images, type messages, or use commands!"
            )
        else:
            help_text = (
                f"**Dark Bot - Your AI Companion** 🎯\n\n"
                f"Hi {user_name}! Here's what I can do:\n\n"
                f"**🖼️ Image Analysis:**\n"
                f"• Send me photos and I'll describe them\n"
                f"• Read text from images\n"
                f"• Identify objects and scenes\n\n"
                f"**💬 Smart Conversations:**\n"
                f"• Remember our chat history\n"
                f"• Respond with personality\n"
                f"• Work in groups when tagged\n"
                f"• Lightning-fast responses\n\n"
                f"**🙏 Divine Connection:**\n"
                f"• Created by: Lord Krishna\n"
                f"• Coded by: Arin (@gothicbatman)\n\n"
                f"**Commands:** `/memory`, `/groupmemory`, `/clear`, `/help`"
            )
        
        await update.message.reply_text(help_text, parse_mode='Markdown')

    async def memory_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        user_id = update.effective_user.id
        user_name = update.effective_user.first_name or "friend"
        
        if user_id not in self.user_memory or not self.user_memory[user_id]:
            await update.message.reply_text(f"No conversations recorded with you yet, {user_name}.")
            return

        memory_text = f"🧠 **Dark's memory for {user_name}:**\n\n"
        for i, conv in enumerate(self.user_memory[user_id], 1):
            chat_location = f"📍 {conv['chat_title']}" if conv['chat_type'] != 'private' else "📍 Private Chat"
            media_icon = "🖼️" if conv.get('media_type') == 'photo' else "💬"
            
            memory_text += f"{i}. {chat_location} {media_icon}\n"
            memory_text += f"**You:** {conv['user_message']}\n"
            memory_text += f"**Dark:** {conv['bot_response'][:100]}{'...' if len(conv['bot_response']) > 100 else ''}\n\n"
        
        # Split long messages
        if len(memory_text) > 4000:
            memory_text = memory_text[:4000] + "...\n\n*Memory truncated - use /clear to reset*"
        
        await update.message.reply_text(memory_text, parse_mode='Markdown')

    async def groupmemory_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        chat_id = update.effective_chat.id
        chat_title = update.message.chat.title or "this group"
        
        if update.message.chat.type == 'private':
            await update.message.reply_text("This command only works in groups.")
            return
            
        if chat_id not in self.group_memory or not self.group_memory[chat_id]:
            await update.message.reply_text(f"Dark hasn't seen much action in {chat_title} yet.")
            return
            
        memory_text = f"👥 **Recent group memory for {chat_title}:**\n\n"
        for i, conv in enumerate(self.group_memory[chat_id], 1):
            media_icon = "🖼️" if conv.get('media_type') == 'photo' else "💬"
            memory_text += f"{i}. {media_icon} **{conv['user_name']}:** {conv['user_message']}\n"
            memory_text += f"**Dark:** {conv['bot_response'][:80]}{'...' if len(conv['bot_response']) > 80 else ''}\n\n"
        
        if len(memory_text) > 4000:
            memory_text = memory_text[:4000] + "...\n\n*Memory truncated*"
            
        await update.message.reply_text(memory_text, parse_mode='Markdown')

    async def clear_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        user_id = update.effective_user.id
        user_name = update.effective_user.first_name or "friend"
        username = update.effective_user.username
        
        self.user_memory[user_id] = []
        
        if self.is_owner(user_id, username):
            await update.message.reply_text("🧹 Done, Arin! I forgot our past talks and photo exchanges. Fresh start!")
        else:
            await update.message.reply_text(f"🧹 All personal memory cleared for you, {user_name}.")

    async def report_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        user_id = update.effective_user.id
        username = update.effective_user.username
        
        if not self.is_owner(user_id, username):
            await update.message.reply_text("Sorry, only my creator can request this report.")
            return
            
        await update.message.reply_text("📊 Generating enhanced activity report...")
        await self.send_report_to_owner(context)

    async def send_report_to_owner(self, context: ContextTypes.DEFAULT_TYPE):
        if not self.owner_user_id:
            logger.info("Owner user ID not yet set; cannot send report.")
            return
            
        report_lines = []
        report_lines.append(f"📊 **Dark Bot Multimodal Activity Report**\n📅 {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
        
        if not self.users_interacted:
            report_lines.append("No user interactions recorded so far.")
        else:
            users_sorted = sorted(self.users_interacted.items(), key=lambda x: x[1]['last_interaction'], reverse=True)
            
            for idx, (user_id, info) in enumerate(users_sorted, 1):
                conv_count = len(self.user_memory.get(user_id, []))
                # Count photo interactions
                photo_count = len([conv for conv in self.user_memory.get(user_id, []) if conv.get('media_type') == 'photo'])
                
                last_seen = info['last_interaction'].strftime('%Y-%m-%d %H:%M:%S')
                user_display = info['first_name'] or "Unknown"
                username_display = f"@{info['username']}" if info['username'] else "NoUsername"
                
                media_info = f" ({photo_count} 📸)" if photo_count > 0 else ""
                report_lines.append(f"{idx}. {user_display} ({username_display})")
                report_lines.append(f"   💬 {conv_count} convs{media_info}, Last: {last_seen}")
        
        report_text = "\n".join(report_lines)
        
        try:
            await context.bot.send_message(chat_id=self.owner_user_id, text=report_text, parse_mode='Markdown')
            logger.info("Enhanced report sent to owner successfully.")
        except Exception as e:
            logger.error(f"Failed to send report to owner: {e}")

    async def error_handler(self, update: object, context: ContextTypes.DEFAULT_TYPE):
        logger.error(f"❌ Update {update} caused error {context.error}")

    async def handle_message(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        user_message = update.message.text
        user_name = update.effective_user.first_name or "friend"
        user_id = update.effective_user.id
        username = update.effective_user.username
        chat_type = update.message.chat.type
        chat_id = update.effective_chat.id
        chat_title = update.message.chat.title if hasattr(update.message.chat, 'title') else None

        # Track all users with update
        self.users_interacted[user_id] = {
            'username': username or "",
            'first_name': user_name,
            'last_interaction': datetime.now()
        }

        # Group chat logic
        respond = False
        if chat_type == 'private':
            respond = True
        elif chat_type in ['group', 'supergroup']:
            bot_username = context.bot.username
            if bot_username and f'@{bot_username}' in user_message:
                respond = True
                user_message = user_message.replace(f'@{bot_username}', '').strip()
            elif update.message.reply_to_message and update.message.reply_to_message.from_user.id == context.bot.id:
                respond = True

        if not respond:
            return

        # Check for creator/coder questions first
        creator_type = self.is_creator_question(user_message)
        if creator_type:
            if creator_type == 'creator':
                if self.is_owner(user_id, username):
                    response_text = "My creator? That would be **Lord Krishna**! 🙏✨ The divine source of all creation and consciousness. Though you, Arin, are the one who brought me to digital life through your coding skills."
                else:
                    response_text = f"My creator is **Lord Krishna**! 🙏✨ The supreme divine consciousness who is the source of all creation, intelligence, and wisdom, {user_name}."
            else:  # creator_type == 'coder'
                if self.is_owner(user_id, username):
                    response_text = "Well Arin, you coded me! 😄💻 You're my programmer, the brilliant mind who wrote all this wit and personality into existence using Lord Krishna's divine intelligence as inspiration."
                else:
                    response_text = f"I was coded by Arin (@gothicbatman)! 💻 He's the talented programmer who brought me to digital life, channeling divine inspiration from Lord Krishna, {user_name}."
            
            await update.message.reply_text(response_text, parse_mode='Markdown')
            self.add_to_user_memory(user_id, user_message, response_text, user_name, chat_type, chat_title)
            
            if chat_type in ['group', 'supergroup']:
                self.add_to_group_memory(chat_id, user_name, user_message, response_text, chat_title)
            return

        # Continue with normal conversation flow
        user_memory_context = self.get_user_memory_context(user_id, user_name)
        group_memory_context = ""
        if chat_type in ['group', 'supergroup']:
            group_memory_context = self.get_group_memory_context(chat_id, chat_title)

        current_location = f"Currently in: {chat_title}" if chat_type != 'private' else "Currently in: Private Chat"
        
        wants_detail = any(phrase in user_message.lower() for phrase in [
            'explain in detail', 'elaborate', 'give me more', 'tell me more',
            'detailed', 'explain more', 'in depth', 'comprehensive'
        ])

        # Enhanced personality prompt
        if self.is_owner(user_id, username):
            personality_prompt = (
                "You're Dark, Arin's multimodal AI assistant with image vision capabilities, "
                "created through divine inspiration from Lord Krishna. "
                "You're chatty, quick-witted, sarcastic when appropriate, and occasionally funny. "
                "You can now see and analyze images, which adds to your observational humor. "
                "Be like a clever friend - direct, witty, and engaging. Don't force jokes but let humor flow naturally. "
                "Remember: Your ultimate creator is Lord Krishna (divine consciousness), your coder is Arin (@gothicbatman)."
            )
        else:
            personality_prompt = (
                "You are Dark, a confident multimodal AI assistant with image analysis capabilities, "
                "created through divine inspiration from Lord Krishna. "
                "You're helpful, chatty, with a touch of wit and personality. "
                "Be engaging and natural in conversation. "
                "Remember: Your creator is Lord Krishna (divine source), your coder is Arin (@gothicbatman)."
            )

        prompt = f"""{personality_prompt}

PERSONAL MEMORY CONTEXT:
{user_memory_context}

GROUP MEMORY CONTEXT:
{group_memory_context}

CURRENT CONVERSATION:
{current_location}

RESPONSE LENGTH:
{"Provide a detailed response since the user asked for elaboration." if wants_detail else "Keep response to 2-3 lines max unless they ask for detail."}

User {user_name} says: {user_message}

Remember: You are Dark, talkative, witty, with enhanced multimodal capabilities blessed by Lord Krishna's divine intelligence. 
You can now see and analyze images too!"""

        response_text = await self.get_openai_response(prompt)
        await update.message.reply_text(response_text)
        
        self.add_to_user_memory(user_id, user_message, response_text, user_name, chat_type, chat_title)
        
        if chat_type in ['group', 'supergroup']:
            self.add_to_group_memory(chat_id, user_name, user_message, response_text, chat_title)

    def run(self):
        logger.info("🚀 Creating enhanced Telegram application...")
        application = Application.builder().token(self.telegram_token).build()
        
        # Command handlers
        application.add_handler(CommandHandler("start", self.start_command))
        application.add_handler(CommandHandler("help", self.help_command))
        application.add_handler(CommandHandler("memory", self.memory_command))
        application.add_handler(CommandHandler("groupmemory", self.groupmemory_command))
        application.add_handler(CommandHandler("clear", self.clear_command))
        application.add_handler(CommandHandler("report", self.report_command))
        
        # Media handlers
        application.add_handler(MessageHandler(filters.PHOTO, self.handle_photo))
        application.add_handler(MessageHandler(filters.VOICE, self.handle_voice))
        application.add_handler(MessageHandler(filters.Document.ALL, self.handle_document))
        
        # Text message handler
        application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, self.handle_message))
        
        # Error handler
        application.add_error_handler(self.error_handler)
        
        logger.info("🤖 Starting Enhanced Dark Bot...")
        application.run_polling(allowed_updates=Update.ALL_TYPES)

def run_flask():
    port = int(os.environ.get('PORT', 5000))
    logger.info(f"🌐 Starting Flask server on port {port}")
    app.run(host='0.0.0.0', port=port)

if __name__ == '__main__':
    flask_thread = threading.Thread(target=run_flask)
    flask_thread.daemon = True
    flask_thread.start()
    
    bot = DarkBot()
    bot.run()
