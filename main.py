import pandas as pd
import os
import re
import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    filters,
    ContextTypes,
    CallbackQueryHandler,
)
from pymorphy3 import MorphAnalyzer
from dotenv import load_dotenv

# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

# Загрузка переменных окружения из .env
load_dotenv()

# Конфигурация
TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")  # Токен бота
EXCEL_FILE = "SALES_Stock_report.xlsx"  # Название файла

morph = MorphAnalyzer()  # Инициализация морфологического анализатора
df = pd.DataFrame()  # Глобальный DataFrame для хранения данных из Excel

# Глобальная переменная для хранения результатов поиска
user_data = {}


def normalize_text(text):
    """
    Нормализация текста: удаление знаков препинания, приведение к нижнему регистру, лемматизация.
    :param text: Входной текст.
    :return: Нормализованный текст.
    """
    if not isinstance(text, str):
        return ""

    # Удаляем знаки препинания
    text = re.sub(r'[^\w\s]', '', text)

    # Приводим к нижнему регистру и разбиваем на слова
    words = text.lower().split()

    # Лемматизация и удаление стоп-слов
    normalized_words = []
    for word in words:
        if len(word) > 2:  # Игнорируем короткие слова (например, "и", "в")
            normalized_word = morph.parse(word)[0].normal_form
            normalized_words.append(normalized_word)

    return ' '.join(normalized_words)


def load_data():
    """
    Загрузка данных из Excel-файла.
    """
    global df
    try:
        df = pd.read_excel(EXCEL_FILE)  # Чтение данных из Excel
        df.columns = df.columns.str.strip().str.lower()  # Нормализация названий колонок
        logger.info("Данные успешно загружены!")

        # Нормализация названий товаров для улучшения поиска
        df['норм_название'] = df['наименование'].apply(normalize_text)
    except FileNotFoundError:
        logger.error(f"Файл {EXCEL_FILE} не найден!")
    except Exception as e:
        logger.error(f"Ошибка загрузки файла: {e}")


def search_data(query):
    """
    Поиск данных по запросу.
    :param query: Запрос пользователя (может содержать несколько артикулов или слов).
    :return: DataFrame с результатами поиска.
    """
    try:
        # Разделяем запрос на артикулы и название
        query_parts = re.split(r'[\s,;]+', query.strip())
        query_parts = [part.strip() for part in query_parts if part.strip()]

        # Поиск по артикулам (точное совпадение)
        mask_article = df['материал'].astype(str).str.lower().isin(
            [part.lower() for part in query_parts]
        )

        # Поиск по названию (все слова из запроса должны быть в названии)
        query_norm = normalize_text(" ".join(query_parts))
        search_words = query_norm.split()
        mask_name = df['норм_название'].apply(
            lambda x: all(word in x for word in search_words)
        )

        # Комбинированный поиск
        results = df[mask_article | mask_name].drop_duplicates()

        # Исключаем товары с нулевым количеством в наличии
        results = results[results['в наличии'] > 0]

        logger.info(f"Найдено {len(results)} результатов для запроса: {query}")
        return results
    except Exception as e:
        logger.error(f"Ошибка поиска: {e}")
        return pd.DataFrame()


# Обработчик команды /start
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Обработчик команды /start. Приветствует пользователя и объясняет, как использовать бота.
    """
    await update.message.reply_text(
        "🔍 Привет! Я бот для поиска товаров.\n"
        "Отправьте мне артикул или название товара.\n"
        "Для обновления данных используйте /reload\n"
        "Для получения списка команд используйте /help"
    )


# Обработчик команды /help
async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Обработчик команды /help. Показывает список доступных команд.
    """
    await update.message.reply_text(
        "Список команд:\n"
        "/start - Начать работу с ботом\n"
        "/reload - Обновить данные из Excel-файла\n"
        "/help - Показать это сообщение\n\n"
        "Просто отправьте мне артикул или название товара, чтобы начать поиск."
    )


# Обработчик команды /reload
async def reload(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Обработчик команды /reload. Перезагружает данные из Excel-файла.
    """
    load_data()
    await update.message.reply_text("✅ Данные успешно обновлены!")


# Обработчик текстовых сообщений
async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Обработчик текстовых сообщений. Выполняет поиск по запросу пользователя.
    """
    if df.empty:
        await update.message.reply_text("❌ Данные не загружены. Используйте /reload")
        return

    query = update.message.text.strip()  # Получаем запрос пользователя
    results = search_data(query)  # Выполняем поиск

    if results.empty:
        await update.message.reply_text("😞 Ничего не найдено")
        return

    # Сохраняем результаты в user_data
    user_data[update.effective_user.id] = {
        "results": results,
        "page": 0  # Начинаем с первой страницы
    }

    # Отправляем первую страницу
    await show_page(update, context)


async def show_page(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Отображает текущую страницу результатов.
    """
    user_id = update.effective_user.id
    data = user_data.get(user_id)
    if not data:
        await update.message.reply_text("❌ Данные не найдены. Попробуйте снова.")
        return

    results = data["results"]
    page = data["page"]
    items_per_page = 10  # Количество товаров на странице

    # Выбираем товары для текущей страницы
    start = page * items_per_page
    end = start + items_per_page
    page_results = results[start:end]

    # Формируем сообщение
    response = []
    for _, row in page_results.iterrows():
        quantity = int(round(row['в наличии']))
        reserve = int(round(row['в резерве']))  # Округляем "В резерве" до целых чисел
        response.append(
            f"📦 Артикул: {row['материал']}\n"
            f"📌 Название: {row['наименование']}\n"
            f"🔢 В наличии: {quantity} шт.\n"
            f"📥 В резерве: {reserve} шт.\n"
            "—————————————"
        )

    # Добавляем кнопки пагинации
    total_pages = (len(results) + items_per_page - 1) // items_per_page
    keyboard = []

    # Кнопка "Назад"
    if page > 0:
        keyboard.append(InlineKeyboardButton("⬅️ Назад", callback_data=f"page_{page - 1}"))

    # Кнопка с номером страницы
    keyboard.append(InlineKeyboardButton(f"{page + 1}/{total_pages}", callback_data="none"))

    # Кнопка "Вперед"
    if page < total_pages - 1:
        keyboard.append(InlineKeyboardButton("Вперед ➡️", callback_data=f"page_{page + 1}"))

    reply_markup = InlineKeyboardMarkup([keyboard]) if keyboard else None

    # Отправляем сообщение
    if update.callback_query:
        await update.callback_query.edit_message_text(
            "\n".join(response),
            reply_markup=reply_markup
        )
    else:
        await update.message.reply_text(
            "\n".join(response),
            reply_markup=reply_markup
        )


# Обработчик нажатий на кнопки
async def handle_button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Обрабатывает нажатия на кнопки пагинации.
    """
    query = update.callback_query
    await query.answer()

    user_id = update.effective_user.id
    data = user_data.get(user_id)
    if not data:
        await query.edit_message_text("❌ Данные не найдены. Попробуйте снова.")
        return

    # Обновляем текущую страницу
    if query.data.startswith("page_"):
        page = int(query.data.split("_")[1])
        user_data[user_id]["page"] = page

    # Показываем новую страницу
    await show_page(update, context)


# Основная функция
def main():
    """
    Основная функция для запуска бота.
    """
    # Загрузка данных при старте
    load_data()

    # Создание приложения
    application = Application.builder().token(TOKEN).build()

    # Регистрация обработчиков
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("reload", reload))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
    application.add_handler(CallbackQueryHandler(handle_button))  # Обработчик кнопок

    # Запуск бота
    logger.info("Бот запущен...")
    application.run_polling()


if __name__ == "__main__":
    main()