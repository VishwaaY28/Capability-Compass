from neomodel import db


class GraphSubtreeService:

    @staticmethod
    def get_subtree_by_property(label, match_property, match_value, depth=None, direction='outgoing', rel_types=None):
        direction_map = {'out': 'outgoing', 'in': 'incoming', 'both': 'both', 'outgoing': 'outgoing', 'incoming': 'incoming'}
        direction_norm = direction_map.get(direction.lower())
        if direction_norm is None:
            raise ValueError("Direction must be one of 'outgoing', 'incoming', 'both'")

        depth_str = f'*1..{depth}' if depth is not None else '*'
        rel_filter = f":{('|'.join(rel_types))}" if rel_types else ''

        if direction_norm == 'outgoing':
            rel_pattern = f'-[{rel_filter}{depth_str}]->'
        elif direction_norm == 'incoming':
            rel_pattern = f'<-[{rel_filter}{depth_str}]-'
        else:
            rel_pattern = f'-[{rel_filter}{depth_str}]-'

        query = f"""
MATCH (root:{label} {{{match_property}: $value}})
OPTIONAL MATCH path = (root){rel_pattern}(x)
WITH collect(path) AS paths
UNWIND paths AS p
UNWIND nodes(p) AS nd
UNWIND relationships(p) AS rel
RETURN DISTINCT nd, rel, length(p) AS depth;
        """
        results, _ = db.cypher_query(query, {'value': match_value})

        root_query = f"MATCH (root:{label} {{{match_property}: $value}}) RETURN root"
        root_results, _ = db.cypher_query(root_query, {'value': match_value})
        if not root_results:
            return None

        root_node = root_results[0][0]
        root_id = root_node.id

        nodes_map = {
            root_id: {
                "internal_id": root_id,
                "uid": root_node.get("uid"),
                "labels": list(root_node.labels),
                "properties": dict(root_node),
            }
        }
        node_depths = {root_id: 0}
        max_depth = 0
        relationships_map = {}

        for record in results:
            node, rel, depth_val = record[0], record[1], record[2]
            if depth_val > max_depth:
                max_depth = depth_val
            node_id = node.id
            if node_id not in nodes_map:
                nodes_map[node_id] = {
                    "internal_id": node_id,
                    "uid": node.get("uid"),
                    "labels": list(node.labels),
                    "properties": dict(node),
                }
                node_depths[node_id] = depth_val
            elif depth_val < node_depths[node_id]:
                node_depths[node_id] = depth_val

            if rel is not None:
                rel_id = rel.id
                if rel_id not in relationships_map:
                    relationships_map[rel_id] = {
                        "id": rel_id,
                        "type": rel.type,
                        "start_node_id": rel.start_node.id,
                        "end_node_id": rel.end_node.id,
                        "properties": dict(rel),
                    }

        children_map = {}
        for rel in relationships_map.values():
            start_id, end_id = rel['start_node_id'], rel['end_node_id']
            if direction_norm == 'incoming':
                parent_id, child_id = end_id, start_id
            else:
                parent_id, child_id = start_id, end_id
            children_map.setdefault(parent_id, {}).setdefault(rel['type'], []).append(child_id)

        def build_node(node_id):
            node = nodes_map.get(node_id)
            if not node:
                return None
            node_data = {"internal_id": node["internal_id"], "labels": node["labels"], "properties": node["properties"]}
            rels = children_map.get(node_id)
            if rels:
                node_data["relationships"] = {
                    rel_type: [child for cid in child_ids if (child := build_node(cid))]
                    for rel_type, child_ids in rels.items()
                }
            return node_data

        return {"root": build_node(root_id), "node_depths": node_depths, "max_depth": max_depth}
