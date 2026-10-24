"""Static contract checks only; no feed/model/data reads.
Root supplies the independently approved NEW physical hashes and recipe pins.
Existing reports are deliberately neither opened nor used as acceptance.
"""
from pathlib import Path
import hashlib, importlib.util, json, shlex, sys


def require(value, reason):
    if not value: raise ValueError(reason)

def check_current_port(root, pins, candidate_bodies=None):
    root = Path(root).resolve()
    candidate_bodies = {} if candidate_bodies is None else candidate_bodies
    require(set(candidate_bodies) <= {'policy', 'hourly'}, 'CANDIDATE_ROLE_SCOPE')
    policy_path = pins.get('policy_path', 'config/weekly-derived-selected-policy-v2.json')
    paths = {'policy': policy_path, 'helper': 'tools/weekly_public_feed.py',
             'schema': 'schemas/weekly-derived-selected-feed-v2.json',
             'hourly': '.github/workflows/hourly.yml'}
    def body(name):
        path = root / name
        require(path.resolve().is_relative_to(root) and not path.is_symlink(), 'PATH_SCOPE')
        require(name in set(paths.values()) | set(pins['code_paths']), 'STATIC_FILE_SCOPE')
        require(path.stat().st_size <= 2 << 20, 'STATIC_BYTE_BOUND')
        data = path.read_bytes()
        require(len(data) <= 2 << 20, 'STATIC_BYTE_BOUND')
        return data
    def sha(data): return hashlib.sha256(data).hexdigest()
    def pairs(items):
        result = {}
        for key, value in items:
            require(key not in result, 'DUPLICATE_JSON_KEY')
            result[key] = value
        return result
    def strict(data):
        def invalid(value): raise ValueError('NONFINITE_JSON')
        return json.loads(data, object_pairs_hook=pairs, parse_constant=invalid)
    data = {role: candidate_bodies[role] if role in candidate_bodies else body(name) for role, name in paths.items()}
    require(all(type(value) is bytes and len(value) <= 2 << 20 for value in data.values()), 'CANDIDATE_BYTE_BOUND')
    hashes = {role: sha(value) for role, value in data.items()}
    require(hashes == pins['physical_sha256'], 'NEW_EXACT_PHYSICAL_BYTES_REQUIRED')
    policy, schema = strict(data['policy']), strict(data['schema'])
    require(set(policy['website_code_sha256']) == set(pins['code_paths']), 'CLOSED_CODE_PATHS')
    actual = {name: sha(body(name)) for name in policy['website_code_sha256']}
    require(actual == policy['website_code_sha256'], 'CURRENT_WEBSITE_CODE_INVENTORY')
    old_path, old_no_bytecode = list(sys.path), sys.dont_write_bytecode
    try:
        sys.path.insert(0, str(root / 'tools')); sys.dont_write_bytecode = True
        spec = importlib.util.spec_from_file_location('current_port_reviewed_helper', root / paths['helper'])
        helper = importlib.util.module_from_spec(spec); spec.loader.exec_module(helper)
        helper.policy_check_v2(policy)  # Trusted exact helper; no writer/fetch/export call.
        require(Path(helper.overlay().__file__).resolve() == (root / 'tools/weekly_adaptive_overlay.py').resolve(), 'EXACT_OVERLAY_READER')
        require(policy['publication_authority']['source_sha'] == pins['new_lab_source_sha'], 'NEW_SOURCE')
        require(policy['producer_policy_sha256'] == pins['new_producer_policy_sha256'], 'NEW_PRODUCER')
        require(policy['source_policy_sha256'] == pins['new_source_policy_sha256'], 'NEW_SOURCE_POLICY')
        require(policy['publication_authority']['catalog_freezer_sha256'] == pins['new_catalog_freezer_sha256'], 'NEW_CATALOG')
        require(policy['procedures'] == pins['new_procedures'], 'NEW_RECIPES')
        require(policy['website_code_sha256']['output/app.js'] == pins['new_app_sha256'], 'NEW_UI')
        actual = {name: sha(body(name)) for name in helper.CODE_FILES}
        require(actual == policy['website_code_sha256'], 'CURRENT_WEBSITE_CODE_INVENTORY')
        require(schema['$id'] == schema['properties']['schema_version']['const'] == helper.VERSION_V2, 'V2_SCHEMA')
        require(set(schema['properties']['rows']['items']['required']) == set(helper.overlay().ROW_FIELDS), 'PUBLIC_ROWS')
        require(set(schema['properties']['rows']['items']['properties']['category']['enum']) == set(helper.overlay().PRODUCTS), 'PUBLIC_TARGETS')
        commands = [shlex.split(line.strip()[5:]) for line in data['hourly'].decode().splitlines()
                    if line.strip().startswith('run: python tools/weekly_adaptive_overlay.py ')]
        require(len(commands) == 1, 'SINGLE_OPTIONAL_WRITER')
        command = commands[0]
        require(command[command.index('--feed-policy') + 1] == policy_path, 'WORKFLOW_POLICY_PATH')
        require(command[command.index('--feed-policy-sha256') + 1] == hashes['policy'], 'WORKFLOW_PHYSICAL_POLICY_SHA')
    finally:
        sys.path[:] = old_path; sys.dont_write_bytecode = old_no_bytecode
    return {'state': 'PROPOSED_STATIC_CONTRACT_PASS' if candidate_bodies else 'CURRENT_STATIC_CONTRACT_PASS',
            'candidate_override_roles': sorted(candidate_bodies), 'installed_port_acceptance': not bool(candidate_bodies),
            'physical_sha256': hashes,
            'website_code_inventory_checks': len(actual), 'new_lab_source_sha': pins['new_lab_source_sha'],
            'historical_reports_used': False, 'HTTP': 0, 'model_or_data_reads': 0,
            'hosted_publication_or_deployment_acceptance': False}


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', required=True)
    parser.add_argument('--pins', required=True, help='Separately root-approved new physical hashes and recipes')
    args = parser.parse_args()
    pins_path = Path(args.pins)
    require(pins_path.is_file() and not pins_path.is_symlink() and pins_path.stat().st_size <= 256 << 10, 'PIN_FILE_BOUND')
    pins = json.loads(pins_path.read_bytes())
    print(json.dumps(check_current_port(args.root, pins), indent=2, sort_keys=True))
