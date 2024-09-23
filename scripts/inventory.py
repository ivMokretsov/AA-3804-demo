#!/usr/bin/env python3
import os
import sys
import requests
import json
import urllib3

# Отключаем предупреждения о небезопасном HTTPS
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# Получение переменных из окружения
api_token = os.getenv('AWX_API_TOKEN')
template_id = os.getenv('AWX_TEMPLATE_ID')

# Название инвентори файла
inventory_file = 'local_inventory.ini'

# Путь к локальному INI-файлу
inventory_file_path = os.path.join(os.path.dirname(__file__), inventory_file)

# Обработка ошибок, если переменные не заданы
if not api_token:
    raise ValueError("API Token не задан через переменную окружения 'AWX_API_TOKEN'!")

def extract_ansible_vars(variables):
    """Извлечение ansible_host и ansible_user из переменных"""
    ansible_host = None
    ansible_user = None

    try:
        var_data = json.loads(variables)
        ansible_host = var_data.get('ansible_host', None)
        ansible_user = var_data.get('ansible_user', None)
    except json.JSONDecodeError:
        # Если переменные не в формате JSON, пробуем как YAML/текст
        for line in variables.splitlines():
            if "ansible_host" in line:
                ansible_host = line.split(":")[1].strip()
            if "ansible_user" in line:
                ansible_user = line.split(":")[1].strip()

    return ansible_host, ansible_user


def fetch_host_details(host_id, api_token):
    """Получение ansible_host и ansible_user для конкретного хоста"""
    host_url = f"https://10.177.185.87/api/v2/hosts/{host_id}/"
    headers = {"Authorization": f"Bearer {api_token}"}
    
    try:
        response = requests.get(host_url, headers=headers, verify=False)
        response.raise_for_status()  # Поднимает исключение при неудачном статусе запроса
        host_data = response.json()

        variables = host_data.get('variables', '')
        return extract_ansible_vars(variables)
    except requests.RequestException as e:
        sys.stderr.write(f"Ошибка при получении данных хоста {host_id}: {e}\n")
        return None, None


def load_inventory_from_file(file_path):
    """Загрузка инвентаря из локального INI-файла с хостами и переменными"""
    inventory = {
        "_meta": {"hostvars": {}},
        "all": {"hosts": []}
    }

    try:
        with open(file_path, 'r') as file:
            for line in file:
                line = line.strip()
                if not line or line.startswith('['):  # Пропускаем заголовки и пустые строки
                    continue

                parts = line.split()
                host_name = parts[0]
                inventory["all"]["hosts"].append(host_name)
                inventory["_meta"]["hostvars"][host_name] = {}

                # Обрабатываем переменные для хоста
                for var in parts[1:]:
                    if "=" in var:
                        key, value = var.split("=", 1)
                        inventory["_meta"]["hostvars"][host_name][key] = value

    except FileNotFoundError:
        sys.stderr.write(f"Файл инвентаря '{file_path}' не найден\n")
    except Exception as e:
        sys.stderr.write(f"Ошибка при чтении файла инвентаря: {e}\n")

    return inventory


def fetch_inventory_from_awx(api_token, template_id):
    """Получение информации о последней джобе и хостах с неудачным завершением"""
    api_url = f"https://10.177.185.87/api/v2/job_templates/{template_id}/"
    headers = {"Authorization": f"Bearer {api_token}"}

    try:
        response = requests.get(api_url, headers=headers, verify=False)
        response.raise_for_status()
        template_data = response.json()

        if "last_job" not in template_data.get('related', {}):
            sys.stderr.write("Последняя джоба не найдена. Используется локальный инвентарь.\n")
            return load_inventory_from_file(inventory_file_path)

        last_job_url = template_data['related']['last_job']
        last_job_id = last_job_url.split('/')[-2]

        # Получаем информацию о хостах
        job_host_summaries_url = f"https://10.177.185.87/api/v2/jobs/{last_job_id}/job_host_summaries/"
        job_host_summaries_response = requests.get(job_host_summaries_url, headers=headers, verify=False)
        job_host_summaries_response.raise_for_status()
        job_host_summaries_data = job_host_summaries_response.json()

        inventory = {
            "_meta": {"hostvars": {}},
            "all": {"hosts": []}
        }

        for host_summary in job_host_summaries_data['results']:
            if host_summary.get('failed'):  # Только хосты с неудачными заданиями
                host_name = host_summary['summary_fields']['host']['name']
                host_id = host_summary['summary_fields']['host']['id']
                ansible_host, ansible_user = fetch_host_details(host_id, api_token)

                inventory["_meta"]["hostvars"][host_name] = {
                    "ansible_host": ansible_host,
                    "ansible_user": ansible_user
                }

                inventory["all"]["hosts"].append(host_name)

        return inventory
    except requests.RequestException as e:
        sys.stderr.write(f"Ошибка при получении инвентаря из AWX: {e}\n")
        return {}


def fetch_inventory():
    """Формирование инвентаря в зависимости от состояния"""
    if not template_id:
        sys.stderr.write("Template ID не задан. Используется локальный инвентарь.\n")
        return load_inventory_from_file(inventory_file_path)
    else:
        return fetch_inventory_from_awx(api_token, template_id)


def main():
    try:
        if len(sys.argv) == 2 and sys.argv[1] == '--list':
            inventory = fetch_inventory()
            print(json.dumps(inventory, indent=4))
        elif len(sys.argv) == 3 and sys.argv[1] == '--host':
            print(json.dumps({}, indent=4))
        else:
            print(json.dumps({}, indent=4))
    except Exception as e:
        sys.stderr.write(f"Ошибка выполнения: {e}\n")
        sys.exit(1)


if __name__ == "__main__":
    main()
