from typing import Protocol


class PlatformAdapter(Protocol):
    def capabilities(self) -> dict: ...
    def authorize(self, credentials: dict) -> dict: ...
    def publish(self, content: str, *, owner_approved: bool, permissions_verified: bool) -> dict: ...
    def check_status(self, publication_id: str) -> dict: ...
    def revoke(self) -> dict: ...


class ManualAdapter:
    def capabilities(self):
        return {'mode': 'manual_only', 'permissions_verified': False, 'can_publish': False}

    def authorize(self, credentials):
        return self.capabilities()

    def publish(self, content, *, owner_approved, permissions_verified):
        # No permission evidence can enable an unimplemented adapter.
        raise PermissionError('Manual-only adapter; no platform request made')

    def check_status(self, publication_id):
        return {'status': 'MANUAL_REQUIRED', 'posted': False}

    def revoke(self):
        return {'revoked': True, 'stored_credentials': False}


ADAPTERS: dict[str, PlatformAdapter] = {
    platform: ManualAdapter() for platform in ('threads', 'instagram', 'facebook', 'tiktok')
}
