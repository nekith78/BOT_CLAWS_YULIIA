# Graph Report - e:/BOT_CLAWS_YULIIA  (2026-05-05)

## Corpus Check
- Corpus is ~12,290 words - fits in a single context window. You may not need a graph.

## Summary
- 282 nodes · 355 edges · 38 communities (28 shown, 10 thin omitted)
- Extraction: 75% EXTRACTED · 25% INFERRED · 0% AMBIGUOUS · INFERRED: 89 edges (avg confidence: 0.78)
- Token cost: 0 input · 0 output

## Community Hubs (Navigation)
- [[_COMMUNITY_Appointment Repository|Appointment Repository]]
- [[_COMMUNITY_Storage Tests|Storage Tests]]
- [[_COMMUNITY_Bootstrap & Config|Bootstrap & Config]]
- [[_COMMUNITY_BotService Tests|Bot/Service Tests]]
- [[_COMMUNITY_NotifyRule Repository|NotifyRule Repository]]
- [[_COMMUNITY_Settings Service & Repository|Settings Service & Repository]]
- [[_COMMUNITY_SQLAlchemy Models|SQLAlchemy Models]]
- [[_COMMUNITY_Foundation Plan Tasks|Foundation Plan Tasks]]
- [[_COMMUNITY_Whitelist Middleware|Whitelist Middleware]]
- [[_COMMUNITY_Repository–Model Bridge|Repository–Model Bridge]]
- [[_COMMUNITY_DB Plumbing (Async)|DB Plumbing (Async)]]
- [[_COMMUNITY_Alembic Env|Alembic Env]]
- [[_COMMUNITY_Initial Migration|Initial Migration]]
- [[_COMMUNITY_DB Smoke Tests|DB Smoke Tests]]
- [[_COMMUNITY_Misc Utilities|Misc Utilities]]
- [[_COMMUNITY_SingletonMisc 16|Singleton/Misc 16]]
- [[_COMMUNITY_SingletonMisc 17|Singleton/Misc 17]]
- [[_COMMUNITY_SingletonMisc 18|Singleton/Misc 18]]
- [[_COMMUNITY_SingletonMisc 19|Singleton/Misc 19]]
- [[_COMMUNITY_SingletonMisc 34|Singleton/Misc 34]]
- [[_COMMUNITY_SingletonMisc 35|Singleton/Misc 35]]
- [[_COMMUNITY_SingletonMisc 36|Singleton/Misc 36]]
- [[_COMMUNITY_SingletonMisc 37|Singleton/Misc 37]]

## God Nodes (most connected - your core abstractions)
1. `session fixture` - 30 edges
2. `ClientRepository` - 19 edges
3. `SettingRepository` - 18 edges
4. `Foundation milestone` - 18 edges
5. `NotifyRuleRepository` - 17 edges
6. `AppointmentRepository` - 15 edges
7. `Client` - 10 edges
8. `WhitelistMiddleware` - 8 edges
9. `Appointment` - 8 edges
10. `load_settings()` - 7 edges

## Surprising Connections (you probably didn't know these)
- `test_start_replies_with_menu()` --calls--> `handle_start()`  [INFERRED]
  tests/bot/test_start_handler.py → src/bot/handlers/start.py
- `test_setting_round_trip()` --calls--> `Setting`  [INFERRED]
  tests/storage/test_models.py → src/storage/models.py
- `test_client_unique_name_collation()` --calls--> `Client`  [INFERRED]
  tests/storage/test_models.py → src/storage/models.py
- `test_client_optional_fields_default_none()` --calls--> `Client`  [INFERRED]
  tests/storage/test_models.py → src/storage/models.py
- `test_notify_rule_defaults()` --calls--> `NotifyRule`  [INFERRED]
  tests/storage/test_models.py → src/storage/models.py

## Hyperedges (group relationships)
- **Bot bootstrap sequence** — config_load_settings, main_configure_logging, config_ensure_data_dir, main_seed_defaults, main_build_dispatcher, main_run [EXTRACTED 1.00]
- **Repository pattern with session-based ORM access** — appointments_AppointmentRepository, clients_ClientRepository, notify_rules_NotifyRuleRepository, settings_SettingRepository [INFERRED 0.95]
- **SQLAlchemy model inheritance from Base** — models_Setting, models_Client, models_Appointment, models_NotifyRule, models_ScheduledJob [EXTRACTED 1.00]
- **Storage layer tests (models, db, repos)** — test_db_test_create_engine_and_run_query, test_db_test_session_scope_commits_on_exit, test_models_test_setting_round_trip, test_models_test_client_unique_name_collation, test_models_test_client_optional_fields_default_none, test_models_test_appointment_links_client, test_models_test_appointment_cascade_delete_with_client, test_models_test_notify_rule_defaults, test_models_test_scheduled_job_links_appointment, test_repositories_test_create_and_get_by_id, test_repositories_test_search_by_name_case_insensitive, test_repositories_test_list_recent, test_repositories_test_update_partial, test_repositories_test_delete, test_repositories_test_create_appointment_for_client, test_repositories_test_find_overlap_includes_partial, test_repositories_test_find_overlap_excludes_back_to_back, test_repositories_test_find_overlap_excludes_cancelled, test_repositories_test_list_in_range, test_repositories_test_notify_rule_create_and_list_enabled, test_repositories_test_notify_rule_toggle, test_repositories_test_notify_rule_replace_all, test_repositories_test_setting_get_returns_none_when_missing, test_repositories_test_setting_set_then_get, test_repositories_test_setting_set_overwrites, test_repositories_test_setting_get_int [INFERRED 0.85]
- **Bot layer tests (handlers, keyboards, middleware)** — test_keyboards_test_main_menu_has_required_buttons, test_start_handler_test_start_replies_with_menu, test_whitelist_middleware_test_owner_passes_through, test_whitelist_middleware_test_non_owner_is_silently_dropped, test_whitelist_middleware_test_update_without_user_is_dropped [INFERRED 0.85]
- **Foundation Implementation Tasks 1-18** — plan_task_1, plan_task_2, plan_task_3, plan_task_4, plan_task_5, plan_task_6, plan_task_7, plan_task_8, plan_task_9, plan_task_10, plan_task_11, plan_task_12, plan_task_13, plan_task_14, plan_task_15, plan_task_16, plan_task_17, plan_task_18 [EXTRACTED 1.00]

## Communities (38 total, 10 thin omitted)

### Community 0 - "Appointment Repository"
Cohesion: 0.11
Nodes (17): AppointmentRepository, Appointment repository — CRUD, overlap detection, range queries., Return scheduled appointments overlapping the proposed slot.          Two interv, ClientRepository, Client repository — CRUD and case-insensitive name search., Repository-layer tests (using in-memory SQLite from conftest)., test_create_and_get_by_id(), test_create_appointment_for_client() (+9 more)

### Community 1 - "Storage Tests"
Cohesion: 0.06
Nodes (32): engine fixture, session fixture, test_create_engine_and_run_query, test_session_scope_commits_on_exit, test_appointment_cascade_delete_with_client, test_appointment_links_client, test_client_optional_fields_default_none, test_client_unique_name_collation (+24 more)

### Community 2 - "Bootstrap & Config"
Cohesion: 0.13
Nodes (20): BaseSettings, ensure_data_dir(), load_settings(), Application configuration loaded from environment variables.  Все секреты и наст, Create the parent directory of db_path if it does not exist., Settings, _build_dispatcher(), _configure_logging() (+12 more)

### Community 3 - "Bot/Service Tests"
Cohesion: 0.08
Nodes (21): Keyboard layout tests., test_main_menu_has_required_buttons(), /start handler test — sends welcome with main menu keyboard., test_start_replies_with_menu(), Settings class, ensure_data_dir function, load_settings function, create_engine function (+13 more)

### Community 4 - "NotifyRule Repository"
Cohesion: 0.1
Nodes (12): NotifyRuleRepository, Notify-rule repository — CRUD plus a bulk replace for preset switching., Wipe table and insert new tuples (kind, value, enabled)., Tests for settings_service: seed defaults and helpers., test_seed_creates_defaults_if_empty(), test_seed_is_idempotent(), NotifyRule, Правило уведомлений (UI-настраиваемое).      kind: time_day_before | time_same_d (+4 more)

### Community 5 - "Settings Service & Repository"
Cohesion: 0.13
Nodes (17): Setting model, Settings repository — typed convenience wrappers around key/value storage., SettingRepository, get_default_duration_min(), get_preset(), get_timezone(), High-level settings access plus default seeding.  `seed_defaults` is idempotent, Insert default settings and notify_rules if missing. Idempotent. (+9 more)

### Community 6 - "SQLAlchemy Models"
Cohesion: 0.15
Nodes (18): DeclarativeBase, Appointment, Base, Client, SQLAlchemy declarative models.  Models stay dumb — pure schema, no business logi, Global key/value store. Used for timezone, notify_preset, default_duration_min., Постоянные данные клиента. Один клиент = много appointments., Один визит. Длительность по умолчанию 60 мин — для проверки конфликтов. (+10 more)

### Community 7 - "Foundation Plan Tasks"
Cohesion: 0.13
Nodes (20): Foundation milestone, Task 1: Initialize git and commit scaffold, Task 10: AppointmentRepository with overlap query, Task 11: NotifyRuleRepository, Task 12: SettingRepository (typed key/value), Task 13: settings_service with default seed, Task 14: WhitelistMiddleware, Task 15: Main menu keyboard (+12 more)

### Community 8 - "Whitelist Middleware"
Cohesion: 0.21
Nodes (9): BaseMiddleware, _make_message(), WhitelistMiddleware tests — owner gets through, everyone else is silently droppe, test_non_owner_is_silently_dropped(), test_owner_passes_through(), test_update_without_user_is_dropped(), _extract_user_id(), Whitelist middleware — drops every update not from OWNER_CHAT_ID.  Silent drop ( (+1 more)

### Community 9 - "Repository–Model Bridge"
Cohesion: 0.36
Nodes (9): AppointmentRepository class, ClientRepository class, target_metadata from Base, Appointment model, Base declarative class, Client model, NotifyRule model, ScheduledJob model (+1 more)

### Community 10 - "DB Plumbing (Async)"
Cohesion: 0.29
Nodes (5): create_engine(), Async SQLAlchemy engine, session factory, and a transaction-scoped helper.  Keep, Build an async engine. SQLite gets check_same_thread=False via the URL handler., Open a session, commit on success, rollback on exception., session_scope()

### Community 15 - "Misc Utilities"
Cohesion: 0.5
Nodes (4): bot service, redis service, graphify knowledge graph in docs/graph/, BOT_CLAWS_YULIIA project

### Community 16 - "Singleton/Misc 16"
Cohesion: 0.67
Nodes (3): test_main_menu_has_required_buttons, test_settings_load_with_minimum_env, test_start_replies_with_menu

## Knowledge Gaps
- **96 isolated node(s):** `Application configuration loaded from environment variables.  Все секреты и наст`, `Create the parent directory of db_path if it does not exist.`, `Bot bootstrap.  Startup pipeline: 1. Load config (validates env) 2. Configure lo`, `/start command handler — greets the owner and shows the main menu.`, `Main menu — reply-keyboard, всегда доступная owner'у.` (+91 more)
  These have ≤1 connection - possible missing edges or undocumented components.
- **10 thin communities (<3 nodes) omitted from report** — run `graphify query` to explore isolated nodes.

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **Why does `ClientRepository` connect `Appointment Repository` to `Whitelist Middleware`, `SQLAlchemy Models`?**
  _High betweenness centrality (0.167) - this node is a cross-community bridge._
- **Why does `seed_defaults()` connect `Settings Service & Repository` to `Repository–Model Bridge`, `Bot/Service Tests`, `NotifyRule Repository`?**
  _High betweenness centrality (0.137) - this node is a cross-community bridge._
- **Why does `WhitelistMiddleware` connect `Whitelist Middleware` to `Bootstrap & Config`?**
  _High betweenness centrality (0.121) - this node is a cross-community bridge._
- **Are the 11 inferred relationships involving `ClientRepository` (e.g. with `Client` and `test_create_and_get_by_id()`) actually correct?**
  _`ClientRepository` has 11 INFERRED edges - model-reasoned connections that need verification._
- **Are the 13 inferred relationships involving `SettingRepository` (e.g. with `Setting` and `seed_defaults()`) actually correct?**
  _`SettingRepository` has 13 INFERRED edges - model-reasoned connections that need verification._
- **Are the 7 inferred relationships involving `NotifyRuleRepository` (e.g. with `NotifyRule` and `seed_defaults()`) actually correct?**
  _`NotifyRuleRepository` has 7 INFERRED edges - model-reasoned connections that need verification._
- **What connects `Application configuration loaded from environment variables.  Все секреты и наст`, `Create the parent directory of db_path if it does not exist.`, `Bot bootstrap.  Startup pipeline: 1. Load config (validates env) 2. Configure lo` to the rest of the system?**
  _96 weakly-connected nodes found - possible documentation gaps or missing edges._