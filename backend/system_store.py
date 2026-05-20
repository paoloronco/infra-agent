"""Persistent storage for saved SSH systems and metadata."""
import json
import uuid
from pathlib import Path
from typing import Optional, Any, Dict, List
from datetime import datetime
from utils import utcnow

DEFAULT_STORE = Path(__file__).resolve().parent / 'system_store.json'


def _now_iso() -> str:
    return utcnow().isoformat() + 'Z'


class SystemStore:
    def __init__(self, store_path: Optional[str] = None):
        self.store_path = Path(store_path) if store_path else DEFAULT_STORE
        self.store_path.parent.mkdir(parents=True, exist_ok=True)
        self.records: List[Dict[str, Any]] = self._load()

    def _load(self) -> List[Dict[str, Any]]:
        if not self.store_path.exists():
            return []
        try:
            with self.store_path.open('r', encoding='utf-8') as handle:
                data = json.load(handle)
            return data if isinstance(data, list) else []
        except Exception:
            return []

    def _save(self) -> None:
        with self.store_path.open('w', encoding='utf-8') as handle:
            json.dump(self.records, handle, indent=2)

    def list(self) -> List[Dict[str, Any]]:
        return self.records

    def get(self, system_id: str) -> Optional[Dict[str, Any]]:
        return next((item for item in self.records if item.get('id') == system_id), None)

    def save(self, system_data: Dict[str, Any]) -> Dict[str, Any]:
        system_id = system_data.get('id')
        now = _now_iso()

        if system_id:
            existing = self.get(system_id)
            if existing:
                existing.update({
                    'name': system_data.get('name', existing.get('name')),
                    'host': system_data.get('host', existing.get('host')),
                    'username': system_data.get('username', existing.get('username')),
                    'ssh_key_path': system_data.get('ssh_key_path', existing.get('ssh_key_path', '')),
                    'tags': system_data.get('tags', existing.get('tags', [])) or [],
                    'description': system_data.get('description', existing.get('description', '')),
                    'connection_id': system_data.get('connection_id', existing.get('connection_id')),
                    'updated_at': now,
                })
                self._save()
                return existing

        new_id = system_id or str(uuid.uuid4())
        record = {
            'id': new_id,
            'name': system_data.get('name', f'System {len(self.records) + 1}'),
            'host': system_data.get('host', ''),
            'port': system_data.get('port', 22),
            'username': system_data.get('username', ''),
            'ssh_key_path': system_data.get('ssh_key_path', ''),
            'tags': system_data.get('tags', []) or [],
            'description': system_data.get('description', ''),
            'connection_id': system_data.get('connection_id', ''),
            'created_at': now,
            'updated_at': now,
        }
        self.records.append(record)
        self._save()
        return record

    def delete(self, system_id: str) -> bool:
        original = len(self.records)
        self.records = [item for item in self.records if item.get('id') != system_id]
        self._save()
        return len(self.records) < original
