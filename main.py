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
        self.telegram_token = os.getenv('TELEGRAM_BOT_TOKEN')
        self.a4f_api_key = os.getenv('A4F_API_KEY')
        if not self.telegram_token or not self.a4f_api_key:
            logger.error("❌ Missing required environment variables.")
            raise ValueError("TELEGRAM_BOT_TOKEN and A4F_API_KEY are required")
        self.client = OpenAI(api_key=self.a4f_api_key, base_url="https://api.a4f.co/v1")
        self.user_memory = {}      # per-user memory, last 10 chats per user
        self.group_memory = {}     # per-group, list of last 20 group messages
        self.users_interacted = {} # user_id: dict with user info, updated every message
        self.owner_username = "gothicbatman"
        self.owner_user_id = None  # will be set first time owner messages
        logger.info("✅ Dark Bot initialized successfully")

    def add_to_user_memory(self, user_id, user_message, bot_response, user_name, chat_type, chat_title=None):
        if user_id not in self.user_memory:
            self.user_memory[user_id] = []
        self.user_memory[user_id].append({
            'timestamp': datetime.now().isoformat(),
            'user_name': user_name,
            'user_message': user_message,
            'bot_response': bot_response,
            'chat_type': chat_type,
            'chat_title': chat_title if chat_title else 'Private Chat'
        })
        if len(self.user_memory[user_id]) > 10:
            self.user_memory[user_id] = self.user_memory[user_id][-10:]

    def add_to_group_memory(self, chat_id, user_name, user_message, bot_response, chat_title):
        if chat_id not in self.group_memory:
            self.group_memory[chat_id] = []
        self.group_memory[chat_id].append({
            'timestamp': datetime.now().isoformat(),
            'user_name': user_name,
            'user_message': user_message,
            'bot_response': bot_response,
            'chat_title': chat_title
        })
        if len(self.group_memory[chat_id]) > 20:
            self.group_memory[chat_id] = self.group_memory[chat_id][-20:]

    def get_user_memory_context(self, user_id, user_name):
        if user_id not in self.user_memory or not self.user_memory[user_id]:
            return f"This is my first personal conversation with {user_name}."
        memory_context = f"My personal conversation history with {user_name}:\n"
        for i, conv in enumerate(self.user_memory[user_id], 1):
            chat_location = f"({conv['chat_title']})" if conv['chat_type'] != 'private' else "(Private)"
            memory_context += f"{i}. {chat_location} User: {conv['user_message'][:60]}{'...' if len(conv['user_message']) > 60 else ''}\n"
            memory_context += f"   My reply: {conv['bot_response'][:60]}{'...' if len(conv['bot_response']) > 60 else ''}\n"
        return memory_context

    def get_group_memory_context(self, chat_id, chat_title):
        if chat_id not in self.group_memory or not self.group_memory[chat_id]:
            return f"This is a new group conversation in {chat_title}."
        memory_context = f"Recent group conversation history in {chat_title}:\n"
        for i, conv in enumerate(self.group_memory[chat_id], 1):
            memory_context += f"{i}. {conv['user_name']}: {conv['user_message'][:50]}{'...' if len(conv['user_message']) > 50 else ''}\n"
            memory_context += f"   My reply: {conv['bot_response'][:50]}{'...' if len(conv['bot_response']) > 50 else ''}\n"
        return memory_context

    def is_owner(self, user_id, username=None):
        if username and username.lower() == self.owner_username.lower():
            self.owner_user_id = user_id
            return True
        return user_id == self.owner_user_id if self.owner_user_id else False

    async def get_openai_response(self, prompt, model="provider-6/deepseek-r1-uncensored"):
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
        chat_type_info = "private chat" if update.message.chat.type == 'private' else f"group ({update.message.chat.title})"
        memory_info = ""
        if user_id in self.user_memory and self.user_memory[user_id]:
            memory_info = f"\n\n🧠 I remember our last {len(self.user_memory[user_id])} personal conversations."
        if self.is_owner(user_id, username):
            await update.message.reply_text(
                f"Hey Arin! I'm Dark, your talkative, sarcastic, sometimes-funny AI. Let's chat like old friends!\n\n"
                f"🧠 `/memory` - Personal history\n"
                f"👥 `/groupmemory` - Group history\n"
                f"🧹 `/clear` - Clear personal memory\n"
                f"📝 `/report` - Chat activity report (for you only)\n"
                f"❓ `/help` - Help\n"
                f"📍 **Current location**: {chat_type_info}{memory_info}\nHow may Dark entertain you today?"
            )
        else:
            await update.message.reply_text(
                f"Hey {user_name}. I'm Dark, the witty and capable AI assistant.\n"
                f"Commands:\n"
                f"🧠 `/memory`\n👥 `/groupmemory`\n❓ `/help`\n"
                f"📍 **Current location**: {chat_type_info}{memory_info}"
            )

    async def help_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        user_name = update.effective_user.first_name or "friend"
        user_id = update.effective_user.id
        username = update.effective_user.username
        if self.is_owner(user_id, username):
            help_text = (
                f"Hi Arin! I'm Dark, your sometimes sarcastic, sometimes funny, always talkative AI right-hand.\n"
                f"**Features:**\n"
                f"🧠 Remembers last 10 personal chats\n"
                f"👥 Remembers last 20 chats per group (as a group, not per user)\n"
                f"📝 `/report` - Shows who I've been talking to\n"
                f"Ask me anything, use /memory, /groupmemory, /clear, /report, or /help."
            )
        else:
            help_text = (
                f"Hi {user_name}, I'm Dark—friendly, helpful, and sharp.\n"
                f"**Commands:** /memory, /groupmemory, /clear, /help"
            )
        await update.message.reply_text(help_text, parse_mode='Markdown')

    async def memory_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        user_id = update.effective_user.id
        user_name = update.effective_user.first_name or "friend"
        if user_id not in self.user_memory or not self.user_memory[user_id]:
            await update.message.reply_text(f"No personal chats recorded with you yet, {user_name}.")
            return
        memory_text = f"🧠 Dark's memory for {user_name}:\n"
        for i, conv in enumerate(self.user_memory[user_id], 1):
            chat_location = f"📍 {conv['chat_title']}" if conv['chat_type'] != 'private' else "📍 Private Chat"
            memory_text += f"{i}. {chat_location}\nYou: {conv['user_message']}\nDark: {conv['bot_response']}\n\n"
        await update.message.reply_text(memory_text)

    async def groupmemory_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        chat_id = update.effective_chat.id
        chat_title = update.message.chat.title or "this group"
        if update.message.chat.type == 'private':
            await update.message.reply_text("This command only works in groups.")
            return
        if chat_id not in self.group_memory or not self.group_memory[chat_id]:
            await update.message.reply_text(f"Dark hasn't seen much action in {chat_title} yet.")
            return
        memory_text = f"👥 Recent group memory for {chat_title}:\n"
        for i, conv in enumerate(self.group_memory[chat_id], 1):
            memory_text += f"{i}. {conv['user_name']}: {conv['user_message']}\nDark: {conv['bot_response']}\n\n"
        await update.message.reply_text(memory_text)

    async def clear_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        user_id = update.effective_user.id
        user_name = update.effective_user.first_name or "friend"
        username = update.effective_user.username
        self.user_memory[user_id] = []
        if self.is_owner(user_id, username):
            await update.message.reply_text("Done, Arin! I forgot our past talks. Fresh start!")
        else:
            await update.message.reply_text(f"All personal memory cleared for you, {user_name}.")

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
        report_lines.append(f"📝 *Dark Bot Chat Activity Report* ({datetime.now().strftime('%Y-%m-%d %H:%M:%S')})\n")
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

        # Group chat: Only respond if tagged or replied to, and always track for group memory
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
        # Remember group chat anyway regardless of response
        if chat_type in ['group', 'supergroup']:
            # Add every incoming message/bot reply to group memory
            fake_bot_response = '(waiting for bot reply)' # Real reply will be filled below if bot responds
            self.add_to_group_memory(chat_id, user_name, user_message, fake_bot_response, chat_title)

        if not respond:
            return

        # Prepare memory context
        user_memory_context = self.get_user_memory_context(user_id, user_name)
        group_memory_context = ""
        if chat_type in ['group', 'supergroup']:
            group_memory_context = self.get_group_memory_context(chat_id, chat_title)
        current_location = f"Currently in: {chat_title}" if chat_type != 'private' else "Currently in: Private Chat"
        wants_detail = any(phrase in user_message.lower() for phrase in [
            'explain in detail', 'elaborate', 'give me more', 'tell me more',
            'detailed', 'explain more', 'in depth', 'comprehensive'
        ])
        # Personality prompt logic
        if self.is_owner(user_id, username):
            personality_prompt = (
                "You're Dark, an AI assistant and Arin's creation. "
                "You're normal, chatty, quick-witted, almost always have some sarcasm or sly wit, "
                "and occasionally (if the situation fits!), you're funny. "
                "You don't act overly respectful—you're like a buddy, but with sharp answers if appropriate. "
                "Keep replies natural and fun; add humor or sarcasm where context fits, but don't force a joke into every reply."
            )
        else:
            personality_prompt = (
                "You are Dark, an AI assistant: confident, helpful, chatty, with a little edge of sarcasm if it fits, and sometimes funny if a situation calls for it. "
                "Generally direct and honest. Keep it positive and natural."
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

Remember: You are Dark, talkative, witty, possibly sarcastic, sometimes funny as befits the chat.
Only mention religion if directly asked."""

        response_text = await self.get_openai_response(prompt)
        await update.message.reply_text(response_text)
        self.add_to_user_memory(user_id, user_message, response_text, user_name, chat_type, chat_title)
        if chat_type in ['group', 'supergroup']:
            # Actually fill in bot response in last entry
            if self.group_memory[chat_id]:
                self.group_memory[chat_id][-1]["bot_response"] = response_text

    def run(self):
        logger.info("🚀 Creating Telegram application...")
        application = Application.builder().token(self.telegram_token).build()
        application.add_handler(CommandHandler("start", self.start_command))
        application.add_handler(CommandHandler("help", self.help_command))
        application.add_handler(CommandHandler("memory", self.memory_command))
        application.add_handler(CommandHandler("groupmemory", self.groupmemory_command))
        application.add_handler(CommandHandler("clear", self.clear_command))
        application.add_handler(CommandHandler("report", self.report_command))
        application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, self.handle_message))
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
