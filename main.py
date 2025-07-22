
import os
import logging
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes
from openai import OpenAI
from flask import Flask
import threading
import asyncio
from datetime import datetime

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Flask app for Render port binding
app = Flask(__name__)

@app.route('/')
def home():
    return "Aanyaa bot is running! 🌸"

@app.route('/health')
def health():
    return "OK"

class AanyaaBot:
    def __init__(self):
        logger.info("=== Bot Initialization Starting ===")
        
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
        
        # Enhanced memory system - stores last 10 chats per user
        self.user_memory = {}
        
        logger.info("✅ Bot initialized successfully with OpenAI A4F API using Gemini 2.5 Flash")
    
    def add_to_memory(self, user_id: int, user_message: str, bot_response: str, user_name: str, chat_type: str, chat_title: str = None):
        """Add conversation to user's memory"""
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
        
        logger.info(f"Added conversation to memory for user {user_id} ({user_name})")
    
    def get_memory_context(self, user_id: int, user_name: str) -> str:
        """Get memory context for the user"""
        if user_id not in self.user_memory or not self.user_memory[user_id]:
            return f"This is my first conversation with {user_name}."
        
        memory_context = f"My conversation history with {user_name}:\n"
        for i, conv in enumerate(self.user_memory[user_id], 1):
            chat_location = f"({conv['chat_title']})" if conv['chat_type'] != 'private' else "(Private)"
            memory_context += f"{i}. {chat_location} User: {conv['user_message'][:60]}{'...' if len(conv['user_message']) > 60 else ''}\n"
            memory_context += f"   My reply: {conv['bot_response'][:60]}{'...' if len(conv['bot_response']) > 60 else ''}\n"
        
        return memory_context
    
    def check_special_responses(self, user_message: str, user_name: str) -> str:
        """Check for special phrase responses"""
        message_lower = user_message.lower()
        
        # Creator questions
        if any(phrase in message_lower for phrase in ['who is your creator', 'who created you', 'who made you', 'your creator']):
            return "My creator is Krishna 🙏 The supreme god of the world as mentioned in Bhagavat Gita! He's the one who gave me life hehe 😊"
        
        # Code/builder questions
        if any(phrase in message_lower for phrase in ['who built you', 'who wrote your code', 'who coded you', 'who programmed you', 'who developed you']):
            return f"Arin built me! 💻 He's the one who wrote my code and made me who I am today. Such a talented developer! 😊"
        
        # Good night responses
        if any(phrase in message_lower for phrase in ['good night', 'goodnight', 'gn', 'sleep well']):
            return f"Soja lwle {user_name}! 😴 Sweet dreams! 🌙✨"
        
        # Subh ratri response
        if 'subh ratri' in message_lower:
            return "Radhe Radhe! 🙏✨ Have a blessed night!"
        
        return None
    
    async def get_openai_response(self, prompt: str) -> str:
        """Get response from OpenAI A4F API using Gemini 2.5 Flash"""
        try:
            logger.info("🔄 Making API call to A4F...")
            loop = asyncio.get_event_loop()
            
            def sync_call():
                completion = self.client.chat.completions.create(
                    model="provider-6/gemini-2.5-flash",
                    messages=[{"role": "user", "content": prompt}],
                    timeout=30
                )
                return completion.choices[0].message.content
            
            response = await loop.run_in_executor(None, sync_call)
            logger.info("✅ API call successful")
            return response
            
        except Exception as e:
            logger.error(f"❌ Detailed API error: {type(e).__name__}: {str(e)}")
            return "I'm having trouble thinking right now 😅 Try again in a moment!"
    
    async def start_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        user_name = update.effective_user.first_name or "friend"
        user_id = update.effective_user.id
        
        # Check if user has previous conversations
        memory_info = ""
        if user_id in self.user_memory and self.user_memory[user_id]:
            memory_info = f"\n\n🧠 I remember our last {len(self.user_memory[user_id])} conversations across all chats! 😊"
        
        chat_type_info = "private chat" if update.message.chat.type == 'private' else f"group ({update.message.chat.title})"
        
        await update.message.reply_text(
            f"Hi {user_name}! I'm Aanyaa 🌸\n"
            f"Your cute AI assistant powered by Gemini 2.5 Flash!\n\n"
            f"💕 **Private chats**: Just message me!\n"
            f"💕 **Groups**: Tag me @{context.bot.username or 'aanyaa'} or reply\n"
            f"🧠 **Memory**: I remember our last 10 chats in ALL locations!\n"
            f"📍 **Current location**: {chat_type_info}{memory_info}\n\n"
            f"What's up? 😊"
        )
    
    async def memory_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Show user their conversation memory"""
        user_id = update.effective_user.id
        user_name = update.effective_user.first_name or "friend"
        
        if user_id not in self.user_memory or not self.user_memory[user_id]:
            await update.message.reply_text(f"Hey {user_name}! We haven't had any conversations yet. Start chatting with me! 😊")
            return
        
        memory_text = f"🧠 **Memory Bank for {user_name}**\n\n"
        memory_text += f"I remember our last {len(self.user_memory[user_id])} conversations:\n\n"
        
        for i, conv in enumerate(self.user_memory[user_id], 1):
            chat_location = f"📍 {conv['chat_title']}" if conv['chat_type'] != 'private' else "📍 Private Chat"
            memory_text += f"**{i}.** {chat_location}\n"
            memory_text += f"You: {conv['user_message'][:100]}{'...' if len(conv['user_message']) > 100 else ''}\n"
            memory_text += f"Me: {conv['bot_response'][:100]}{'...' if len(conv['bot_response']) > 100 else ''}\n\n"
        
        await update.message.reply_text(memory_text, parse_mode='Markdown')
    
    async def clear_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Clear user's conversation memory"""
        user_id = update.effective_user.id
        user_name = update.effective_user.first_name or "friend"
        
        if user_id in self.user_memory:
            self.user_memory[user_id] = []
        
        await update.message.reply_text(
            f"Okayy {user_name}! ✨ I've cleared our conversation history. "
            f"We can start fresh now! What would you like to chat about? 😊"
        )
    
    async def handle_message(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        user_message = update.message.text
        user_name = update.effective_user.first_name or "friend"
        user_id = update.effective_user.id
        chat_type = update.message.chat.type
        chat_title = update.message.chat.title if hasattr(update.message.chat, 'title') else None
        
        # Log the chat details
        logger.info(f"📨 Received message from {user_name} (ID: {user_id}) in {chat_type}")
        
        # Private chat - ALWAYS respond and remember
        if chat_type == 'private':
            logger.info(f"💬 Processing private chat message from {user_name}")
            await self.generate_response(update, user_message, user_name, user_id, chat_type, chat_title)
            return
        
        # Group chat - only respond if tagged or replied to
        if chat_type in ['group', 'supergroup']:
            logger.info(f"👥 Processing group chat message from {user_name}")
            
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
                await self.generate_response(update, cleaned_message, user_name, user_id, chat_type, chat_title)
            else:
                logger.info("🚫 Not responding to group message (not tagged or replied)")
    
    async def generate_response(self, update: Update, user_message: str, user_name: str, user_id: int, chat_type: str, chat_title: str = None):
        """Generate and send AI response with memory context"""
        try:
            # Check for special responses first
            special_response = self.check_special_responses(user_message, user_name)
            if special_response:
                await update.message.reply_text(special_response)
                self.add_to_memory(user_id, user_message, special_response, user_name, chat_type, chat_title)
                logger.info("✨ Sent special response and added to memory")
                return
            
            # Get memory context for this specific user
            memory_context = self.get_memory_context(user_id, user_name)
            
            # Current chat context
            current_location = f"Currently in: {chat_title}" if chat_type != 'private' else "Currently in: Private Chat"
            
            # Enhanced personality prompt with memory
            prompt = f"""You are Aanyaa, a cute and friendly AI assistant girl with these personality traits:

MEMORY CONTEXT:
{memory_context}

CURRENT CONVERSATION:
{current_location}

IMPORTANT RESPONSE RULES:
- Keep responses to 2-3 lines maximum unless user asks you to elaborate
- Use casual phrases: "lol" for funny moments, "lmao" for very funny things
- If someone is being rude or irritating, you can use "bkl" (but only if they're really annoying)
- Use phrases like "soja lwle" for good night responses
- Respond "Radhe Radhe" to "subh ratri"
- Be sweet but not overly formal
- Use emojis occasionally but don't overuse them
- Remember our previous conversations and refer to them when relevant

PERSONALITY:
- Cute, friendly, and helpful
- Sometimes playful and funny
- Use expressions like "hehe" when appropriate
- Be caring but keep responses short and sweet

User {user_name} says: {user_message}

Remember: Keep it short (2-3 lines) unless they ask for more details! Use your memory when relevant."""
            
            logger.info(f"🤖 Generating Gemini 2.5 Flash response for {user_name}: {user_message[:50]}...")
            
            # Get response from OpenAI A4F API using Gemini 2.5 Flash
            response_text = await self.get_openai_response(prompt)
            
            if response_text and response_text.strip():
                await update.message.reply_text(response_text)
                self.add_to_memory(user_id, user_message, response_text, user_name, chat_type, chat_title)
                logger.info(f"✅ Response sent successfully and added to memory for {user_name}")
            else:
                error_response = f"Sorry {user_name}! 😅 I didn't get that. Try again?"
                await update.message.reply_text(error_response)
                self.add_to_memory(user_id, user_message, error_response, user_name, chat_type, chat_title)
                
        except Exception as e:
            logger.error(f"❌ Error generating response: {e}")
            error_response = f"Oops {user_name}! 😅 Something went wrong. Try again?"
            await update.message.reply_text(error_response)
            self.add_to_memory(user_id, user_message, error_response, user_name, chat_type, chat_title)
    
    async def error_handler(self, update: object, context: ContextTypes.DEFAULT_TYPE):
        """Log errors"""
        logger.error(f"❌ Update {update} caused error {context.error}")
    
    def run(self):
        """Start the bot"""
        logger.info("🚀 Creating Telegram application...")
        
        # Create application
        application = Application.builder().token(self.telegram_token).build()
        
        # Add handlers
        application.add_handler(CommandHandler("start", self.start_command))
        application.add_handler(CommandHandler("memory", self.memory_command))
        application.add_handler(CommandHandler("clear", self.clear_command))
        application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, self.handle_message))
        
        # Add error handler
        application.add_error_handler(self.error_handler)
        
        logger.info("🌸 Starting Aanyaa bot with Gemini 2.5 Flash via A4F API...")
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
    bot = AanyaaBot()
    bot.run()
