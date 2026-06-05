import os
from unittest.mock import patch, MagicMock

def test_get_client_returns_singleton():
    # Clear lru_cache before test
    import importlib
    import db.client as client_mod
    client_mod.get_client.cache_clear()

    with patch.dict(os.environ, {"SUPABASE_URL": "https://x.supabase.co", "SUPABASE_SERVICE_KEY": "key"}):
        with patch("db.client.create_client") as mock_create:
            mock_create.return_value = MagicMock()
            from db.client import get_client
            get_client.cache_clear()
            c1 = get_client()
            c2 = get_client()
            assert c1 is c2
            assert mock_create.call_count == 1
