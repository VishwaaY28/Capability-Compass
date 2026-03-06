import csv
from typing import List, Dict, Any
from collections import OrderedDict


def parse_csv_to_nested_json(csv_path: str) -> List[Dict[str, Any]]:
    capabilities = OrderedDict()

    uid_counters = {
        'capability': 0,
        'process': 0,
        'subprocess': 0,
        'data_entity': 0,
        'data_element': 0
    }

    uid_maps = {
        'capability': {},
        'process': {},
        'subprocess': {},
        'data_entity': {},
        'data_element': {}
    }

    # Track subprocess and data entity/element uniqueness per capability
    subprocess_per_capability = {}  # {capability_name: {process_name: {subprocess_name}}}
    data_entity_per_subprocess = {}  # {capability_name: {process_name: {subprocess_name: {entity_name}}}}
    data_element_per_entity = {}  # {capability_name: {process_name: {subprocess_name: {entity_name: {element_name}}}}}

    def get_uid(entity_type: str, name: str, capability_name: str = None) -> int:
        # For capability, use just the name; for others, scope by capability
        if entity_type == 'capability':
            key = name
        else:
            key = f"{capability_name}#{name}" if capability_name else name
        
        if key in uid_maps[entity_type]:
            return uid_maps[entity_type][key]
        uid_counters[entity_type] += 1
        uid_maps[entity_type][key] = uid_counters[entity_type]
        return uid_counters[entity_type]

    with open(csv_path, 'r', encoding='latin-1') as f:
        reader = csv.DictReader(f)

        for row in reader:
            cap_name = row.get('Capability Name', '').strip()
            proc_name = row.get('Process', '').strip()
            proc_desc = row.get('Process Description', '').strip()
            subproc_name = row.get('Sub Process', '').strip()
            subproc_desc = row.get('Sub-Process Description', '').strip()
            entity_name = row.get('Data Entity', '').strip()
            entity_desc = row.get('Data Entity Description', '').strip()
            element_name = row.get('Data Element', '').strip()
            element_desc = row.get('Data Element Description', '').strip()
            org_units = row.get('Organization Units','').strip()
            application = row.get('Applications','').strip()

            if not cap_name:
                continue

            # Initialize capability tracking dicts if not exists
            if cap_name not in subprocess_per_capability:
                subprocess_per_capability[cap_name] = {}
                data_entity_per_subprocess[cap_name] = {}
                data_element_per_entity[cap_name] = {}

            if cap_name not in capabilities:
                capabilities[cap_name] = {
                    'id': get_uid('capability', cap_name, None),
                    'name': cap_name,
                    'description': '',
                    'vertical': 'Capital Markets',
                    'subvertical': 'Asset Management',
                    'processes': OrderedDict()
                }

            cap = capabilities[cap_name]

            if proc_name and proc_name not in cap['processes']:
                cap['processes'][proc_name] = {
                    'id': get_uid('process', proc_name, cap_name),
                    'name': proc_name,
                    'description': proc_desc,
                    'level': 1,
                    'category': 'Back Office',
                    'subprocesses': OrderedDict()
                }
                # Initialize subprocess tracking for this process in this capability
                subprocess_per_capability[cap_name][proc_name] = set()
                data_entity_per_subprocess[cap_name][proc_name] = {}

            # Only add subprocess if it hasn't been added to this specific capability+process combination
            if proc_name and subproc_name:
                proc = cap['processes'][proc_name]
                # Check if this subprocess is already in this capability's process
                if subproc_name not in subprocess_per_capability[cap_name][proc_name]:
                    if subproc_name not in proc['subprocesses']:
                        proc['subprocesses'][subproc_name] = {
                            'id': get_uid('subprocess', subproc_name, cap_name),
                            'name': subproc_name,
                            'description': subproc_desc,
                            'category': 'Back Office',
                            'data_entities': OrderedDict()
                        }
                        # Track this subprocess as added for this capability+process
                        subprocess_per_capability[cap_name][proc_name].add(subproc_name)
                        data_entity_per_subprocess[cap_name][proc_name][subproc_name] = set()
                        data_element_per_entity[cap_name][proc_name + '_' + subproc_name] = {}

                # Only add data entity if subprocess exists in this capability
                if entity_name and subproc_name in proc['subprocesses']:
                    subproc = proc['subprocesses'][subproc_name]
                    if entity_name not in data_entity_per_subprocess[cap_name][proc_name].get(subproc_name, set()):
                        if entity_name not in subproc['data_entities']:
                            subproc['data_entities'][entity_name] = {
                                'data_entity_id': get_uid('data_entity', entity_name, cap_name),
                                'data_entity_name': entity_name,
                                'data_entity_description': entity_desc,
                                'data_elements': OrderedDict()
                            }
                            if subproc_name not in data_entity_per_subprocess[cap_name][proc_name]:
                                data_entity_per_subprocess[cap_name][proc_name][subproc_name] = set()
                            data_entity_per_subprocess[cap_name][proc_name][subproc_name].add(entity_name)
                            key = cap_name + '_' + proc_name + '_' + subproc_name + '_' + entity_name
                            data_element_per_entity[cap_name][key] = set()

                    # Only add data element if entity exists in this capability's subprocess
                    if element_name and entity_name in subproc['data_entities']:
                        entity = subproc['data_entities'][entity_name]
                        key = cap_name + '_' + proc_name + '_' + subproc_name + '_' + entity_name
                        if element_name not in data_element_per_entity[cap_name].get(key, set()):
                            if element_name not in entity['data_elements']:
                                entity['data_elements'][element_name] = {
                                    'data_element_id': get_uid('data_element', element_name, cap_name),
                                    'data_element_name': element_name,
                                    'data_element_description': element_desc
                                }
                                if key not in data_element_per_entity[cap_name]:
                                    data_element_per_entity[cap_name][key] = set()
                                data_element_per_entity[cap_name][key].add(element_name)

    result = []
    for cap in capabilities.values():
        cap_copy = dict(cap)
        cap_copy['processes'] = []
        for proc in cap['processes'].values():
            proc_copy = dict(proc)
            proc_copy['subprocesses'] = []
            for subproc in proc['subprocesses'].values():
                subproc_copy = dict(subproc)
                subproc_copy['data_entities'] = []
                for entity in subproc['data_entities'].values():
                    entity_copy = dict(entity)
                    entity_copy['data_elements'] = list(entity['data_elements'].values())
                    subproc_copy['data_entities'].append(entity_copy)
                proc_copy['subprocesses'].append(subproc_copy)
            cap_copy['processes'].append(proc_copy)
        result.append(cap_copy)

    return result


def import_csv_to_neo4j(csv_path: str) -> Dict[str, Any]:
    from services.upload_service import import_capabilities

    nested_data = parse_csv_to_nested_json(csv_path)

    stats = {
        'capabilities': len(nested_data),
        'processes': sum(len(c['processes']) for c in nested_data),
        'subprocesses': sum(len(p['subprocesses']) for c in nested_data for p in c['processes']),
        'data_entities': sum(
            len(s['data_entities']) for c in nested_data for p in c['processes'] for s in p['subprocesses']),
        'data_elements': sum(
            len(e['data_elements']) for c in nested_data for p in c['processes'] for s in p['subprocesses'] for e in
            s['data_entities'])
    }

    import_capabilities(nested_data)

    return stats
