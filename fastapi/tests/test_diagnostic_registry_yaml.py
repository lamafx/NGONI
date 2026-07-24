"""Tests de la Phase 5 (voir docs/diagnostic-roadmap.md, etapes 23-24) :
le Registry decouvre desormais les microservices via services_registry.yaml
au lieu d'une liste codee en dur, et relit ce fichier a chaque refresh() --
ces tests prouvent qu'un service ajoute au fichier PENDANT que le process
tourne devient routable au refresh() suivant, sans redemarrage (etape 24).

N'utilisent jamais le vrai fastapi/services_registry.yaml du projet (chaque
test ecrit son propre fichier temporaire, via tmp_path) : aucun risque
d'interference avec la configuration reelle ni entre tests.
"""

import sys
from pathlib import Path

import httpx
import pytest
import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.domains.diagnostic.registry import (  # noqa: E402
    CapabilityRegistry,
    _load_services_from_yaml,
)

WALLET_MANIFEST = {
    "service": "wallet",
    "manifest_version": "1.0.0",
    "base_url": "http://wallet.test/api/v1",
    "protocol": "REST",
    "problems": [
        {
            "id": "withdrawal_pending",
            "label": "Retrait bloque",
            "keywords": ["retrait"],
            "endpoint": {"method": "POST", "path": "/diagnostic/withdrawal"},
            "required_fields": [],
            "optional_fields": [],
        },
    ],
}

FICTIONAL_MANIFEST = {
    "service": "fictional",
    "manifest_version": "1.0.0",
    "base_url": "http://fictional.test/api/v1",
    "protocol": "REST",
    "problems": [
        {
            "id": "made_up_problem",
            "label": "Probleme fictif",
            "keywords": ["fictif"],
            "endpoint": {"method": "POST", "path": "/diagnostic/made_up"},
            "required_fields": [],
            "optional_fields": [],
        },
    ],
}


def write_registry_yaml(path: Path, service_names: list[str]) -> None:
    entries = []
    for name in service_names:
        entries.append(
            {
                "name": name,
                "base_url_env": f"{name.upper()}_TEST_URL_ENV_UNUSED",
                "base_url_default": f"http://{name}.test/api/v1",
                "internal_secret_env": f"{name.upper()}_TEST_SECRET_ENV_UNUSED",
            }
        )
    path.write_text(yaml.safe_dump({"services": entries}), encoding="utf-8")


class TestLoadServicesFromYaml:
    def test_loads_declared_services_with_default_base_url(self, tmp_path, monkeypatch):
        registry_file = tmp_path / "services_registry.yaml"
        write_registry_yaml(registry_file, ["wallet", "user"])

        services = _load_services_from_yaml(registry_file)

        assert {s.name for s in services} == {"wallet", "user"}
        wallet = next(s for s in services if s.name == "wallet")
        assert wallet.base_url == "http://wallet.test/api/v1"

    def test_env_var_overrides_default(self, tmp_path, monkeypatch):
        registry_file = tmp_path / "services_registry.yaml"
        write_registry_yaml(registry_file, ["wallet"])
        monkeypatch.setenv("WALLET_TEST_URL_ENV_UNUSED", "http://overridden.example/api/v1")

        services = _load_services_from_yaml(registry_file)

        assert services[0].base_url == "http://overridden.example/api/v1"

    def test_missing_file_returns_empty_list_not_an_exception(self, tmp_path):
        services = _load_services_from_yaml(tmp_path / "does_not_exist.yaml")
        assert services == []

    def test_malformed_yaml_returns_empty_list_not_an_exception(self, tmp_path):
        registry_file = tmp_path / "services_registry.yaml"
        registry_file.write_text("services: [this is not: valid: yaml:", encoding="utf-8")

        services = _load_services_from_yaml(registry_file)
        assert services == []

    def test_entry_missing_required_key_is_skipped_others_still_load(self, tmp_path):
        registry_file = tmp_path / "services_registry.yaml"
        registry_file.write_text(
            yaml.safe_dump(
                {
                    "services": [
                        {"name": "broken"},  # pas de base_url_env
                        {
                            "name": "wallet",
                            "base_url_env": "WALLET_TEST_URL_ENV_UNUSED",
                            "base_url_default": "http://wallet.test/api/v1",
                        },
                    ]
                }
            ),
            encoding="utf-8",
        )

        services = _load_services_from_yaml(registry_file)

        assert [s.name for s in services] == ["wallet"]


class TestHotReloadWithoutRestart:
    """Preuve directe de l'etape 24 : ajouter un service au fichier entre
    deux refresh() du MEME CapabilityRegistry (aucune nouvelle instance, donc
    rien d'equivalent a un redemarrage du process) le rend routable."""

    @pytest.mark.anyio
    async def test_new_service_appended_between_two_refreshes_is_discovered(self, tmp_path):
        registry_file = tmp_path / "services_registry.yaml"
        write_registry_yaml(registry_file, ["wallet"])

        def handler(request: httpx.Request) -> httpx.Response:
            if "fictional" in str(request.url):
                return httpx.Response(200, json=FICTIONAL_MANIFEST)
            return httpx.Response(200, json=WALLET_MANIFEST)

        transport = httpx.MockTransport(handler)
        registry = CapabilityRegistry(transport=transport, registry_path=registry_file)

        await registry.refresh()
        assert registry.lookup("wallet", "withdrawal_pending") is not None
        assert registry.lookup("fictional", "made_up_problem") is None

        # Le service fictif rejoint le registre PENDANT que `registry` existe
        # deja et a deja fait un refresh() -- rien n'est recree.
        write_registry_yaml(registry_file, ["wallet", "fictional"])
        await registry.refresh()

        assert registry.lookup("wallet", "withdrawal_pending") is not None
        assert registry.lookup("fictional", "made_up_problem") is not None

    @pytest.mark.anyio
    async def test_explicit_services_never_reload_from_file(self, tmp_path):
        """Garde-fou de compatibilite : quand `services` est fourni
        explicitement (tests existants, voir test_diagnostic_pipeline.py),
        le fichier YAML n'est jamais consulte, meme s'il existe."""
        from app.domains.diagnostic.registry import RegisteredService

        registry_file = tmp_path / "services_registry.yaml"
        write_registry_yaml(registry_file, ["fictional"])

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json=WALLET_MANIFEST)

        transport = httpx.MockTransport(handler)
        registry = CapabilityRegistry(
            services=[RegisteredService(name="wallet", base_url="http://wallet.test/api/v1", internal_secret="s")],
            transport=transport,
            registry_path=registry_file,
        )

        await registry.refresh()

        assert registry.lookup("wallet", "withdrawal_pending") is not None
        assert registry.lookup("fictional", "made_up_problem") is None


@pytest.fixture
def anyio_backend():
    return "asyncio"
