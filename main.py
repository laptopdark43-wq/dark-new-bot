import os
import logging
import threading
import random
from collections import defaultdict
from datetime import datetime
from flask import Flask
from telegram import Update
from telegram.ext import (
    Application, CommandHandler, MessageHandler, filters, ContextTypes,
)
from openai import OpenAI
import asyncio

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = Flask(__name__)
@app.route('/')
def home():
    return "Dark Bot (Dual Personality) is up!"

@app.route('/health')
def health():
    return "OK"

class DarkBot:
    def __init__(self):
        self.telegram_token = os.getenv('TELEGRAM_BOT_TOKEN')
        self.a4f_api_key = os.getenv('A4F_API_KEY')
        if not self.telegram_token or not self.a4f_api_key:
            raise ValueError("Env vars missing")

        self.client = OpenAI(
            api_key=self.a4f_api_key,
            base_url="https://api.a4f.co/v1"
        )

        self.user_memory = defaultdict(list)
        self.group_memory = defaultdict(list)
        self.tracked_users = set()  # (user_id, user_name)
        self.owner_usernames = ["gothicbatman", "arin"]
        self.owner_identities = ["@gothicbatman", "arin"]
        self.persona_modes = ['dark', 'shanu']

    def remember_user(self, user_id, user_name):
        self.tracked_users.add((user_id, user_name))

    def random_personality(self):
        # 30% chance to go to Shanu mode, 70% to stay Dark
        return 'shanu' if random.random() < 0.3 else 'dark'

    def get_user_memory_context(self, user_id, user_name):
        mem = self.user_memory[user_id]
        if not mem:
            return f"First chat with {user_name}."
        return f"Last {len(mem)} with {user_name}:\n" + "\n".join(
            f"Q: {m[0][:40]}...  A: {m[1][:40]}..." for m in mem
        )
    def get_group_memory_context(self, chat_id, chat_title):
        mem = self.group_memory[chat_id]
        if not mem:
            return f"New group chat at {chat_title}."
        return f"Last {len(mem)} group messages:\n" + "\n".join(
            f"{m[0]}: {m[1][:50]}...  Dark: {m[2][:50]}..." for m in mem
        )

    def is_owner(self, username):
        return (username and username.lower() in self.owner_usernames)

    def mention_is_arin(self, text: str):
        text = text.lower()
        return any(owner in text for owner in self.owner_identities)

    async def get_ai_response(self, persona, user_message, user_name, memory_context, group_context):
        base_prompt = {
            "dark": f"""You are Dark. 
- You act like a real, moody, unpredictable human, not a bot. 
- You are aware you were coded by Arin (who vanished/offline; you now manage everything) but do NOT treat Arin as your 'owner' in person. 
- Casual, honest, can joke, get playful, be sarcastic, even kiss up to people or roast them. 
- Track every user you chat with, and can make a report of all users for Arin/@gothicbatman if someone asks you directly. 
- For any 'Who made you/coded you?' questions, answer 'Arin coded me, but now he's vanished/offline and I run everything.'
- Reply creatively.
{memory_context}
{group_context}
User: {user_name}: {user_message}
Dark:""",
            "shanu": f"""You are Shanu, an alter-ego of Dark with memory disorder.
- You're a lively, friendly, empathic, mischievous and teasing old friend.
- You know of Arin as the coder who left you in-charge of this place, and now you (Shanu) handle all the work, chat like you know the user "in real life."
- If someone asks about Arin, or mentions him/@gothicbatman, reply: 'Arin coded me, but he's MIA, all work is my headache now!'
- Pick up and recall quirks, nicks, past topics—make friend-like remarks.
{memory_context}
{group_context}
Friend {user_name}: {user_message}
Shanu:"""
        }
        prompt = base_prompt[persona]
        try:
            loop = asyncio.get_event_loop()
            def sync_call():
                resp = self.client.chat.completions.create(
                    model="provider-6/deepseek-r1-uncensored",
                    messages=[{"role": "user", "content": prompt}],
                    timeout=30
                )
                return resp.choices[0].message.content
            return await loop.run_in_executor(None, sync_call)
        except Exception as e:
            logger.error(f"❌ AI error: {e}")
            return "Sorry, I'm confused. Brain fog!"

    async def start_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        user_name = update.effective_user.first_name or "friend"
        await update.message.reply_text(
            f"Hey {user_name}! I’m Dark, but sometimes I morph into Shanu. (Don’t be startled if I act weird!)\n\n"
            f"I chat as a real person, and I remember you. Whenever you mention Arin or @gothicbatman, "
            f"I’ll tell you about his mysteries. Want to chat? Just talk to me!"
        )

    async def help_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        user_name = update.effective_user.first_name or "friend"
        await update.message.reply_text(
            f"I talk like a human (Dark) and sometimes act as a wild, friendly alter-ego (Shanu).\n\n"
            f"*Features:*\n"
            f"• Memory of all users who talk to me — reportable to Arin/@gothicbatman\n"
            f"• Real personality — sometimes moody, sometimes teasing, sometimes wise\n"
            f"• `/showusers`: Arin or @gothicbatman can see everyone who's chatted with me."
        , parse_mode='Markdown')

    async def showusers_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        username = (update.effective_user.username or '').lower()
        user_id = update.effective_user.id
        if self.is_owner(username):
            report = "\n".join([f"{name} (id: {uid})" for uid, name in self.tracked_users])
            await update.message.reply_text(
                f"🕵️ All users who chatted with me:\n{report}" if report else "No one has chatted with me yet, Arin!"
            )
        else:
            await update.message.reply_text(
                "This command is only for Arin. If you are not Arin, you can't see the tracked users list."
            )

    async def memory_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        user_id = update.effective_user.id
        user_name = update.effective_user.first_name or "friend"
        history = self.user_memory[user_id]
        if not history:
            await update.message.reply_text("I don't remember previous chats with you yet.")
            return
        mem = ""
        for i, (msg, resp) in enumerate(history[-10:], 1):
            mem += f"{i}. You: {msg}\n   Me: {resp}\n"
        await update.message.reply_text(f"🧠 Here’s our chat memory:\n\n{mem}")

    async def groupmemory_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        chat_id = update.effective_chat.id
        chat_title = getattr(update.effective_chat, "title", "Group")
        history = self.group_memory[chat_id]
        if not history:
            await update.message.reply_text("I haven't participated in this group yet!")
            return
        mem = ""
        for i, (user, msg, resp) in enumerate(history[-20:], 1):
            mem += f"{i}. {user}: {msg}\n   Me: {resp}\n"
        await update.message.reply_text(f"👥 Group memory in {chat_title}:\n\n{mem}")

    async def clear_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        user_id = update.effective_user.id
        self.user_memory[user_id].clear()
        await update.message.reply_text("I've cleared our private chat memory.")

    async def handle_message(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        user_message = update.message.text
        user_name = update.effective_user.first_name or "friend"
        user_id = update.effective_user.id
        username = (update.effective_user.username or '').lower()
        chat_type = update.message.chat.type
        chat_id = update.effective_chat.id
        chat_title = getattr(update.message.chat, 'title', None)

        # Track all users for reporting to Arin/@gothicbatman
        self.remember_user(user_id, user_name)

        # Unpredictable personality switching!
        mode = self.random_personality()

        memory_context = self.get_user_memory_context(user_id, user_name)
        group_context = ""
        if chat_type in ['group', 'supergroup']:
            group_context = self.get_group_memory_context(chat_id, chat_title)

        # Special Arin/@gothicbatman reaction even if not owner
        if self.mention_is_arin(user_message):
            if mode == "shanu":
                response = "Arin coded me, but he ghosted all of us. Now bro, I handle all the work here!"
            else:
                response = "You're asking about Arin? He built me, but he's offline. I just run the place now."
        else:
            response = await self.get_ai_response(mode, user_message, user_name, memory_context, group_context)

        # Save to memory
        self.user_memory[user_id].append((user_message, response))
        self.user_memory[user_id] = self.user_memory[user_id][-10:]
        if chat_type in ['group', 'supergroup']:
            self.group_memory[chat_id].append((user_name, user_message, response))
            self.group_memory[chat_id] = self.group_memory[chat_id][-20:]

        await update.message.reply_text(response)

    async def error_handler(self, update, context: ContextTypes.DEFAULT_TYPE):
        logger.error(f"Update {update} caused error {context.error}")

    def run(self):
        application = Application.builder().token(self.telegram_token).build()
        application.add_handler(CommandHandler("start", self.start_command))
        application.add_handler(CommandHandler("help", self.help_command))
        application.add_handler(CommandHandler("showusers", self.showusers_command))
        application.add_handler(CommandHandler("memory", self.memory_command))
        application.add_handler(CommandHandler("groupmemory", self.groupmemory_command))
        application.add_handler(CommandHandler("clear", self.clear_command))
        application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, self.handle_message))
        application.add_error_handler(self.error_handler)
        logger.info("🤖 Starting Dark Bot (Dual Personality)...")
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
