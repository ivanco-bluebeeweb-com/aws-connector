# AWS (Amazon Web Services) Connector — Connector Discovery

**Дата discovery:** 2026-08-24
**Vikunja task:** #2398 (BBW Imperal Apps), [App Development].
**Статус:** Ярусы 1-3 определены на основе официальной документации AWS
(docs.aws.amazon.com, прочитано 2026-08-24). Пользователь явно заявил
"приступай к разработке всех приложений Гипермасштабные облака (IaaS/PaaS)
категории" — это заранее заявленное решение объёма ("максимум"), по
прецеденту GitLab CI/CD/MuleSoft/Automation Anywhere/UiPath/Blue Prism, где
аналогичная явная формулировка уже освобождала от повторного вопроса в §7.

---

## 1. Целевой сервис и источники

AWS — **не единый API**, а несколько сотен независимых сервисных API, у
каждого свой base endpoint (`https://<service>.<region>.amazonaws.com`) и
свой протокол (EC2 — Query/XML, S3 — REST+XML, Lambda/Cost Explorer/IAM —
JSON поверх AWS JSON 1.1 или REST). Общее у всех — единая схема подписи
запросов **Signature Version 4 (SigV4)**.

Источники (прочитаны 2026-08-24):
- `docs.aws.amazon.com/IAM/latest/UserGuide/reference_sigv.html` — обзор SigV4/SigV4a
- `docs.aws.amazon.com/IAM/latest/UserGuide/reference_sigv-create-signed-request.html` — пошаговый алгоритм подписи
- `docs.aws.amazon.com/IAM/latest/UserGuide/reference_sigv-signing-elements.html` — обязательные элементы подписи (canonical request, string to sign, signing key)
- `docs.aws.amazon.com/IAM/latest/UserGuide/programming.html` — модель вызова через HTTPS + подписанные query-запросы
- `aws.amazon.com/sdk-for-python/` — справочно, какие сервисы считаются "ядром" (EC2, S3, RDS, Lambda, IAM, CloudWatch, Cost Explorer) — НЕ как источник для использования самого SDK

## 2. Auth-модель — почему это принципиально другой случай

**SigV4, не Bearer/PAT/OAuth.** Каждый HTTP-запрос подписывается отдельно:

1. Строится canonical request (метод, путь, query, canonical headers, подписанные заголовки, хэш тела).
2. Строится string-to-sign (алгоритм `AWS4-HMAC-SHA256`, дата, credential scope `<date>/<region>/<service>/aws4_request`, хэш canonical request).
3. Выводится signing key цепочкой HMAC: `HMAC(HMAC(HMAC(HMAC("AWS4"+secret, date), region), service), "aws4_request")`.
4. Итоговая подпись кладётся в заголовок `Authorization` (или query-параметр для presigned URL).

Это значит: **отдельный модуль `aws_sigv4.py`** с чистыми функциями подписи
(hashlib/hmac из стандартной библиотеки Python — никаких внешних крипто-пакетов
нужно, `hmac`+`hashlib` в stdlib достаточно), который вызывается из
`aws_client.py` перед каждым запросом. Ни один существующий коннектор в
портфеле (grep подтвердил) не реализует HMAC-подпись запроса — это первый
такой случай, поэтому решение фиксируется явно, а не по аналогии.

**Секреты, которые хранит коннектор:** `access_key_id`, `secret_access_key`,
`default_region` (обязателен — нет единого глобального endpoint кроме IAM/
Route53/CloudFront), опционально `session_token` (для временных STS-креденшлов,
если пользователь захочет использовать assumed-role доступ вместо
долгоживущего IAM-пользователя — Ярус 2).

**IAM permissions — явное предупреждение на этапе connect.** BYOK здесь —
максимально высокий риск в портфеле: неправильно созданный Access Key может
дать полный административный доступ к инфраструктуре клиента. `connect_aws`
обязан:
- объяснить прямым текстом, что стоит создать отдельного IAM-пользователя
  с **read-only управляемой политикой** (`ReadOnlyAccess` или точечные
  `*:Describe*`/`*:List*`/`*:Get*`) для базового сценария просмотра;
- предупреждать (не блокировать — решение пользователя), если во время
  проверки токена (`sts:GetCallerIdentity`) выясняется, что аккаунт — root
  или есть основания полагать широкий доступ;
- никогда не предлагать использовать root-креденшлы (это отдельная,
  явно запрещённая AWS best practice).

**401/403 обрабатываются по-разному, тот же принцип, что в GitLab/n8n/MuleSoft:**
`InvalidClientTokenId`/`SignatureDoesNotMatch` = ключи не распознаны (опечатка,
отозванный ключ) — конкретное сообщение "ключ похоже отозван или введён с
ошибкой, проверьте в IAM Console"; `AccessDenied` = ключ валиден, но не
хватает IAM-прав на конкретное действие — конкретное сообщение "у этого IAM
пользователя нет прав на `<action>`, добавьте нужную policy", не generic
auth error.

## 3. Домен покрытия — сознательное ограничение

AWS целиком покрыть невозможно и не нужно (как и с GitLab — CI/CD, не весь
GitLab). Коннектор фокусируется на **обзоре инфраструктуры + стоимости +
базовом lifecycle-управлении** самых массовых сервисов, а не на глубокой
конфигурации каждого из ~250 AWS-сервисов:

- **EC2** (виртуальные машины) —核心 compute-домен, на нём строится
  большая часть остальной инфраструктуры.
- **S3** (объектное хранилище) — второй по универсальности сервис.
- **RDS** (управляемые базы данных).
- **Lambda** (serverless-функции).
- **IAM** (пользователи/роли/политики) — обязателен для самой модели connect,
  плюс value-add аудит прав доступа.
- **CloudWatch** (метрики/алармы/логи) — обзор здоровья и производительности.
- **Cost Explorer** (стоимость и использование) — критичный B2B/enterprise
  сценарий: "сколько мы тратим и на что", ежедневная FinOps-задача.
- **VPC** (базовый обзор сетей — subnets/security groups), нужен как контекст
  для EC2-инстансов, не как отдельный полноценный network-management домен.

**Сознательно вне охвата в этом заходе:** ECS/EKS (контейнерная оркестрация —
отдельный по сложности домен), Route53 (DNS), CloudFormation (IaC-деплойменты),
Organizations (multi-account management), любые ML/AI-сервисы (SageMaker и
т.п.), специализированные аналитические/data-сервисы (Redshift, Athena,
Glue — это уже домен "Cloud Data Warehouse" категории, отдельный будущий
коннектор). Если позже понадобится — отдельный заход, не тихое добавление.

## 4. Карта возможностей (направление на каждую)

| Домен | Возможность | Ingress/Egress/Both | Комментарий |
|---|---|---|---|
| **STS** | `GetCallerIdentity` | Ingress | Проверка валидности ключей при connect — не требует отдельных прав |
| **EC2** | Describe instances/AMIs/security groups/subnets/VPCs/volumes/snapshots | Ingress | Основной "что у нас есть" обзор инфраструктуры |
| **EC2** | Start/stop/reboot/terminate instance | Egress | Прямое управление жизненным циклом ВМ |
| **EC2** | Create/delete security group rule | Egress | Точечное управление сетевым доступом |
| **EC2** | Create/delete snapshot | Both | Резервное копирование томов |
| **S3** | List buckets, list objects, get object metadata | Ingress | Обзор хранилища |
| **S3** | Create/delete bucket, put/get/delete object, set bucket policy | Both | Прямое управление содержимым |
| **S3** | Get bucket public-access-block / ACL | Ingress | Value-add: аудит публичного доступа (частая причина утечек данных) |
| **RDS** | Describe DB instances/snapshots/clusters | Ingress | Обзор баз данных |
| **RDS** | Start/stop/reboot DB instance, create snapshot | Both | Управление жизненным циклом |
| **Lambda** | List functions, get function config/code location | Ingress | Обзор serverless-функций |
| **Lambda** | Invoke function, update function config, publish version | Both | Прямой вызов и конфигурация |
| **IAM** | List users/roles/policies/groups, get policy document | Ingress | Аудит прав доступа |
| **IAM** | Create/delete access key, attach/detach policy | Both | Управление доступом (высокий риск — Ярус 2/3 с явным подтверждением) |
| **CloudWatch** | List metrics, get metric statistics, list alarms | Ingress | Обзор здоровья/производительности |
| **CloudWatch** | Create/update/delete alarm | Both | Настройка мониторинга |
| **CloudWatch Logs** | Describe log groups, filter log events | Ingress | Диагностика (аналог `get_job_trace` у GitLab) |
| **Cost Explorer** | Get cost and usage, get cost forecast, get dimension values | Ingress | FinOps — сколько тратится и на что |
| **VPC** | Describe VPCs/subnets/route tables/internet gateways | Ingress | Контекст для EC2 (не отдельный полноценный network domain) |

## 5. Классификация по типу функционала (Шаг 1 стандарта)

- **Ingress (сильный):** все Describe/List/Get-вызовы по EC2/S3/RDS/Lambda/
  IAM/CloudWatch/Cost Explorer/VPC — то, что коннектор должен уметь
  *показывать* в первую очередь (обзор инфраструктуры, здоровья, расходов).
- **Egress (сильный):** start/stop/reboot/terminate instance, invoke Lambda,
  create/delete S3 object, create/delete CloudWatch alarm, attach/detach IAM
  policy.
- **Both:** снапшоты (список = чтение, создание/удаление = запись), bucket/
  object management, DB instance lifecycle.

## 6. Ярус 1 — Ключевые функции (P0-кандидаты)

Ближайший операционный аналог "обзор инфраструктуры + costs + базовые
действия", по образцу уже существующих коннекторов:

1. `connect_aws` / `disconnect_aws` — access_key_id + secret_access_key +
   default_region, проверка через `sts:GetCallerIdentity`
2. `list_ec2_instances` — обзор ВМ со статусом/типом/регионом
3. `get_ec2_instance` — детали одной ВМ
4. `start_ec2_instance` / `stop_ec2_instance` / `reboot_ec2_instance`
5. `list_s3_buckets` — обзор хранилищ
6. `list_s3_objects` — содержимое бакета
7. `list_rds_instances` — обзор баз данных
8. `list_lambda_functions` — обзор функций
9. `invoke_lambda_function`
10. `get_cost_and_usage` — расходы за период с разбивкой по сервису
11. `list_cloudwatch_alarms` — текущие алармы (какие в ALARM-статусе)
12. `get_caller_identity` — кто подключён (аккаунт/ARN) — value-add диагностика

## 7. Ярус 2 — Полное покрытие

| Возможность | Статус | Причина/триггер |
|---|---|---|
| Terminate/create EC2 instance | included | Полный lifecycle, максимум явно требует |
| Security group CRUD | included | Прямое продолжение EC2-домена |
| EBS snapshot create/delete | included | Естественное расширение resource lifecycle |
| S3 bucket create/delete, object put/delete, bucket policy get/set | included | Полный CRUD над хранилищем |
| S3 public-access-block audit | included | Value-add диагностика безопасности |
| RDS start/stop/reboot/snapshot | included | Полный lifecycle управляемых БД |
| Lambda update config/publish version | included | Полное управление функциями |
| IAM list users/roles/policies/groups | included | Аудит прав доступа — критично для enterprise/B2G compliance |
| IAM create/delete access key, attach/detach policy | included | Максимум требует, НО с явным предупреждением о риске в UI (не тихая операция) |
| CloudWatch alarm CRUD | included | Полное управление мониторингом |
| CloudWatch Logs — filter log events | included | Диагностика по логам Lambda/EC2 |
| Cost Explorer forecast + dimension breakdown | included | Полное покрытие FinOps-сценария |
| VPC/subnet/route table describe | included | Контекст инфраструктуры |

## 8. Ярус 3 — Функции на нашей стороне (value-add)

- **`audit_aws_account`** — агрегирующий отчёт: инстансы без тегов,
  остановленные инстансы старше N дней (платное хранилище EBS без пользы),
  публично доступные S3-бакеты, IAM-пользователи без MFA, неиспользуемые
  Elastic IP — вместо ручного обхода Describe по каждому сервису (аналог
  `audit_cloudhub_environment` у MuleSoft / `audit_project_ci` у GitLab).
- **`get_cost_anomalies`** — сравнение текущих трат с историческим средним
  по сервису, флаг резких скачков (Cost Explorer не даёт готового "что
  внезапно подорожало" в простом виде программно).
- **`get_idle_resources_report`** — ЕC2 с CPU-утилизацией ниже порога за N
  дней, неиспользуемые EBS-тома (не attached), остановленные RDS дольше N
  дней — типичный FinOps value-add отчёт.
- **`bulk_stop_ec2_instances`** / **`bulk_start_ec2_instances`** — массовое
  управление несколькими инстансами одним вызовом (AWS API это делает и сам
  через `InstanceIds` список, но нормализуем под наш bulk-паттерн с
  continue-on-failure, как в остальном портфеле).

## 9. Решение по объёму этого захода

Явный запрос пользователя "приступай к разработке всех приложений
Гипермасштабные облака (IaaS/PaaS) категории" в контексте установленного
дефолтного поведения "максимум" — берём **Ярус 1 + Ярус 2 + Ярус 3** целиком,
без дополнительного вопроса, по прецеденту GitLab CI/CD/MuleSoft/Automation
Anywhere/UiPath/Blue Prism.

**Явный вопрос (не про объём, а про архитектуру), фиксируемый, не блокирующий:**
Домен ограничен EC2/S3/RDS/Lambda/IAM/CloudWatch/Cost Explorer/VPC (см. §3).
ECS/EKS, Route53, CloudFormation, Organizations и специализированные data-
сервисы сознательно вне охвата — отдельный будущий заход при явном запросе.
