<div align="center">

<img src="../../assets/logo.svg" alt="AEC Model Bridge logo: an isometric model cube with a bridge arch" height="120">

[English](../../README.md) | [简体中文](README.zh-CN.md) | [Español](README.es.md) | [हिन्दी](README.hi.md) | [العربية](README.ar.md) | [Português (BR)](README.pt-BR.md) | **Русский** | [日本語](README.ja.md) | [Deutsch](README.de.md) | [Français](README.fr.md) | [Bahasa Indonesia](README.id.md) | [Türkçe](README.tr.md) | [한국어](README.ko.md) | [Tiếng Việt](README.vi.md) | [Italiano](README.it.md) | [Polski](README.pl.md) | [繁體中文](README.zh-TW.md)

> Этот перевод выполнен с помощью ИИ. Основным источником остаётся английский [README](../../README.md); исправления приветствуются через pull request (см. [CONTRIBUTING.md](../../CONTRIBUTING.md)).

**Задавайте ИИ вопросы об открытой модели Revit. По умолчанию ничего не изменится, пока вы не подтвердите.**

Открытый MCP-сервер и нативный плагин для Revit 2024 – 2027. Работает с Claude, Codex и другими MCP-клиентами.

[![CI](https://img.shields.io/github/actions/workflow/status/Sam-AEC/aec-model-bridge/ci.yml?branch=main&style=flat-square&label=CI)](https://github.com/Sam-AEC/aec-model-bridge/actions/workflows/ci.yml)
[![Release](https://img.shields.io/github/v/release/Sam-AEC/aec-model-bridge?style=flat-square&color=0F766E)](https://github.com/Sam-AEC/aec-model-bridge/releases/latest)
[![Revit](https://img.shields.io/badge/Revit-2024--2027-0696D7?style=flat-square)](#поддерживаемые-версии-revit)
[![License](https://img.shields.io/badge/license-GPL--3.0%20%2B%20commercial-2563EB?style=flat-square)](../../LICENSING.md)

[Начало работы](#быстрый-старт) | [Примеры рабочих процессов](#примеры-рабочих-процессов) | [Инструменты](../tools-generated.md) | [Документация](#документация) | [Скачать](https://github.com/Sam-AEC/aec-model-bridge/releases/latest)

</div>

<p align="center">
  <img src="../images/readme/demo.gif" alt="Демонстрация: ИИ-ассистент находит 12 дверей без Mark и составляет план. План ждёт в панели Revit, пока вы его не подтвердите, затем значения считываются обратно для проверки. Примерные значения, имитация сессии." width="900">
</p>

Подключите Claude, Codex или другой MCP-клиент к открытой модели Revit. AEC Model Bridge объединяет MCP-сервер на Python и нативный плагин для Revit: инструменты только для чтения сразу изучают модель, а любые изменения модели по умолчанию требуют утверждённого плана. [Как устроено утверждение](#как-работает-утверждение).

В тот же сервер входят проверка IFC, автоматизация Rhino и Grasshopper и интеграция со Speckle. В разделе [Статус интеграций](#другие-интеграции) указано, какие провайдеры уже доступны, а какие ещё в разработке.

## Примеры рабочих процессов

Для BIM-координаторов: проверить качество модели, просмотреть затронутые элементы, утвердить исправление параметров, затем проверить результат и выгрузить отчёт. В примерах используются инструменты из [текущего каталога](../tools-generated.md).

| Процесс | Пример запроса | Используемые инструменты |
| --- | --- | --- |
| Проверка модели | "Покажи активный документ, перечисли предупреждения и найди затронутые элементы." | `revit_get_document_info`, `revit_get_warnings`, `revit_get_elements_by_type` |
| Обновление параметров | "Найди стены на уровне Level 02, покажи значения Comments и предложи пакетное обновление." | `revit_get_elements_by_type`, `revit_get_element_parameters`, `revit_batch_set_parameters` |
| Выпуск чертежей | "Подготовь список листов из этого CSV, затем предложи создать листы и разместить виды." | `revit_batch_create_sheets_from_csv`, `revit_place_viewport_on_sheet` |
| Проверка IFC | "Покажи этажи этого IFC-файла, изучи свойства стен и сообщи о проблемах проверки схемы." | `ifc_get_spatial_structure`, `ifc_get_properties`, `ifc_validate` |

Для первого запуска в Revit попробуйте:

```text
Read the active model's warnings. Group them by description and show the
affected element IDs. Then suggest which issues to investigate first.
```

Затем попробуйте исправить параметр, подставив уровень и значение из вашего проекта:

```text
Find walls on Level 02 and show their current Comments values. Propose setting
Comments to "Coordination reviewed" for the elements I choose. After I approve
the plan in Revit, apply it and read the values back to confirm the result.
```

Для правок ассистент составляет план через `plan_actions`; вы просматриваете его на панели Revit, и только потом `execute_plan` его применяет. Проверка IFC работает без Revit.

Модули QA/QC и отчётов на основе снимков (snapshot) требуют совместимого сохранённого снимка. Сейчас передача снимка из Revit в модуль требует согласованности имени файла и рабочей области; если не указать `snapshot_id`, могут вернуться сгенерированные демонстрационные данные. Для работы с живой моделью используйте прямые инструменты Revit выше. [Запланированные исправления и демо](../roadmap.md).

## Быстрый старт

**Установка в один клик**

[![Install in VS Code](https://img.shields.io/badge/Install_in-VS_Code-0098FF?style=for-the-badge)](../install-buttons.md#vs-code)
[![Install in Cursor](https://img.shields.io/badge/Install_in-Cursor-111111?style=for-the-badge)](https://cursor.com/en/install-mcp?name=aec-model-bridge&config=eyJjb21tYW5kIjoidXZ4IiwiYXJncyI6WyItLWZyb20iLCJnaXQraHR0cHM6Ly9naXRodWIuY29tL1NhbS1BRUMvYWVjLW1vZGVsLWJyaWRnZSNzdWJkaXJlY3Rvcnk9cGFja2FnZXMvbWNwLXNlcnZlci1yZXZpdCIsImFlYy1tb2RlbC1icmlkZ2UiXSwiZW52Ijp7Ik1DUF9SRVZJVF9NT0RFIjoiYnJpZGdlIn19)
[![Claude Desktop bundle](https://img.shields.io/badge/Claude_Desktop-.mcpb_bundle-D97757?style=for-the-badge)](https://github.com/Sam-AEC/aec-model-bridge/releases/latest)

Кнопкам нужен только [uv](https://docs.astral.sh/uv/getting-started/installation/), другая настройка не требуется: сервер использует `~/Documents/AEC Model Bridge` как рабочую папку, если вы не задали свою. Для Claude Desktop скачайте файл `.mcpb` из последнего релиза и откройте его. Для работы с живым Revit по-прежнему нужны Revit и [плагин](#установка-плагина-revit); режиму mock ничего не нужно.

**Ручная настройка**

Для автоматизации живого Revit нужны Windows, лицензионный Revit 2024–2027, Python 3.11 или новее, [uv](https://docs.astral.sh/uv/getting-started/installation/) и плагин Revit ([шаги установки](#установка-плагина-revit)). Затем добавьте это в `claude_desktop_config.json` (Codex, Cursor и VS Code используют те же значения; две переменные с каталогами необязательны, по умолчанию берётся рабочая папка, указанная выше):

```json
{
  "mcpServers": {
    "aec-model-bridge": {
      "command": "uvx",
      "args": [
        "--from",
        "git+https://github.com/Sam-AEC/aec-model-bridge#subdirectory=packages/mcp-server-revit",
        "aec-model-bridge"
      ],
      "env": {
        "MCP_REVIT_MODE": "bridge",
        "MCP_REVIT_WORKSPACE_DIR": "C:\\RevitProjects",
        "MCP_REVIT_ALLOWED_DIRECTORIES": "C:\\RevitProjects"
      }
    }
  }
}
```

Хотите сначала посмотреть инструменты без Revit? Задайте `"MCP_REVIT_MODE": "mock"`. Сервер запустится где угодно, покажет все инструменты со схемами и будет возвращать готовые ответы, не трогая модель. `Dockerfile` для такого же режима mock лежит в корне репозитория (`docker build -t aec-model-bridge .`, затем `docker run -i --rm aec-model-bridge`).

Используете VS Code? [Исходный код расширения и шаги локальной установки](../../extensions/vscode/README.md) регистрируют MCP-сервер и показывают состояние подключения к Revit. В Marketplace расширение не опубликовано.

### Инструменты вкратце

| Область | Инструменты | Что делают |
| --- | --- | --- |
| Revit | 103 | Чтение модели, создание и правка элементов, параметров, видов, листов, спецификаций, экспорт, совместная работа |
| Утверждение | 6 | Планирование, проверка, утверждение, выполнение и откат изменений модели |
| Модули | 34 | Анализ снимков, таблицы параметров, проверки QA/QC, рецепты, отчёты, выборки |
| Rhino и Grasshopper | 19 | Геометрия, слои, материалы, булевы операции |
| Speckle | 17 | Проекты, модели, версии, отправка и получение |
| Navisworks | 15 | Дерево модели, точки обзора, проверка коллизий (в разработке) |
| IFC | 7 | Чтение IFC-файлов без Revit: структура, свойства, проверка |
| Граф, снимки, экспорт, задания | 18 | Аудит семантического графа, сравнение снимков, экспорт в SQLite, фоновые задания |

В конфигурации по умолчанию доступно 219 инструментов (подсчитано на текущем сервере в режиме mock). Инструменты Autodesk Data появляются, когда настроены учётные данные APS. В [справочнике инструментов](../tools-generated.md) перечислены все инструменты. У каждого инструмента есть аннотации MCP (`readOnlyHint`, `destructiveHint`, `idempotentHint`, `openWorldHint`), по которым клиенты отличают чтение от записи.

### Расширенная автоматизация Revit

Помимо запросов к модели и обновления параметров, инструменты Revit создают строительные элементы, виды, листы, спецификации, марки и размеры, а также экспортируют файлы IFC, DWG, изображения и Navisworks. Поддерживаемые операции и входные данные описаны в [справочнике инструментов](../tools-generated.md).

Для задач, которых нет в каталоге, `revit_invoke_method`, `revit_reflect_get` и `revit_reflect_set` работают с открытыми членами Revit API, а `revit_execute_python` запускает IronPython внутри Revit. У этих инструментов те же права, что и у процесса Revit. Используйте их только с MCP-клиентами и промптами, которым доверяете.

## Как это работает

MCP-клиент обращается к одному Python-хабу. Хаб передаёт каждый вызов провайдеру, которому принадлежит инструмент. Провайдеры для настольных приложений общаются по localhost с небольшим плагином внутри этого приложения.

<p align="center">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="../images/architecture-dark.png">
    <img src="../images/architecture-light.png" alt="Architecture of AEC Model Bridge: an MCP client such as Claude or Codex calls the Python MCP hub, which routes tool calls to the Revit, Rhino, Navisworks, IFC and Speckle providers. The Revit and Rhino providers talk to add-ins over localhost HTTP, the IFC provider reads IFC files with IfcOpenShell, and Navisworks is still in progress." width="900">
  </picture>
</p>

<sub>Исходник диаграммы: [architecture.mmd](../diagrams/architecture.mmd). Пересоздать изображения можно командой `python scripts/render_diagrams.py`.</sub>

Бирюзовые блоки работают уже сейчас. Янтарные блоки с пунктиром ещё в разработке. Индиго обозначает данные и внешние сервисы.

### Как работает утверждение

Хаб останавливает любой вызов инструмента, меняющий модель, если с ним не передан утверждённый план. Режим по умолчанию — `required`. ИИ предлагает план, вы просматриваете его на боковой панели Revit, а плагин выполняет его в основном потоке Revit в именованной транзакции.

<p align="center">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="https://raw.githubusercontent.com/Sam-AEC/aec-model-bridge/main/docs/images/readme/readme-workflow-dark.png">
    <img src="https://raw.githubusercontent.com/Sam-AEC/aec-model-bridge/main/docs/images/readme/readme-workflow-light.png" alt="Inspect, Propose, Approve, Verify. Four steps: inspect finds an empty Mark, propose drafts a change, approve is a human decision, verify reads the value back. Example values are illustrative." width="900">
  </picture>
</p>

<p align="center">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="../images/approval-flow-dark.png">
    <img src="../images/approval-flow-light.png" alt="Approval flow: the AI assistant proposes a plan, the MCP hub and ApprovalGate show it in the Revit side panel, and only after you approve does execute_plan forward the commands to the Revit add-in, which runs them in one named transaction. If you reject or never approve, the call is blocked and the model stays untouched." width="900">
  </picture>
</p>

<sub>Исходник диаграммы: [approval-flow.mmd](../diagrams/approval-flow.mmd). Пересоздать изображения можно командой `python scripts/render_diagrams.py`.</sub>

Если утверждённый план позже оказался ошибочным, `rollback_plan` отменяет его. Откат использует «Отмену» Revit в том же сеансе или обратные значения параметров. Операции, которые нельзя отменить, например запись файлов, запрашивают повторное подтверждение. Жизненный цикл описан в [ADR 0008](../0008-approval-gate-lifecycle.md).

Для конвейеров без участия человека можно задать `MCP_REVIT_APPROVAL_MODE=auto`. Это отключает проверку человеком, поэтому используйте режим только в контролируемой среде.

## Поддерживаемые версии Revit

| Версия Revit | Целевая платформа плагина | Средства сборки |
|---|---|---|
| 2024 | .NET Framework 4.8 | .NET 8 SDK и пакет разработчика .NET Framework 4.8 |
| 2025 | .NET 8 for Windows | .NET 8 SDK |
| 2026 | .NET 8 for Windows | .NET 8 SDK |
| 2027 | .NET 10 for Windows | .NET 10 SDK |

Также нужны Windows 10 или 11, Python 3.11 или новее и лицензионная установка нужной версии Revit. Режим mock запускает сервер без Revit, что удобно для разработки и тестов.

### Другие интеграции

| Интеграция | Статус |
|---|---|
| Revit | Доступно. Нативный плагин на C#. |
| IFC (IfcOpenShell) | Доступно. Читает IFC-файлы без запущенного Revit. |
| Rhino и Grasshopper | Доступно. Подключается к плагину Rhino на `localhost:3004`. |
| Speckle | Доступно. Нужен идентификатор клиента Speckle в вашем окружении. |
| Navisworks Manage | В разработке. Провайдер и его инструменты зарегистрированы. Плагин для Navisworks не закончен. |
| Power BI | В разработке. Провайдер и инструмент есть, но не зарегистрированы в хабе. |
| Excel, Parquet и DuckDB | Запланировано. |

## Установка плагина Revit

**Проще всего (Windows):** скачайте `AECModelBridge-Setup-<version>.exe` из [последнего релиза](https://github.com/Sam-AEC/aec-model-bridge/releases/latest), запустите его двойным щелчком, выберите версии Revit и перезапустите Revit. Он установит плагин, встроенный сервер Python и, если отметить галочку, настройки Claude Desktop и VS Code с резервной копией текущих настроек. Удалить программу можно в параметрах Windows. Шаги ниже нужны для сборки из исходников.

Устанавливаются две части: MCP-сервер на Python и плагин Revit. Для работы с живым Revit нужны обе.

### 1. Установка MCP-сервера

```powershell
git clone https://github.com/Sam-AEC/aec-model-bridge.git
cd aec-model-bridge

py -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e packages/mcp-server-revit
```

### 2. Установка плагина Revit

Укажите версию, соответствующую вашей установке Revit. Если Windows блокирует скачанные скрипты, щёлкните каждый файл `.ps1` правой кнопкой, откройте «Свойства» и перед запуском выберите «Разблокировать».

```powershell
$RevitVersion = Read-Host "Revit year (2024, 2025, 2026, or 2027)"

.\scripts\package.ps1 -RevitVersion $RevitVersion
.\scripts\install.ps1 -RevitVersion $RevitVersion
```

Установщик помещает бинарные файлы для каждой версии в:

```text
C:\ProgramData\AECModelBridge\bin\<year>
```

Манифест плагина устанавливается для текущего пользователя в:

```text
%APPDATA%\Autodesk\Revit\Addins\<year>
```

Добавьте `-AllUsers` к `install.ps1`, чтобы вместо этого установить манифест в `C:\ProgramData\Autodesk\Revit\Addins\<year>`.

Чтобы подготовить бинарные файлы сразу для всех поддерживаемых версий:

```powershell
.\scripts\package.ps1 -RevitVersion All
```

В каждом [релизе на GitHub](https://github.com/Sam-AEC/aec-model-bridge/releases/latest) есть готовый пакет для каждого года Revit, например `aec-model-bridge-revit-2026-<version>.zip`. Распакуйте его и выполните `.\install.ps1 -RevitVersion 2026` вместо сборки из исходников. Установщик Windows с запуском двойным щелчком собирается скриптом `scripts/build-installer.ps1` с помощью Inno Setup. Полное руководство с разбором неполадок — в [docs/install.md](../install.md).

## Подключение Claude Desktop к Revit

Добавьте сервер в конфигурацию MCP-клиента. В Claude Desktop это раздел `mcpServers` файла `claude_desktop_config.json`. Codex, Cursor, VS Code и другие MCP-клиенты используют те же значения `command`, `args` и `env` в своём формате конфигурации.

Используйте исполняемый файл Python из вашего виртуального окружения и выберите рабочую папку, к которой серверу разрешён доступ:

```json
{
  "mcpServers": {
    "aec-model-bridge": {
      "command": "C:\\path\\to\\aec-model-bridge\\.venv\\Scripts\\python.exe",
      "args": ["-m", "revit_mcp_server.mcp_server"],
      "env": {
        "MCP_REVIT_MODE": "bridge",
        "MCP_REVIT_WORKSPACE_DIR": "C:\\RevitProjects",
        "MCP_REVIT_ALLOWED_DIRECTORIES": "C:\\RevitProjects"
      }
    },
    "aec-model-bridge-revit-2026": {
      "command": "C:\\path\\to\\aec-model-bridge\\.venv\\Scripts\\python.exe",
      "args": ["-m", "revit_mcp_server.mcp_server"],
      "env": {
        "MCP_REVIT_MODE": "bridge",
        "MCP_REVIT_HOST_VERSION": "2026",
        "MCP_REVIT_WORKSPACE_DIR": "C:\\RevitProjects",
        "MCP_REVIT_ALLOWED_DIRECTORIES": "C:\\RevitProjects"
      }
    }
  }
}
```

Если не указывать `MCP_REVIT_HOST_VERSION`, будет выбран самый новый из открытых экземпляров Revit. Задайте год, например `2024` или `2026`, чтобы закрепить запись клиента за этой версией Revit. `MCP_REVIT_BRIDGE_URL` переопределяет адрес в сложных конфигурациях.

Пользователи VS Code могут взять за основу [`.vscode/mcp.json`](../../.vscode/mcp.json). Пользователи Hermes Desktop могут взять [`docs/examples/hermes-desktop.json`](../examples/hermes-desktop.json), заменив путь к Python-заглушке. Клиенты с поддержкой MCP Bundles могут установить файл `.mcpb` из [последнего релиза](https://github.com/Sam-AEC/aec-model-bridge/releases/latest). Плагин Revit по-прежнему обязателен, потому что сервер обращается к запущенному настольному приложению.

### Проверка подключения

Перезапустите Revit после установки плагина, откройте модель и выполните:

```powershell
$registry = Get-ChildItem "$env:LOCALAPPDATA\AECModelBridge\registry\revit-*.json" | Select-Object -First 1
$switch = Get-Content $registry.FullName -Raw | ConvertFrom-Json
Invoke-RestMethod "$($switch.endpoint)/health"
```

В ответе должны быть `healthy` и версия запущенного Revit. В Revit найдите вкладку ленты `AEC Bridge`. На панели Workflows есть Open Panel, Health Check, Pending Actions и Reports. На панели Tools — Config, Help и About.

## Безопасность

- Мост Revit слушает только localhost.
- Сервер читает и записывает данные только в папках из `MCP_REVIT_ALLOWED_DIRECTORIES`.
- Инструментам, изменяющим модель, нужен утверждённый план, если вы не отключили утверждение.
- Вызовы инструментов записываются в журнал аудита, секреты скрываются.

Подробности — в [docs/security.md](../security.md). О найденной уязвимости сообщайте по правилам из [SECURITY.md](../../SECURITY.md).

## Вопросы и ответы

### Что такое MCP-сервер для Revit?

Model Context Protocol (MCP) — открытый стандарт, позволяющий ИИ-ассистентам вызывать инструменты в другом ПО. MCP-сервер для Revit предоставляет операции Revit в виде инструментов. Ассистент выбирает инструменты, а плагин выполняет их внутри Revit.

### С какими ИИ-ассистентами это работает?

С любым MCP-клиентом, который умеет запускать локальный stdio-сервер. Мы описываем Claude Desktop, VS Code с GitHub Copilot и клиенты, читающие стандартную конфигурацию `mcpServers`. Чат на панели может также использовать ключ Anthropic API или консольные утилиты `claude` и `codex`, если они установлены. См. [ADR 0012](../0012-native-agent-chat-backend.md).

### Может ли ИИ изменить мою модель без спроса?

В режиме по умолчанию нет. Инструменты, меняющие модель, блокируются, пока план не утверждён на панели Revit. Инструменты только для чтения работают без утверждения. Если задать `MCP_REVIT_APPROVAL_MODE=auto`, утверждение пропускается.

### Отправляется ли моя модель в облако?

Сервер и плагин работают на вашем компьютере, а мост слушает только localhost. Что увидит ИИ-ассистент, зависит от используемого клиента: результаты инструментов отправляются провайдеру модели этого клиента. Облачные провайдеры, такие как Speckle, работают только тогда, когда вы их настроили и вызвали их инструменты.

### Работает ли это с IFC-файлами без Revit?

Да. Провайдер IFC читает файлы через IfcOpenShell. Он возвращает метаданные файла, пространственную структуру, свойства элементов и габаритные рамки, выполняет запросы по классу, GUID, имени или свойству и проверяет схему. Редактировать IFC-файлы он не умеет.

### Можно ли использовать без установленного Revit?

Сервер можно запускать в режиме mock для разработки и тестов. Для работы с живой моделью нужны Revit 2024–2027 и плагин.

## Релизы и версии

AEC Model Bridge следует семантическому версионированию. Релизы помечаются тегами `vX.Y.Z` на GitHub, а номер версии хранится в файле `VERSION` в корне. Процесс выпуска описан в [docs/versioning.md](../versioning.md), изменения каждой версии — в [CHANGELOG.md](../../CHANGELOG.md).

## Разработка

```powershell
# Python tests
python -m pytest packages/mcp-server-revit/tests

# Build one Revit version, for example 2026
.\scripts\build-addin.ps1 -RevitVersion 2026 -Configuration Release

# Build all supported versions
.\scripts\package.ps1 -RevitVersion All
```

CI собирает Python-сервер и целевые сборки плагина для Revit 2024–2027. Перед созданием pull request прочитайте [CONTRIBUTING.md](../../CONTRIBUTING.md).

## Документация

- [Руководство по установке](../install.md)
- [Справочник инструментов](../tools-generated.md)
- [Архитектура](../0001-multi-provider-architecture.md)
- [Справочник по конфигурации](../configuration-reference.md)
- [Безопасность](../security.md)
- [MCP-клиенты и реестр](../marketplaces.md)
- [Версионирование и релизы](../versioning.md)
- [Вся документация](../README.md)
- [Участие в проекте](../../CONTRIBUTING.md) и [Кодекс поведения](../../CODE_OF_CONDUCT.md)
- [Участники](../../CONTRIBUTORS.md)

## Проект и лицензия

Поддерживает [A. Sam Mohammad](https://github.com/Sam-AEC).
[LinkedIn](https://www.linkedin.com/in/a-sam-mohammad-92790416b) |
[Issues](https://github.com/Sam-AEC/aec-model-bridge/issues)

[GPL-3.0-or-later с исключением Revit Linking Exception или коммерческая лицензия](../../LICENSING.md).
