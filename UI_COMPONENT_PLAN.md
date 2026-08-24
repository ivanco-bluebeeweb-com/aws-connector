# AWS Connector — UI component plan

Источники: `Docs/session-notes/UI_COMPONENT_VOCABULARY.md`, `UI_INTERFACE_STANDARD.md`,
`concepts/panels.md`. Основано на `IDEAL_ONBOARDING.md` и `PREPARATION.md` этого приложения.

## 0. Разница с реализацией сейчас

Приложение ещё не реализовано (Фаза 1 discovery/preparation только что
завершена) — этот план описывает целевой интерфейс, который строится
сразу вместе с кодом Яруса 1, а не добавляется после.

## 1. Компоненты

| Экран | Примитивы | Почему именно эти |
|---|---|---|
| Sidebar (left) | `Column`(align="start") + `Text`(имя подключения / IAM ARN) + `Select`(region_switch) + `Divider` + navigation `ListItem`(EC2/S3/RDS/Lambda/IAM/CloudWatch/Cost) + `Button`("App settings") | Без карточек по стандарту. Region-select живёт в сайдбаре, т.к. большинство операций регионально-специфичны (см. IDEAL_ONBOARDING §2.7). |
| Cloud Overview (center, `center_overlay=True`) | `Stats`(EC2 running/stopped, S3 buckets, RDS instances, Lambda errors 24ч) + `Chart`(type="bar", месячные расходы по сервисам — Cost Explorer) | Первый экран после подключения — сразу actionable сводка "облачного здоровья", как требует IDEAL_ONBOARDING §2.4. |
| EC2 Instances | `Select`(region_filter, state_filter: running/stopped) + `DataTable`(instance_id, type, state Badge, region, launch_time; sortable) | Табличный список ресурсов — стандартный паттерн портфеля (см. Home Assistant Entity List). |
| EC2 Instance Detail | Back-button + `KeyValue`(AMI, VPC, subnet, security groups, tags) + `Row`(Button "Stop", Button "Start" — Ярус 3, за confirm-модалкой) | Деструктивные операции — отдельная кнопка с подтверждением, не auto-execute (PREPARATION §4). |
| S3 Buckets | `DataTable`(bucket_name, region, created_at, object_count; sortable) | Простой список — S3 buckets не требуют сложной иерархии на верхнем уровне. |
| S3 Bucket Detail | Back-button + `Breadcrumb`-подобная навигация через `Row`(Text current_prefix) + `DataTable`(key, size, last_modified; поддержка вложенных "папок" через prefix-фильтр) | Object listing внутри bucket навигируется через prefix, аналогично файловой системе. |
| RDS Instances | `DataTable`(db_instance_id, engine, status Badge, region, storage_gb; sortable) | Тот же табличный паттерн. |
| Lambda Functions | `DataTable`(function_name, runtime, last_modified, error_count_24h Badge; sortable) + row action "View Logs" | Ошибки за 24ч — сразу видимый Badge, не нужно открывать CloudWatch отдельно. |
| Lambda Function Detail | Back-button + `KeyValue`(runtime, memory, timeout, handler) + `Code`(последний лог, read-only) + `Button`("Invoke") | `Code` примитив — то, чем показывать сырой лог-вывод. |
| IAM Users/Roles | `Tabs`(Users / Roles / Policies) + `DataTable`(name, created_at, attached_policies_count; sortable) | IAM — три связанных, но разных сущности; `Tabs` разводит их без потери контекста. |
| CloudWatch Alarms | `DataTable`(alarm_name, state Badge: OK/ALARM/INSUFFICIENT_DATA, metric, threshold; sortable) | Состояние алармов — тот же паттерн Badge-колонки, что enabled/disabled у автоматизаций Home Assistant. |
| Cost Explorer | `Select`(period: MTD/last_month/last_3_months) + `Chart`(type="bar", по сервисам) + `Chart`(type="line", тренд по дням) + `Stat`(total_cost, forecast) | Расходы — единственный экран, где две диаграммы оправданы (breakdown + тренд), обе из проверенного словаря. |
| Empty states | `Empty`(message + CTA) — до первого подключения и при пустых списках ресурсов в регионе | Каноничный `Empty`, не кастомный текст. |
| App settings | `Form`(region select, IAM ARN read-only, disconnect Button) | Единственное место с инструкцией по управлению подключением — не дублируется в сайдбаре (правило из UI_INTERFACE_STANDARD). |

## 2. Формы — обязательные требования (UI_INTERFACE_STANDARD)

- Все инпуты — с лейблами, плейсхолдер контекстно-подходящий (например
  для Access Key ID: `"AKIA..."`, для Secret Access Key: `"вставьте секретный ключ"`).
- Контейнер формы подключения растянут на всю ширину левого сайдбара;
  содержимое растянуто внутри себя на всю ширину контейнера.
- Инструкция по кнопке подключения — только в модалке/тултипе кнопки,
  не дублируется отдельным текстом в сайдбаре.

## 3. Навигация между экранами

`Sidebar ListItem` → меняет активный домен (EC2/S3/RDS/Lambda/IAM/
CloudWatch/Cost) → центральная панель рендерит соответствующий
`DataTable`/`Stats`/`Chart` экран. Detail-экраны открываются кликом по
строке `DataTable`, с явной кнопкой "Назад" (Back-button паттерн,
использован во всех detail-экранах портфеля — Home Assistant, GitLab).
