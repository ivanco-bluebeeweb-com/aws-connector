# Pricing History — AWS Connector

Обязательный журнал: каждое выставление или изменение цен на функции этого
приложения фиксируется здесь — что изменилось, почему, и на основании
чего. Не переписывать прошлые записи — только дописывать новые сверху.

---

## 2026-08-24 — первичный прайсинг, ДО submit_for_review (правило соблюдено)

**Метод — `developer.update_pricing`** (тот же подтверждённо рабочий метод,
что и для MuleSoft/GitLab CI/CD Connector): `pricing_config` передан как
настоящий JSON-объект, `pricing_model` = `per_action`, `revenue_split_dev`
= 95 (partner-тир) передан явным параметром.

**Известный платформенный баг (см. таск #2230 в Imperal Cloud, применим
портфельно):** первый вызов (`developer.save_pricing`) вернул явный отказ
— КАЖДЫЙ переданный `tool_prices` элемент отмечен `was not stored`, модель
осталась `free`. Немедленный повторный вызов ЧЕРЕЗ `developer.update_pricing`
с идентичным payload прошёл без единой ошибки — тот же класс транзиентного
расхождения, что задокументирован для GitLab CI/CD Connector.

**Шкала цен (per_action, tokens):**
- `0` — connect_aws, disconnect_aws, list_connections (подключение/список — всегда бесплатно)
- `8` — все read-операции: list_ec2_instances, get_ec2_instance, list_s3_buckets,
  list_s3_objects, list_rds_instances, list_rds_snapshots, list_lambda_functions,
  list_iam_users, list_iam_roles, list_cloudwatch_alarms, get_metric_statistics,
  get_cost_and_usage, get_cost_forecast
- `16` — write/action-операции с реальным эффектом: start_ec2_instance,
  stop_ec2_instance, invoke_lambda
- `40` — get_cloud_overview (Tier 3 value-add: агрегирует 4 отдельных API-вызова
  в одну сводку — оценено выше обычного read)

**Категория:** `cloud-infrastructure` (подтверждено платформой как валидный
id для группы "Infrastructure" — исходная попытка `Hyperscale Clouds
(IaaS/PaaS)` была отклонена API с явной подсказкой правильного id).
