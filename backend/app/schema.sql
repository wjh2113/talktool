-- AI 沟通训练工具 · SQLite 建表脚本
-- 时间字段统一存本地时间字符串：YYYY-MM-DD HH:MM:SS（时区见 .env 的 APP_TIMEZONE）

CREATE TABLE IF NOT EXISTS category (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    name        TEXT    NOT NULL UNIQUE,
    sort_order  INTEGER NOT NULL DEFAULT 0,
    is_system   INTEGER NOT NULL DEFAULT 0       -- 1 = 系统分类（如“我的场景”），不在场景页展示
);

-- 场景大类（如“临时点名发言”）
CREATE TABLE IF NOT EXISTS scenario (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    category_id  INTEGER NOT NULL REFERENCES category(id) ON DELETE CASCADE,
    title        TEXT    NOT NULL,
    subtitle     TEXT    NOT NULL DEFAULT '',
    sort_order   INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_scenario_category ON scenario(category_id);

-- 训练卡片（真正可以开始训练的单元）
CREATE TABLE IF NOT EXISTS drill (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    scenario_id     INTEGER NOT NULL REFERENCES scenario(id) ON DELETE CASCADE,
    title           TEXT    NOT NULL,
    description     TEXT    NOT NULL,              -- 完整背景设定（展示给用户）
    cover_image     TEXT    NOT NULL DEFAULT '',   -- 封面图 URL，空则前端用渐变占位
    pressure_level  TEXT    NOT NULL DEFAULT '低压' CHECK (pressure_level IN ('低压','中压','高压')),
    duration_min    INTEGER NOT NULL DEFAULT 3,
    mode            TEXT    NOT NULL DEFAULT '纯语音',
    ai_role         TEXT    NOT NULL DEFAULT '',
    user_role       TEXT    NOT NULL DEFAULT '',
    training_goal   TEXT    NOT NULL DEFAULT '',
    opening_line    TEXT    NOT NULL DEFAULT '',   -- AI 开场白；为空则由 LLM 生成
    system_prompt   TEXT    NOT NULL DEFAULT '',   -- 自定义 system prompt；为空则按模板生成
    status          TEXT    NOT NULL DEFAULT 'online' CHECK (status IN ('online','offline')),
    sort_order      INTEGER NOT NULL DEFAULT 0,
    owner_id        TEXT,                          -- NULL = 公共场景；否则为用户自定义场景
    sample_script   TEXT    NOT NULL DEFAULT '',   -- 跟读示范稿（首次请求时由 LLM 生成并缓存）
    pitfalls        TEXT    NOT NULL DEFAULT '[]'  -- 本场景常见误区 JSON
);
CREATE INDEX IF NOT EXISTS idx_drill_scenario ON drill(scenario_id);

-- 训练会话
CREATE TABLE IF NOT EXISTS session (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id       TEXT    NOT NULL,
    drill_id      INTEGER NOT NULL REFERENCES drill(id),
    started_at    TEXT    NOT NULL,
    ended_at      TEXT,
    duration_sec  INTEGER NOT NULL DEFAULT 0,
    status        TEXT    NOT NULL DEFAULT 'in_progress'
                  CHECK (status IN ('in_progress','completed','too_short','abandoned')),
    transcript    TEXT    NOT NULL DEFAULT '[]',   -- JSON: [{role:'ai'|'user', text, at, metrics?}]
    metrics       TEXT    NOT NULL DEFAULT '{}',   -- JSON: 表达数据汇总（语速/口头禅/停顿/反应时间）
    ip            TEXT,                            -- 客户端 IP（每日限额用）
    report_status TEXT    NOT NULL DEFAULT 'none'  -- none | pending 生成中 | ready | failed
);
CREATE INDEX IF NOT EXISTS idx_session_user ON session(user_id, started_at DESC);

-- 训练报告
CREATE TABLE IF NOT EXISTS report (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id      INTEGER NOT NULL UNIQUE REFERENCES session(id) ON DELETE CASCADE,
    scores          TEXT    NOT NULL DEFAULT '{}', -- JSON: {"逻辑表达":8,...}
    total_score     INTEGER NOT NULL DEFAULT 0,
    summary         TEXT    NOT NULL DEFAULT '',
    highlights      TEXT    NOT NULL DEFAULT '[]', -- JSON array
    improvements    TEXT    NOT NULL DEFAULT '[]', -- JSON array
    detail_comment  TEXT    NOT NULL DEFAULT '',   -- Markdown
    turn_reviews    TEXT    NOT NULL DEFAULT '[]', -- JSON: [{turn, user_text, better, tip}] 逐句示范；null/[] = 未生成（按需）
    created_at      TEXT    NOT NULL
);

-- 练习本：收藏的话术 / 建议 / 示范稿
CREATE TABLE IF NOT EXISTS note (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id      TEXT    NOT NULL,
    kind         TEXT    NOT NULL DEFAULT 'phrase' CHECK (kind IN ('phrase','tip','script')),
    text         TEXT    NOT NULL,
    source_text  TEXT    NOT NULL DEFAULT '',     -- 原话（话术类）
    drill_id     INTEGER REFERENCES drill(id),
    session_id   INTEGER REFERENCES session(id) ON DELETE SET NULL,
    best_score   INTEGER,                         -- 跟读最高分
    created_at   TEXT    NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_note_user ON note(user_id, created_at DESC);

-- ============ 账号体系 ============
-- 用户：业务表里的 user_id 统一用 "acc_<id>"
CREATE TABLE IF NOT EXISTS app_user (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    username       TEXT    NOT NULL UNIQUE COLLATE NOCASE,
    password_hash  TEXT    NOT NULL,               -- pbkdf2_sha256$迭代次数$salt$hash
    nickname       TEXT    NOT NULL DEFAULT '',
    role           TEXT    NOT NULL DEFAULT 'user' CHECK (role IN ('admin','user')),
    status         TEXT    NOT NULL DEFAULT 'active' CHECK (status IN ('active','disabled')),
    invite_code    TEXT,                           -- 注册时用的邀请码
    tts_gender     TEXT    NOT NULL DEFAULT 'male' CHECK (tts_gender IN ('male','female')),  -- 示范/对练音色
    created_at     TEXT    NOT NULL,
    last_login_at  TEXT
);

-- 邀请码：管理员生成，注册时消耗
CREATE TABLE IF NOT EXISTS invite_code (
    code        TEXT    PRIMARY KEY,
    created_by  INTEGER REFERENCES app_user(id),
    max_uses    INTEGER NOT NULL DEFAULT 1,
    used_count  INTEGER NOT NULL DEFAULT 0,
    expires_at  TEXT,                              -- NULL = 永不过期
    note        TEXT    NOT NULL DEFAULT '',
    disabled    INTEGER NOT NULL DEFAULT 0,
    created_at  TEXT    NOT NULL
);

-- 登录令牌（只存哈希，可随时吊销）
CREATE TABLE IF NOT EXISTS auth_token (
    token_hash  TEXT    PRIMARY KEY,
    user_id     INTEGER NOT NULL REFERENCES app_user(id) ON DELETE CASCADE,
    created_at  TEXT    NOT NULL,
    expires_at  TEXT    NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_token_user ON auth_token(user_id);

-- 用量计数（每日限额 / 登录失败锁定）
CREATE TABLE IF NOT EXISTS usage_counter (
    subject  TEXT    NOT NULL,                     -- 用户 uid 或 ip:<地址>
    bucket   TEXT    NOT NULL,                     -- 日期或时间窗口
    kind     TEXT    NOT NULL,
    count    INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (subject, bucket, kind)
);

-- ============ 表达框架库 ============
CREATE TABLE IF NOT EXISTS framework (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    code         TEXT    NOT NULL UNIQUE,
    name         TEXT    NOT NULL,
    category     TEXT    NOT NULL,
    summary      TEXT    NOT NULL DEFAULT '',
    steps        TEXT    NOT NULL DEFAULT '[]',   -- JSON: [{key, name, desc}]
    when_to_use  TEXT    NOT NULL DEFAULT '',
    example      TEXT    NOT NULL DEFAULT '',
    pitfalls     TEXT    NOT NULL DEFAULT '[]',
    tips         TEXT    NOT NULL DEFAULT '[]',
    detail       TEXT    NOT NULL DEFAULT '',     -- 详细说明（写作/讲述要点）
    source       TEXT    NOT NULL DEFAULT '',
    pitfall_source TEXT  NOT NULL DEFAULT '',     -- 常见误区出自资料的哪一节
    sort_order   INTEGER NOT NULL DEFAULT 0
);

-- 训练 ↔ 推荐框架（example = 本场景下的示例说法）
CREATE TABLE IF NOT EXISTS drill_framework (
    drill_id      INTEGER NOT NULL REFERENCES drill(id) ON DELETE CASCADE,
    framework_id  INTEGER NOT NULL REFERENCES framework(id) ON DELETE CASCADE,
    example       TEXT    NOT NULL DEFAULT '',
    sort_order    INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (drill_id, framework_id)
);
CREATE INDEX IF NOT EXISTS idx_df_framework ON drill_framework(framework_id);

-- ============ AI 智囊团 ============
-- 谋略库（内置按 code 同步；customized=1 表示后台改过或导入的，启动同步不覆盖）
CREATE TABLE IF NOT EXISTS strategy (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    code            TEXT    NOT NULL UNIQUE,
    school          TEXT    NOT NULL,
    name            TEXT    NOT NULL,
    sub             TEXT    NOT NULL DEFAULT '',     -- 如“第1计 · 胜战计”
    origin          TEXT    NOT NULL DEFAULT '',     -- 原文
    plain           TEXT    NOT NULL DEFAULT '',     -- 白话
    domains         TEXT    NOT NULL DEFAULT '[]',
    how_to_do       TEXT    NOT NULL DEFAULT '[]',
    how_to_say      TEXT    NOT NULL DEFAULT '',
    framework_codes TEXT    NOT NULL DEFAULT '[]',
    misuses         TEXT    NOT NULL DEFAULT '',
    caution         INTEGER NOT NULL DEFAULT 0,      -- 1 = 慎用：只用于识别和防范
    customized      INTEGER NOT NULL DEFAULT 0,
    enabled         INTEGER NOT NULL DEFAULT 1,
    sort_order      INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_strategy_school ON strategy(school);

-- 谋士
CREATE TABLE IF NOT EXISTS advisor (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    code        TEXT    NOT NULL UNIQUE,
    name        TEXT    NOT NULL,
    avatar      TEXT    NOT NULL DEFAULT '',
    schools     TEXT    NOT NULL DEFAULT '[]',
    persona     TEXT    NOT NULL DEFAULT '',
    style       TEXT    NOT NULL DEFAULT '',
    owner_id    TEXT,                               -- NULL = 内置
    customized  INTEGER NOT NULL DEFAULT 0,
    sort_order  INTEGER NOT NULL DEFAULT 0
);

-- 智囊团（code 同时是意图识别的大类；prompt key = council.<code>）
CREATE TABLE IF NOT EXISTS council (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    code         TEXT    NOT NULL UNIQUE,
    name         TEXT    NOT NULL,
    icon         TEXT    NOT NULL DEFAULT '',
    description  TEXT    NOT NULL DEFAULT '',
    advisors     TEXT    NOT NULL DEFAULT '[]',
    schools      TEXT    NOT NULL DEFAULT '[]',     -- 谋略子库：按体系
    domains      TEXT    NOT NULL DEFAULT '[]',     -- 谋略子库：按领域
    requirement  TEXT    NOT NULL DEFAULT '',
    examples     TEXT    NOT NULL DEFAULT '[]',
    enabled      INTEGER NOT NULL DEFAULT 1,
    customized   INTEGER NOT NULL DEFAULT 0,
    sort_order   INTEGER NOT NULL DEFAULT 0
);

-- 提示词版本（没有 active 版本的 key 用代码里的默认版）
CREATE TABLE IF NOT EXISTS prompt_template (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    key          TEXT    NOT NULL,
    version      INTEGER NOT NULL,
    system       TEXT    NOT NULL DEFAULT '',
    user_template TEXT   NOT NULL DEFAULT '',
    capability   TEXT    NOT NULL DEFAULT '',
    max_tokens   INTEGER NOT NULL DEFAULT 0,
    temperature  REAL,
    status       TEXT    NOT NULL DEFAULT 'draft' CHECK (status IN ('draft','active','archived')),
    note         TEXT    NOT NULL DEFAULT '',
    updated_by   INTEGER,
    created_at   TEXT    NOT NULL,
    UNIQUE (key, version)
);
CREATE INDEX IF NOT EXISTS idx_prompt_key ON prompt_template(key, status);

-- 问计
CREATE TABLE IF NOT EXISTS consult (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id           TEXT    NOT NULL,
    title             TEXT    NOT NULL DEFAULT '',
    council_code      TEXT    NOT NULL DEFAULT '',
    intent            TEXT    NOT NULL DEFAULT '{}',
    situation_summary TEXT    NOT NULL DEFAULT '',
    status            TEXT    NOT NULL DEFAULT 'asking' CHECK (status IN ('asking','clarifying','routed','planned','safety','failed')),
    case_id           INTEGER,                        -- 关联的事件线（memory_subject）
    follow_up_at      TEXT,                           -- 该回来复盘的时间（按紧急程度推算）
    extra_advisors    TEXT    NOT NULL DEFAULT '[]',  -- 列席的私人谋士 code
    created_at        TEXT    NOT NULL,
    updated_at        TEXT    NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_consult_user ON consult(user_id, updated_at);

CREATE TABLE IF NOT EXISTS consult_message (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    consult_id  INTEGER NOT NULL REFERENCES consult(id) ON DELETE CASCADE,
    role        TEXT    NOT NULL CHECK (role IN ('user','advisor')),
    kind        TEXT    NOT NULL DEFAULT 'text',      -- ask | answer | clarify | plan | reply | safety | review | route | roundtable
    text        TEXT    NOT NULL DEFAULT '',
    data        TEXT    NOT NULL DEFAULT '{}',
    plan_id     INTEGER,
    created_at  TEXT    NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_cmsg_consult ON consult_message(consult_id, id);

-- 锦囊（每次修改存新版本）
CREATE TABLE IF NOT EXISTS plan (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    consult_id      INTEGER NOT NULL REFERENCES consult(id) ON DELETE CASCADE,
    version         INTEGER NOT NULL,
    content         TEXT    NOT NULL DEFAULT '{}',
    strategy_codes  TEXT    NOT NULL DEFAULT '[]',
    memory_refs     TEXT    NOT NULL DEFAULT '[]',
    prompt_versions TEXT    NOT NULL DEFAULT '{}',
    drill_id        INTEGER,                         -- 由这版锦囊生成的对练场景
    rating          INTEGER,                         -- 用户评价：1 有用 / -1 没用
    rating_reason   TEXT    NOT NULL DEFAULT '',
    rated_at        TEXT,
    created_at      TEXT    NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_plan_consult ON plan(consult_id, version);

CREATE TABLE IF NOT EXISTS plan_action (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    plan_id     INTEGER NOT NULL REFERENCES plan(id) ON DELETE CASCADE,
    text        TEXT    NOT NULL,
    due_hint    TEXT    NOT NULL DEFAULT '',
    done        INTEGER NOT NULL DEFAULT 0,
    result      TEXT    NOT NULL DEFAULT '',
    sort_order  INTEGER NOT NULL DEFAULT 0,
    done_at     TEXT,
    remind_at   TEXT                                  -- 提醒日期 YYYY-MM-DD
);

-- 长期记忆：人物卡 / 事件线的“卡头”
CREATE TABLE IF NOT EXISTS memory_subject (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id     TEXT    NOT NULL,
    kind        TEXT    NOT NULL CHECK (kind IN ('person','case')),
    name        TEXT    NOT NULL,
    aliases     TEXT    NOT NULL DEFAULT '[]',
    summary     TEXT    NOT NULL DEFAULT '',
    status      TEXT    NOT NULL DEFAULT 'open',     -- case: open | done | dormant
    last_seen   TEXT    NOT NULL,
    compacted_at TEXT,                               -- 上次整理（压缩）的时间
    created_at  TEXT    NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_msubject_user ON memory_subject(user_id, kind);

-- 长期记忆：一条一行（profile = 我的档案；fact = 人物卡上的事；event = 事件线进展）
CREATE TABLE IF NOT EXISTS memory_item (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id     TEXT    NOT NULL,
    type        TEXT    NOT NULL CHECK (type IN ('profile','fact','event')),
    subject_id  INTEGER REFERENCES memory_subject(id) ON DELETE CASCADE,
    text        TEXT    NOT NULL,
    source      TEXT    NOT NULL DEFAULT '',          -- 出处：哪次问计 / 训练、哪天
    consult_id  INTEGER,
    pinned      INTEGER NOT NULL DEFAULT 0,
    created_at  TEXT    NOT NULL,
    updated_at  TEXT    NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_mitem_user ON memory_item(user_id, type);

CREATE TABLE IF NOT EXISTS memory_setting (
    user_id     TEXT    PRIMARY KEY,
    paused      INTEGER NOT NULL DEFAULT 0,           -- 默认开启
    updated_at  TEXT    NOT NULL
);
