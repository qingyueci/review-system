"""首板布局运行数据库。

本存储只会打开 ``dragon_runtime.db``（或显式传入的路径），用于规则、确认快照、
行情快照、筛选、分析记录和异步任务。历史模型资料由独立的
``DragonKnowledgeStore`` 负责，既有复盘数据库不在此模块的读写范围内。
"""

from __future__ import annotations

from datetime import date, datetime
import json
import os
from pathlib import Path
import sqlite3
from typing import Any, Iterable

from .schemas import (
    CandidateScreeningResult,
    AttributeAliasInput,
    AttributeAliasVersion,
    AttributeAliasVersionCreateRequest,
    DragonAnalysisRecord,
    DragonJob,
    MarketSnapshot,
    ReviewSnapshot,
    ReviewSnapshotInput,
    RuleDefinition,
    RuleDefinitionInput,
    RuleVersion,
    RuleVersionCreateRequest,
)


def _isolated_runtime_path(path: str | Path) -> Path:
    normalized = Path(path).expanduser().resolve()
    if normalized.name.casefold() != "dragon_runtime.db":
        raise ValueError(
            f"首板布局运行库必须使用 dragon_runtime.db，不能使用 {normalized.name}"
        )
    return normalized


def default_runtime_db_path() -> Path:
    """返回首板模块自己的默认运行库路径。"""

    configured = os.getenv("DRAGON_RUNTIME_DB", "").strip()
    if configured:
        return _isolated_runtime_path(configured)
    # 复用本机 data 目录位置，但不复用已有任何数据库文件。
    from ..config import DATA_DIR

    return _isolated_runtime_path(Path(DATA_DIR) / "dragon_runtime.db")


def _now() -> datetime:
    return datetime.now().replace(microsecond=0)


def _dump(value: Any) -> str:
    if hasattr(value, "model_dump"):
        value = value.model_dump(mode="json")
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), default=str)


def _load(value: str | None, fallback: Any) -> Any:
    if not value:
        return fallback
    return json.loads(value)


def _review_snapshot_from_row(row: sqlite3.Row) -> ReviewSnapshot:
    """以数据库状态列覆盖 JSON，避免旧快照反确认后仍显示已确认。"""

    payload = _load(row["snapshot_json"], {})
    confirmed = bool(row["is_confirmed"])
    payload.update(
        {
            "snapshot_id": row["snapshot_id"],
            "trade_date": row["trade_date"],
            "is_confirmed": confirmed,
            "confirm_as_layout": confirmed,
            "confirmed_at": row["confirmed_at"] if confirmed else None,
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
        }
    )
    return ReviewSnapshot.model_validate(payload)


class DragonRuntimeStore:
    """SQLite 持久层；连接按操作创建，适合 FastAPI 后台线程并发使用。"""

    def __init__(self, path: str | Path | None = None) -> None:
        self.path = _isolated_runtime_path(path) if path is not None else default_runtime_db_path()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=10)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys=ON")
        return connection

    def _initialize(self) -> None:
        with self._connect() as connection:
            connection.executescript(
                """
                PRAGMA journal_mode=WAL;

                CREATE TABLE IF NOT EXISTS dragon_rule_versions (
                    version_id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    note TEXT NOT NULL DEFAULT '',
                    is_active INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS dragon_rules (
                    rule_id TEXT PRIMARY KEY,
                    version_id TEXT NOT NULL,
                    position INTEGER NOT NULL DEFAULT 0,
                    name TEXT NOT NULL,
                    data_field TEXT NOT NULL,
                    calculation TEXT NOT NULL DEFAULT '',
                    comparison TEXT NOT NULL,
                    threshold_json TEXT,
                    hard_condition INTEGER NOT NULL DEFAULT 0,
                    missing_policy TEXT NOT NULL DEFAULT '保留',
                    enabled INTEGER NOT NULL DEFAULT 1,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    FOREIGN KEY(version_id) REFERENCES dragon_rule_versions(version_id)
                );
                CREATE INDEX IF NOT EXISTS idx_dragon_rules_version
                ON dragon_rules(version_id, position, rule_id);

                CREATE TABLE IF NOT EXISTS dragon_attribute_alias_versions (
                    version_id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    note TEXT NOT NULL DEFAULT '',
                    aliases_json TEXT NOT NULL DEFAULT '[]',
                    is_active INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_dragon_attribute_alias_versions_active
                ON dragon_attribute_alias_versions(is_active, created_at DESC);

                CREATE TABLE IF NOT EXISTS dragon_review_snapshots (
                    snapshot_id TEXT PRIMARY KEY,
                    trade_date TEXT NOT NULL,
                    snapshot_json TEXT NOT NULL,
                    is_confirmed INTEGER NOT NULL DEFAULT 0,
                    confirmed_at TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_dragon_review_snapshots_date
                ON dragon_review_snapshots(trade_date, is_confirmed, updated_at DESC);

                CREATE TABLE IF NOT EXISTS dragon_market_snapshots (
                    market_snapshot_id TEXT PRIMARY KEY,
                    trade_date TEXT NOT NULL,
                    provider_name TEXT NOT NULL DEFAULT '',
                    snapshot_json TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_dragon_market_snapshots_date
                ON dragon_market_snapshots(trade_date, created_at DESC);

                CREATE TABLE IF NOT EXISTS dragon_screening_runs (
                    screening_id TEXT PRIMARY KEY,
                    market_snapshot_id TEXT NOT NULL,
                    trade_date TEXT NOT NULL,
                    rule_version_id TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL,
                    FOREIGN KEY(market_snapshot_id)
                        REFERENCES dragon_market_snapshots(market_snapshot_id)
                );
                CREATE INDEX IF NOT EXISTS idx_dragon_screening_runs_date
                ON dragon_screening_runs(trade_date, created_at DESC);

                CREATE TABLE IF NOT EXISTS dragon_screening_results (
                    screening_id TEXT NOT NULL,
                    stock_code TEXT NOT NULL,
                    result_json TEXT NOT NULL,
                    PRIMARY KEY(screening_id, stock_code),
                    FOREIGN KEY(screening_id)
                        REFERENCES dragon_screening_runs(screening_id) ON DELETE CASCADE
                );

                CREATE TABLE IF NOT EXISTS dragon_jobs (
                    job_id TEXT PRIMARY KEY,
                    kind TEXT NOT NULL,
                    status TEXT NOT NULL,
                    trade_date TEXT,
                    message TEXT NOT NULL DEFAULT '',
                    current_step INTEGER NOT NULL DEFAULT 0,
                    total_steps INTEGER NOT NULL DEFAULT 0,
                    payload_json TEXT NOT NULL DEFAULT '{}',
                    result_json TEXT NOT NULL DEFAULT '{}',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_dragon_jobs_updated
                ON dragon_jobs(updated_at DESC);

                CREATE TABLE IF NOT EXISTS dragon_analysis_records (
                    analysis_id TEXT PRIMARY KEY,
                    job_id TEXT NOT NULL DEFAULT '',
                    trade_date TEXT NOT NULL,
                    stock_code TEXT NOT NULL,
                    stock_name TEXT NOT NULL,
                    basic_pass INTEGER NOT NULL,
                    rule_version_id TEXT NOT NULL DEFAULT '',
                    snapshot_id TEXT NOT NULL DEFAULT '',
                    result_json TEXT NOT NULL,
                    context_json TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_dragon_analysis_records_date
                ON dragon_analysis_records(trade_date DESC, created_at DESC);
                CREATE INDEX IF NOT EXISTS idx_dragon_analysis_records_stock
                ON dragon_analysis_records(stock_code, created_at DESC);

                CREATE TABLE IF NOT EXISTS dragon_batch_audits (
                    job_id TEXT PRIMARY KEY,
                    policy_json TEXT NOT NULL DEFAULT '{}',
                    audit_json TEXT NOT NULL DEFAULT '{}',
                    status TEXT NOT NULL,
                    error TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    FOREIGN KEY(job_id) REFERENCES dragon_jobs(job_id) ON DELETE CASCADE
                );
                """
            )

    def __enter__(self) -> "DragonRuntimeStore":
        return self

    def __exit__(self, *_args: object) -> None:
        # 每个方法都短连接，无需在上下文退出时关闭共享连接。
        return None

    # --- 规则版本 ---------------------------------------------------------

    def save_rule_version(
        self,
        payload: RuleVersion | RuleVersionCreateRequest | Iterable[RuleDefinitionInput | RuleDefinition],
        *,
        name: str | None = None,
        note: str = "",
        activate: bool = True,
    ) -> RuleVersion:
        """保存一份不可变规则版本；“修改规则”应创建新的版本记录。"""

        now = _now()
        if isinstance(payload, RuleVersion):
            version = payload.model_copy(
                update={
                    "created_at": payload.created_at or now,
                    "is_active": activate,
                }
            )
            input_rules = version.rules
        elif isinstance(payload, RuleVersionCreateRequest):
            activate = payload.activate
            version = RuleVersion(
                name=payload.name,
                note=payload.note,
                is_active=activate,
                created_at=now,
            )
            input_rules = payload.rules
        else:
            if not name:
                raise ValueError("保存规则版本需要名称")
            version = RuleVersion(name=name, note=note, is_active=activate, created_at=now)
            input_rules = list(payload)

        assigned_rules: list[RuleDefinition] = []
        for position, item in enumerate(input_rules):
            rule = (
                item
                if isinstance(item, RuleDefinition)
                else RuleDefinition.model_validate(item.model_dump())
            )
            assigned_rules.append(
                rule.model_copy(
                    update={
                        "version_id": version.version_id,
                        "position": position,
                        "created_at": rule.created_at or now,
                        "updated_at": now,
                    }
                )
            )
        version = version.model_copy(update={"rules": assigned_rules})

        with self._connect() as connection:
            if activate:
                connection.execute("UPDATE dragon_rule_versions SET is_active = 0")
            connection.execute(
                """
                INSERT INTO dragon_rule_versions(version_id, name, note, is_active, created_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    version.version_id,
                    version.name,
                    version.note,
                    int(version.is_active),
                    version.created_at.isoformat(),
                ),
            )
            connection.executemany(
                """
                INSERT INTO dragon_rules(
                    rule_id, version_id, position, name, data_field, calculation,
                    comparison, threshold_json, hard_condition, missing_policy, enabled,
                    created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    (
                        rule.rule_id,
                        rule.version_id,
                        rule.position,
                        rule.name,
                        rule.data_field,
                        rule.calculation,
                        rule.comparison,
                        _dump(rule.threshold),
                        int(rule.hard_condition),
                        rule.missing_policy,
                        int(rule.enabled),
                        rule.created_at.isoformat() if rule.created_at else now.isoformat(),
                        rule.updated_at.isoformat() if rule.updated_at else now.isoformat(),
                    )
                    for rule in assigned_rules
                ],
            )
        return version

    # 兼容路由层更直观的命名。
    create_rule_version = save_rule_version

    def _rules_for_version(self, connection: sqlite3.Connection, version_id: str) -> list[RuleDefinition]:
        rows = connection.execute(
            """
            SELECT * FROM dragon_rules
            WHERE version_id = ?
            ORDER BY position ASC, rule_id ASC
            """,
            (version_id,),
        ).fetchall()
        return [
            RuleDefinition(
                rule_id=row["rule_id"],
                version_id=row["version_id"],
                position=row["position"],
                name=row["name"],
                data_field=row["data_field"],
                calculation=row["calculation"],
                comparison=row["comparison"],
                threshold=_load(row["threshold_json"], None),
                hard_condition=bool(row["hard_condition"]),
                missing_policy=row["missing_policy"],
                enabled=bool(row["enabled"]),
                created_at=datetime.fromisoformat(row["created_at"]),
                updated_at=datetime.fromisoformat(row["updated_at"]),
            )
            for row in rows
        ]

    def list_rule_versions(self, limit: int = 100) -> list[RuleVersion]:
        safe_limit = max(1, min(limit, 500))
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT * FROM dragon_rule_versions
                ORDER BY created_at DESC
                LIMIT ?
                """,
                (safe_limit,),
            ).fetchall()
            return [
                RuleVersion(
                    version_id=row["version_id"],
                    name=row["name"],
                    note=row["note"],
                    is_active=bool(row["is_active"]),
                    created_at=datetime.fromisoformat(row["created_at"]),
                    rules=self._rules_for_version(connection, row["version_id"]),
                )
                for row in rows
            ]

    def get_rule_version(self, version_id: str) -> RuleVersion | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM dragon_rule_versions WHERE version_id = ?", (version_id,)
            ).fetchone()
            if row is None:
                return None
            return RuleVersion(
                version_id=row["version_id"],
                name=row["name"],
                note=row["note"],
                is_active=bool(row["is_active"]),
                created_at=datetime.fromisoformat(row["created_at"]),
                rules=self._rules_for_version(connection, row["version_id"]),
            )

    def get_active_rule_version(self) -> RuleVersion | None:
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT * FROM dragon_rule_versions
                WHERE is_active = 1
                ORDER BY created_at DESC
                LIMIT 1
                """
            ).fetchone()
            if row is None:
                return None
            return RuleVersion(
                version_id=row["version_id"],
                name=row["name"],
                note=row["note"],
                is_active=True,
                created_at=datetime.fromisoformat(row["created_at"]),
                rules=self._rules_for_version(connection, row["version_id"]),
            )

    def ensure_confirmed_default_rules(self) -> RuleVersion:
        """在新运行库首次使用时写入已确认的基础硬规则版本。

        这是显式的一次性初始化，不会覆盖用户已经保存的规则版本。
        """

        active = self.get_active_rule_version()
        if active is not None:
            return active
        from .field_registry import default_hard_rule_inputs

        return self.save_rule_version(
            default_hard_rule_inputs(),
            name="首板基础标准 v1（已确认）",
            note="用户确认：主板普通10cm、首板双重确认、时间窗口、封单额、流通市值、13:00后炸板。",
            activate=True,
        )

    def set_active_rule_version(self, version_id: str) -> RuleVersion:
        with self._connect() as connection:
            exists = connection.execute(
                "SELECT 1 FROM dragon_rule_versions WHERE version_id = ?", (version_id,)
            ).fetchone()
            if not exists:
                raise KeyError(f"规则版本不存在：{version_id}")
            connection.execute("UPDATE dragon_rule_versions SET is_active = 0")
            connection.execute(
                "UPDATE dragon_rule_versions SET is_active = 1 WHERE version_id = ?",
                (version_id,),
            )
        result = self.get_rule_version(version_id)
        if result is None:  # pragma: no cover - 仅防止外部并发删除
            raise KeyError(f"规则版本不存在：{version_id}")
        return result

    def delete_rule_version(self, version_id: str) -> None:
        """删除未启用且未被历史结果引用的规则版本。"""

        with self._connect() as connection:
            row = connection.execute(
                "SELECT is_active FROM dragon_rule_versions WHERE version_id = ?",
                (version_id,),
            ).fetchone()
            if row is None:
                raise KeyError(f"规则版本不存在：{version_id}")
            if bool(row["is_active"]):
                raise ValueError("当前启用的规则版本需先切换到其他版本后再删除")
            referenced = connection.execute(
                """
                SELECT 1 FROM dragon_screening_runs WHERE rule_version_id = ?
                UNION ALL
                SELECT 1 FROM dragon_analysis_records WHERE rule_version_id = ?
                LIMIT 1
                """,
                (version_id, version_id),
            ).fetchone()
            if referenced is not None:
                raise ValueError("该规则版本已有筛选或分析记录，需保留作为历史依据")
            connection.execute("DELETE FROM dragon_rules WHERE version_id = ?", (version_id,))
            connection.execute("DELETE FROM dragon_rule_versions WHERE version_id = ?", (version_id,))

    def list_rules(self, version_id: str | None = None, *, enabled_only: bool = False) -> list[RuleDefinition]:
        if version_id is None:
            active = self.get_active_rule_version()
            return [rule for rule in (active.rules if active else []) if rule.enabled or not enabled_only]
        version = self.get_rule_version(version_id)
        if version is None:
            return []
        return [rule for rule in version.rules if rule.enabled or not enabled_only]

    def save_attribute_alias_version(
        self,
        payload: AttributeAliasVersion | AttributeAliasVersionCreateRequest | Iterable[AttributeAliasInput],
        *,
        name: str | None = None,
        note: str = "",
        activate: bool = True,
    ) -> AttributeAliasVersion:
        """保存人工维护的精确别名表；不做自动语义合并。"""

        now = _now()
        if isinstance(payload, AttributeAliasVersion):
            version = payload.model_copy(update={"created_at": payload.created_at or now, "is_active": activate})
        elif isinstance(payload, AttributeAliasVersionCreateRequest):
            version = AttributeAliasVersion(
                name=payload.name, note=payload.note, aliases=payload.aliases,
                is_active=payload.activate, created_at=now,
            )
            activate = payload.activate
        else:
            if not name:
                raise ValueError("保存属性别名版本需要名称")
            version = AttributeAliasVersion(name=name, note=note, aliases=list(payload), is_active=activate, created_at=now)
        with self._connect() as connection:
            if activate:
                connection.execute("UPDATE dragon_attribute_alias_versions SET is_active = 0")
            connection.execute(
                """INSERT INTO dragon_attribute_alias_versions(version_id, name, note, aliases_json, is_active, created_at)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (version.version_id, version.name, version.note, _dump(version.aliases), int(version.is_active), version.created_at.isoformat()),
            )
        return version

    def list_attribute_alias_versions(self, limit: int = 100) -> list[AttributeAliasVersion]:
        safe_limit = max(1, min(limit, 500))
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT * FROM dragon_attribute_alias_versions ORDER BY created_at DESC LIMIT ?", (safe_limit,)
            ).fetchall()
        return [self._alias_version_from_row(row) for row in rows]

    def get_active_attribute_alias_version(self) -> AttributeAliasVersion | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM dragon_attribute_alias_versions WHERE is_active = 1 ORDER BY created_at DESC LIMIT 1"
            ).fetchone()
        return self._alias_version_from_row(row) if row else None

    def get_attribute_alias_version(self, version_id: str) -> AttributeAliasVersion | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM dragon_attribute_alias_versions WHERE version_id = ?", (version_id,)
            ).fetchone()
        return self._alias_version_from_row(row) if row else None

    def set_active_attribute_alias_version(self, version_id: str) -> AttributeAliasVersion:
        with self._connect() as connection:
            if connection.execute("SELECT 1 FROM dragon_attribute_alias_versions WHERE version_id = ?", (version_id,)).fetchone() is None:
                raise KeyError(f"属性别名版本不存在：{version_id}")
            connection.execute("UPDATE dragon_attribute_alias_versions SET is_active = 0")
            connection.execute("UPDATE dragon_attribute_alias_versions SET is_active = 1 WHERE version_id = ?", (version_id,))
        result = self.get_attribute_alias_version(version_id)
        if result is None:  # pragma: no cover
            raise KeyError(f"属性别名版本不存在：{version_id}")
        return result

    @staticmethod
    def _alias_version_from_row(row: sqlite3.Row) -> AttributeAliasVersion:
        aliases = _load(row["aliases_json"], [])
        return AttributeAliasVersion(
            version_id=row["version_id"], name=row["name"], note=row["note"],
            aliases=[AttributeAliasInput.model_validate(item) for item in aliases],
            is_active=bool(row["is_active"]), created_at=datetime.fromisoformat(row["created_at"]),
        )

    # --- 当日复盘结论快照 -------------------------------------------------

    def save_review_snapshot(
        self,
        payload: ReviewSnapshotInput | ReviewSnapshot,
        *,
        confirm: bool | None = None,
    ) -> ReviewSnapshot:
        """写入一个新快照；确认时同一交易日只保留一个有效确认版本。"""

        now = _now()
        requested_confirmation = (
            confirm
            if confirm is not None
            else (payload.is_confirmed if isinstance(payload, ReviewSnapshot) else payload.confirm_as_layout)
        )
        if isinstance(payload, ReviewSnapshot):
            snapshot = payload.model_copy(
                update={
                    "is_confirmed": requested_confirmation,
                    "confirmed_at": now if requested_confirmation else None,
                    "created_at": payload.created_at or now,
                    "updated_at": now,
                    "confirm_as_layout": requested_confirmation,
                }
            )
        else:
            snapshot = ReviewSnapshot(
                **payload.model_dump(),
                is_confirmed=requested_confirmation,
                confirmed_at=now if requested_confirmation else None,
                created_at=now,
                updated_at=now,
            )

        with self._connect() as connection:
            if snapshot.is_confirmed:
                previous_rows = connection.execute(
                    """
                    SELECT * FROM dragon_review_snapshots
                    WHERE trade_date = ? AND is_confirmed = 1
                    """,
                    (snapshot.trade_date.isoformat(),),
                ).fetchall()
                for row in previous_rows:
                    previous = _review_snapshot_from_row(row).model_copy(
                        update={
                            "is_confirmed": False,
                            "confirm_as_layout": False,
                            "confirmed_at": None,
                            "updated_at": now,
                        }
                    )
                    connection.execute(
                        """
                        UPDATE dragon_review_snapshots
                        SET snapshot_json = ?, is_confirmed = 0, confirmed_at = NULL,
                            updated_at = ?
                        WHERE snapshot_id = ?
                        """,
                        (_dump(previous), now.isoformat(), row["snapshot_id"]),
                    )
            connection.execute(
                """
                INSERT INTO dragon_review_snapshots(
                    snapshot_id, trade_date, snapshot_json, is_confirmed, confirmed_at,
                    created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    snapshot.snapshot_id,
                    snapshot.trade_date.isoformat(),
                    _dump(snapshot),
                    int(snapshot.is_confirmed),
                    snapshot.confirmed_at.isoformat() if snapshot.confirmed_at else None,
                    snapshot.created_at.isoformat() if snapshot.created_at else now.isoformat(),
                    snapshot.updated_at.isoformat() if snapshot.updated_at else now.isoformat(),
                ),
            )
        return snapshot

    def get_review_snapshot(
        self, trade_date: date | str, *, confirmed_only: bool = False
    ) -> ReviewSnapshot | None:
        normalized_date = date.fromisoformat(str(trade_date)[:10]).isoformat()
        query = "SELECT rowid AS _rowid, * FROM dragon_review_snapshots WHERE trade_date = ?"
        params: list[Any] = [normalized_date]
        if confirmed_only:
            query += " AND is_confirmed = 1"
        query += " ORDER BY updated_at DESC, _rowid DESC LIMIT 1"
        with self._connect() as connection:
            row = connection.execute(query, params).fetchone()
        return _review_snapshot_from_row(row) if row else None

    def list_review_snapshots(
        self, *, trade_date: date | str | None = None, limit: int = 100
    ) -> list[ReviewSnapshot]:
        safe_limit = max(1, min(limit, 500))
        query = "SELECT rowid AS _rowid, * FROM dragon_review_snapshots"
        params: list[Any] = []
        if trade_date is not None:
            query += " WHERE trade_date = ?"
            params.append(date.fromisoformat(str(trade_date)[:10]).isoformat())
        query += " ORDER BY updated_at DESC, _rowid DESC LIMIT ?"
        params.append(safe_limit)
        with self._connect() as connection:
            rows = connection.execute(query, params).fetchall()
        return [_review_snapshot_from_row(row) for row in rows]

    # --- 行情与基础筛选快照 -----------------------------------------------

    def save_market_snapshot(self, snapshot: MarketSnapshot) -> MarketSnapshot:
        for candidate in snapshot.candidates:
            if candidate.trade_date != snapshot.trade_date:
                raise ValueError("行情快照中的候选交易日期必须一致")
        now = snapshot.created_at or _now()
        normalized = snapshot.model_copy(update={"created_at": now})
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO dragon_market_snapshots(
                    market_snapshot_id, trade_date, provider_name, snapshot_json, created_at
                ) VALUES (?, ?, ?, ?, ?)
                """,
                (
                    normalized.market_snapshot_id,
                    normalized.trade_date.isoformat(),
                    normalized.provider_name,
                    _dump(normalized),
                    now.isoformat(),
                ),
            )
        return normalized

    def get_market_snapshot(self, market_snapshot_id: str) -> MarketSnapshot | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT snapshot_json FROM dragon_market_snapshots WHERE market_snapshot_id = ?",
                (market_snapshot_id,),
            ).fetchone()
        return MarketSnapshot.model_validate(_load(row["snapshot_json"], {})) if row else None

    def latest_market_snapshot(self, trade_date: date | str) -> MarketSnapshot | None:
        normalized_date = date.fromisoformat(str(trade_date)[:10]).isoformat()
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT snapshot_json FROM dragon_market_snapshots
                WHERE trade_date = ?
                ORDER BY created_at DESC
                LIMIT 1
                """,
                (normalized_date,),
            ).fetchone()
        return MarketSnapshot.model_validate(_load(row["snapshot_json"], {})) if row else None

    def save_screening_results(
        self,
        market_snapshot_id: str,
        results: Iterable[CandidateScreeningResult],
        *,
        rule_version_id: str = "",
    ) -> str:
        results = list(results)
        market = self.get_market_snapshot(market_snapshot_id)
        if market is None:
            raise KeyError(f"行情快照不存在：{market_snapshot_id}")
        now = _now()
        screening_id = f"screening_{now.strftime('%Y%m%d%H%M%S%f')}"
        effective_version = rule_version_id or (results[0].rule_version_id if results else "")
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO dragon_screening_runs(
                    screening_id, market_snapshot_id, trade_date, rule_version_id, created_at
                ) VALUES (?, ?, ?, ?, ?)
                """,
                (
                    screening_id,
                    market_snapshot_id,
                    market.trade_date.isoformat(),
                    effective_version,
                    now.isoformat(),
                ),
            )
            connection.executemany(
                """
                INSERT INTO dragon_screening_results(screening_id, stock_code, result_json)
                VALUES (?, ?, ?)
                """,
                [
                    (screening_id, result.candidate.stock_code, _dump(result))
                    for result in results
                ],
            )
        return screening_id

    def latest_screening_results(
        self, trade_date: date | str
    ) -> tuple[str, list[CandidateScreeningResult]] | None:
        normalized_date = date.fromisoformat(str(trade_date)[:10]).isoformat()
        with self._connect() as connection:
            run = connection.execute(
                """
                SELECT screening_id FROM dragon_screening_runs
                WHERE trade_date = ?
                ORDER BY created_at DESC
                LIMIT 1
                """,
                (normalized_date,),
            ).fetchone()
            if run is None:
                return None
            rows = connection.execute(
                """
                SELECT result_json FROM dragon_screening_results
                WHERE screening_id = ?
                ORDER BY stock_code ASC
                """,
                (run["screening_id"],),
            ).fetchall()
        return (
            run["screening_id"],
            [CandidateScreeningResult.model_validate(_load(row["result_json"], {})) for row in rows],
        )

    # --- 异步任务与分析记录 ------------------------------------------------

    def create_job(
        self,
        *,
        kind: str = "analysis",
        trade_date: date | None = None,
        payload: dict[str, Any] | None = None,
        total: int = 0,
    ) -> DragonJob:
        now = _now()
        job = DragonJob(
            kind=kind,
            trade_date=trade_date,
            payload=payload or {},
            total=total,
            created_at=now,
            updated_at=now,
        )
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO dragon_jobs(
                    job_id, kind, status, trade_date, message, current_step, total_steps,
                    payload_json, result_json, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    job.job_id,
                    job.kind,
                    job.status,
                    job.trade_date.isoformat() if job.trade_date else None,
                    job.message,
                    job.current,
                    job.total,
                    _dump(job.payload),
                    _dump(job.result),
                    now.isoformat(),
                    now.isoformat(),
                ),
            )
        return job

    def get_job(self, job_id: str) -> DragonJob | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM dragon_jobs WHERE job_id = ?", (job_id,)
            ).fetchone()
        return self._job_from_row(row) if row else None

    def update_job(
        self,
        job_id: str,
        *,
        status: str | None = None,
        message: str | None = None,
        current: int | None = None,
        total: int | None = None,
        result: dict[str, Any] | None = None,
    ) -> DragonJob:
        job = self.get_job(job_id)
        if job is None:
            raise KeyError(f"首板布局任务不存在：{job_id}")
        update: dict[str, Any] = {"updated_at": _now()}
        if status is not None:
            update["status"] = status
        if message is not None:
            update["message"] = message
        if current is not None:
            update["current"] = current
        if total is not None:
            update["total"] = total
        if result is not None:
            update["result"] = result
        try:
            updated = job.model_copy(update=update)
            # 立即触发模型校验，避免持久化未知状态。
            updated = DragonJob.model_validate(updated.model_dump())
        except Exception as exc:
            raise ValueError(f"任务状态更新无效：{exc}") from exc
        with self._connect() as connection:
            connection.execute(
                """
                UPDATE dragon_jobs
                SET status = ?, message = ?, current_step = ?, total_steps = ?,
                    result_json = ?, updated_at = ?
                WHERE job_id = ?
                """,
                (
                    updated.status,
                    updated.message,
                    updated.current,
                    updated.total,
                    _dump(updated.result),
                    updated.updated_at.isoformat() if updated.updated_at else _now().isoformat(),
                    job_id,
                ),
            )
        return updated

    def _job_from_row(self, row: sqlite3.Row) -> DragonJob:
        return DragonJob(
            job_id=row["job_id"],
            kind=row["kind"],
            status=row["status"],
            trade_date=date.fromisoformat(row["trade_date"]) if row["trade_date"] else None,
            message=row["message"],
            current=row["current_step"],
            total=row["total_steps"],
            payload=_load(row["payload_json"], {}),
            result=_load(row["result_json"], {}),
            created_at=datetime.fromisoformat(row["created_at"]),
            updated_at=datetime.fromisoformat(row["updated_at"]),
        )

    def save_batch_audit(
        self,
        job_id: str,
        *,
        policy: dict[str, Any],
        audit: dict[str, Any],
        status: str,
        error: str = "",
    ) -> None:
        now = _now().isoformat()
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO dragon_batch_audits(
                    job_id, policy_json, audit_json, status, error, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(job_id) DO UPDATE SET
                    policy_json=excluded.policy_json,
                    audit_json=excluded.audit_json,
                    status=excluded.status,
                    error=excluded.error,
                    updated_at=excluded.updated_at
                """,
                (job_id, _dump(policy), _dump(audit), status, error[:4_000], now, now),
            )

    def get_batch_audit(self, job_id: str) -> dict[str, Any] | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM dragon_batch_audits WHERE job_id = ?", (job_id,)
            ).fetchone()
        if row is None:
            return None
        return {
            "job_id": row["job_id"],
            "policy": _load(row["policy_json"], {}),
            "audit": _load(row["audit_json"], {}),
            "status": row["status"],
            "error": row["error"],
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
        }

    def save_analysis_record(self, record: DragonAnalysisRecord) -> DragonAnalysisRecord:
        now = record.created_at or _now()
        normalized = record.model_copy(update={"created_at": now})
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO dragon_analysis_records(
                    analysis_id, job_id, trade_date, stock_code, stock_name, basic_pass,
                    rule_version_id, snapshot_id, result_json, context_json, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    normalized.analysis_id,
                    normalized.job_id,
                    normalized.trade_date.isoformat(),
                    normalized.stock_code,
                    normalized.stock_name,
                    int(normalized.basic_pass),
                    normalized.rule_version_id,
                    normalized.snapshot_id,
                    _dump(normalized.result),
                    _dump(normalized.context),
                    now.isoformat(),
                ),
            )
        return normalized

    # 短名称方便在路由层调用。
    save_analysis = save_analysis_record

    def get_analysis(self, analysis_id: str) -> DragonAnalysisRecord | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM dragon_analysis_records WHERE analysis_id = ?", (analysis_id,)
            ).fetchone()
        return self._analysis_from_row(row) if row else None

    def list_analyses(
        self, *, trade_date: date | str | None = None, limit: int = 30
    ) -> list[DragonAnalysisRecord]:
        safe_limit = max(1, min(limit, 200))
        query = "SELECT * FROM dragon_analysis_records"
        params: list[Any] = []
        if trade_date is not None:
            query += " WHERE trade_date = ?"
            params.append(date.fromisoformat(str(trade_date)[:10]).isoformat())
        query += " ORDER BY created_at DESC LIMIT ?"
        params.append(safe_limit)
        with self._connect() as connection:
            rows = connection.execute(query, params).fetchall()
        return [self._analysis_from_row(row) for row in rows]

    def _analysis_from_row(self, row: sqlite3.Row) -> DragonAnalysisRecord:
        result = _load(row["result_json"], {})
        context = _load(row["context_json"], {})
        return DragonAnalysisRecord.model_validate(
            {
                "analysis_id": row["analysis_id"],
                "job_id": row["job_id"],
                "trade_date": row["trade_date"],
                "stock_code": row["stock_code"],
                "stock_name": row["stock_name"],
                "basic_pass": bool(row["basic_pass"]),
                "rule_version_id": row["rule_version_id"],
                "snapshot_id": row["snapshot_id"],
                "result": result,
                "context": context,
                "created_at": row["created_at"],
            }
        )

    def stats(self) -> dict[str, Any]:
        """独立运行库的轻量状态，供 `/api/dragon/status` 展示。"""

        tables = {
            "rule_versions": "dragon_rule_versions",
            "rules": "dragon_rules",
            "attribute_alias_versions": "dragon_attribute_alias_versions",
            "review_snapshots": "dragon_review_snapshots",
            "confirmed_snapshots": "dragon_review_snapshots WHERE is_confirmed = 1",
            "market_snapshots": "dragon_market_snapshots",
            "screening_runs": "dragon_screening_runs",
            "analysis_records": "dragon_analysis_records",
            "jobs": "dragon_jobs",
        }
        with self._connect() as connection:
            result = {
                key: int(connection.execute(f"SELECT COUNT(*) FROM {target}").fetchone()[0])
                for key, target in tables.items()
            }
        return {
            "database_path": str(self.path),
            "database_name": self.path.name,
            **result,
        }
