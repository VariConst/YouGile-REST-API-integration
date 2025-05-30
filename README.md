# YouGile-REST-API-integration
Скрипт, запрашивающий данные задач через YouGile REST API v2.0 и сохраняющий их в csv-файл. Выполнено для заказа на FL - см. ссылку на портфолио https://www.fl.ru/user/krylovconst/portfolio/7943130/

Скрипт запрашивает все необходимые данные доски, колонок, задач и стикеров с помощью API https://ru.yougile.com/api-v2#/ , формирует и сохраняет всё в нужном виде в csv-файл. При первом запуске происходит полная выгрузка данных задач, при повторном - только данных задач с дедлайном < 2 месяцев, которые обновляются или добавляются к данным старых задач в сохранённом csv-файле.

Для получения `idTaskProject` задач, имеющих вид "АБ-1234", отображаемых в самом приложении YouGile, приходится запрашивать каждую задачу по одной, поскольку при запросе всех задач эти Id не приходят с ответом, поэтому выгрузка большого количества задач занимает некоторое время. При этом приходится иметь дело с HTTP ответом сервера 429 "Too Many Requests", что также замедляет выгрузку задач.

Также оказалось, что помимо стикеров, получаемых по запросу `/api-v2/string-stickers`, есть ещё стикеры доски `custom`, для которых можно получить только Id этих стикеров по запросу `/api-v2/boards/{id}` (`stickers -> custom`). Чтобы добавить данные этих стикеров в csv-файл с корректными заголовками типа "Стоимость заказа", пришлось вычислить, какие Id каким названиям стикеров соответствуют и захаркодить их в скрипте.

При работе с задачами заказчика при первом запуске скрипт выгрузил данные ~2300 задач за ~25 минут, при повторном запуске скрипт выгрузил и обновил данные ~600 задач с дедлайном < 2 месяцев за ~6 минут.

<img width="640" alt="01_YouGile_API_console_log_start" src="https://github.com/user-attachments/assets/e373d9bf-83f2-4384-89b0-a132d2b29672" />
<img width="574" alt="02_YouGile_API_console_log_tasks" src="https://github.com/user-attachments/assets/288cce98-46dd-4947-a2da-25c541daae78" />
<img width="899" alt="03_YouGile_API_result_csv" src="https://github.com/user-attachments/assets/f3b71e81-c915-4ed5-894d-64917f9830d1" />
