import json
import logging
import os
import re
import time
from itertools import chain
from typing import Any, Callable, Dict, List, Optional
import pandas as pd
import requests

logger = logging.getLogger(__name__)


class Notion:
    """Generic Notion API wrapper supporting DataFrame synchronization."""

    def __init__(self, token: Optional[str] = None):
        self.NOTION_TOKEN = token or os.environ.get("NOTION_TOKEN", "")
        self.headers = {
            "Authorization": f"Bearer {self.NOTION_TOKEN}",
            "Content-Type": "application/json",
            "Notion-Version": "2022-06-28",
        }
        self.accessor: Dict[str, Callable[[Any], Any]] = {
            "date": lambda x: x["start"] if x else None,
            "rich_text": lambda x: x[0]["text"]["content"] if (x and len(x) > 0 and "text" in x[0]) else None,
            "number": lambda x: x if x is not None else None,
            "relation": lambda x: x[0]["id"] if (x and len(x) > 0 and "id" in x[0]) else None,
            "unique_id": lambda x: (
                (x["prefix"] + str(x["number"])) if (x and x.get("prefix")) else (str(x["number"]) if x and "number" in x else None)
            ),
            "title": lambda x: x[0]["text"]["content"] if (x and len(x) > 0 and "text" in x[0]) else None,
            "select": lambda x: x["name"] if x else None,
            "status": lambda x: x["name"] if x else None,
            "rollup": lambda x: self.find_rollup(x),
            "formula": lambda x: self.find_formula(x),
            "email": lambda x: x if x else None,
            "phone_number": lambda x: x if x else None,
            "url": lambda x: x if x else None,
            "checkbox": lambda x: x if x is not None else False,
        }
        self.mutator: Dict[str, Callable[[Any], Any]] = {
            "number": lambda x: x,
            "date": lambda x: {"start": x, "end": None, "time_zone": None} if x is not None else None,
            "rich_text": lambda x: [{"text": {"content": x}}] if x is not None else [],
            "status": lambda x: {"name": x} if x is not None else None,
        }
        self.constants = ["formula"]
        self.database_id = ""
        self.schemas: Dict[str, str] = {}
        self.relations: Optional[Dict[str, Any]] = None
        self.origin: Dict[str, Any] = {}
        self._df: Optional[pd.DataFrame] = None
        self._merged_df: Optional[pd.DataFrame] = None
        self.table_name = ""

    def find_formula(self, data: Optional[Dict[str, Any]]) -> Any:
        if not data:
            return None
        supported = ["number", "string"]
        formula_type = data.get("type")
        if formula_type not in supported:
            logger.warning("data formula - %s not supported. returning None", formula_type)
            return None
        return data.get(formula_type)

    def find_rollup(self, column: str) -> str:
        if not self.relations or column not in self.relations:
            raise ValueError(f'rollup column "{column}" not defined in Table relations.')
        target_table_id = id(self.relations[column]["from_table"])
        related = [
            c for c in self.relations
            if id(self.relations[c]["from_table"]) == target_table_id
        ]
        return related[0]

    def reads(self) -> None:
        url = f"https://api.notion.com/v1/databases/{self.database_id}/query"
        resp = requests.post(url, headers=self.headers)
        if resp.status_code != 200:
            logger.error("Failed to query database %s: <%s> %s", self.database_id, resp.status_code, resp.text)
            resp.raise_for_status()
        self.origin = resp.json()
        while self.origin.get("has_more"):
            payload = {
                "page_size": 100,
                "start_cursor": self.origin.get("next_cursor"),
            }
            r = requests.post(url, headers=self.headers, json=payload)
            if r.status_code != 200:
                logger.error("Failed to fetch database page %s: <%s> %s", self.database_id, r.status_code, r.text)
                r.raise_for_status()
            page_data = r.json()
            self.origin["results"] += page_data.get("results", [])
            self.origin["has_more"] = page_data.get("has_more", False)
            self.origin["next_cursor"] = page_data.get("next_cursor")
            time.sleep(0.1)
        self._load_to_pandas()

    def write(self, where_notion_id: str, SET: str, TO: Any) -> Optional[requests.Response]:
        url = f"https://api.notion.com/v1/pages/{where_notion_id}"
        data_type = self.schemas.get(SET)
        if not data_type:
            logger.warning("Column %s not found in schema. Skipping write.", SET)
            return None
        if data_type in self.constants:
            logger.warning("Cannot modify constant data_type %s for column %s. Skipping.", self.constants, SET)
            return None
        try:
            val = self.mutator[data_type](TO)
            data = {"properties": {SET: {data_type: val}}}
        except KeyError:
            raise UserWarning(f"Framework doesn't support update data_type {data_type}. Modifying {SET} to {TO} is skipped.")
        time.sleep(0.1)
        resp = requests.patch(url, headers=self.headers, data=json.dumps(data))
        if resp.status_code != 200:
            logger.error("Notion write failed <%s>: %s", resp.status_code, resp.text)
        return resp

    def writes(self, with_reference_table: bool = True) -> None:
        if self._df is None or self.merged_df is None:
            return
        diff = self._df.compare(self.merged_df[self._df.columns])
        changes: List[Dict[str, Any]] = []
        if not diff.empty:
            for col in diff.columns.levels[0]:
                for idx in diff.index:
                    if pd.notna(diff.at[idx, (col, "self")]) or pd.notna(diff.at[idx, (col, "other")]):
                        changes.append({
                            "notion_id": self._df.at[idx, "notion_id"],
                            "column": col,
                            "new_value": diff.at[idx, (col, "self")],
                            "old_value": diff.at[idx, (col, "other")],
                        })
            for change in changes:
                if pd.isna(change["new_value"]):
                    change["new_value"] = None
                r = self.write(
                    where_notion_id=change["notion_id"],
                    SET=change["column"],
                    TO=change["new_value"],
                )
                if r is not None and hasattr(r, "status_code"):
                    logger.info(
                        "<%s>: notion_id %s, SET %s FROM %s TO %s",
                        r.status_code,
                        change["notion_id"],
                        change["column"],
                        change["old_value"],
                        change["new_value"],
                    )
                    if r.status_code != 200:
                        logger.error(r.json().get("message", r.text))
        else:
            logger.info("No update for table: %s", self.table_name)
        self.merged_df.update(self._df)
        if with_reference_table:
            self.write_reference_tables()

    def mapping_relations(self) -> Dict[str, List[str]]:
        relations: Dict[str, List[str]] = {column: [] for column, col_type in self.schemas.items() if col_type == "relation"}
        for column, col_type in self.schemas.items():
            if col_type == "rollup":
                rel_col = self.accessor[col_type](column)
                if rel_col in relations:
                    relations[rel_col].append(column)
        return relations

    def write_reference_tables(self) -> None:
        if self.relations and self.merged_df is not None:
            for relation in self.relations:
                if relation in list(chain(*self.mapping_relations().values())):
                    continue
                table = self.relations[relation]["from_table"]
                columns = [i for i in self.merged_df.columns if re.match(rf"^{relation}\|", i)]
                temp = self.merged_df[columns].copy()
                temp.columns = temp.columns.str.removeprefix(f"{relation}|")
                table.df.update(temp)
                table.writes()

    def update(self, WHERE: str, IS: Any, SET: str, TO: Any) -> None:
        self.df.loc[self.df[WHERE] == IS, SET] = TO

    def update_where_index(self, IS: Any, SET: str, TO: Any) -> None:
        self.df.loc[IS, SET] = TO

    def _load_to_pandas(self) -> None:
        raise NotImplementedError


class Table(Notion):
    """Notion Table represented as a pandas DataFrame with lazy-loading."""

    def __init__(
        self,
        database_id: str,
        relations: Optional[Dict[str, Any]] = None,
        token: Optional[str] = None,
    ):
        super().__init__(token=token)
        self.table_name = database_id[-8:]
        self.columns_with_default_value = ["notion_id", "unique_id", "status"]
        self.database_id = database_id
        self.schemas: Dict[str, str] = {}
        self.relations = relations or {}
        self._df: Optional[pd.DataFrame] = None
        self._merged_df: Optional[pd.DataFrame] = None

    @property
    def df(self) -> pd.DataFrame:
        if self._df is None:
            self.reads()
        return self._df  # type: ignore[return-value]

    @property
    def merged_df(self) -> pd.DataFrame:
        if self._merged_df is None:
            _ = self.df
        return self._merged_df  # type: ignore[return-value]

    def _load_to_pandas(self) -> None:
        results = self.origin.get("results", [])
        rows = []
        for d in results:
            tmp: Dict[str, Any] = {"notion_id": d["id"]}
            sorted_keys = sorted(
                d["properties"].keys(),
                key=lambda x: d["properties"][x].get("type") == "rollup",
            )
            for k in sorted_keys:
                t = d["properties"][k]["type"]
                v = d["properties"][k]
                if k not in self.schemas:
                    self.schemas[k] = t
                try:
                    if t != "rollup":
                        tmp[k] = self.accessor[t](v.get(t))
                    else:
                        tmp[k] = tmp[self.accessor[t](k)]
                except KeyError:
                    logger.warning("Framework doesn't support data type %s yet. Skip loading it.", t)
            rows.append(tmp)

        self._df = pd.DataFrame(rows)

        # clean empty lines
        defaults = [i for i in self.schemas.values() if i in self.columns_with_default_value] + ["notion_id"]
        if not self._df.empty:
            self._df = self._df[~(self._df.isna().sum(axis=1) == len(self._df.columns) - len(defaults))]

        columns: List[str] = []
        if self.relations:
            rel_mapping = self.mapping_relations()
            for relation, rollups in rel_mapping.items():
                ref_table = self.relations[relation]["from_table"]
                relation_column = self.relations[relation]["lookup_column"]
                columns += [f"{relation}|{i}" for i in ["notion_id", relation_column] + rollups]
                self._df = self._df.merge(
                    ref_table.merged_df.add_prefix(f"{relation}|"),
                    left_on=relation,
                    right_on=f"{relation}|notion_id",
                    how="left",
                )

        if not self._df.empty and "notion_id" in self._df.columns:
            self._df = self._df.set_index("notion_id", drop=False)
        self._merged_df = self._df.copy()

        if columns:
            cols_to_keep = [
                i for i in self._merged_df.columns
                if ("|" not in i or (i in columns and "|notion_id" not in i))
                and i not in self.relations
            ]
            self._df = self._merged_df[cols_to_keep]
