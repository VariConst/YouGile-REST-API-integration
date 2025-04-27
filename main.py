import os
import requests
import csv
import json
from time import sleep

# NOTE(const): Чтобы для метода dt.datetime.fromtimestamp() можно было передать dt.UTC
import datetime as dt

# 🔐 Конфигурация
API_KEY    = "<Добавьте ваш ключ API сюда>"
BOARD_ID   = "11111111-1111-1111-1111-111111111111"
#COLUMN_ID  = "22222222-2222-2222-2222-222222222222" # конкретная колонка
BASE_URL   = "https://ru.yougile.com/api-v2"
HEADERS    = {
    "Authorization": f"Bearer {API_KEY}",
    "Content-Type": "application/json"
}

CSV_TASK_ID_HEADER = "task_id"

CSV_FILE_PATH = os.path.join(r".", "yougile_tasks.csv")

# NOTE(const): id стикеров (т.е. групп стикеров), которые не вытягиваются по api
HARDCODED_STICKERS = {
    "33333333-3333-3333-3333-333333333333": "Стикер 1",
    "44444444-4444-4444-4444-444444444444": "Стикер 2",
    "55555555-5555-5555-5555-555555555555": "Стикер 3",
}

# NOTE(const): Для колонок из этого списка полные данные будут выгружаться только для тех задач, у
# которых дедлайн меньше указанного срока
COLUMNS_TO_CHECK_DEADLINE_IDS = [
    "66666666-6666-6666-6666-666666666666", # "Готово"
]

# NOTE(const): Колонки с id из этого списка вообще исключаются из запросов
EXCLUDE_COLUMNS_WITH_IDS = [
    "77777777-7777-7777-7777-777777777777", # "Проблема"
]

def log(msg):
    print(f"📝 {msg}")

def get_datetime(task_timestamp):
    """
    NOTE(const): Python выдавал DeprecationWarning на
        datetime.datetime.utcfromtimestamp(ts / 1000)
    и рекомендовал использовать
        datetime.datetime.fromtimestamp(timestamp, datetime.UTC)
    """
    return dt.datetime.fromtimestamp(task_timestamp / 1000, dt.UTC)

def format_timestamp(task_timestamp):
    """
    NOTE(const): Если у задачи нет дедлайна, то помечаем task_timestamp как None - в этом случае
    этот метод возвращает пустую строку ""
    """
    if task_timestamp is None:
        return ""
    return get_datetime(task_timestamp).strftime("%d.%m.%Y %H:%M")

def save_to_csv(file_path, rows):
    os.makedirs(os.path.dirname(file_path), exist_ok=True)
    log(f"Запись в CSV: {file_path}")
    with open(file_path, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.writer(f)
        writer.writerows(rows)

def read_csv(file_path):
    if not os.path.isfile(file_path):
        log(f'❌ CSV файл не найден: "{file_path}"')
        return []

    rows = []
    log(f"Чтение CSV: {file_path}")
    with open(file_path, "r", newline="", encoding="utf-8-sig") as f:
        reader = csv.reader(f)
        rows.extend(reader)

    return rows

# NOTE(const): Возвращает вторым значением True/False, означающий успех/провал загрузки данных
def _fetch_data(url, retries=5, backoff=2):
    log(f"Запрашиваем URL: {url}")
    for i in range(retries):
        r = requests.get(url, headers=HEADERS)
        if r.status_code == 429:
            wait = int(r.headers.get("Retry-After", backoff))
            log(f"⚠️ 429 — спим {wait}s (попытка {i+1}/{retries})")
            sleep(wait)
            continue
        try:
            r.raise_for_status()
            return r.json(), True
        except Exception as e:
            log(f"❌ Ошибка при запросе {url}: {e}")
            break
    log(f"❌ Не удалось получить данные")
    return {}, False

# TODO(const): Сделать так, чтобы метод сам мог понять, есть ли уже query в переданном url или нет?
def _fetch_data_page(url_with_query, limit=1000, offset=0):
    """
    NOTE(const): url_with_query - это url, в котором уже есть в конце query `?...` -
    чтобы можно было добавить к ней f"limit={limit}&offset={offset}"
    Возвращает список content и True/False, означающий, есть ли ещё данные после данного page
    """
    final_url = f"{url_with_query}&limit={limit}&offset={offset}"
    data, success = _fetch_data(final_url)

    # NOTE(const): Запрашиваем данные page до тех пор, пока не будет успех
    while not success:
        wait = 10
        log(f"Ждём {wait}s и вновь пытаемся загрузить данные...")
        sleep(wait)
        data, success = _fetch_data(final_url)

    return data.get("content", []), data.get("paging", {}).get("next")

# TODO(const): См. комментарий у _fetch_data_page выше
def _fetch_data_in_pages(url_with_query, limit=1000, offset=0):
    content = []
    while True:
        chunk, has_next_page = _fetch_data_page(url_with_query, limit=limit, offset=offset)
        if not chunk:
            break
        content.extend(chunk)
        if not has_next_page:
            break
        offset += limit
    return content

def fetch_columns(boardId):
    log(f'Запрашиваем данные колонок для доски "{boardId}"')
    url = f"{BASE_URL}/columns?boardId={boardId}"
    columns = _fetch_data_in_pages(url)
    log(f"Получено колонок: {len(columns)}")
    return columns

def get_columns_without_checking_deadline_ids(columns):
    result_columns = []
    for column in columns:
        if column.get("id", "") in EXCLUDE_COLUMNS_WITH_IDS:
            log(f'Исключаем из запросов колонку "{column["id"]}" ("{column["title"]}")')
            continue

        if column.get("id") in COLUMNS_TO_CHECK_DEADLINE_IDS:
            log(f'Исключаем колонку "{column["id"]}" ("{column["title"]}") из запросов без проверки дедлайна')
            continue

        result_columns.append(column.get("id"))

    return result_columns

def fetch_tasks(columns_ids):
    log("Начинаем загрузку задач...")
    tasks = []
    for column_id in columns_ids:
        # NOTE(const): В документации указано, что запрос по `/api-v2/tasks` deprecated и что
        # нужно использовать `/api-v2/task-list` вместо этого
        url = f"{BASE_URL}/task-list?columnId={column_id}"

        # NOTE(const): Небольшой набор задач, чтобы удобнее было отлаживать
        #tasks, _ = _fetch_data_page(url, limit=100, offset=1710)

        tasks.extend(_fetch_data_in_pages(url))

    log(f"Получено задач: {len(tasks)}")
    return tasks

def get_recent_tasks(tasks, deadline_days_offset):
    """
    NOTE(const): Возвращает спискок задач, у которых дедлайн указан позже, чем текущее время
    минус deadline_days_offset дней
    """
    today = dt.datetime.now(dt.UTC)
    today_minus_offset_days = today - dt.timedelta(days=deadline_days_offset)
    recent_tasks = []
    for task in tasks:
        task_id = task.get("id")

        # NOTE(const): Чтобы задачи без дедлайна учитывались при условии "< X месяцев", указываю
        # здесь у них в качестве дедлайна текущее время
        deadline_datetime = today
        if "deadline" in task and "deadline" in task["deadline"]:
            deadline_datetime = get_datetime(task["deadline"]["deadline"])

        if deadline_datetime > today_minus_offset_days:
            recent_tasks.append(task)

    return recent_tasks

# NOTE(const): При запросе всех задач через `/api-v2/task-list` приходит немного меньше данных, чем
# при запросе отдельной задачи через `/api-v2/tasks/{id}` - в частности, только во втором случае мы
# получаем данные для `idTaskCommon` и `idTaskProject`
def fetch_full_task(task_id):
    data, _ = _fetch_data(f"{BASE_URL}/tasks/{task_id}")
    return data

def _try_fetch_full_tasks(tasks_ids):
    """
    NOTE(const): Возвращает список всех загруженных задач и список id всех незагруженных задач,
    чтобы можно было для них повторно сделать запросы
    """
    tasks = []
    missing_tasks_ids = []
    offset = 0
    for idx, task_id in enumerate(tasks_ids, 1):
        task = fetch_full_task(task_id)
        if task == {}:
            missing_tasks_ids.append(task_id)
            continue
        tasks.append(task)
        title = task.get("title", "")
        log(f"[{idx}/{len(tasks_ids)}] ✅ {title}")

    log(f"Получено полных данных задач: {len(tasks)}/{len(tasks_ids)}")
    return tasks, missing_tasks_ids

# TODO(const): Добавить настраиваемое время ожидания wait?
# TODO(const): Ограничить количество повторных вызовов аргументом?
def fetch_full_tasks_by_ids(tasks_ids):
    log(f"Начинаем загрузку полных данных {len(tasks_ids)} задач...")
    full_tasks, missing_tasks_ids = _try_fetch_full_tasks(tasks_ids)

    # NOTE(const): Если какие-то задачи не были загружены методом fetch_full_task() из-за кода 429,
    # то выполняем для них запросы до тех пор, пока не будут получены данные всех задач
    while len(missing_tasks_ids) > 0:
        wait = 10
        log(f"Ждём {wait}s и пытаемся загрузить полные данные оставшихся {len(missing_tasks_ids)} задач...")
        sleep(wait)
        remaining_tasks, missing_tasks_ids = _try_fetch_full_tasks(missing_tasks_ids)
        full_tasks.extend(remaining_tasks)

    log(f"Итого получено полных данных задач: {len(full_tasks)}/{len(tasks_ids)}")
    return full_tasks

def fetch_full_tasks(tasks):
    """
    NOTE(const): Для всех тасков из tasks выгрузить полные данные по одному
    """
    return fetch_full_tasks_by_ids([task.get("id") for task in tasks])

def fetch_stickers():
    stickers = []
    log("Начинаем загрузку всех стикеров...")

    # NOTE(const): Добавит в конце "?", чтобы в _fetch_data_in_pages() корректно добавились
    # элементы для limit и offset
    url = f"{BASE_URL}/string-stickers?"

    stickers = _fetch_data_in_pages(url)
    log(f"Загружено групп стикеров: {len(stickers)}")
    return stickers

def get_stickers_groups(stickers):
    groups_names = {}
    groups_values = {}
    values_count = 0
    for group in stickers:
        group_id = group["id"]
        groups_names[group_id] = group.get("name", "")

        values = {}
        states = group.get("states", [])
        for state in states:
            values[state["id"]] = state.get("name", "")

        groups_values[group_id] = values
        values_count += len(values)

    log(f"Всего загружено стикеров: {values_count}")
    return groups_names, groups_values

def get_tasks_csv_rows(tasks, stickers):
    sticker_groups_names, sticker_groups_values = get_stickers_groups(stickers)

    # NOTE(const): Учитываем здесь также стикеры HARDCODED_STICKERS, которые не вытягиваются по API
    all_sticker_groups_names = { **sticker_groups_names, **HARDCODED_STICKERS }

#    for group_id in all_sticker_groups_names:
#        print(f"`{group_id}`, `{all_sticker_groups_names[group_id]}`, {len(sticker_groups_values[group_id])} штук")
#        print(f"`{all_sticker_groups_names[group_id]}`:")
#        group_values = sticker_groups_values[group_id]
#        for value_id in group_values:
#            print(f"`{value_id}`, {group_values[value_id]}")

    sorted_sticker_groups_names = sorted(set(all_sticker_groups_names.values()))

    group_id_for_name = {}
    for group_id in all_sticker_groups_names:
        group_id_for_name[all_sticker_groups_names[group_id]] = group_id

    sorted_stickers_groups_ids = []
    for group_name in sorted_sticker_groups_names:
        sorted_stickers_groups_ids.append(group_id_for_name[group_name])

#    for idx, group_id in enumerate(sorted_stickers_groups_ids):
#        print(f"`{group_id}`, `{sorted_sticker_groups_names[idx]}`")

    task_headers = [CSV_TASK_ID_HEADER, "Название", "Дедлайн", "Проектный ID"]
    #sticker_headers = [f'Стикер "{name}"' for name in sorted_sticker_groups_names]
    sticker_headers = sorted_sticker_groups_names
    all_headers = task_headers + sticker_headers
    rows = []
    rows.append(all_headers)
    for task in tasks:
        task_id = task.get("id")

        deadline_timestamp = None
        if "deadline" in task and "deadline" in task["deadline"]:
            deadline_timestamp = task["deadline"]["deadline"]
        #deadline_timestamp_str = "" if deadline_timestamp is None else str(deadline_timestamp)

        title    = task.get("title", "")
        deadline = format_timestamp(deadline_timestamp)
        proj_id  = task.get("idTaskProject", "")

        row = [task_id, title, deadline, proj_id]

        task_stickers = task.get("stickers", {})

        # NOTE(const): Проверяем, что все указанные в задачах id стикеров учитываются нами через
        # запрос стикеров по API и через HARDCODED_STICKERS
        for task_sticker_id in task_stickers:
            if (task_sticker_id not in sorted_stickers_groups_ids):
                log(f'❌ Стикер с id `{task_sticker_id}` в задаче с id `{task_id}` не найден среди'
                    + ' определённых в скрипте стикеров:\n    `{}`'.format("`,\n    `".join(sorted_stickers_groups_ids)))

        for group_id in sorted_stickers_groups_ids:
            group_values = sticker_groups_values.get(group_id, {})
            value = ""

            # NOTE(const): Если group_values пустой, то скорее всего это стикер из
            # HARDCODED_STICKERS - в этом случае в качестве значения идёт не id состояния, а
            # непосредственно содержимое стикера
            if group_values:
                value_id = task_stickers.get(group_id, "")
                value = group_values.get(value_id, "")
            else:
                value = task_stickers.get(group_id, "")

            row.append(value)

        rows.append(row)

    return rows

def get_tasks_rows_from_file(csv_file_path, task_id_header=CSV_TASK_ID_HEADER):
    csv_rows = read_csv(csv_file_path)
    if not csv_rows:
        log(f'❌ Не найдено данных в CSV файле: "{csv_file_path}"')
        return []
    csv_headers = csv_rows[0]
    if not task_id_header in csv_headers:
        log(f'❌ Не найден заголовок "{task_id_header}" в CSV файле: "{csv_file_path}"')
        return []
    return csv_rows

def are_headers_match(headers1, headers2):
    if len(headers1) == len(headers2):
        for idx in range(len(headers1)):
            if headers1[idx] != headers2[idx]:
                return False
        return True
    return False

def combine_tasks_rows(new_csv_rows, all_old_csv_rows, task_id_header=CSV_TASK_ID_HEADER):
    csv_headers = new_csv_rows[0]
    task_id_idx = csv_headers.index(task_id_header)
    new_tasks_ids = [row[task_id_idx] for row in new_csv_rows[1:]]

    result_rows = new_csv_rows[:]
    used_old_rows_count = 0
    for old_row in all_old_csv_rows[1:]:
        old_task_id = old_row[task_id_idx]
        if not old_task_id in new_tasks_ids:
            result_rows.append(old_row)
            used_old_rows_count += 1

    log(f"Объединяем новые данные для {len(new_tasks_ids)} задач вместе со старыми данными"
        + f" остальных {used_old_rows_count} задач из CSV файла")
    return result_rows

def get_combined_tasks_csv_rows(tasks, stickers, old_csv_rows):
    new_csv_rows = get_tasks_csv_rows(tasks, stickers)

    old_csv_headers = old_csv_rows[0]
    new_csv_headers = new_csv_rows[0]
    if not are_headers_match(old_csv_headers, new_csv_headers):
        log(f'❌ CSV заголовки не совпадают:\n - заголовки в файле: "{old_csv_headers}"\n - новые заголовки: "{new_csv_headers}"')
        return []

    result_rows = combine_tasks_rows(new_csv_rows, old_csv_rows)
    return result_rows

def main():
    # NOTE(const): Тестовая задача "АБ-1234", чтобы определить id стикеров для HARDCODED_STICKERS
    #test_task = fetch_full_task("88888888-8888-8888-8888-888888888888")
    #with open(os.path.join(r".", "test_task.json"), "w", newline="", encoding="utf-8-sig") as f:
    #    json.dump(test_task, f, ensure_ascii=False, indent=4)

    # NOTE(const): Можно запросить данные стикеров для доски, где в качестве значений просто стоит
    # true - но id всех HARDCODED_STICKERS есть в этом списке, а также имеются некоторые другие id
    #board_data, _ = _fetch_data(f"{BASE_URL}/boards/{BOARD_ID}")
    #board_stickers = board_data.get('stickers')
    #with open(os.path.join(r".", "board_stickers.json"), "w", newline="", encoding="utf-8-sig") as f:
    #    json.dump(board_stickers, f, ensure_ascii=False, indent=4)

    log("🚀 Старт выгрузки Yougile...")

    board_columns = fetch_columns(BOARD_ID)

    # NOTE(const): Можно использовать, чтобы загружать задачи только  из колонки "Готово"
    #columns_without_checking_deadline_ids = []
    columns_without_checking_deadline_ids = get_columns_without_checking_deadline_ids(board_columns)

    # NOTE(const): Можно использовать, чтобы загружать задачи только из других колонок без
    # проверки дедлайна, как это нужно делать для задач из колонки "Готово"
    #tasks_to_check_deadline = fetch_tasks([])
    tasks_to_check_deadline = fetch_tasks(COLUMNS_TO_CHECK_DEADLINE_IDS)

    tasks_without_checking_deadline = fetch_tasks(columns_without_checking_deadline_ids)

    stickers = fetch_stickers()

    new_csv_rows = []
    if os.path.isfile(CSV_FILE_PATH):
        log(f'Файл "{CSV_FILE_PATH}" существует -> выгружаем данные задач с дедлайном < 2 месяцев')

        recent_tasks = get_recent_tasks(tasks_to_check_deadline, 60)
        log(f"Обнаружено {len(recent_tasks)} задач с дедлайном меньше 2 месяцев назад")

        tasks_to_update = recent_tasks + tasks_without_checking_deadline

        old_csv_rows = get_tasks_rows_from_file(CSV_FILE_PATH)
        if not old_csv_rows:
            log(f'❌ Ошибка при чтении данных задач из CSV файла "{CSV_FILE_PATH}"')
            exit(1)

        # NOTE(const): Для отладки, чтобы использовались не полностью выгруженные задачи, что
        # намного быстрее
        #new_csv_rows = get_combined_tasks_csv_rows(tasks_to_update, stickers, old_csv_rows)

        full_tasks_to_update = fetch_full_tasks(tasks_to_update)
        new_csv_rows = get_combined_tasks_csv_rows(full_tasks_to_update, stickers, old_csv_rows)
        if not new_csv_rows:
            log(f'❌ Ошибка при попытке объединить данные загруженных задач с данными задач из CSV файла "{CSV_FILE_PATH}"')
            exit(1)

        backup_csv_file_path = f"{CSV_FILE_PATH}.backup"
        log(f'Создаём бэкап файла с названием "{backup_csv_file_path}"')
        save_to_csv(backup_csv_file_path, old_csv_rows)
    else:
        log(f'Файл "{CSV_FILE_PATH}" не существует -> выгружаем данные всех задач')

        # NOTE(const): Если это первый запуск скрипта, то сохраняем данные всех задач без проверки
        # дедлайнов
        tasks_to_save = tasks_to_check_deadline + tasks_without_checking_deadline

        # NOTE(const): Для отладки, чтобы выгрузить не все задачи, а только с дедлайном < 2
        # месяцев, чтобы было побыстрее
        #recent_tasks = get_recent_tasks(tasks_to_check_deadline, 60)
        #full_tasks_to_save = fetch_full_tasks(recent_tasks)

        # NOTE(const): Для отладки, чтобы выгружались не полные данные задач по одной, а общим
        # запросом, что намного быстрее
        #new_csv_rows = get_tasks_csv_rows(tasks_to_save, stickers)

        full_tasks_to_save = fetch_full_tasks(tasks_to_save)
        new_csv_rows = get_tasks_csv_rows(full_tasks_to_save, stickers)

        log(f"Сохраняем данные всех загруженных {len(tasks_to_save)} задач")

    save_to_csv(CSV_FILE_PATH, new_csv_rows)
    log("🎉 Готово! Файл сохранён.")

if __name__ == "__main__":
    main()
