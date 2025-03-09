import psycopg2
from psycopg2 import Error
import os

def get_db_connection():
    try:
        # Сначала пробуем подключиться через DATABASE_URL
        database_url = os.getenv('DATABASE_URL')
        if database_url:
            connection = psycopg2.connect(database_url)
        else:
            # Если DATABASE_URL не установлен, используем отдельные параметры
            connection = psycopg2.connect(
                user=os.getenv('DB_USER', 'postgres_web'),
                password=os.getenv('DB_PASSWORD', 'aVJe7nlX6QA4aEoT1lX3Q92Ugkv4uxeW'),
                host=os.getenv('DB_HOST', 'dpg-cv6nv1btq21c73dkj53g-a.frankfurt-postgres.render.com'),
                port=os.getenv('DB_PORT', '5432'),
                database=os.getenv('DB_NAME', 'web_tb1a')
            )
        return connection
    except Exception as error:
        print("Ошибка при подключении к PostgreSQL:", error)
        return None

def close_db_connection(connection):
    if connection:
        connection.close()
        print("Соединение с PostgreSQL закрыто")

def create_users_table():
    connection = None
    try:
        connection = psycopg2.connect(
            user="postgres",
            password="bew",
            host="127.0.0.1",
            port="5432",
            database="postgres"
        )
        
        cursor = connection.cursor()
        
        # Создаем таблицу users с полем email
        create_table_query = '''
        CREATE TABLE IF NOT EXISTS users (
            id SERIAL PRIMARY KEY,
            username VARCHAR(50) UNIQUE NOT NULL,
            password VARCHAR(255) NOT NULL,
            email VARCHAR(255),
            role VARCHAR(20) DEFAULT 'user',
            created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
            last_login TIMESTAMP WITH TIME ZONE
        );
        '''
        cursor.execute(create_table_query)
        
        # Создаем первого пользователя
        insert_query = '''
        INSERT INTO users (username, password, email, role)
        VALUES (%s, %s, %s, %s)
        ON CONFLICT (username) DO NOTHING;
        '''
        cursor.execute(insert_query, ('adrian', 'bew', 'adrian@example.com', 'user'))
        
        connection.commit()
        print("Таблица users успешно создана или уже существует")
        print("Пользователь adrian успешно добавлен или уже существует")
        
    except Exception as error:
        print(f"Ошибка при работе с PostgreSQL: {error}")
    finally:
        if connection:
            cursor.close()
            connection.close()
            print("Соединение с PostgreSQL закрыто")

def set_admin_privilege(user_id=1, privilege_id=1):
    """
    Устанавливает пользователя с указанным ID как администратора
    с указанным ID привилегии
    """
    connection = None
    try:
        connection = get_db_connection()
        cursor = connection.cursor()
        
        # Проверяем существование таблицы user_privileges
        check_table_query = """
        SELECT EXISTS (
            SELECT FROM information_schema.tables 
            WHERE table_name = 'user_privileges'
        );
        """
        cursor.execute(check_table_query)
        table_exists = cursor.fetchone()[0]
        
        # Если таблица не существует, создаем ее
        if not table_exists:
            create_privileges_table = """
            CREATE TABLE user_privileges (
                id SERIAL PRIMARY KEY,
                user_id INTEGER NOT NULL,
                privilege_name VARCHAR(50) NOT NULL,
                is_active BOOLEAN DEFAULT TRUE,
                created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
                UNIQUE (user_id, privilege_name)
            );
            """
            cursor.execute(create_privileges_table)
            print("Таблица user_privileges успешно создана")
        
        # Проверяем существование пользователя
        check_user_query = "SELECT id FROM users WHERE username = 'adrian' AND password = 'bew';"
        cursor.execute(check_user_query)
        user_result = cursor.fetchone()
        
        # Если пользователь не существует или не соответствует credentials
        if not user_result:
            print("Пользователь adrian не найден или неверный пароль")
            return
        
        user_id = user_result[0]
        
        # Устанавливаем привилегию администратора
        set_admin_query = """
        INSERT INTO user_privileges (user_id, privilege_name, is_active)
        VALUES (%s, 'Администратор', TRUE)
        ON CONFLICT (user_id, privilege_name) DO UPDATE 
        SET is_active = TRUE;
        """
        cursor.execute(set_admin_query, (user_id,))
        
        # Обновляем роль пользователя
        update_role_query = """
        UPDATE users 
        SET role = 'admin'
        WHERE id = %s;
        """
        cursor.execute(update_role_query, (user_id,))
        
        connection.commit()
        print(f"Пользователь с ID {user_id} успешно назначен администратором с ID привилегии {privilege_id}")
        
    except Exception as error:
        if connection:
            connection.rollback()
        print(f"Ошибка при назначении администратора: {error}")
    finally:
        if connection:
            cursor.close()
            connection.close()

def create_promo_codes_table():
    """
    Создает таблицу промокодов, если она не существует
    """
    connection = None
    try:
        connection = get_db_connection()
        cursor = connection.cursor()
        
        # Проверяем существование таблицы promo_codes
        check_table_query = """
        SELECT EXISTS (
            SELECT FROM information_schema.tables 
            WHERE table_name = 'promo_codes'
        );
        """
        cursor.execute(check_table_query)
        table_exists = cursor.fetchone()[0]
        
        # Если таблица не существует, создаем ее
        if not table_exists:
            create_table_query = """
            CREATE TABLE promo_codes (
                id SERIAL PRIMARY KEY,
                code VARCHAR(50) NOT NULL UNIQUE,
                description TEXT,
                discount_percent INTEGER,
                discount_amount NUMERIC(10, 2),
                is_active BOOLEAN DEFAULT TRUE,
                max_uses INTEGER DEFAULT NULL,
                current_uses INTEGER DEFAULT 0,
                start_date TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
                end_date TIMESTAMP WITH TIME ZONE DEFAULT NULL,
                created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
            );
            
            -- Индекс для быстрого поиска по коду
            CREATE INDEX idx_promo_codes_code ON promo_codes(code);
            """
            cursor.execute(create_table_query)
            
            # Добавляем примеры промокодов
            insert_promos_query = """
            INSERT INTO promo_codes (code, description, discount_percent, is_active) VALUES
            ('MUFFINWEEKEND', 'Скидка на выходные', 15, TRUE),
            ('WEEKEND2025', 'Специальная скидка 2025', 20, TRUE),
            ('MUFFIN0303', 'Мартовская скидка', 10, TRUE),
            ('GOGOMUFFIN', 'Приветственная скидка', 25, TRUE),
            ('MUFFIN2024', 'Годовая скидка', 30, TRUE);
            """
            cursor.execute(insert_promos_query)
            
            connection.commit()
            print("Таблица промокодов успешно создана и заполнена")
        
    except Exception as error:
        if connection:
            connection.rollback()
        print(f"Ошибка при создании таблицы промокодов: {error}")
    finally:
        if connection:
            cursor.close()
            connection.close()
            print("Соединение с PostgreSQL закрыто")

def create_maintenance_table():
    """Создает таблицу для хранения информации о техническом обслуживании"""
    connection = get_db_connection()
    if not connection:
        print("Ошибка подключения к базе данных")
        return
    
    try:
        cursor = connection.cursor()
        
        # Проверяем существование таблицы games
        cursor.execute("""
            SELECT EXISTS (
                SELECT FROM information_schema.tables 
                WHERE table_name = 'games'
            );
        """)
        games_table_exists = cursor.fetchone()[0]
        
        if not games_table_exists:
            print("ОШИБКА: Таблица games не существует! Невозможно создать таблицу maintenance.")
            return
        
        # Создаем таблицу, если она не существует
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS maintenance (
                id SERIAL PRIMARY KEY,
                game_id INTEGER NOT NULL REFERENCES games(id) ON DELETE CASCADE,
                is_active BOOLEAN NOT NULL DEFAULT FALSE,
                start_time TIMESTAMP,
                end_time TIMESTAMP,
                message TEXT,
                created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
        """)
        
        connection.commit()
        print("Таблица maintenance создана успешно")
    
    except Exception as e:
        print(f"Ошибка при создании таблицы maintenance: {e}")
        connection.rollback()
    
    finally:
        close_db_connection(connection)

def create_news_table():
    """Создает таблицу для хранения новостей и объявлений"""
    connection = get_db_connection()
    if not connection:
        print("Ошибка подключения к базе данных")
        return
    
    try:
        cursor = connection.cursor()
        
        # Проверяем существование таблицы games
        cursor.execute("""
            SELECT EXISTS (
                SELECT FROM information_schema.tables 
                WHERE table_name = 'games'
            );
        """)
        games_table_exists = cursor.fetchone()[0]
        
        if not games_table_exists:
            print("ОШИБКА: Таблица games не существует! Невозможно создать таблицу news.")
            return
        
        # Создаем таблицу, если она не существует
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS news (
                id SERIAL PRIMARY KEY,
                game_id INTEGER NOT NULL REFERENCES games(id) ON DELETE CASCADE,
                news_type VARCHAR(20) NOT NULL CHECK (news_type IN ('event', 'announcement', 'maintenance')),
                title VARCHAR(255) NOT NULL,
                content TEXT NOT NULL,
                is_active BOOLEAN NOT NULL DEFAULT TRUE,
                start_date TIMESTAMP,
                end_date TIMESTAMP,
                created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
        """)
        
        connection.commit()
        print("Таблица news создана успешно")
    
    except Exception as e:
        print(f"Ошибка при создании таблицы news: {e}")
        connection.rollback()
    
    finally:
        close_db_connection(connection)

# Тестирование подключения
# Добавляем вызов функции в блок if __name__ == "__main__":
if __name__ == "__main__":
    connection = get_db_connection()
    if connection:
        try:
            cursor = connection.cursor()
            cursor.execute("SELECT version();")
            db_version = cursor.fetchone()
            print(f"Успешное подключение к PostgreSQL! Версия: {db_version[0]}")
            
            # Вызываем функцию для установки администратора
            set_admin_privilege(7, 1)
            
            # Создаем таблицу промокодов
            create_promo_codes_table()
        except Error as e:
            print(f"Ошибка при выполнении запроса: {e}")
        finally:
            close_db_connection(connection)