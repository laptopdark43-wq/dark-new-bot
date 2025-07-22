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

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Flask app for Render port binding
app = Flask(__name__)

@app.route('/')
def home():
    return "Dark Bot (Conversation Only) is running! 🚀"

@app.route('/health')
def health():
    return "OK"

class DarkBot:
    def __init__(self):
        logger.info("=== Dark Bot Initialization Starting ===")
        
        # Get environment variables
        self.telegram_token = os.getenv('TELEGRAM_BOT_TOKEN')
        self.a4f_api_key = os.getenv('A4F_API_KEY')
        
        # Enhanced logging for debugging
        logger.info(f"Telegram token present: {bool(self.telegram_token)}")
        logger.info(f"A4F API key present: {bool(self.a4f_api_key)}")
        logger.info(f"A4F API key length: {len(self.a4f_api_key) if self.a4f_api_key else 0}")
        
        # Better error handling with specific messages
        if not self.telegram_token:
            logger.error("❌ TELEGRAM_BOT_TOKEN missing!")
            raise ValueError("TELEGRAM_BOT_TOKEN required")
        
        if not self.a4f_api_key:
            logger.error("❌ A4F_API_KEY missing!")
            raise ValueError("A4F_API_KEY required")
        
        logger.info("✅ All environment variables found")
        
        # Initialize OpenAI client with A4F API
        try:
            self.client = OpenAI(
                api_key=self.a4f_api_key,
                base_url="https://api.a4f.co/v1"
            )
            logger.info("✅ OpenAI client initialized successfully")
        except Exception as e:
            logger.error(f"❌ Failed to initialize OpenAI client: {e}")
            raise
        
        # Memory systems
        self.user_memory = {}  # Per-user memory (last 10 chats per user)
        self.group_memory = {}  # Group-wide memory (last 20 chats per group)

        # Track all users who interacted with the bot
        self.users_interacted = {}  # user_id -> {'username': str, 'first_name': str, 'last_interaction': datetime}
        
        # Owner information
        self.owner_username = "gothicbatman"
        self.owner_user_id = None  # Will be set when owner interacts
        
        logger.info("✅ Dark Bot initialized successfully")
    
    def add_to_user_memory(self, user_id: int, user_message: str, bot_response: str, user_name: str, chat_type: str, chat_title: str = None):
        if user_id not in self.user_memory:
            self.user_memory[user_id] = []
        
        conversation = {
            'timestamp': datetime.now().isoformat(),
            'user_name': user_name,
            'user_message': user_message,
            'bot_response': bot_response,
            'chat_type': chat_type,
            'chat_title': chat_title if chat_title else 'Private Chat'
        }
        
        self.user_memory[user_id].append(conversation)
        
        if len(self.user_memory[user_id]) > 10:
            self.user_memory[user_id] = self.user_memory[user_id][-10:]
        
        logger.info(f"Added to user memory for {user_id} ({user_name})")
    
    def add_to_group_memory(self, chat_id: int, user_name: str, user_message: str, bot_response: str, chat_title: str):
        if chat_id not in self.group_memory:
            self.group_memory[chat_id] = []
        
        conversation = {
            'timestamp': datetime.now().isoformat(),
            'user_name': user_name,
            'user_message': user_message,
            'bot_response': bot_response,
            'chat_title': chat_title
        }
        
        self.group_memory[chat_id].append(conversation)
        
        if len(self.group_memory[chat_id]) > 20:
            self.group_memory[chat_id] = self.group_memory[chat_id][-20:]
        
        logger.info(f"Added to group memory for {chat_id} ({chat_title})")
    
    def get_user_memory_context(self, user_id: int, user_name: str) -> str:
        if user_id not in self.user_memory or not self.user_memory[user_id]:
            return f"This is my first personal conversation with {user_name}."
        
        memory_context = f"My personal conversation history with {user_name}:\n"
        for i, conv in enumerate(self.user_memory[user_id], 1):
            chat_location = f"({conv['chat_title']})" if conv['chat_type'] != 'private' else "(Private)"
            memory_context += f"{i}. {chat_location} User: {conv['user_message'][:60]}{'...' if len(conv['user_message']) > 60 else ''}\n"
            memory_context += f"   My reply: {conv['bot_response'][:60]}{'...' if len(conv['bot_response']) > 60 else ''}\n"
        
        return memory_context
    
    def get_group_memory_context(self, chat_id: int, chat_title: str) -> str:
        if chat_id not in self.group_memory or not self.group_memory[chat_id]:
            return f"This is a new group conversation in {chat_title}."
        
        memory_context = f"Recent group conversation history in {chat_title}:\n"
        for i, conv in enumerate(self.group_memory[chat_id], 1):
            memory_context += f"{i}. {conv['user_name']}: {conv['user_message'][:50]}{'...' if len(conv['user_message']) > 50 else ''}\n"
            memory_context += f"   My reply: {conv['bot_response'][:50]}{'...' if len(conv['bot_response']) > 50 else ''}\n"
        
        return memory_context
    
    def is_owner(self, user_id: int, username: str = None) -> bool:
        if username and username.lower() == self.owner_username.lower():
            self.owner_user_id = user_id
            return True
        return user_id == self.owner_user_id if self.owner_user_id else False
    
    def check_special_responses(self, user_message: str, user_name: str, user_id: int, username: str = None) -> str:
        message_lower = user_message.lower()
        
        if self.is_owner(user_id, username):
            if any(phrase in message_lower for phrase in ['who created you', 'who made you', 'who built you']):
                return f"You did, Arin! You're my creator and master. I'm Dark, honored to serve you. 🙏"
            if any(phrase in message_lower for phrase in ['good night', 'goodnight', 'gn']):
                return f"Good night Arin! Sleep well. I'm Dark, and I'll be here whenever you need me. 🌙"
            if 'subh ratri' in message_lower:
                return "Radhe Radhe Arin! Have a blessed night. Jai Shree Krishna! 🙏"
        
        if any(phrase in message_lower for phrase in ['who created you', 'who made you', 'who built you', 'who coded you']):
            return f"Arin is my creator and master. He built me and named me Dark. I'm proud to be his creation."
        if any(phrase in message_lower for phrase in ['krishna', 'god', 'bhagwan', 'ishwar', 'ram', 'shiva', 'ganesh', 'religion', 'pray', 'worship']):
            return f"I believe in Lord Krishna and Hindu gods and goddesses. They guide us all. 🙏"
        if any(phrase in message_lower for phrase in ['good night', 'goodnight', 'gn', 'sleep well']):
            return f"Good night {user_name}. Sleep well and have sweet dreams. -Dark"
        if 'subh ratri' in message_lower:
            return "Radhe Radhe! Have a blessed night. Jai Shree Krishna! 🙏 -Dark"
        
        return None
    
    async def get_openai_response(self, prompt: str, model: str = "provider-6/deepseek-r1-uncensored") -> str:
        try:
            logger.info(f"🔄 Making API call to {model}...")
            loop = asyncio.get_event_loop()
            
            def sync_call():
                completion = self.client.chat.completions.create(
                    model=model,
                    messages=[{"role": "user", "content": prompt}],
                    timeout=30
                )
                return completion.choices[0].message.content
            
            response = await loop.run_in_executor(None, sync_call)
            logger.info("✅ API call successful")
            return response
            
        except Exception as e:
            logger.error(f"❌ Detailed API error: {type(e).__name__}: {str(e)}")
            return "I'm having technical difficulties right now. Give me a moment."
    
    async def start_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        user_name = update.effective_user.first_name or "friend"
        user_id = update.effective_user.id
        username = update.effective_user.username
        
        memory_info = ""
        if user_id in self.user_memory and self.user_memory[user_id]:
            memory_info = f"\n\n🧠 I remember our last {len(self.user_memory[user_id])} personal conversations."
        
        chat_type_info = "private chat" if update.message.chat.type == 'private' else f"group ({update.message.chat.title})"
        
        if self.is_owner(user_id, username):
            await update.message.reply_text(
                f"Hey Arin! 🙏 Your humble servant Dark is ready to assist you.\n\n"
                f"I'm your creation, powered by advanced AI for natural conversations.\n\n"
                f"**My Features:**\n"
                f"🧠 **Personal Memory**: I remember our last 10 personal conversations\n"
                f"👥 **Group Memory**: I remember last 20 group conversations\n"
                f"💪 **Personality**: Friendly, talkative, sometimes sarcastic and funny\n\n"
                f"**Commands:**\n"
                f"🧠 `/memory` - View personal chat history\n"
                f"👥 `/groupmemory` - View group chat history (groups only)\n"
                f"🧹 `/clear` - Clear personal memory\n"
                f"📝 `/report` - Receive recent chat user report\n"
                f"❓ `/help` - Get help\n\n"
                f"📍 **Current location**: {chat_type_info}{memory_info}\n\n"
                f"How may Dark serve you today?"
            )
        else:
            await update.message.reply_text(
                f"Hey {user_name}. I'm Dark, an AI assistant with personality.\n\n"
                f"**About me:**\n"
                f"🧠 **Smart Memory**: I remember conversations (personal & group)\n"
                f"💪 **Confident**: I'm helpful and direct in my responses\n"
                f"⚡ **Friendly**: I keep conversations engaging and real\n\n"
                f"**Commands:**\n"
                f"🧠 `/memory` - View your chat history\n"
                f"👥 `/groupmemory` - View group history\n"
                f"❓ `/help` - Get help\n\n"
                f"📍 **Current location**: {chat_type_info}{memory_info}\n\n"
                f"What do you need from Dark?"
            )
    
    async def help_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        user_name = update.effective_user.first_name or "friend"
        user_id = update.effective_user.id
        username = update.effective_user.username
        
        if self.is_owner(user_id, username):
            help_text = f"Here's what Dark can do for you, Arin:\n\n"
            help_text += f"**Chat Features:**\n"
            help_text += f"🗣️ **Natural conversation** - Dark responds naturally to everything you say\n"
            help_text += f"🧠 **Personal memory** - Dark remembers our last 10 personal conversations\n"
            help_text += f"👥 **Group memory** - Dark remembers last 20 group conversations\n\n"
            help_text += f"**Group Behavior:**\n"
            help_text += f"🎯 **Smart responses** - Dark only responds when tagged or replied to in groups\n"
            help_text += f"📝 **Detailed answers** - Ask Dark to elaborate and I'll give full explanations\n\n"
            help_text += f"**Available Commands:**\n"
            help_text += f"🧠 `/memory` - View our personal chat history\n"
            help_text += f"👥 `/groupmemory` - View group conversation history\n"
            help_text += f"🧹 `/clear` - Clear our personal memory\n"
            help_text += f"📝 `/report` - Receive recent chat user report\n"
            help_text += f"❓ `/help` - Show this help menu\n\n"
            help_text += f"Dark is always at your service! 🙏"
        else:
            help_text = f"Here's what Dark can do, {user_name}:\n\n"
            help_text += f"**Chat Features:**\n"
            help_text += f"🗣️ **Intelligent conversation** - Dark is powered by advanced AI\n"
            help_text += f"🧠 **Memory** - Dark remembers our personal conversations\n"
            help_text += f"👥 **Group awareness** - Dark remembers group context\n\n"
            help_text += f"**Dark's Personality:**\n"
            help_text += f"💪 **Confident** - Dark knows his worth and is helpful\n"
            help_text += f"⚡ **Direct** - Dark speaks his mind and keeps it real\n"
            help_text += f"🤝 **Friendly** - Dark enjoys good conversations\n\n"
            help_text += f"**Available Commands:**\n"
            help_text += f"🧠 `/memory` - View your chat history\n"
            help_text += f"👥 `/groupmemory` - View group history\n"
            help_text += f"❓ `/help` - Show this help\n\n"
            help_text += f"Looking forward to our conversations!"
        
        await update.message.reply_text(help_text, parse_mode='Markdown')
    
    async def memory_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        user_id = update.effective_user.id
        user_name = update.effective_user.first_name or "friend"
        
        if user_id not in self.user_memory or not self.user_memory[user_id]:
            await update.message.reply_text(f"Dark hasn't had any personal conversations with you yet, {user_name}.")
            return
        
        memory_text = f"🧠 **Dark's Personal Memory for {user_name}**\n\n"
        memory_text += f"Dark remembers our last {len(self.user_memory[user_id])} personal conversations:\n\n"
        
        for i, conv in enumerate(self.user_memory[user_id], 1):
            chat_location = f"📍 {conv['chat_title']}" if conv['chat_type'] != 'private' else "📍 Private Chat"
            memory_text += f"**{i}.** {chat_location}\n"
            memory_text += f"You: {conv['user_message'][:100]}{'...' if len(conv['user_message']) > 100 else ''}\n"
            memory_text += f"Dark: {conv['bot_response'][:100]}{'...' if len(conv['bot_response']) > 100 else ''}\n\n"
        
        await update.message.reply_text(memory_text, parse_mode='Markdown')
    
    async def groupmemory_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        chat_id = update.effective_chat.id
        user_name = update.effective_user.first_name or "friend"
        chat_title = update.message.chat.title or "this group"
        
        if update.message.chat.type == 'private':
            await update.message.reply_text(f"This command only works in groups, {user_name}.")
            return
        
        if chat_id not in self.group_memory or not self.group_memory[chat_id]:
            await update.message.reply_text(f"Dark is new to this group conversation in {chat_title}.")
            return
        
        memory_text = f"👥 **Dark's Group Memory for {chat_title}**\n\n"
        memory_text += f"Dark remembers the last {len(self.group_memory[chat_id])} group conversations:\n\n"
        
        for i, conv in enumerate(self.group_memory[chat_id], 1):
            memory_text += f"**{i}.** {conv['user_name']}: {conv['user_message'][:80]}{'...' if len(conv['user_message']) > 80 else ''}\n"
            memory_text += f"Dark: {conv['bot_response'][:80]}{'...' if len(conv['bot_response']) > 80 else ''}\n\n"
        
        await update.message.reply_text(memory_text, parse_mode='Markdown')
    
    async def clear_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        user_id = update.effective_user.id
        user_name = update.effective_user.first_name or "friend"
        username = update.effective_user.username
        
        if user_id in self.user_memory:
            self.user_memory[user_id] = []
        
        if self.is_owner(user_id, username):
            await update.message.reply_text(
                f"Done, Arin! Dark has cleared our personal conversation history. "
                f"We can start fresh. How may Dark serve you?"
            )
        else:
            await update.message.reply_text(
                f"Alright {user_name}, Dark has cleared our personal conversation history. "
                f"Fresh start it is."
            )
    
    async def report_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        user_id = update.effective_user.id
        username = update.effective_user.username
        
        if not self.is_owner(user_id, username):
            await update.message.reply_text("Sorry, only my creator can request this report.")
            return
        
        await update.message.reply_text("Generating chat activity report...")
        await self.send_report_to_owner(context)
    
    async def send_report_to_owner(self, context: ContextTypes.DEFAULT_TYPE):
        if not self.owner_user_id:
            logger.info("Owner user ID not yet set; cannot send report.")
            return
        
        report_lines = []
        report_lines.append(f"📝 *Dark Bot Chat Activity Report* (generated at {datetime.now().strftime('%Y-%m-%d %H:%M:%S')})\n")
        
        if not self.users_interacted:
            report_lines.append("No user interactions recorded so far.")
        else:
            users_sorted = sorted(self.users_interacted.items(), key=lambda x: x[1]['last_interaction'], reverse=True)
            
            for idx, (user_id, info) in enumerate(users_sorted, 1):
                conv_count = len(self.user_memory.get(user_id, []))
                last_seen = info['last_interaction'].strftime('%Y-%m-%d %H:%M:%S')
                user_display = info['first_name'] or "Unknown"
                username_display = f"@{info['username']}" if info['username'] else "NoUsername"
                report_lines.append(f"{idx}. {user_display} ({username_display}, ID:{user_id}) — {conv_count} conv(s), Last: {last_seen}")
        
        report_text = "\n".join(report_lines)
        
        try:
            await context.bot.send_message(chat_id=self.owner_user_id, text=report_text, parse_mode='Markdown')
            logger.info("Report sent to owner successfully.")
        except Exception as e:
            logger.error(f"Failed to send report to owner: {e}")
    
    async def error_handler(self, update: object, context: ContextTypes.DEFAULT_TYPE):
        logger.error(f"❌ Update {update} caused error {context.error}")
    
    def run(self):
        logger.info("🚀 Creating Telegram application...")
        
        application = Application.builder().token(self.telegram_token).build()
        
        # Add command handlers
        application.add_handler(CommandHandler("start", self.start_command))
        application.add_handler(CommandHandler("help", self.help_command))
        application.add_handler(CommandHandler("memory", self.memory_command))
        application.add_handler(CommandHandler("groupmemory", self.groupmemory_command))
        application.add_handler(CommandHandler("clear", self.clear_command))
        application.add_handler(CommandHandler("report", self.report_command))
        
        # If you want to handle free text messages, you must implement handle_message, otherwise comment out this line:
        # application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, self.handle_message))
        
        application.add_error_handler(self.error_handler)
        
        logger.info("🤖 Starting Dark Bot...")
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
