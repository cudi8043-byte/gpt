from database import Database
import os

def test_database():
    db_name = "test_bot.db"
    if os.path.exists(db_name):
        os.remove(db_name)
    
    db = Database(db_name)
    user_id = 12345
    
    # 1. Тест добавления пользователя и настроек
    print("Добавление пользователя...")
    db.add_user(user_id, "test_user", "Test User")
    
    settings = db.get_user_settings(user_id)
    print(f"Настройки по умолчанию: {settings}")
    assert settings['model_name'] == 'gpt-3.5-turbo'
    
    # 2. Тест обновления настроек
    print("Обновление настроек...")
    db.update_user_setting(user_id, 'temperature', 0.9)
    updated_settings = db.get_user_settings(user_id)
    print(f"Обновленные настройки: {updated_settings}")
    assert updated_settings['temperature'] == 0.9
    
    # 3. Тест добавления сообщений
    print("Добавление сообщений...")
    db.add_message(user_id, "user", "Привет, нейросеть!")
    db.add_message(user_id, "assistant", "Привет! Чем могу помочь?")
    
    # 4. Тест получения истории для ИИ
    print("Получение истории для ИИ...")
    ai_history = db.get_history_for_ai(user_id)
    print(f"История для ИИ: {ai_history}")
    assert len(ai_history) == 2
    assert ai_history[0]['role'] == 'user'
    
    print("\nВсе тесты пройдены успешно!")
    
    # Очистка после теста
    if os.path.exists(db_name):
        os.remove(db_name)

if __name__ == "__main__":
    test_database()
