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
    sample_script   TEXT    NOT NULL DEFAULT ''    -- 跟读示范稿（首次请求时由 LLM 生成并缓存）
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
