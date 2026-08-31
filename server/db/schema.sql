-- Schema: notebooklm
-- Executar como superuser no EasyPanel antes do primeiro deploy

CREATE SCHEMA IF NOT EXISTS notebooklm;

-- Usuários e níveis de acesso
CREATE TABLE IF NOT EXISTS notebooklm.users (
    email        TEXT PRIMARY KEY,
    nome         TEXT,
    nivel        TEXT CHECK (nivel IN ('admin', 'gestor', 'juridico', 'financeiro')),
    skills       TEXT[],         -- RESERVADO: não usado pelo código (não controla acesso)
    api_token    TEXT UNIQUE,    -- HASH SHA-256 do token Bearer (nunca o token em claro)
    ativo        BOOLEAN DEFAULT true,
    criado_em    TIMESTAMPTZ DEFAULT now()
);

-- Tokens criptografados por email (Fernet)
CREATE TABLE IF NOT EXISTS notebooklm.tokens (
    email            TEXT PRIMARY KEY REFERENCES notebooklm.users(email) ON DELETE CASCADE,
    storage_state    TEXT NOT NULL,  -- JSON criptografado com Fernet
    expires_at       TIMESTAMPTZ,    -- RESERVADO: não populado/lido hoje (sem TTL automático)
    atualizado_em    TIMESTAMPTZ DEFAULT now()
);

-- Catálogo de notebooks por área
CREATE TABLE IF NOT EXISTS notebooklm.notebooks (
    id           TEXT PRIMARY KEY,
    titulo       TEXT NOT NULL,
    area         TEXT CHECK (area IN ('juridico', 'financeiro', 'comercial')),
    niveis       TEXT[]  -- RESERVADO: o gate de acesso é só por `area` (get_allowed_notebooks); esta coluna não é lida
);

-- Tokens de onboarding por-usuário (uso único, com expiração).
-- Substituem a connector key COMPARTILHADA no /token/upload: um token vazado
-- só serve para o email a que foi emitido, e só uma vez.
CREATE TABLE IF NOT EXISTS notebooklm.onboarding_tokens (
    token_hash   TEXT PRIMARY KEY,   -- SHA-256 do token one-time (nunca em claro)
    email        TEXT NOT NULL,      -- email para o qual o token é válido
    criado_por   TEXT,               -- admin que emitiu
    expires_at   TIMESTAMPTZ NOT NULL,
    usado_em     TIMESTAMPTZ,        -- NULL até ser consumido (single-use)
    criado_em    TIMESTAMPTZ DEFAULT now()
);

-- Vinculo do bot: separado do onboarding; so para usuarios ja ativos.
CREATE TABLE IF NOT EXISTS notebooklm.bot_links (
    token_hash TEXT PRIMARY KEY,
    email TEXT NOT NULL REFERENCES notebooklm.users(email) ON DELETE CASCADE,
    expires_at TIMESTAMPTZ NOT NULL,
    usado_em TIMESTAMPTZ,
    criado_em TIMESTAMPTZ DEFAULT now()
);

-- Audit log imutável
CREATE TABLE IF NOT EXISTS notebooklm.audit_log (
    id           BIGSERIAL PRIMARY KEY,
    email        TEXT,
    notebook_id  TEXT,
    pergunta     TEXT,
    resposta     TEXT,
    timestamp    TIMESTAMPTZ DEFAULT now()
);

-- Imutabilidade real do audit_log: bloqueia UPDATE e DELETE no nível do banco,
-- não só por convenção. Append-only de verdade (relevante p/ LGPD/trilha).
CREATE OR REPLACE FUNCTION notebooklm.audit_log_append_only()
RETURNS trigger AS $$
BEGIN
    RAISE EXCEPTION '%.% e append-only: % nao permitido',
        TG_TABLE_SCHEMA, TG_TABLE_NAME, TG_OP;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_audit_log_append_only ON notebooklm.audit_log;
CREATE TRIGGER trg_audit_log_append_only
    BEFORE UPDATE OR DELETE ON notebooklm.audit_log
    FOR EACH ROW EXECUTE FUNCTION notebooklm.audit_log_append_only();

-- ── Correlação (IP ↔ conta acessada ↔ cadastro) ────────────────────────────────
-- Idempotente: roda em bancos já existentes sem quebrar.
-- google_account = conta Google real dona da sessão (pode divergir do cadastro).
ALTER TABLE notebooklm.tokens    ADD COLUMN IF NOT EXISTS google_account  TEXT;
-- Enriquecimento do audit para a visão "usos e dados de cada requisição".
ALTER TABLE notebooklm.audit_log ADD COLUMN IF NOT EXISTS ip              TEXT;
ALTER TABLE notebooklm.audit_log ADD COLUMN IF NOT EXISTS session_account TEXT;

-- ── Log de ACESSOS (eventos + IP), append-only — base do painel ─────────────────
-- Registra TODO acesso (não só perguntas): login OAuth, onboarding, upload de
-- sessão, listagens, criações, negações e visualização de teor (break-glass).
CREATE TABLE IF NOT EXISTS notebooklm.access_log (
    id              BIGSERIAL PRIMARY KEY,
    ts              TIMESTAMPTZ DEFAULT now(),
    evento          TEXT NOT NULL,      -- oauth_login|onboarding_emitido|onboarding_consumido|
                                        -- sessao_enviada|pergunta|listagem|criacao|add_fonte|ver_teor|negado
    identity_email  TEXT,               -- quem chamou (OAuth/Bearer)
    session_account TEXT,               -- conta Google cuja sessão foi usada (quando aplica)
    ip              TEXT,
    user_agent      TEXT,
    notebook_id     TEXT,
    resultado       TEXT DEFAULT 'ok',  -- ok | negado | suspeito
    detalhe         TEXT
);

CREATE INDEX IF NOT EXISTS idx_access_log_email ON notebooklm.access_log (identity_email, ts DESC);
CREATE INDEX IF NOT EXISTS idx_access_log_ts    ON notebooklm.access_log (ts DESC);

-- Mesma imutabilidade do audit_log (reusa a função append-only)
DROP TRIGGER IF EXISTS trg_access_log_append_only ON notebooklm.access_log;
CREATE TRIGGER trg_access_log_append_only
    BEFORE UPDATE OR DELETE ON notebooklm.access_log
    FOR EACH ROW EXECUTE FUNCTION notebooklm.audit_log_append_only();

-- TRUNCATE e evento de trigger SEPARADO no Postgres: nao e coberto por
-- "BEFORE UPDATE OR DELETE". Sem isto, `TRUNCATE TABLE notebooklm.audit_log`
-- apaga a trilha inteira sem o trigger reclamar — verificado contra banco real
-- em 12/08/2026, o banco aceitou a operacao nas duas tabelas.
-- Gatilho de TRUNCATE tem que ser FOR EACH STATEMENT: nao existe "linha" a
-- percorrer, entao FOR EACH ROW e recusado na criacao.
DROP TRIGGER IF EXISTS trg_audit_log_no_truncate ON notebooklm.audit_log;
CREATE TRIGGER trg_audit_log_no_truncate
    BEFORE TRUNCATE ON notebooklm.audit_log
    FOR EACH STATEMENT EXECUTE FUNCTION notebooklm.audit_log_append_only();

DROP TRIGGER IF EXISTS trg_access_log_no_truncate ON notebooklm.access_log;
CREATE TRIGGER trg_access_log_no_truncate
    BEFORE TRUNCATE ON notebooklm.access_log
    FOR EACH STATEMENT EXECUTE FUNCTION notebooklm.audit_log_append_only();

-- ── Compartilhamento (fonte de verdade nossa do "de quem é") ────────────────────
-- O objeto Notebook do notebooklm-py 0.6.0 tem `is_owner` (meu vs compartilhado)
-- mas NAO traz o email do dono. Reconstruimos isso enumerando get_status sob a
-- sessao do admin (sincronizar_compartilhamentos). Tabelas MUTAVEIS (sem trigger
-- append-only) — refletem estado atual, nao trilha.
CREATE TABLE IF NOT EXISTS notebooklm.notebook_owners (
    notebook_id  TEXT PRIMARY KEY,
    owner_email  TEXT NOT NULL,
    atualizado_em TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE IF NOT EXISTS notebooklm.notebook_shares (
    notebook_id   TEXT NOT NULL,
    shared_with   TEXT NOT NULL,
    permission    TEXT,                 -- viewer | editor | owner
    view_level    TEXT,                 -- completo | chat
    atualizado_em TIMESTAMPTZ DEFAULT now(),
    PRIMARY KEY (notebook_id, shared_with)
);

CREATE INDEX IF NOT EXISTS idx_notebook_shares_with ON notebooklm.notebook_shares (shared_with);

-- Sem seed de admin: um usuario admin pre-criado no schema seria uma conta com
-- privilegio total cujo dono ninguem controla. O primeiro admin e criado
-- explicitamente no deploy, via server/db/gen_token.py (ver DEPLOY.md, passo 6).
