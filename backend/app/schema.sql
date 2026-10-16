-- AI 沟通训练工具 · SQLite 建表脚本
-- 时间字段统一存本地时间字符串：YYYY-MM-DD HH:MM:SS（时区见 .env 的 APP_TIMEZONE）

CREATE TABLE IF NOT EXISTS category (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    name        TEXT    NOT NULL UNIQUE,
    sort_order  INTEGER NOT NULL DEFAULT 0
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
    sort_order      INTEGER NOT NULL DEFAULT 0
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
    transcript    TEXT    NOT NULL DEFAULT '[]'    -- JSON: [{role:'ai'|'user', text, at}]
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
    created_at      TEXT    NOT NULL
);
