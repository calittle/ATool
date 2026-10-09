"""Original Comms package/version response normalization, without Tk initialization."""
from __future__ import annotations
import re
from datetime import datetime

class PackageResponses:
    @staticmethod
    def _available_versions_from_occs_error(parsed: dict[str, object]) -> list[object]:
        error = parsed.get('error')
        details = error.get('details') if isinstance(error, dict) else None
        if not isinstance(details, dict):
            return []
        available_versions = details.get('availableVersions')
        return available_versions if isinstance(available_versions, list) else []

    @staticmethod
    def _normalize_occs_packages(result: dict[str, object]) -> list[dict[str, str]]:
        packages = result.get('packages')
        if not isinstance(packages, list):
            return []
        normalized: list[dict[str, str]] = []
        for package in packages:
            if not isinstance(package, dict):
                continue
            item = {'shortName': str(package.get('shortName', '')).strip(), 'name': str(package.get('name', '')).strip(), 'description': str(package.get('description', '')).strip(), 'packageUuid': str(package.get('packageUuid', '')).strip(), 'configId': PackageResponses._occs_package_config_id(package)}
            if item['shortName']:
                normalized.append(item)
        return PackageResponses._sort_occs_packages(normalized)

    @staticmethod
    def _occs_package_config_id(package: dict[object, object]) -> str:
        for key in ('configId', 'id', 'packageId', 'ConfigId', 'PackageId'):
            value = package.get(key)
            text = str(value).strip() if value is not None else ''
            if text:
                return text
        configuration = package.get('configuration')
        if isinstance(configuration, dict):
            value = configuration.get('id')
            text = str(value).strip() if value is not None else ''
            if text:
                return text
        return ''

    @staticmethod
    def _sort_occs_packages(packages: list[dict[str, str]]) -> list[dict[str, str]]:
        return sorted(packages, key=PackageResponses._occs_package_sort_key)

    @staticmethod
    def _occs_package_sort_key(package: dict[str, str]) -> tuple[str, str, str, str]:
        """Keep the package picker in the same order users scan its first column."""
        return (package.get('shortName', '').casefold(), package.get('name', '').casefold(), package.get('configId', '').casefold(), package.get('packageUuid', '').casefold())

    @staticmethod
    def _normalize_occs_package_versions(result: dict[str, object], package_name: str='') -> list[dict[str, str]]:
        raw_versions: list[object] = []
        root_versions = result.get('versions')
        if isinstance(root_versions, list):
            raw_versions.extend(root_versions)
        root_package = result.get('package')
        if isinstance(root_package, dict):
            raw_versions.extend(PackageResponses._raw_occs_package_versions(root_package))
        packages = result.get('packages')
        if isinstance(packages, list):
            package_key = package_name.strip().lower()
            selected_packages: list[dict[object, object]] = []
            for package in packages:
                if not isinstance(package, dict):
                    continue
                short_name = str(package.get('shortName', '')).strip().lower()
                if not package_key or short_name == package_key:
                    selected_packages.append(package)
            if not selected_packages and len(packages) == 1 and isinstance(packages[0], dict):
                selected_packages.append(packages[0])
            for package in selected_packages:
                raw_versions.extend(PackageResponses._raw_occs_package_versions(package))
        normalized: list[dict[str, str]] = []
        seen: set[str] = set()
        for raw_version in raw_versions:
            item = PackageResponses._normalize_occs_package_version(raw_version)
            if item is None:
                continue
            key = item['shortName'].lower()
            if key in seen:
                continue
            seen.add(key)
            normalized.append(item)
        return PackageResponses._sort_occs_package_versions(normalized)

    @staticmethod
    def _raw_occs_package_versions(package: dict[object, object]) -> list[object]:
        versions: list[object] = []
        for key in ('versions', 'packageVersions', 'package_versions', 'CommunicationPackageMasterVersions', 'CommunicationPackageConfigVersions'):
            value = package.get(key)
            if isinstance(value, list):
                versions.extend(value)
        return versions

    @staticmethod
    def _normalize_occs_package_version(raw_version: object) -> dict[str, str] | None:
        if isinstance(raw_version, str):
            short_name = raw_version.strip()
            if not short_name:
                return None
            return {'shortName': short_name, 'description': '', 'effectiveAt': '', 'versionUuid': '', 'configId': ''}
        if not isinstance(raw_version, dict):
            return None
        rec = raw_version.get('CommunicationPackageVersionConfigRec')
        if not isinstance(rec, dict):
            rec = raw_version
        info = rec.get('CommunicationPackageVersionConfigInfo') if isinstance(rec, dict) else None
        if not isinstance(info, dict):
            nested_info = raw_version.get('CommunicationPackageVersionConfigInfo')
            info = nested_info if isinstance(nested_info, dict) else {}
        short_name = PackageResponses._first_nonempty_text(info.get('ShortName'), raw_version.get('shortName'), raw_version.get('version'), raw_version.get('versionName'), raw_version.get('name'))
        if not short_name:
            return None
        return {'shortName': short_name, 'description': PackageResponses._first_nonempty_text(info.get('Desc'), raw_version.get('description'), raw_version.get('desc')), 'effectiveAt': PackageResponses._first_nonempty_text(raw_version.get('effectiveAt'), raw_version.get('effectiveDate'), raw_version.get('EffDtTm'), raw_version.get('createdAt'), PackageResponses._occs_version_status_effective_at(raw_version), PackageResponses._occs_version_status_effective_at(rec)), 'versionUuid': PackageResponses._first_nonempty_text(rec.get('CommunicationPackageVersionConfigUuid') if isinstance(rec, dict) else '', raw_version.get('versionUuid'), raw_version.get('uuid')), 'configId': PackageResponses._first_nonempty_text(info.get('ConfigId'), rec.get('ConfigId') if isinstance(rec, dict) else '', raw_version.get('configId'), raw_version.get('id'))}

    @staticmethod
    def _occs_version_status_effective_at(version: object) -> str:
        if not isinstance(version, dict):
            return ''
        for status_key in ('ConfigurationStatus', 'CommunicationPackageVersionConfigStatus', 'status'):
            status = version.get(status_key)
            if not isinstance(status, dict):
                continue
            items = status.get('Items')
            if isinstance(items, list):
                for item in items:
                    if isinstance(item, dict):
                        effective = PackageResponses._first_nonempty_text(item.get('EffDtTm'), item.get('effectiveAt'))
                        if effective:
                            return effective
            effective = PackageResponses._first_nonempty_text(status.get('EffDtTm'), status.get('effectiveAt'))
            if effective:
                return effective
        return ''

    @staticmethod
    def _sort_occs_package_versions(versions: list[dict[str, str]]) -> list[dict[str, str]]:
        return sorted(versions, key=PackageResponses._occs_package_version_sort_key)

    @staticmethod
    def _occs_package_version_sort_key(version: dict[str, str]) -> tuple[object, ...]:
        effective_at = PackageResponses._occs_effective_sort_value(version.get('effectiveAt', ''))
        version_parts = PackageResponses._parse_occs_version_number(version.get('shortName', ''))
        padded_version = tuple((-(part or 0) for part in (version_parts or ())[:8]))
        padded_version = padded_version + tuple((0 for _ in range(max(0, 8 - len(padded_version)))))
        return (0 if version_parts else 1, padded_version, 0 if effective_at is not None else 1, -effective_at if effective_at is not None else 0, version.get('shortName', '').lower())

    @staticmethod
    def _parse_occs_version_number(value: object) -> tuple[int, ...] | None:
        match = re.search('\\d+(?:\\.\\d+)*', str(value or ''))
        if not match:
            return None
        return tuple((int(part) for part in match.group(0).split('.')))

    @staticmethod
    def _occs_effective_sort_value(value: object) -> float | None:
        text = str(value or '').strip()
        if not text:
            return None
        if re.fullmatch('\\d+(?:\\.\\d+)?', text):
            numeric = float(text)
            return numeric / 1000 if numeric > 100000000000 else numeric
        normalized = text[:-1] + '+00:00' if text.endswith('Z') else text
        try:
            return datetime.fromisoformat(normalized).timestamp()
        except ValueError:
            pass
        for date_format in ('%m/%d/%Y', '%m/%d/%y', '%Y/%m/%d'):
            try:
                return datetime.strptime(text, date_format).timestamp()
            except ValueError:
                continue
        return None

    @staticmethod
    def _first_nonempty_text(*values: object) -> str:
        for value in values:
            text = str(value).strip() if value is not None else ''
            if text:
                return text
        return ''

    def _fuzzy_text_match(self, query: str, text: str) -> bool:
        normalized_query = query.strip().casefold()
        normalized_text = text.casefold()
        if not normalized_query:
            return True
        tokens = [token for token in normalized_query.split() if token]
        if not tokens:
            return True
        words = [word for word in re.split('[^a-z0-9]+', normalized_text) if word]
        for token in tokens:
            if token in normalized_text:
                continue
            if len(token) <= 2 and self._is_subsequence(token, normalized_text):
                continue
            if any((token in word for word in words)):
                continue
            if len(token) <= 2 and any((self._is_subsequence(token, word) for word in words)):
                continue
            return False
        return True

    @staticmethod
    def _is_subsequence(token: str, text: str) -> bool:
        if token in text:
            return True
        start = 0
        for character in token:
            index = text.find(character, start)
            if index < 0:
                return False
            start = index + 1
        return True
