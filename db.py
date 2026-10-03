"""
資料庫連線層
本地開發：自動使用 SQLite（檔案：freelance_system.db）
雲端部署：從 Streamlit Secrets 讀取 Supabase PostgreSQL 連線
"""

import os
import streamlit as st
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from contextlib import contextmanager

# ---------- 判斷環境，取得連線字串 ----------
def get_database_url():
	"""優先讀取 Streamlit Secrets（雲端），否則用本地 SQLite"""
	try:
		if "DATABASE_URL" in st.secrets:
			return st.secrets["DATABASE_URL"]
	except Exception:
		pass
	return "sqlite:///freelance_system.db"


# ---------- 建立 Engine ----------
@st.cache_resource
def get_engine():
    url = get_database_url()
    if url.startswith("sqlite"):
        return create_engine(url, connect_args={"check_same_thread": False})
    # 加入連線逾時（秒），避免卡死
    return create_engine(
        url,
        pool_pre_ping=True,
        pool_recycle=300,
        connect_args={"connect_timeout": 10},
    )


# ---------- Session 管理 ----------
@contextmanager
def get_session():
	engine = get_engine()
	Session = sessionmaker(bind=engine)
	session = Session()
	try:
		yield session
		session.commit()
	except Exception:
		session.rollback()
		raise
	finally:
		session.close()


# ---------- 初始化資料表 ----------
def init_db():
    """建立資料表，失敗時不讓 App 崩潰"""
    try:
        engine = get_engine()
        with engine.connect() as conn:
            conn.execute(text("""
                CREATE TABLE IF NOT EXISTS users (
                    username    TEXT PRIMARY KEY,
                    password    TEXT NOT NULL,
                    contact     TEXT,
                    amount      TEXT DEFAULT '',
                    last5       TEXT DEFAULT '',
                    status      TEXT DEFAULT '未審核',
                    plan        TEXT DEFAULT 'free',
                    usage_count INTEGER DEFAULT 0,
                    created_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """))
            conn.execute(text("""
                CREATE TABLE IF NOT EXISTS usage_log (
                    id        SERIAL PRIMARY KEY,
                    username  TEXT,
                    filename  TEXT,
                    rows      INTEGER,
                    cols      INTEGER,
                    actions   TEXT,
                    timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """))
            conn.execute(text("""
                CREATE TABLE IF NOT EXISTS feedback (
                    id        SERIAL PRIMARY KEY,
                    username  TEXT,
                    subject   TEXT,
                    message   TEXT,
                    contact   TEXT,
                    status    TEXT DEFAULT '未處理',
                    timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """))
            conn.commit()
    except Exception as e:
        # 印出錯誤但不要讓 App 崩潰
        print(f"[init_db] 資料庫初始化失敗：{e}")

# ---------- 輔助查詢函式 ----------
def fetch_one(query, params=None):
	with get_session() as session:
		result = session.execute(text(query), params or {})
		return result.fetchone()


def fetch_all(query, params=None):
	with get_session() as session:
		result = session.execute(text(query), params or {})
		return result.fetchall()


def execute(query, params=None):
	with get_session() as session:
		session.execute(text(query), params or {})
