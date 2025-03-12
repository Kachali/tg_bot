import pandas as pd
import os
import re
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    filters,
    ContextTypes,
    CallbackQueryHandler,
    ConversationHandler
)
from pymorphy2 import MorphAnalyzer
from dotenv import load_dotenv

# Загрузка переменных окружения
load_dotenv()

# Конфигурационные константы
TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
EXCEL_FILE = "SALES_Stock_report.xlsx"

# Состояния диалога
CHOOSE_MODE, INPUT_ARTICLE, INPUT_NAME = range(3)

morph = MorphAnalyzer()
df = pd.DataFrame()


def normalize_text(text: str) -> str:
    """Нормализует текст для поиска"""
    text = re.sub(r'[^\w\s]', '', str(text))
    words = text.lower().split()
    normalized_words = [
        morph.parse(word)[0].normal_form
        for word in words
        if len(word) > 1
    ]
    return ' '.join(normalized_words)


def load_data():
    """Загружает и подготавливает данные из Excel файла"""
    global df
    try:
        df = pd.read_excel(EXCEL_FILE)
        df.columns = df.columns.str.strip().str.lower()
        df['норм_название'] = df['наименование'].apply(normalize_text)
        print("Данные успешно загружены")
    except Exception as e:
        print(f"Ошибка загрузки данных: {e}")


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик команды /start, показывает меню выбора типа поиска"""
    print("[DEBUG] Команда /start вызвана")

    keyboard = [
        [InlineKeyboardButton("🔢 Поиск по материалу", callback_data='article_search')],
        [InlineKeyboardButton("📖 Поиск по названию", callback_data='name_search')]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    if update.message:
        await update.message.reply_text(
            "🔍 Выберите тип поиска:",
            reply_markup=reply_markup
        )
    else:
        await update.callback_query.edit_message_text(
            "🔍 Выберите тип поиска:",
            reply_markup=reply_markup
        )

    return CHOOSE_MODE


async def choose_mode(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обрабатывает выбор типа поиска"""
    query = update.callback_query
    await query.answer()

    if query.data == 'article_search':
        await query.edit_message_text("📝 Введите материал(ы) через пробел или запятую:")
        return INPUT_ARTICLE

    elif query.data == 'name_search':
        await query.edit_message_text("📝 Введите название товара:")
        return INPUT_NAME


async def handle_article(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обрабатывает поиск по материалам"""
    user_input = update.message.text
    articles = [a.strip() for a in re.split(r'[^\d]+', user_input) if a.strip()]

    results = df[df['материал'].astype(str).isin(articles)]
    results = results[results['в наличии'] > 0]

    if results.empty:
        await update.message.reply_text("😞 Ничего не найдено.")
        return ConversationHandler.END  # Завершаем сессию, если ничего не найдено
    else:
        context.user_data['results'] = results
        context.user_data['page'] = 0  # Начинаем с первой страницы
        await show_page(update, context, page=0)
        return CHOOSE_MODE  # Оставляем сессию активной


async def handle_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обрабатывает поиск по названию"""
    try:
        user_input = update.message.text
        normalized_query = normalize_text(user_input)
        search_words = normalized_query.split()

        if not search_words:
            await update.message.reply_text("❌ Введите корректное название")
            return ConversationHandler.END

        mask = df['норм_название'].apply(
            lambda x: all(word in x for word in search_words)
        )
        results = df[mask]

        if results.empty:
            for word in search_words:
                mask = df['норм_название'].apply(lambda x: word in x)
                results = df[mask]
                if not results.empty:
                    break

        results = results[results['в наличии'] > 0]

        if results.empty:
            await update.message.reply_text("😞 Ничего не найдено.")
            return ConversationHandler.END  # Завершаем сессию, если ничего не найдено
        else:
            context.user_data['results'] = results
            context.user_data['page'] = 0  # Начинаем с первой страницы
            await show_page(update, context, page=0)
            return CHOOSE_MODE  # Оставляем сессию активной

    except Exception as e:
        print(f"[ERROR] Ошибка в handle_name: {str(e)}")
        await update.message.reply_text("⚠️ Произошла ошибка при поиске")
        return ConversationHandler.END

async def handle_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обрабатывает поиск по названию"""
    try:
        user_input = update.message.text
        normalized_query = normalize_text(user_input)
        search_words = normalized_query.split()

        if not search_words:
            await update.message.reply_text("❌ Введите корректное название")
            return ConversationHandler.END

        mask = df['норм_название'].apply(
            lambda x: all(word in x for word in search_words)
        )
        results = df[mask]

        if results.empty:
            for word in search_words:
                mask = df['норм_название'].apply(lambda x: word in x)
                results = df[mask]
                if not results.empty:
                    break

        results = results[results['в наличии'] > 0]

        if results.empty:
            await update.message.reply_text("😞 Ничего не найдено.")
        else:
            context.user_data['results'] = results
            context.user_data['page'] = 0  # Начинаем с первой страницы
            await show_page(update, context, page=0)

        # Завершаем сессию
        await update.message.reply_text("✅ Сессия завершена. Для нового поиска введите /start")
        return ConversationHandler.END

    except Exception as e:
        print(f"[ERROR] Ошибка в handle_name: {str(e)}")
        await update.message.reply_text("⚠️ Произошла ошибка при поиске")
        return ConversationHandler.END

async def show_page(update: Update, context: ContextTypes.DEFAULT_TYPE, page: int = 0):
    """Отображает страницу с результатами и кнопками управления"""
    results = context.user_data.get('results')
    if results is None or results.empty:
        await update.message.reply_text("❌ Нет данных для отображения")
        return

    items_per_page = 10
    total_pages = (len(results) + items_per_page - 1) // items_per_page

    # Получаем данные для текущей страницы
    page_data = results.iloc[page * items_per_page: (page + 1) * items_per_page]
    response = [
        f"📦 Материал: {row['материал']}\n"
        f"📌 Название: {row['наименование']}\n"
        f"🔢 В наличии: {int(round(row['в наличии']))} шт.\n"
        f"📥 В резерве: {int(round(row['в резерве']))} шт.\n"
        "—————————————"
        for _, row in page_data.iterrows()
    ]

    # Создаем клавиатуру для пагинации
    keyboard = []
    if total_pages > 1:
        pagination_buttons = []
        if page > 0:
            pagination_buttons.append(InlineKeyboardButton("⬅️", callback_data=f"prev_{page}"))
        pagination_buttons.append(InlineKeyboardButton(f"{page + 1}/{total_pages}", callback_data="curr"))
        if page < total_pages - 1:
            pagination_buttons.append(InlineKeyboardButton("➡️", callback_data=f"next_{page}"))
        keyboard.append(pagination_buttons)

    reply_markup = InlineKeyboardMarkup(keyboard)

    if update.message:
        await update.message.reply_text("\n".join(response), reply_markup=reply_markup)
    else:
        await update.callback_query.edit_message_text(
            "\n".join(response),
            reply_markup=reply_markup
        )


async def handle_pagination(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обрабатывает нажатия кнопок пагинации"""
    query = update.callback_query
    await query.answer()

    action, page = query.data.split('_') if '_' in query.data else (query.data, 0)
    new_page = int(page) - 1 if action == 'prev' else int(page) + 1

    context.user_data['page'] = new_page
    await show_page(update, context, new_page)


async def handle_menu_buttons(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обрабатывает кнопки управления после поиска"""
    query = update.callback_query
    await query.answer()

    if query.data == 'new_search':
        context.user_data.clear()
        await query.edit_message_text("🔄 Перезапуск поиска...")
        return await start(update, context)
    elif query.data == 'exit':
        await query.edit_message_text("✅ Сессия завершена. Для нового поиска введите /start")
        return ConversationHandler.END

def main():
    """Основная функция инициализации бота"""
    print("[DEBUG] Запуск функции main()")
    load_data()

    application = Application.builder().token(TOKEN).build()

    conv_handler = ConversationHandler(
        entry_points=[CommandHandler('start', start)],
        states={
            CHOOSE_MODE: [
                CallbackQueryHandler(choose_mode),  # Обработчик выбора типа поиска
                CallbackQueryHandler(handle_pagination, pattern=r"^(prev|next)_\d+"),  # Обработчик пагинации
            ],
            INPUT_ARTICLE: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_article)],
            INPUT_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_name)],
        },
        fallbacks=[],
        per_message=False,
        per_chat=True,
        per_user=True
    )

    application.add_handler(conv_handler)
    print("Бот запущен и готов к работе!")
    application.run_polling()


if __name__ == "__main__":
    main()