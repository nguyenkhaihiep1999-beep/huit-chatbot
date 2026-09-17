"""
conftest.py
Fixture và Mock hạ tầng 100% Offline cho Pytest:
- Mock toàn bộ kết nối MongoDB (chặn 100% việc kết nối tới Atlas Cluster).
- Mock StorageAdapter (sử dụng LocalStorageAdapter với thư mục tạm trong scratch).
- Dọn dẹp RAM Cache sau mỗi test case.
"""
import copy
import re
import pytest
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from unittest.mock import MagicMock, patch

from backend.app.repositories.mongo_repository import MongoRepository
from backend.app.services.asset_store import AssetStore, ArtifactStore
from backend.app.middleware.rate_limiter import clear_rate_limits_for_testing


class MockCursor:
    def __init__(self, docs: List[Dict[str, Any]]):
        self._docs = list(docs)
        self._index = 0

    def sort(self, key_or_list, direction=1):
        # Đơn giản hóa: hỗ trợ sort theo trường
        if isinstance(key_or_list, str):
            reverse = (direction == -1)
            self._docs.sort(key=lambda d: str(d.get(key_or_list, "")), reverse=reverse)
        elif isinstance(key_or_list, list) and key_or_list:
            field, direction = key_or_list[0]
            self._docs.sort(key=lambda d: str(d.get(field, "")), reverse=(direction == -1))
        return self

    def limit(self, n: int):
        self._docs = self._docs[:n]
        return self

    def batch_size(self, n: int):
        return self

    def __iter__(self):
        return iter(self._docs)

    def __next__(self):
        if self._index < len(self._docs):
            doc = self._docs[self._index]
            self._index += 1
            return doc
        raise StopIteration


class MockCollection:
    def __init__(self, name: str):
        self.name = name
        self.docs: Dict[str, Dict[str, Any]] = {}
        self.indexes: Dict[str, Dict[str, Any]] = {
            "_id_": {"key": [("_id", 1)], "v": 2}
        }
        self.database = MagicMock()
        self.database.command.return_value = {"ok": 1}

    def _matches(self, doc: Dict[str, Any], query: Dict[str, Any]) -> bool:
        if not query:
            return True
        for k, v in query.items():
            if k == "$or" and isinstance(v, list):
                if not any(self._matches(doc, subq) for subq in v):
                    return False
                continue
            if k == "$and" and isinstance(v, list):
                if not all(self._matches(doc, subq) for subq in v):
                    return False
                continue
            
            if k == "$expr" and isinstance(v, dict):
                if "$lt" in v and isinstance(v["$lt"], list) and len(v["$lt"]) == 2:
                    left_spec, right_spec = v["$lt"]
                    left_val = 0
                    if isinstance(left_spec, dict) and "$ifNull" in left_spec:
                        field_name = str(left_spec["$ifNull"][0]).lstrip("$")
                        default_val = left_spec["$ifNull"][1]
                        left_val = doc.get(field_name, default_val)
                    elif isinstance(left_spec, str) and left_spec.startswith("$"):
                        left_val = doc.get(left_spec.lstrip("$"), 0)
                    elif isinstance(left_spec, (int, float)):
                        left_val = left_spec

                    right_val = 3
                    if isinstance(right_spec, dict) and "$ifNull" in right_spec:
                        field_name = str(right_spec["$ifNull"][0]).lstrip("$")
                        default_val = right_spec["$ifNull"][1]
                        right_val = doc.get(field_name, default_val)
                    elif isinstance(right_spec, str) and right_spec.startswith("$"):
                        right_val = doc.get(right_spec.lstrip("$"), 3)
                    elif isinstance(right_spec, (int, float)):
                        right_val = right_spec

                    if not (left_val < right_val):
                        return False
                continue

            val = doc.get(k)
            if isinstance(v, dict):
                if "$exists" in v:
                    exists = (k in doc)
                    if v["$exists"] != exists:
                        return False
                if "$ne" in v:
                    if val == v["$ne"]:
                        return False
                if "$gt" in v:
                    target = v["$gt"]
                    val_c = val
                    if isinstance(val_c, str) and isinstance(target, datetime):
                        try:
                            val_c = datetime.fromisoformat(val_c.replace("Z", "+00:00"))
                        except Exception:
                            pass
                    if not (val_c is not None and val_c > target):
                        return False
                if "$gte" in v:
                    target = v["$gte"]
                    val_c = val
                    if isinstance(val_c, str) and isinstance(target, datetime):
                        try:
                            val_c = datetime.fromisoformat(val_c.replace("Z", "+00:00"))
                        except Exception:
                            pass
                    if not (val_c is not None and val_c >= target):
                        return False
                if "$lt" in v:
                    target = v["$lt"]
                    val_c = val
                    if isinstance(val_c, str) and isinstance(target, datetime):
                        try:
                            val_c = datetime.fromisoformat(val_c.replace("Z", "+00:00"))
                        except Exception:
                            pass
                    if not (val_c is not None and val_c < target):
                        return False
                if "$lte" in v:
                    target = v["$lte"]
                    val_c = val
                    if isinstance(val_c, str) and isinstance(target, datetime):
                        try:
                            val_c = datetime.fromisoformat(val_c.replace("Z", "+00:00"))
                        except Exception:
                            pass
                    if not (val_c is not None and val_c <= target):
                        return False
                if "$in" in v:
                    if val not in v["$in"]:
                        return False
                if "$type" in v:
                    expected = v["$type"]
                    if expected == "string" and not isinstance(val, str):
                        return False
                    if expected == "date" and not isinstance(val, datetime):
                        return False
            else:
                if val != v:
                    return False
        return True

    def find_one(self, query: Dict[str, Any] = None, projection: Dict[str, Any] = None) -> Optional[Dict[str, Any]]:
        query = query or {}
        for d in self.docs.values():
            if self._matches(d, query):
                res = copy.deepcopy(d)
                if projection and projection.get("_id") == 0:
                    res.pop("_id", None)
                return res
        return None

    def find(self, query: Dict[str, Any] = None, projection: Dict[str, Any] = None) -> MockCursor:
        query = query or {}
        matched = []
        for d in self.docs.values():
            if self._matches(d, query):
                res = copy.deepcopy(d)
                if projection and projection.get("_id") == 0:
                    res.pop("_id", None)
                matched.append(res)
        return MockCursor(matched)

    def insert_one(self, doc: Dict[str, Any]):
        d = copy.deepcopy(doc)
        if self.name == "admin_sessions" and "session_hash" in d:
            for existing in self.docs.values():
                if existing.get("session_hash") == d["session_hash"]:
                    import pymongo.errors
                    raise pymongo.errors.DuplicateKeyError("E11000 duplicate key error collection: admin_sessions index: uniq_session_hash")
        _id = str(d.get("_id") or d.get("id") or len(self.docs) + 1)
        d["_id"] = _id
        self.docs[_id] = d
        return MagicMock(inserted_id=_id)

    def update_one(self, filter_q: Dict[str, Any], update: Dict[str, Any], upsert: bool = False):
        target_id = None
        for k, d in self.docs.items():
            if self._matches(d, filter_q):
                target_id = k
                break

        if target_id is None:
            if upsert:
                new_doc = {}
                if "_id" in filter_q:
                    new_doc["_id"] = filter_q["_id"]
                elif "asset_id" in filter_q:
                    new_doc["_id"] = filter_q["asset_id"]
                elif "artifact_id" in filter_q:
                    new_doc["_id"] = filter_q["artifact_id"]
                elif "job_id" in filter_q:
                    new_doc["_id"] = filter_q["job_id"]
                else:
                    new_doc["_id"] = str(len(self.docs) + 1)

                if "$set" in update:
                    new_doc.update(copy.deepcopy(update["$set"]))
                self.docs[new_doc["_id"]] = new_doc
                return MagicMock(matched_count=0, modified_count=1, upserted_id=new_doc["_id"])
            return MagicMock(matched_count=0, modified_count=0)

        existing = self.docs[target_id]
        if "$set" in update:
            existing.update(copy.deepcopy(update["$set"]))
        if "$unset" in update:
            for field in update["$unset"]:
                existing.pop(field, None)
        if "$inc" in update:
            for field, inc_val in update["$inc"].items():
                existing[field] = existing.get(field, 0) + inc_val

        return MagicMock(matched_count=1, modified_count=1)

    def find_one_and_update(self, filter_q: Dict[str, Any], update: Dict[str, Any], return_document=False, upsert=False):
        target_id = None
        for k, d in self.docs.items():
            if self._matches(d, filter_q):
                target_id = k
                break

        if target_id is None:
            if upsert:
                new_doc = {}
                if "_id" in filter_q:
                    new_doc["_id"] = filter_q["_id"]
                elif "job_id" in filter_q:
                    new_doc["_id"] = filter_q["job_id"]
                else:
                    new_doc["_id"] = str(len(self.docs) + 1)
                if "$set" in update:
                    new_doc.update(copy.deepcopy(update["$set"]))
                self.docs[new_doc["_id"]] = new_doc
                return copy.deepcopy(new_doc)
            return None

        existing = self.docs[target_id]
        before = copy.deepcopy(existing)
        if "$set" in update:
            existing.update(copy.deepcopy(update["$set"]))
        if "$unset" in update:
            for field in update["$unset"]:
                existing.pop(field, None)
        if "$inc" in update:
            for field, inc_val in update["$inc"].items():
                existing[field] = existing.get(field, 0) + inc_val

        if return_document:
            return copy.deepcopy(existing)
        return before

    def count_documents(self, filter_q: Dict[str, Any]) -> int:
        count = 0
        for d in self.docs.values():
            if self._matches(d, filter_q):
                count += 1
        return count

    def delete_one(self, filter_q: Dict[str, Any]):
        for k, d in list(self.docs.items()):
            if self._matches(d, filter_q):
                del self.docs[k]
                return MagicMock(deleted_count=1)
        return MagicMock(deleted_count=0)

    def delete_many(self, filter_q: Dict[str, Any] = None):
        filter_q = filter_q or {}
        deleted = 0
        for k, d in list(self.docs.items()):
            if self._matches(d, filter_q):
                del self.docs[k]
                deleted += 1
        return MagicMock(deleted_count=deleted)

    def insert_many(self, docs: List[Dict[str, Any]]):
        ids = []
        for doc in docs:
            res = self.insert_one(doc)
            ids.append(res.inserted_id)
        return MagicMock(inserted_ids=ids)

    def aggregate(self, pipeline: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        results = [copy.deepcopy(d) for d in self.docs.values()]
        for stage in pipeline:
            if "$match" in stage:
                results = [d for d in results if self._matches(d, stage["$match"])]
            if "$limit" in stage:
                results = results[:stage["$limit"]]
        return results

    def create_index(self, keys, **kwargs):
        idx_name = kwargs.get("name") or "_".join(f"{k}_{d}" for k, d in keys)
        info = {"key": keys, **kwargs}
        self.indexes[idx_name] = info
        return idx_name

    def index_information(self) -> Dict[str, Any]:
        return copy.deepcopy(self.indexes)

    def drop_index(self, name: str):
        self.indexes.pop(name, None)


_MOCK_COLLECTIONS: Dict[str, MockCollection] = {}


def get_mock_collection(name: str) -> MockCollection:
    if name not in _MOCK_COLLECTIONS:
        _MOCK_COLLECTIONS[name] = MockCollection(name)
    return _MOCK_COLLECTIONS[name]


class MockSyncRedis:
    def __init__(self):
        self._store = {}

    def get(self, k):
        val = self._store.get(k)
        if isinstance(val, str):
            return val.encode("utf-8")
        return val

    def set(self, k, v, ex=None):
        self._store[k] = v
        return True

    def delete(self, k):
        return bool(self._store.pop(k, None))

    def clear(self):
        self._store.clear()


@pytest.fixture(autouse=True)
def isolate_test_environment(monkeypatch, tmp_path):
    """
    Tự động cô lập toàn bộ test case:
    1. Đảm bảo 100% offline, không chạm tới MongoDB Atlas.
    2. Reset RAM cache của AssetStore, ArtifactStore, RateLimiter và JobQueueManager.
    3. Cô lập StorageAdapter trong thư mục tạm tmp_path (tuyệt đối không ghi vào data/artifacts_store).
    """
    from backend.app.storage.storage_adapter import LocalStorageAdapter, reset_storage_adapter_for_testing
    from backend.app.services.job_queue import clear_jobs_for_testing
    from backend.app.cache.redis_client import set_redis_client_for_testing

    from backend.app.middleware.rate_limiter import InMemoryRateLimitStore, set_rate_limit_store_for_testing
    _MOCK_COLLECTIONS.clear()
    AssetStore.clear_memory_cache_for_testing()
    set_rate_limit_store_for_testing(InMemoryRateLimitStore())
    mock_redis = MockSyncRedis()
    set_redis_client_for_testing(async_client=None, sync_client=mock_redis)
    clear_rate_limits_for_testing()
    clear_jobs_for_testing()

    test_storage = LocalStorageAdapter(root_dir=(tmp_path / "artifacts_store"))
    reset_storage_adapter_for_testing(test_storage)

    # Monkeypatch MongoRepository để dùng MockCollection trong RAM
    monkeypatch.setattr(MongoRepository, "get_collection", staticmethod(get_mock_collection))
    monkeypatch.setattr(MongoRepository, "get_artifacts_collection", staticmethod(lambda: get_mock_collection("artifacts")))
    monkeypatch.setattr(MongoRepository, "get_cache_collection", staticmethod(lambda: get_mock_collection("query_cache")))
    monkeypatch.setattr(MongoRepository, "get_events_collection", staticmethod(lambda: get_mock_collection("rag_events")))

    mock_db = MagicMock()
    mock_db.name = "huit_chatbot_test"
    mock_db.__getitem__.side_effect = get_mock_collection
    mock_db.list_collection_names.side_effect = lambda: list(_MOCK_COLLECTIONS.keys())
    mock_db.command.return_value = {"ok": 1}

    mock_client = MagicMock()
    mock_client.__getitem__.return_value = mock_db
    monkeypatch.setattr(MongoRepository, "get_client", classmethod(lambda cls: mock_client))
    monkeypatch.setattr(MongoRepository, "get_db", classmethod(lambda cls: mock_db))

    yield

    _MOCK_COLLECTIONS.clear()
    AssetStore.clear_memory_cache_for_testing()
    clear_rate_limits_for_testing()
    set_rate_limit_store_for_testing(None)
    set_redis_client_for_testing(None, None)
    clear_jobs_for_testing()
    reset_storage_adapter_for_testing(None)

