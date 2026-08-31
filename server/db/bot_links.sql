-- Migracao pontual: requer o schema existente. Nao altera tokens/usuarios.
CREATE TABLE IF NOT EXISTS notebooklm.bot_links (
    token_hash TEXT PRIMARY KEY,
    email TEXT NOT NULL REFERENCES notebooklm.users(email) ON DELETE CASCADE,
    expires_at TIMESTAMPTZ NOT NULL,
    usado_em TIMESTAMPTZ,
    criado_em TIMESTAMPTZ DEFAULT now()
);
