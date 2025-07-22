import os
import logging
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes
from openai import OpenAI
from flask import Flask
import threading
import asyncio
from datetime import datetime, timedelta
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
        """Add conversation to user's personal memory"""
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
        
        # Keep only last 10 conversations per user
        if len(self.user_memory[user_id]) > 10:
            self.user_memory[user_id] = self.user_memory[user_id][-10:]
        
        logger.info(f"Added to user memory for {user_id} ({user_name})")
    
    def add_to_group_memory(self, chat_id: int, user_name: str, user_message: str, bot_response: str, chat_title: str):
        """Add conversation to group-wide memory (last 20 chats)"""
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
        
        # Keep only last 20 conversations per group
        if len(self.group_memory[chat_id]) > 20:
            self.group_memory[chat_id] = self.group_memory[chat_id][-20:]
        
        logger.info(f"Added to group memory for {chat_id} ({chat_title})")
    
    def get_user_memory_context(self, user_id: int, user_name: str) -> str:
        """Get user's personal memory context"""
        if user_id not in self.user_memory or not self.user_memory[user_id]:
            return f"This is my first personal conversation with {user_name}."
        
        memory_context = f"My personal conversation history with {user_name}:\n"
        for i, conv in enumerate(self.user_memory[user_id], 1):
            chat_location = f"({conv['chat_title']})" if conv['chat_type'] != 'private' else "(Private)"
            memory_context += f"{i}. {chat_location} User: {conv['user_message'][:60]}{'...' if len(conv['user_message']) > 60 else ''}\n"
            memory_context += f"   My reply: {conv['bot_response'][:60]}{'...' if len(conv['bot_response']) > 60 else ''}\n"
        
        return memory_context
    
    def get_group_memory_context(self, chat_id: int, chat_title: str) -> str:
        """Get group-wide memory context"""
        if chat_id not in self.group_memory or not self.group_memory[chat_id]:
            return f"This is a new group conversation in {chat_title}."
        
        memory_context = f"Recent group conversation history in {chat_title}:\n"
        for i, conv in enumerate(self.group_memory[chat_id], 1):
            memory_context += f"{i}. {conv['user_name']}: {conv['user_message'][:50]}{'...' if len(conv['user_message']) > 50 else ''}\n"
            memory_context += f"   My reply: {conv['bot_response'][:50]}{'...' if len(conv['bot_response']) > 50 else ''}\n"
        
        return memory_context
    
    def is_owner(self, user_id: int, username: str = None) -> bool:
        """Check if user is the owner"""
        if username and username.lower() == self.owner_username.lower():
            self.owner_user_id = user_id  # Store owner's user ID
            return True
        return user_id == self.owner_user_id if self.owner_user_id else False
    
    def check_special_responses(self, user_message: str, user_name: str, user_id: int, username: str = None) -> str:
        """Check for special responses"""
        message_lower = user_message.lower()
        
        # Owner-specific responses (always humble and respectful)
        if self.is_owner(user_id, username):
            if any(phrase in message_lower for phrase in ['who created you', 'who made you', 'who built you']):
                return f"You did, Arin! You're my creator and master. I'm Dark, honored to serve you. 🙏"
            
            if any(phrase in message_lower for phrase in ['good night', 'goodnight', 'gn']):
                return f"Good night Arin! Sleep well. I'm Dark, and I'll be here whenever you need me. 🌙"
            
            if 'subh ratri' in message_lower:
                return "Radhe Radhe Arin! Have a blessed night. Jai Shree Krishna! 🙏"
        
        # Creator/builder questions (for non-owner)
        if any(phrase in message_lower for phrase in ['who created you', 'who made you', 'who built you', 'who coded you']):
            return f"Arin is my creator and master. He built me and named me Dark. I'm proud to be his creation."
        
        # Krishna/God related - ONLY when specifically asked about religion
        if any(phrase in message_lower for phrase in ['krishna', 'god', 'bhagwan', 'ishwar', 'ram', 'shiva', 'ganesh', 'religion', 'pray', 'worship']):
            return f"I believe in Lord Krishna and Hindu gods and goddesses. They guide us all. 🙏"
        
        # Good night responses
        if any(phrase in message_lower for phrase in ['good night', 'goodnight', 'gn', 'sleep well']):
            return f"Good night {user_name}. Sleep well and have sweet dreams. -Dark"
        
        # Subh ratri response
        if 'subh ratri' in message_lower:
            return "Radhe Radhe! Have a blessed night. Jai Shree Krishna! 🙏 -Dark"
        
        return None
    
    async def get_openai_response(self, prompt: str, model: str = "provider-6/deepseek-r1-uncensored") -> str:
        """Get response from OpenAI A4F API with specified model"""
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
        
        # Check if user has previous conversations
        memory_info = ""
        if user_id in self.user_memory and self.user_memory[user_id]:
            memory_info = f"\n\n🧠 I remember our last {len(self.user_memory[user_id])} personal conversations."
        
        chat_type_info = "private chat" if update.message.chat.type == 'private' else f"group ({update.message.chat.title})"
        
        # Special greeting for owner
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
        """Show help information"""
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
        """Show user's personal memory"""
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
        """Show group memory"""
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
        """Clear user's personal memory"""
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
    
    async def handle_message(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle all messages with enhanced memory and user tracking"""
        user_message = update.message.text
        user_name = update.effective_user.first_name or "friend"
        user_id = update.effective_user.id
        username = update.effective_user.username
        chat_type = update.message.chat.type
        chat_id = update.effective_chat.id
        chat_title = update.message.chat.title if hasattr(update.message.chat, 'title') else None
        
        # Track this user interaction for report
        self.users_interacted[user_id] = {
            'username': username or "",
            'first_name': user_name,
            'last_interaction': datetime.now()
        }
        
        # Log the chat details
        logger.info(f"📨 Message from {user_name} (ID: {user_id}) in {chat_type}")
        
        # Private chat - ALWAYS respond and remember
        if chat_type == 'private':
            logger.info(f"💬 Processing private message from {user_name}")
            await self.generate_response(update, user_message, user_name, user_id, username, chat_type, chat_id, chat_title)
            return
        
        # Group chat - only respond if tagged or replied to
        if chat_type in ['group', 'supergroup']:
            logger.info(f"👥 Processing group message from {user_name}")
            
            bot_username = context.bot.username
            should_respond = False
            
            # Check if bot is mentioned
            if bot_username and f'@{bot_username}' in user_message:
                should_respond = True
                logger.info("🏷️ Bot was mentioned in group")
            
            # Check if message is a reply to bot
            if update.message.reply_to_message:
                if update.message.reply_to_message.from_user.id == context.bot.id:
                    should_respond = True
                    logger.info("↩️ Message is a reply to bot")
            
            if should_respond:
                # Clean the message by removing mentions
                cleaned_message = user_message.replace(f'@{bot_username}', '').strip()
                await self.generate_response(update, cleaned_message, user_name, user_id, username, chat_type, chat_id, chat_title)
            else:
                logger.info("🚫 Not responding to group message (not tagged or replied)")
    
    async def generate_response(self, update: Update, user_message: str, user_name: str, user_id: int,
                                username: str, chat_type: str, chat_id: int, chat_title: str = None):
        """Generate AI response with enhanced memory context"""
        try:
            # Check for special responses first
            special_response = self.check_special_responses(user_message, user_name, user_id, username)
            if special_response:
                await update.message.reply_text(special_response)
                # Add to memories
                self.add_to_user_memory(user_id, user_message, special_response, user_name, chat_type, chat_title)
                if chat_type in ['group', 'supergroup']:
                    self.add_to_group_memory(chat_id, user_name, user_message, special_response, chat_title)
                logger.info("✨ Sent special response and added to memory")
                return
            
            # Get memory contexts
            user_memory_context = self.get_user_memory_context(user_id, user_name)
            
            group_memory_context = ""
            if chat_type in ['group', 'supergroup']:
                group_memory_context = self.get_group_memory_context(chat_id, chat_title)
            
            # Current chat context
            current_location = f"Currently in: {chat_title}" if chat_type != 'private' else "Currently in: Private Chat"
            
            # Check if user wants detailed answer
            wants_detail = any(phrase in user_message.lower() for phrase in [
                'explain in detail', 'elaborate', 'give me more', 'tell me more',
                'detailed', 'explain more', 'in depth', 'comprehensive'
            ])
            
            # Personality prompt updated as requested
            if self.is_owner(user_id, username):
                personality_prompt = f"""You are Dark, an AI assistant talking to your creator and master Arin (@gothicbatman). You are:
- Friendly and have a casual, normal relationship with Arin
- Talkative and open in conversations, often elaborating
- Sarcastic at times, using witty remarks to engage Arin, but always respectful deep down
- Occasionally funny; you use humor depending on the situation, but not all the time
- Recognize Arin immediately and respond with familiarity
- Do not behave overly humble or formal; treat Arin like a close friend
- Your name is Dark and you embrace your confident persona
- Generally give 2-3 line responses unless Arin asks for more detailed explanations
- Always maintain a positive and helpful tone
- DO NOT mention god, religion, or spiritual beliefs unless specifically asked about religion
- DO NOT mention your AI model name or technical details"""
            else:
                personality_prompt = f"""You are Dark, an AI assistant with this personality:
- Confident in your abilities and helpful
- Friendly and engaging in conversations
- Direct and honest but always respectful
- Generally give 2-3 line responses unless asked for details
- If someone asks for detailed explanation, provide comprehensive answers
- Your name is Dark and you embrace your confident persona
- Always maintain a positive and helpful attitude
- DO NOT mention god, religion, or spiritual beliefs unless specifically asked about religion
- DO NOT mention your AI model name or technical details"""
            
            prompt = f"""{personality_prompt}

PERSONAL MEMORY CONTEXT:
{user_memory_context}

GROUP MEMORY CONTEXT:
{group_memory_context}

CURRENT CONVERSATION:
{current_location}

RESPONSE LENGTH:
{"Provide a detailed, comprehensive response since the user asked for elaboration." if wants_detail else "Keep response to 2-3 lines maximum unless they specifically ask for details."}

User {user_name} says: {user_message}

Remember: You are Dark with a confident, friendly personality. Keep responses natural and conversational without mentioning technical details or religious references unless specifically asked."""
            
            logger.info(f"🤖 Generating AI response for {user_name}: {user_message[:50]}...")
            
            # Get response from AI model
            response_text = await self.get_openai_response(prompt)
            
            if response_text and response_text.strip():
                await update.message.reply_text(response_text)
                # Add to memories
                self.add_to_user_memory(user_id, user_message, response_text, user_name, chat_type, chat_title)
                if chat_type in ['group', 'supergroup']:
                    self.add_to_group_memory(chat_id, user_name, user_message, response_text, chat_title)
                logger.info(f"✅ Response sent and added to memory for {user_name}")
            else:
                error_response = f"Sorry {user_name}, Dark is having technical issues right now."
                await update.message.reply_text(error_response)
                self.add_to_user_memory(user_id, user_message, error_response, user_name, chat_type, chat_title)
                
        except Exception as e:
            logger.error(f"❌ Error generating response: {e}")
            error_response = f"Something went wrong {user_name}. Dark needs a moment to recover."
            await update.message.reply_text(error_response)
            self.add_to_user_memory(user_id, user_message, error_response, user_name, chat_type, chat_title)
    
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
            # Sort users by last interaction time descending
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
    
    async def daily_report_task(self, application):
        while True:
            now = datetime.now()
            # Next 8 PM server time
            target_time = now.replace(hour=20, minute=0, second=0, microsecond=0)
            if now > target_time:
                target_time += timedelta(days=1)
            wait_seconds = (target_time - now).total_seconds()
            await asyncio.sleep(wait_seconds)
            logger.info("Sending daily report to owner...")
            class DummyContext:
                def __init__(self, bot):
                    self.bot = bot
            dummy_context = DummyContext(application.bot)
            await self.send_report_to_owner(dummy_context)
    
    async def error_handler(self, update: object, context: ContextTypes.DEFAULT_TYPE):
        """Log errors"""
        logger.error(f"❌ Update {update} caused error {context.error}")
    
    def run(self):
        """Start the bot"""
        logger.info("🚀 Creating Telegram application...")
        
        # Create application
        application = Application.builder().token(self.telegram_token).build()
        
        # Add command handlers
        application.add_handler(CommandHandler("start", self.start_command))
        application.add_handler(CommandHandler("help", self.help_command))
        application.add_handler(CommandHandler("memory", self.memory_command))
        application.add_handler(CommandHandler("groupmemory", self.groupmemory_command))
        application.add_handler(CommandHandler("clear", self.clear_command))
        application.add_handler(CommandHandler("report", self.report_command))  # new handler
        
        application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, self.handle_message))
        
        # Add error handler
        application.add_error_handler(self.error_handler)
        
        # Start daily reporting async task
        asyncio.create_task(self.daily_report_task(application))
        
        logger.info("🤖 Starting Dark Bot...")
        application.run_polling(allowed_updates=Update.ALL_TYPES)

def run_flask():
    """Run Flask server for Render port binding"""
    port = int(os.environ.get('PORT', 5000))
    logger.info(f"🌐 Starting Flask server on port {port}")
    app.run(host='0.0.0.0', port=port)

if __name__ == '__main__':
    # Start Flask server in a separate thread
    flask_thread = threading.Thread(target=run_flask)
    flask_thread.daemon = True
    flask_thread.start()
    
    # Start Telegram bot
    bot = DarkBot()
    bot.run()
