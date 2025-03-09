from flask import Flask, render_template, request, redirect, url_for, flash, session, send_from_directory
from werkzeug.security import generate_password_hash, check_password_hash
from db import get_db_connection, close_db_connection
import psycopg2
from psycopg2 import Error
from functools import wraps
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
import random
from sendgrid import SendGridAPIClient
from sendgrid.helpers.mail import Mail
import yagmail
import requests
import sqlite3
import os
from werkzeug.utils import secure_filename
from datetime import datetime
import shutil

app = Flask(__name__)
app.secret_key = 'bew'  # Замените на случайную строку

# Настройка для загрузки файлов
UPLOAD_FOLDER = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'static/images')
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024  # 16 MB максимальный размер файла

# Декоратор для проверки авторизации
def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        print(f"Проверка авторизации: user_id={session.get('user_id')}, username={session.get('username')}")
        if 'user_id' not in session:
            flash('Пожалуйста, войдите в систему')
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated_function

# Декоратор для проверки прав администратора
def admin_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        print(f"Проверка прав администратора: user_id={session.get('user_id')}, is_admin={session.get('is_admin')}")
        if 'user_id' not in session:
            flash('Пожалуйста, войдите в систему')
            return redirect(url_for('login'))
        if not session.get('is_admin', False):
            flash('У вас нет прав для доступа к этой странице')
            return redirect(url_for('home'))
        return f(*args, **kwargs)
    return decorated_function

@app.route('/')
def index():
    # Перенаправляем на страницу игры вместо страницы входа
    return redirect(url_for('game_detail', game_id=1))

@app.route('/login', methods=['GET', 'POST'])
def login():
    error_message = None
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        
        connection = get_db_connection()
        if connection:
            try:
                cursor = connection.cursor()
                cursor.execute("SELECT * FROM users WHERE username = %s", (username,))
                user = cursor.fetchone()
                
                if user:
                    # Проверяем, совпадает ли пароль
                    if user[2] == password:  # Предполагается, что пароль в 3-м столбце
                        # Сохраняем данные пользователя в сессии
                        session['user_id'] = user[0]
                        session['username'] = user[1]
                        session['user_role'] = user[3]
                        
                        # Проверяем, является ли пользователь администратором
                        cursor.execute("""
                            SELECT EXISTS(
                                SELECT 1 FROM user_privileges 
                                WHERE user_id = %s AND privilege_name = 'administrator' AND is_active = TRUE
                            )
                        """, (user[0],))
                        is_admin = cursor.fetchone()[0]
                        session['is_admin'] = is_admin
                        
                        print(f"Пользователь вошел в систему: ID={user[0]}, имя={user[1]}, роль={user[3]}, админ={is_admin}")
                        
                        flash('Вы успешно вошли в систему!')
                        
                        # Обновляем время последнего входа
                        cursor.execute("UPDATE users SET last_login = NOW() WHERE id = %s", (user[0],))
                        connection.commit()
                        return redirect(url_for('index'))
                    else:
                        error_message = 'Неверный логин или пароль'
                else:
                    error_message = 'Неверный логин или пароль'
            except Exception as e:
                error_message = f'Ошибка при входе: {e}'
                print(f"Ошибка: {e}")
            finally:
                close_db_connection(connection)
        else:
            error_message = 'Не удалось подключиться к базе данных'
    return render_template('login.html', error_message=error_message)

@app.route('/home')
@login_required
def home():
    # Обновляем данные пользователя из базы данных
    user_id = session.get('user_id')
    if user_id:
        connection = get_db_connection()
        if connection:
            try:
                cursor = connection.cursor()
                cursor.execute("SELECT username, role FROM users WHERE id = %s", (user_id,))
                user_data = cursor.fetchone()
                if user_data:
                    session['username'] = user_data[0]
                    session['user_role'] = user_data[1]
                    print(f"Обновлены данные пользователя: {user_data[0]}, {user_data[1]}")
            except Exception as e:
                print(f"Ошибка при обновлении данных пользователя: {e}")
            finally:
                close_db_connection(connection)
    
    # Перенаправляем пользователя на страницу с классами
    return redirect(url_for('game_detail', game_id=1))

# Добавляем маршрут для панели администратора
@app.route('/admin')
@admin_required
def admin_panel():
    return render_template('admin.html', username=session.get('username'))

@app.route('/test_db')
def test_db():
    connection = get_db_connection()
    if connection:
        try:
            cursor = connection.cursor()
            cursor.execute("SELECT version();")
            db_version = cursor.fetchone()
            return f"Подключение успешно! Версия PostgreSQL: {db_version[0]}"
        except Exception as e:
            return f"Ошибка: {str(e)}"
        finally:
            close_db_connection(connection)
    return "Не удалось подключиться к базе данных"

# Изменяем маршрут для выхода из системы
@app.route('/logout')
def logout():
    session.clear()
    # Перенаправляем на страницу игры вместо страницы входа
    return redirect(url_for('game_detail', game_id=1))

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        email = request.form['email']
        
        connection = get_db_connection()
        if connection:
            try:
                cursor = connection.cursor()
                
                # Проверяем, существует ли пользователь
                cursor.execute("SELECT * FROM users WHERE username = %s", (username,))
                if cursor.fetchone():
                    flash('Пользователь с таким именем уже существует')
                    return redirect(url_for('register'))

                # Вставляем нового пользователя без хеширования пароля
                insert_query = '''
                INSERT INTO users (username, password, email, role)
                VALUES (%s, %s, %s, %s);
                '''
                cursor.execute(insert_query, (username, password, email, 'user'))  # Сохраняем пароль в открытом виде
                connection.commit()

                # Устанавливаем сообщение в сессии
                session['registration_success'] = True
                return redirect(url_for('login'))
            except Exception as e:
                flash('Ошибка при регистрации')
                print(f"Ошибка: {e}")
            finally:
                close_db_connection(connection)
        else:
            flash('Ошибка подключения к базе данных')
        return redirect(url_for('register'))
    
    # Удаляем сообщение из сессии, если оно есть
    if 'registration_success' in session:
        flash('Регистрация прошла успешно! Вы можете войти в систему.')
        session.pop('registration_success')  # Удаляем сообщение из сессии

    return render_template('register.html')

@app.route('/confirm_registration', methods=['GET', 'POST'])
def confirm_registration():
    if request.method == 'POST':
        entered_code = request.form['confirmation_code']
        pending_user = session.get('pending_user')

        if pending_user and str(pending_user['confirmation_code']) == entered_code:
            connection = get_db_connection()
            if connection:
                try:
                    cursor = connection.cursor()
                    # Вставляем нового пользователя
                    insert_query = '''
                    INSERT INTO users (username, password, role)
                    VALUES (%s, %s, %s);
                    '''
                    cursor.execute(insert_query, (pending_user['username'], pending_user['password'], 'user'))
                    connection.commit()  # Сохраняем изменения
                    flash('Регистрация прошла успешно!')
                    return redirect(url_for('login'))
                except Exception as e:
                    flash('Ошибка при добавлении пользователя')
                    print(f"Ошибка: {e}")  # Отладочное сообщение
                finally:
                    close_db_connection(connection)
        else:
            flash('Неверный код подтверждения')

    return render_template('confirm_registration.html')

def send_confirmation_email(email, code):
    # Настройки для Gmail
    sender_email = "your.email@gmail.com"  # Замените на ваш Gmail
    app_password = "your-app-password"  # Замените на ваш пароль приложения

    # Создаем сообщение
    msg = MIMEMultipart()
    msg['From'] = sender_email
    msg['To'] = email
    msg['Subject'] = "Код подтверждения регистрации"

    # Создаем текст письма
    body = f"""
    Здравствуйте!
    
    Ваш код подтверждения для регистрации: {code}
    
    Если вы не запрашивали этот код, просто проигнорируйте это письмо.
    
    С уважением,
    Ваше приложение
    """
    msg.attach(MIMEText(body, 'plain'))

    try:
        # Создаем SMTP-сессию для отправки email
        server = smtplib.SMTP('smtp.gmail.com', 587)
        server.starttls()  # Включаем шифрование
        
        # Логинимся на почтовый сервер
        server.login(sender_email, app_password)
        
        # Отправляем email
        text = msg.as_string()
        server.sendmail(sender_email, email, text)
        
        # Закрываем соединение
        server.quit()
        
        print(f"""
        ===============================
        Код подтверждения отправлен:
        Email: {email}
        Код: {code}
        ===============================
        """)
        return True
        
    except Exception as e:
        print(f"Ошибка при отправке email: {e}")
        return False

@app.route('/send_confirmation_code', methods=['POST'])
def send_confirmation_code():
    data = request.get_json()
    email = data.get('email')

    if not email:
        return {'success': False, 'message': 'Email не указан'}

    try:
        # Генерируем код подтверждения
        code = random.randint(100000, 999999)
        
        # Сохраняем код и email в сессии
        session['confirmation_code'] = code
        session['confirmation_email'] = email
        
        # Отправляем код
        if send_confirmation_email(email, code):
            return {
                'success': True,
                'message': 'Код подтверждения отправлен на ваш email'
            }
        else:
            return {
                'success': False,
                'message': 'Ошибка при отправке кода'
            }
            
    except Exception as e:
        print(f"Ошибка: {e}")
        return {
            'success': False,
            'message': 'Произошла ошибка при генерации кода'
        }

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
        
        # Создаем таблицу users
        create_table_query = '''
        CREATE TABLE IF NOT EXISTS users (
            id SERIAL PRIMARY KEY,
            username VARCHAR(50) UNIQUE NOT NULL,
            password VARCHAR(255) NOT NULL,
            role VARCHAR(20) DEFAULT 'user',
            created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
            last_login TIMESTAMP WITH TIME ZONE
        );
        '''
        cursor.execute(create_table_query)
        
        # Вставка пользователя по умолчанию
        insert_query = '''
        INSERT INTO users (username, password, role)
        VALUES (%s, %s, %s)
        ON CONFLICT (username) DO NOTHING;
        '''
        cursor.execute(insert_query, ('adrian', 'bew', 'user'))
        
        connection.commit()
        print("Таблица users создана успешно")
        print("Пользователь adrian добавлен успешно")
        
    except (Exception, Error) as error:
        print("Ошибка при работе с PostgreSQL:", error)
    finally:
        if connection:
            cursor.close()
            connection.close()
            print("Соединение с PostgreSQL закрыто")

def get_db_connection():
    try:
        connection = psycopg2.connect(
            user=os.getenv('DB_USER', 'postgres'),
            password=os.getenv('DB_PASSWORD', 'bew'),
            host=os.getenv('DB_HOST', '127.0.0.1'),
            port=os.getenv('DB_PORT', '5432'),
            database=os.getenv('DB_NAME', 'postgres')
        )
        return connection
    except (Exception, Error) as error:
        print("Ошибка при подключении к PostgreSQL:", error)
        return None

@app.route('/reset_password', methods=['GET', 'POST'])
def reset_password():
    if request.method == 'POST':
        email = request.form['email']
        
        connection = get_db_connection()
        if connection:
            try:
                cursor = connection.cursor()
                # Проверяем, существует ли пользователь с таким email
                cursor.execute("SELECT * FROM users WHERE email = %s", (email,))
                user = cursor.fetchone()
                
                if user:
                    # Здесь можно добавить логику для генерации временного пароля
                    # и отправки его на email пользователя
                    flash('Инструкции по сбросу пароля отправлены на ваш email')
                    return redirect(url_for('login'))
                else:
                    flash('Пользователь с таким email не найден')
            except Exception as e:
                flash('Ошибка при сбросе пароля')
                print(f"Ошибка при сбросе пароля: {e}")
            finally:
                close_db_connection(connection)
        return redirect(url_for('reset_password'))
    return render_template('reset_password.html')

def create_privileges_table():
    connection = None
    try:
        connection = get_db_connection()
        if connection:
            cursor = connection.cursor()
            
            # Создаем таблицу привилегий если она не существует
            create_table_query = '''
            CREATE TABLE IF NOT EXISTS user_privileges (
                id SERIAL PRIMARY KEY,
                user_id INTEGER NOT NULL,
                privilege_name VARCHAR(50) NOT NULL,
                is_active BOOLEAN DEFAULT TRUE,
                created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
                UNIQUE (user_id, privilege_name)
            );
            
            CREATE INDEX IF NOT EXISTS idx_user_privileges_user_id ON user_privileges(user_id);
            '''
            cursor.execute(create_table_query)
            
            connection.commit()
            print("Таблица user_privileges создана успешно или уже существует")
            
    except Exception as error:
        print(f"Ошибка при создании таблицы привилегий: {error}")
    finally:
        if connection:
            cursor.close()
            connection.close()

def set_user_as_admin(user_id=1):
    connection = None
    try:
        connection = get_db_connection()
        if connection:
            cursor = connection.cursor()
            
            # Проверяем существование пользователя
            cursor.execute("SELECT EXISTS(SELECT 1 FROM users WHERE id = %s)", (user_id,))
            if not cursor.fetchone()[0]:
                print(f"Пользователь с ID {user_id} не найден")
                return False
            
            # Обновляем роль пользователя
            cursor.execute("UPDATE users SET role = 'Администратор' WHERE id = %s", (user_id,))
            
            # Добавляем привилегию администратора
            cursor.execute("""
            INSERT INTO user_privileges (user_id, privilege_name, is_active)
            VALUES (%s, 'administrator', TRUE)
            ON CONFLICT (user_id, privilege_name) DO UPDATE 
            SET is_active = TRUE
            """, (user_id,))
            
            connection.commit()
            print(f"Пользователь с ID {user_id} успешно назначен администратором")
            return True
            
    except Exception as error:
        print(f"Ошибка при назначении администратора: {error}")
        return False
    finally:
        if connection:
            cursor.close()
            connection.close()

@app.route('/profile')
@login_required
def profile():
    user_id = session.get('user_id')
    print(f"Профиль пользователя: ID={user_id}")
    
    connection = get_db_connection()
    user_data = None
    
    if connection:
        try:
            cursor = connection.cursor()
            # Получаем данные пользователя
            cursor.execute("SELECT username, email, role FROM users WHERE id = %s", (user_id,))
            user_data = cursor.fetchone()  # Получаем данные пользователя
            print(f"Данные пользователя: {user_data}")
            
            if user_data:
                session['username'] = user_data[0]  # Обновляем имя пользователя в сессии
                session['user_role'] = user_data[2]  # Обновляем роль пользователя в сессии
        except Exception as e:
            print("Ошибка при работе с базой данных:", e)
        finally:
            close_db_connection(connection)
    
    username = session.get('username', 'User')
    user_role = session.get('user_role', 'User Role')
    
    return render_template('profile.html', user_data=user_data, username=username, user_role=user_role)

@app.route('/game/<int:game_id>')
def game_detail(game_id):
    connection = get_db_connection()
    if not connection:
        return render_template('error.html', 
                             error_message="Ошибка подключения к базе данных"), 500
    try:
        # Получение данных об игре
        cursor = connection.cursor()
        cursor.execute("SELECT name, description FROM games WHERE id = %s", (game_id,))
        game_data = cursor.fetchone()
        
        # Получение информации о техническом обслуживании
        maintenance_info = None
        try:
            cursor.execute("""
                SELECT is_active, start_time, end_time, message 
                FROM maintenance 
                WHERE game_id = %s AND is_active = TRUE
            """, (game_id,))
            maintenance_info = cursor.fetchone()
        except psycopg2.errors.UndefinedTable:
            # Если таблица не существует, просто продолжаем без информации о техобслуживании
            connection.rollback()  # Важно откатить транзакцию после ошибки
        
        # Получение новостей и объявлений
        news = []
        try:
            cursor.execute("""
                SELECT id, news_type, title, content, start_date, end_date
                FROM news
                WHERE game_id = %s AND title IS NOT NULL AND content IS NOT NULL AND title != '' AND content != ''
                ORDER BY created_at DESC
                LIMIT 10
            """, (game_id,))
            news = cursor.fetchall()
            print(f"Получено новостей: {len(news)}")  # Отладочная информация
        except psycopg2.errors.UndefinedTable:
            # Если таблица не существует, просто продолжаем без новостей
            connection.rollback()
        except Exception as e:
            print(f"Ошибка при получении новостей: {e}")
            connection.rollback()
        
        # Получение классов из базы данных
        cursor.execute("SELECT id, name, description, image_path FROM game_classes")
        classes_data = cursor.fetchall()
        
        # Преобразование в список словарей для удобства использования в шаблоне
        classes = []
        for class_data in classes_data:
            classes.append({
                'id': class_data[0],
                'name': class_data[1],
                'description': class_data[2],
                'image_path': class_data[3]
            })
        
        # Получение всех промокодов, включая неактивные
        try:
            cursor.execute("""
                SELECT code, description, is_active, 
                       (end_date IS NOT NULL AND end_date <= CURRENT_TIMESTAMP) as expired
                FROM promo_codes 
                WHERE code IS NOT NULL AND code != ''
                ORDER BY is_active DESC, created_at DESC
                LIMIT 10
            """)
            promo_codes = cursor.fetchall()
        except Exception as e:
            print(f"Ошибка при получении промокодов: {e}")
            promo_codes = []
        
        # Добавляем флаг is_guest для шаблона
        is_guest = 'user_id' not in session
        
        # Получаем текущую тему из localStorage (если есть)
        current_theme = 'dark'  # По умолчанию темная тема
        
        # Закрываем соединение
        close_db_connection(connection)
        
        return render_template('game_detail.html', 
                              game_data=game_data, 
                              classes=classes, 
                              promo_codes=promo_codes,
                              game_id=game_id,
                              maintenance_info=maintenance_info,
                              news=news,
                              is_guest=is_guest,
                              current_theme=current_theme)  # Передаем текущую тему
    except Exception as e:
        print(f"Ошибка: {e}")
        return render_template('error.html', 
                             error_message="Произошла ошибка при загрузке данных"), 500

# Переименуйте эту функцию, чтобы избежать конфликта
def get_sqlite_connection():
    conn = sqlite3.connect('database.db')
    conn.row_factory = sqlite3.Row
    return conn

# Добавьте эти функции для управления классами в админ-панели (если она у вас есть)
@app.route('/admin/classes')
@admin_required
def admin_classes():
    try:
        # Используем PostgreSQL вместо SQLite
        from db import get_db_connection as pg_get_db_connection
        connection = pg_get_db_connection()
        cursor = connection.cursor()
        cursor.execute('SELECT * FROM player_class ORDER BY name')
        
        # Преобразуем результаты в список словарей
        columns = [desc[0] for desc in cursor.description]
        classes = [dict(zip(columns, row)) for row in cursor.fetchall()]
        
        cursor.close()
        connection.close()
    except Exception as e:
        print(f"Ошибка при получении классов: {e}")
        classes = []
    
    return render_template('admin/classes.html', classes=classes, 
                          username=session.get('username', 'User'),
                          is_admin=session.get('is_admin', False))

@app.route('/admin/classes/add', methods=['GET', 'POST'])
@admin_required
def add_class():
    if request.method == 'POST':
        name = request.form['name']
        image_path = request.form['image_path']
        description = request.form['description']
        difficulty = request.form['difficulty']
        role = request.form['role']
        primary_stat = request.form['primary_stat']
        abilities = request.form.get('abilities', '')
        is_active = True if 'is_active' in request.form else False
        
        try:
            # Используем PostgreSQL вместо SQLite
            from db import get_db_connection as pg_get_db_connection
            connection = pg_get_db_connection()
            cursor = connection.cursor()
            cursor.execute('''
                INSERT INTO player_class (name, image_path, description, difficulty, role, primary_stat, abilities, is_active)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            ''', (name, image_path, description, difficulty, role, primary_stat, abilities, is_active))
            connection.commit()
            cursor.close()
            connection.close()
            
            # Обработка загрузки изображения, если необходимо
            if 'image_file' in request.files:
                file = request.files['image_file']
                if file.filename != '':
                    filename = secure_filename(file.filename)
                    file.save(os.path.join(app.config['UPLOAD_FOLDER'], 'class', filename))
            
            flash('Класс успешно добавлен', 'success')
        except Exception as e:
            flash(f'Ошибка при добавлении класса: {e}', 'error')
        
        return redirect(url_for('admin_classes'))
    
    return render_template('admin/add_class.html', 
                          username=session.get('username', 'User'),
                          is_admin=session.get('is_admin', False))

@app.route('/admin/classes/edit/<int:id>', methods=['GET', 'POST'])
@admin_required
def edit_class(id):
    try:
        # Используем PostgreSQL вместо SQLite
        from db import get_db_connection as pg_get_db_connection
        connection = pg_get_db_connection()
        cursor = connection.cursor()
        
        if request.method == 'POST':
            name = request.form['name']
            image_path = request.form['image_path']
            description = request.form['description']
            difficulty = request.form['difficulty']
            role = request.form['role']
            primary_stat = request.form['primary_stat']
            abilities = request.form.get('abilities', '')
            is_active = True if 'is_active' in request.form else False
            
            cursor.execute('''
                UPDATE player_class
                SET name = %s, image_path = %s, description = %s, difficulty = %s, 
                    role = %s, primary_stat = %s, abilities = %s, is_active = %s,
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = %s
            ''', (name, image_path, description, difficulty, role, primary_stat, abilities, is_active, id))
            connection.commit()
            
            # Обработка загрузки изображения, если необходимо
            if 'image_file' in request.files:
                file = request.files['image_file']
                if file.filename != '':
                    filename = secure_filename(file.filename)
                    file.save(os.path.join(app.config['UPLOAD_FOLDER'], 'class', filename))
            
            flash('Класс успешно обновлен', 'success')
            return redirect(url_for('admin_classes'))
        
        # Получаем данные класса для формы редактирования
        cursor.execute('SELECT * FROM player_class WHERE id = %s', (id,))
        columns = [desc[0] for desc in cursor.description]
        player_class = dict(zip(columns, cursor.fetchone()))
        
        cursor.close()
        connection.close()
        
        return render_template('admin/edit_class.html', player_class=player_class,
                              username=session.get('username', 'User'),
                              is_admin=session.get('is_admin', False))
    except Exception as e:
        flash(f'Ошибка при редактировании класса: {e}', 'error')
        return redirect(url_for('admin_classes'))

@app.route('/admin/classes/delete/<int:id>')
@admin_required
def delete_class(id):
    try:
        # Используем PostgreSQL вместо SQLite
        from db import get_db_connection as pg_get_db_connection
        connection = pg_get_db_connection()
        cursor = connection.cursor()
        cursor.execute('DELETE FROM player_class WHERE id = %s', (id,))
        connection.commit()
        cursor.close()
        connection.close()
        flash('Класс успешно удален', 'success')
    except Exception as e:
        flash(f'Ошибка при удалении класса: {e}', 'error')
    
    return redirect(url_for('admin_classes'))

def create_pg_player_class_table():
    """Создает таблицу player_class в PostgreSQL, если она не существует"""
    try:
        from db import get_db_connection as pg_get_db_connection
        connection = pg_get_db_connection()
        cursor = connection.cursor()
        
        # Проверяем, существует ли таблица
        cursor.execute("""
        SELECT EXISTS (
            SELECT FROM information_schema.tables 
            WHERE table_schema = 'public' 
            AND table_name = 'player_class'
        );
        """)
        
        table_exists = cursor.fetchone()[0]
        
        if not table_exists:
            print("Создаем таблицу player_class в PostgreSQL...")
            
            # Создаем таблицу
            cursor.execute("""
            CREATE TABLE player_class (
                id SERIAL PRIMARY KEY,
                name TEXT NOT NULL,
                image_path TEXT NOT NULL,
                description TEXT,
                difficulty INTEGER DEFAULT 1,
                role TEXT,
                primary_stat TEXT,
                abilities TEXT,
                is_active BOOLEAN DEFAULT TRUE,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
            
            -- Индекс для быстрого поиска по имени
            CREATE INDEX idx_player_class_name ON player_class(name);
            """)
            
            # Добавляем начальные данные только если таблица была создана
            classes = [
                ('Мечник', 'mech.jpg', 'Мастер ближнего боя, специализирующийся на мечах и щитах. Отличная выживаемость и средний урон.', 2, 'Tank', 'Сила'),
                ('Маг', 'mag.jpg', 'Владеет разрушительной магией стихий. Высокий урон по площади, но низкая защита.', 3, 'DPS', 'Интеллект'),
                ('Лучник', 'luch.jpg', 'Эксперт дальнего боя с высокой мобильностью и точностью. Наносит высокий урон одиночным целям.', 3, 'DPS', 'Ловкость'),
                ('Целитель', 'heal.jpg', 'Специалист по исцелению и поддержке союзников. Незаменим в групповых сражениях.', 4, 'Healer', 'Интеллект'),
                ('Ассасин', 'ass.jpg', 'Мастер скрытности и внезапных атак. Наносит огромный урон, но уязвим в длительных сражениях.', 4, 'DPS', 'Ловкость')
            ]
            
            cursor.executemany("""
            INSERT INTO player_class (name, image_path, description, difficulty, role, primary_stat)
            VALUES (%s, %s, %s, %s, %s, %s)
            """, classes)
            
            connection.commit()
            print("Таблица player_class успешно создана и заполнена в PostgreSQL")
        
        cursor.close()
        connection.close()
    except Exception as e:
        print(f"Ошибка при создании таблицы player_class: {e}")

@app.context_processor
def inject_user():
    """Добавляет информацию о пользователе во все шаблоны"""
    user_data = {
        'username': session.get('username', 'User'),
        'user_role': session.get('user_role', 'User Role'),
        'is_admin': session.get('is_admin', False),
        'user_id': session.get('user_id', None)
    }
    return {'user': user_data}

def create_game_tables():
    """Создает таблицы games и game_classes, если они не существуют"""
    connection = None
    try:
        connection = get_db_connection()
        if connection:
            cursor = connection.cursor()
            
            # Создаем таблицу games
            cursor.execute("""
            CREATE TABLE IF NOT EXISTS games (
                id SERIAL PRIMARY KEY,
                name VARCHAR(100) NOT NULL,
                description TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
            """)
            
            # Проверяем, есть ли записи в таблице games
            cursor.execute("SELECT COUNT(*) FROM games")
            count = cursor.fetchone()[0]
            
            # Если записей нет, добавляем пример игры
            if count == 0:
                cursor.execute("""
                INSERT INTO games (name, description) VALUES
                ('GoGoMuffin', 'Увлекательная многопользовательская ролевая игра с открытым миром');
                """)
            
            # Создаем таблицу game_classes
            cursor.execute("""
            CREATE TABLE IF NOT EXISTS game_classes (
                id SERIAL PRIMARY KEY,
                name VARCHAR(100) NOT NULL,
                description VARCHAR(255) NOT NULL,
                image_path VARCHAR(255) NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
            """)
            
            # Проверяем, есть ли записи в таблице game_classes
            cursor.execute("SELECT COUNT(*) FROM game_classes")
            count = cursor.fetchone()[0]
            
            # Если записей нет, добавляем примеры классов
            if count == 0:
                classes = [
                    ('Целитель', 'Специалист по исцелению и поддержке союзников', 'heal.jpg'),
                    ('Воин', 'Мастер ближнего боя с высокой выживаемостью', 'mech.jpg'),
                    ('Маг', 'Владеет разрушительной магией стихий', 'mag.jpg'),
                    ('Лучник', 'Эксперт дальнего боя с высокой точностью', 'luch.jpg'),
                    ('Ассасин', 'Мастер скрытности и внезапных атак', 'ass.jpg')
                ]
                
                cursor.executemany("""
                INSERT INTO game_classes (name, description, image_path)
                VALUES (%s, %s, %s)
                """, classes)
            
            connection.commit()
            print("Таблицы games и game_classes успешно созданы и заполнены")
            
        else:
            print("Не удалось подключиться к базе данных")
            
    except Exception as e:
        print(f"Ошибка при создании таблиц: {e}")
        if connection:
            connection.rollback()
    finally:
        if connection:
            close_db_connection(connection)

@app.route('/admin/promo_codes')
@admin_required
def admin_promo_codes():
    connection = get_db_connection()
    promo_codes = []
    
    if connection:
        try:
            cursor = connection.cursor()
            cursor.execute("""
                SELECT id, code, description, is_active, max_uses, 
                       current_uses, start_date, end_date
                FROM promo_codes
                ORDER BY created_at DESC
            """)
            
            columns = [desc[0] for desc in cursor.description]
            promo_codes = [dict(zip(columns, row)) for row in cursor.fetchall()]
            
        except Exception as e:
            flash(f'Ошибка при получении промокодов: {e}', 'error')
        finally:
            close_db_connection(connection)
    
    return render_template('admin/promo_codes.html', promo_codes=promo_codes, now=datetime.now())

@app.route('/admin/promo_codes/add', methods=['POST'])
@admin_required
def admin_add_promo():
    if request.method == 'POST':
        code = request.form['code']
        description = request.form['description']
        is_active = 'is_active' in request.form
        
        # Получаем ограничения использования
        max_uses = request.form['max_uses'] or None
        end_date = request.form['end_date'] or None
        
        connection = get_db_connection()
        if connection:
            try:
                cursor = connection.cursor()
                cursor.execute("""
                    INSERT INTO promo_codes 
                    (code, description, is_active, max_uses, end_date)
                    VALUES (%s, %s, %s, %s, %s)
                """, (code, description, is_active, max_uses, end_date))
                
                connection.commit()
                flash('Промокод успешно добавлен', 'success')
            except Exception as e:
                connection.rollback()
                flash(f'Ошибка при добавлении промокода: {e}', 'error')
            finally:
                close_db_connection(connection)
    
    return redirect(url_for('admin_promo_codes'))

@app.route('/admin/promo_codes/edit/<int:id>', methods=['GET', 'POST'])
@admin_required
def admin_edit_promo(id):
    connection = get_db_connection()
    
    if request.method == 'POST':
        code = request.form['code']
        description = request.form['description']
        
        if connection:
            try:
                cursor = connection.cursor()
                cursor.execute("""
                    UPDATE promo_codes 
                    SET code = %s, description = %s, updated_at = CURRENT_TIMESTAMP
                    WHERE id = %s
                """, (code, description, id))
                
                connection.commit()
                flash('Промокод успешно обновлен', 'success')
                return redirect(url_for('admin_promo_codes'))
            except Exception as e:
                connection.rollback()
                flash(f'Ошибка при обновлении промокода: {e}', 'error')
            finally:
                close_db_connection(connection)
    
    # Получаем данные промокода для формы редактирования
    promo = None
    if connection:
        try:
            cursor = connection.cursor()
            cursor.execute("""
                SELECT id, code, description
                FROM promo_codes
                WHERE id = %s
            """, (id,))
            
            columns = [desc[0] for desc in cursor.description]
            row = cursor.fetchone()
            
            if row:
                promo = dict(zip(columns, row))
            else:
                flash('Промокод не найден', 'error')
                return redirect(url_for('admin_promo_codes'))
                
        except Exception as e:
            flash(f'Ошибка при получении данных промокода: {e}', 'error')
        finally:
            close_db_connection(connection)
    
    return render_template('admin/edit_promo.html', promo=promo)

@app.route('/admin/promo_codes/delete/<int:id>')
@admin_required
def admin_delete_promo(id):
    connection = get_db_connection()
    if connection:
        try:
            cursor = connection.cursor()
            cursor.execute("DELETE FROM promo_codes WHERE id = %s", (id,))
            connection.commit()
            flash('Промокод успешно удален', 'success')
        except Exception as e:
            connection.rollback()
            flash(f'Ошибка при удалении промокода: {e}', 'error')
        finally:
            close_db_connection(connection)
    
    return redirect(url_for('admin_promo_codes'))

@app.route('/admin/promo_codes/quick_add/<int:game_id>', methods=['POST'])
@admin_required
def admin_add_promo_quick(game_id):
    if request.method == 'POST':
        code = request.form['code']
        description = request.form['description']
        
        connection = get_db_connection()
        if connection:
            try:
                cursor = connection.cursor()
                cursor.execute("""
                    INSERT INTO promo_codes 
                    (code, description, is_active)
                    VALUES (%s, %s, TRUE)
                """, (code, description))
                
                connection.commit()
                flash('Промокод успешно добавлен', 'success')
            except Exception as e:
                connection.rollback()
                flash(f'Ошибка при добавлении промокода: {e}', 'error')
            finally:
                close_db_connection(connection)
    
    return redirect(url_for('game_detail', game_id=game_id))

@app.route('/admin/promo_codes/delete_by_code/<string:code>')
@admin_required
def admin_delete_promo_by_code(code):
    redirect_to = request.args.get('redirect_to', url_for('admin_promo_codes'))
    
    connection = get_db_connection()
    if connection:
        try:
            cursor = connection.cursor()
            cursor.execute("DELETE FROM promo_codes WHERE code = %s", (code,))
            connection.commit()
            flash('Промокод успешно удален', 'success')
        except Exception as e:
            connection.rollback()
            flash(f'Ошибка при удалении промокода: {e}', 'error')
        finally:
            close_db_connection(connection)
    
    return redirect(redirect_to)

# Добавьте новый маршрут для загрузки дополнительных промокодов
@app.route('/load_more_promos/<int:game_id>/<int:offset>')
def load_more_promos(game_id, offset):
    connection = get_db_connection()
    if not connection:
        return {"success": False, "error": "Ошибка подключения к базе данных"}, 500
    
    try:
        cursor = connection.cursor()
        cursor.execute("""
            SELECT code, description, is_active, 
                   (end_date IS NOT NULL AND end_date <= CURRENT_TIMESTAMP) as expired
            FROM promo_codes 
            WHERE code IS NOT NULL AND code != ''
            ORDER BY is_active DESC, created_at DESC
            LIMIT 10 OFFSET %s
        """, (offset,))
        
        promo_codes = cursor.fetchall()
        
        # Преобразуем результаты в список словарей для JSON
        result = []
        for promo in promo_codes:
            result.append({
                "code": promo[0],
                "description": promo[1] if promo[1] else "",
                "is_active": promo[2],
                "expired": promo[3]
            })
        
        # Проверяем, есть ли еще промокоды
        cursor.execute("SELECT COUNT(*) FROM promo_codes WHERE code IS NOT NULL AND code != ''")
        total_count = cursor.fetchone()[0]
        
        has_more = (offset + 10) < total_count
        
        return {"success": True, "promos": result, "has_more": has_more}
    
    except Exception as e:
        return {"success": False, "error": str(e)}, 500
    
    finally:
        close_db_connection(connection)

# Добавьте новый маршрут для переключения статуса промокода
@app.route('/admin/promo_codes/toggle_status/<int:id>', methods=['POST'])
@admin_required
def admin_toggle_promo_status(id):
    data = request.json
    is_active = data.get('is_active', False)
    
    connection = get_db_connection()
    if not connection:
        return {"success": False, "error": "Ошибка подключения к базе данных"}, 500
    
    try:
        cursor = connection.cursor()
        cursor.execute("""
            UPDATE promo_codes 
            SET is_active = %s, updated_at = CURRENT_TIMESTAMP
            WHERE id = %s
        """, (is_active, id))
        
        connection.commit()
        return {"success": True}
    
    except Exception as e:
        connection.rollback()
        return {"success": False, "error": str(e)}, 500
    
    finally:
        close_db_connection(connection)

# Добавляем маршрут для управления статусом технического обслуживания
@app.route('/admin/maintenance', methods=['GET', 'POST'])
@admin_required
def admin_maintenance():
    connection = get_db_connection()
    if not connection:
        flash('Ошибка подключения к базе данных', 'error')
        return redirect(url_for('home'))
    
    try:
        cursor = connection.cursor()
        
        # Обработка формы
        if request.method == 'POST':
            game_id = request.form.get('game_id')
            is_maintenance = request.form.get('is_maintenance') == 'on'
            start_time = request.form.get('start_time')
            end_time = request.form.get('end_time')
            message = request.form.get('message')
            
            # Проверяем, существует ли уже запись для этой игры
            cursor.execute("SELECT id FROM maintenance WHERE game_id = %s", (game_id,))
            maintenance_id = cursor.fetchone()
            
            if maintenance_id:
                # Обновляем существующую запись
                cursor.execute("""
                    UPDATE maintenance 
                    SET is_active = %s, start_time = %s, end_time = %s, message = %s, updated_at = CURRENT_TIMESTAMP
                    WHERE game_id = %s
                """, (is_maintenance, start_time, end_time, message, game_id))
            else:
                # Создаем новую запись
                cursor.execute("""
                    INSERT INTO maintenance (game_id, is_active, start_time, end_time, message, created_at, updated_at)
                    VALUES (%s, %s, %s, %s, %s, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
                """, (game_id, is_maintenance, start_time, end_time, message))
            
            connection.commit()
            flash('Статус технического обслуживания обновлен', 'success')
            return redirect(url_for('admin_maintenance'))
        
        # Получаем список игр
        cursor.execute("SELECT id, name FROM games ORDER BY name")
        games = cursor.fetchall()
        
        # Получаем текущие настройки технического обслуживания
        cursor.execute("""
            SELECT m.id, m.game_id, g.name as game_name, m.is_active, m.start_time, m.end_time, m.message, m.updated_at
            FROM maintenance m
            JOIN games g ON m.game_id = g.id
            ORDER BY g.name
        """)
        maintenance_settings = cursor.fetchall()
        
        return render_template('admin/maintenance.html', games=games, maintenance_settings=maintenance_settings)
    
    except Exception as e:
        flash(f'Ошибка: {str(e)}', 'error')
        return redirect(url_for('home'))
    
    finally:
        close_db_connection(connection)

# Добавляем фильтр для форматирования даты и времени
@app.template_filter('strftime')
def _jinja2_filter_datetime(date, fmt=None):
    if date is None:
        return ""
    if fmt is None:
        fmt = '%d.%m.%Y %H:%M'  # Формат по умолчанию включает время
    return date.strftime(fmt)

@app.route('/admin/add_news/<int:game_id>', methods=['POST'])
@admin_required
def admin_add_news(game_id):
    # Получаем данные из формы
    news_type = request.form.get('news_type')
    title = request.form.get('title')
    content = request.form.get('content')
    is_active = request.form.get('is_active') == 'on'
    start_date = request.form.get('start_date')
    end_date = request.form.get('end_date')
    
    connection = get_db_connection()
    if not connection:
        flash('Ошибка подключения к базе данных', 'error')
        return redirect(url_for('game_detail', game_id=game_id))
    
    try:
        cursor = connection.cursor()
        
        # Добавляем новость
        cursor.execute("""
            INSERT INTO news (game_id, news_type, title, content, is_active, start_date, end_date, created_at, updated_at)
            VALUES (%s, %s, %s, %s, %s, %s, %s, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
        """, (game_id, news_type, title, content, is_active, start_date, end_date))
        
        connection.commit()
        flash('Новость успешно добавлена', 'success')
    
    except Exception as e:
        connection.rollback()
        flash(f'Ошибка при добавлении новости: {e}', 'error')
    
    finally:
        close_db_connection(connection)
    
    return redirect(url_for('game_detail', game_id=game_id))

@app.route('/admin/edit_news/<int:news_id>', methods=['GET', 'POST'])
@admin_required
def admin_edit_news(news_id):
    connection = get_db_connection()
    if not connection:
        flash('Ошибка подключения к базе данных', 'error')
        return redirect(url_for('home'))
    
    try:
        cursor = connection.cursor()
        
        # Получаем данные о новости
        cursor.execute("""
            SELECT id, game_id, news_type, title, content, is_active, start_date, end_date
            FROM news
            WHERE id = %s
        """, (news_id,))
        news = cursor.fetchone()
        
        if not news:
            flash('Новость не найдена', 'error')
            return redirect(url_for('home'))
        
        # Обработка формы
        if request.method == 'POST':
            news_type = request.form.get('news_type')
            title = request.form.get('title')
            content = request.form.get('content')
            is_active = request.form.get('is_active') == 'on'
            start_date = request.form.get('start_date')
            end_date = request.form.get('end_date')
            
            # Обновляем новость
            cursor.execute("""
                UPDATE news
                SET news_type = %s, title = %s, content = %s, is_active = %s, 
                    start_date = %s, end_date = %s, updated_at = CURRENT_TIMESTAMP
                WHERE id = %s
            """, (news_type, title, content, is_active, start_date, end_date, news_id))
            
            # Если тип новости - техническое обслуживание, обновляем также таблицу maintenance
            if news_type == 'maintenance':
                game_id = news[1]  # Получаем game_id из данных новости
                
                # Проверяем, существует ли уже запись для этой игры
                cursor.execute("SELECT id FROM maintenance WHERE game_id = %s", (game_id,))
                maintenance_id = cursor.fetchone()
                
                if maintenance_id:
                    # Обновляем существующую запись
                    cursor.execute("""
                        UPDATE maintenance 
                        SET is_active = %s, start_time = %s, end_time = %s, message = %s, updated_at = CURRENT_TIMESTAMP
                        WHERE game_id = %s
                    """, (is_active, start_date, end_date, content, game_id))
                else:
                    # Создаем новую запись
                    cursor.execute("""
                        INSERT INTO maintenance (game_id, is_active, start_time, end_time, message, created_at, updated_at)
                        VALUES (%s, %s, %s, %s, %s, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
                    """, (game_id, is_active, start_date, end_date, content))
            
            connection.commit()
            flash('Новость успешно обновлена', 'success')
            return redirect(url_for('game_detail', game_id=news[1]))
        
        # Получаем список игр для выпадающего списка
        cursor.execute("SELECT id, name FROM games ORDER BY name")
        games = cursor.fetchall()
        
        return render_template('admin/edit_news.html', news=news, games=games)
    
    except Exception as e:
        connection.rollback()
        flash(f'Ошибка: {str(e)}', 'error')
        return redirect(url_for('home'))
    
    finally:
        close_db_connection(connection)

@app.route('/admin/delete_news/<int:news_id>/<int:game_id>')
@admin_required
def admin_delete_news(news_id, game_id):
    connection = get_db_connection()
    if not connection:
        flash('Ошибка подключения к базе данных', 'error')
        return redirect(url_for('game_detail', game_id=game_id))
    
    try:
        cursor = connection.cursor()
        
        # Получаем тип новости перед удалением
        cursor.execute("SELECT news_type FROM news WHERE id = %s", (news_id,))
        news_type = cursor.fetchone()
        
        # Удаляем новость
        cursor.execute("DELETE FROM news WHERE id = %s", (news_id,))
        
        # Если это было техническое обслуживание, деактивируем его в таблице maintenance
        if news_type and news_type[0] == 'maintenance':
            cursor.execute("""
                UPDATE maintenance 
                SET is_active = FALSE, updated_at = CURRENT_TIMESTAMP
                WHERE game_id = %s
            """, (game_id,))
        
        connection.commit()
        flash('Новость успешно удалена', 'success')
    
    except Exception as e:
        connection.rollback()
        flash(f'Ошибка при удалении новости: {e}', 'error')
    
    finally:
        close_db_connection(connection)
    
    return redirect(url_for('game_detail', game_id=game_id))

@app.route('/admin/update_maintenance/<int:game_id>', methods=['POST'])
@admin_required
def admin_update_maintenance(game_id):
    if request.method == 'POST':
        message = request.form.get('message')
        start_time = request.form.get('start_time') or None
        end_time = request.form.get('end_time') or None
        
        connection = get_db_connection()
        if not connection:
            flash('Ошибка подключения к базе данных', 'error')
            return redirect(url_for('game_detail', game_id=game_id))
        
        try:
            cursor = connection.cursor()
            
            # Проверяем, существует ли запись о техническом обслуживании
            cursor.execute("SELECT id FROM maintenance WHERE game_id = %s", (game_id,))
            maintenance_id = cursor.fetchone()
            
            if maintenance_id:
                # Обновляем существующую запись
                cursor.execute("""
                    UPDATE maintenance 
                    SET is_active = %s, start_time = %s, end_time = %s, message = %s, updated_at = CURRENT_TIMESTAMP
                    WHERE game_id = %s
                """, (is_active, start_time, end_time, message, game_id))
            else:
                # Создаем новую запись
                cursor.execute("""
                    INSERT INTO maintenance (game_id, is_active, start_time, end_time, message, created_at, updated_at)
                    VALUES (%s, TRUE, %s, %s, %s, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
                """, (game_id, is_active, start_time, end_time, message))
            
            # Также создаем или обновляем новость типа 'maintenance'
            cursor.execute("""
                SELECT id FROM news 
                WHERE game_id = %s AND news_type = 'maintenance' AND is_active = TRUE
                ORDER BY created_at DESC LIMIT 1
            """, (game_id,))
            news_id = cursor.fetchone()
            
            if news_id:
                # Обновляем существующую новость
                cursor.execute("""
                    UPDATE news 
                    SET title = 'Техническое обслуживание', content = %s, 
                        start_date = %s, end_date = %s, updated_at = CURRENT_TIMESTAMP
                    WHERE id = %s
                """, (message, start_time, end_time, news_id[0]))
            else:
                # Создаем новую новость
                cursor.execute("""
                    INSERT INTO news (game_id, news_type, title, content, start_date, end_date, created_at, updated_at)
                    VALUES (%s, 'maintenance', 'Техническое обслуживание', %s, %s, %s, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
                """, (game_id, message, start_time, end_time))
            
            connection.commit()
            flash('Информация о техническом обслуживании обновлена', 'success')
        
        except Exception as e:
            connection.rollback()
            print(f"Ошибка при обновлении технического обслуживания: {e}")
            flash(f'Ошибка при обновлении технического обслуживания: {e}', 'error')
        
        finally:
            close_db_connection(connection)
        
    return redirect(url_for('game_detail', game_id=game_id))

# Добавьте эту функцию для создания статических файлов для GitHub Pages
@app.route('/generate_static_site')
@admin_required
def generate_static_site():
    # Создаем директорию для статических файлов
    static_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'docs')
    if os.path.exists(static_dir):
        shutil.rmtree(static_dir)
    os.makedirs(static_dir)
    
    # Копируем все статические файлы
    static_source = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'static')
    static_dest = os.path.join(static_dir, 'static')
    shutil.copytree(static_source, static_dest)
    
    # Создаем index.html
    with open(os.path.join(static_dir, 'index.html'), 'w', encoding='utf-8') as f:
        # Получаем данные для страницы игры
        connection = get_db_connection()
        cursor = connection.cursor()
        
        # Получаем данные об игре
        cursor.execute("SELECT name, description FROM games WHERE id = %s", (1,))
        game_data = cursor.fetchone()
        
        # Получаем классы
        cursor.execute("SELECT id, name, description, image_path FROM game_classes")
        classes_data = cursor.fetchall()
        
        # Преобразование в список словарей
        classes = []
        for class_data in classes_data:
            classes.append({
                'id': class_data[0],
                'name': class_data[1],
                'description': class_data[2],
                'image_path': class_data[3]
            })
        
        # Получаем промокоды
        cursor.execute("""
            SELECT code, description, is_active, 
                   (end_date IS NOT NULL AND end_date <= CURRENT_TIMESTAMP) as expired
            FROM promo_codes 
            WHERE code IS NOT NULL AND code != ''
            ORDER BY is_active DESC, created_at DESC
            LIMIT 10
        """)
        promo_codes = cursor.fetchall()
        
        # Получаем новости
        cursor.execute("""
            SELECT id, news_type, title, content, start_date, end_date
            FROM news
            WHERE game_id = %s AND title IS NOT NULL AND content IS NOT NULL AND title != '' AND content != ''
            ORDER BY created_at DESC
            LIMIT 10
        """, (1,))
        news = cursor.fetchall()
        
        close_db_connection(connection)
        
        # Рендерим шаблон
        content = render_template('game_detail.html', 
                                 game_data=game_data, 
                                 classes=classes, 
                                 promo_codes=promo_codes,
                                 game_id=1,
                                 maintenance_info=None,
                                 news=news,
                                 is_guest=True,
                                 current_theme='dark')
        
        f.write(content)
    
    # Создаем файл .nojekyll для GitHub Pages
    with open(os.path.join(static_dir, '.nojekyll'), 'w') as f:
        f.write('')
    
    return "Статический сайт успешно сгенерирован в директории 'docs'"

# Добавьте новый маршрут для статических файлов
@app.route('/static/<path:path>')
def serve_static(path):
    return send_from_directory('static', path)

def initialize_database(app):
    try:
        connection = get_db_connection()
        if connection:
            create_users_table()
            create_privileges_table()
            create_game_tables()
            create_pg_player_class_table()
            set_user_as_admin(1)
            create_promo_codes_table()
            create_maintenance_table()
            create_news_table()
            connection.close()
        else:
            print("Не удалось подключиться к базе данных при инициализации")
    except Exception as e:
        print(f"Ошибка при инициализации базы данных: {e}")

# Создаем функцию для инициализации приложения
def create_app():
    app = Flask(__name__)
    app.secret_key = os.getenv('SECRET_KEY', 'bew')
    
    # Настройка для загрузки файлов
    UPLOAD_FOLDER = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'static/images')
    app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
    app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024
    
    with app.app_context():
        initialize_database(app)
    
    return app

if __name__ == '__main__':
    app = create_app()
    app.run(host='0.0.0.0', port=int(os.getenv('PORT', 10000)))