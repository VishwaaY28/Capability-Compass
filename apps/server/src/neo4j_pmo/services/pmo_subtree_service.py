from neo4j_pmo.services.pmo_query_service import PmoQueryService


class PmoSubtreeService:

    @staticmethod
    def get_subtree_by_uri(label, uri, depth=None, direction="outgoing", rel_types=None):
        direction_map = {
            "out": "outgoing",
            "in": "incoming",
            "both": "both",
            "outgoing": "outgoing",
            "incoming": "incoming",
        }
        direction_norm = direction_map.get(direction.lower())
        if direction_norm is None:
            raise ValueError("Direction must be one of 'outgoing', 'incoming', 'both'")

        depth_str = f"*1..{depth}" if depth is not None else "*"
        rel_filter = f":{('|'.join(rel_types))}" if rel_types else ""

        if direction_norm == "outgoing":
            rel_pattern = f"-[{rel_filter}{depth_str}]->"
        elif direction_norm == "incoming":
            rel_pattern = f"<-[{rel_filter}{depth_str}]-"
        else:
            rel_pattern = f"-[{rel_filter}{depth_str}]-"

        nodes_query = f"""
MATCH (root:{label} {{uri: $value}})
OPTIONAL MATCH path = (root){rel_pattern}(x)
WITH root, collect(path) AS paths
UNWIND (CASE WHEN size(paths) = 0 THEN [null] ELSE paths END) AS p
WITH root, p, CASE WHEN p IS NULL THEN [root] ELSE nodes(p) END AS path_nodes
UNWIND path_nodes AS nd
RETURN DISTINCT
  elementId(nd) AS node_id,
  labels(nd) AS labels,
  properties(nd) AS properties,
  CASE WHEN nd = root THEN 0 ELSE coalesce(length(p), 0) END AS depth
        """

        rels_query = f"""
MATCH (root:{label} {{uri: $value}})
OPTIONAL MATCH path = (root){rel_pattern}(x)
WITH collect(path) AS paths
UNWIND paths AS p
UNWIND relationships(p) AS rel
RETURN DISTINCT
  elementId(rel) AS rel_id,
  type(rel) AS rel_type,
  elementId(startNode(rel)) AS start_node_id,
  elementId(endNode(rel)) AS end_node_id,
  properties(rel) AS rel_properties
        """

        svc = PmoQueryService()
        try:
            node_results = svc.execute_cypher(nodes_query, {"value": uri})
            if not node_results:
                return None

            nodes_map = {}
            node_depths = {}
            max_depth = 0
            root_id = None

            for record in node_results:
                node_id = record["node_id"]
                if not node_id:
                    continue
                depth_val = record["depth"] if record["depth"] is not None else 0
                if depth_val == 0 and root_id is None:
                    root_id = node_id
                if depth_val > max_depth:
                    max_depth = depth_val
                nodes_map[node_id] = {
                    "internal_id": node_id,
                    "labels": record["labels"] or [],
                    "properties": record["properties"] or {},
                }
                node_depths[node_id] = min(node_depths.get(node_id, depth_val), depth_val)

            if not root_id:
                return None

            relationships = []
            rel_results = svc.execute_cypher(rels_query, {"value": uri})
            for record in rel_results:
                rel_id = record["rel_id"]
                start_id = record["start_node_id"]
                end_id = record["end_node_id"]
                if not rel_id or not start_id or not end_id:
                    continue
                if start_id not in nodes_map or end_id not in nodes_map:
                    continue
                relationships.append({
                    "id": rel_id,
                    "type": record["rel_type"],
                    "start_node_id": start_id,
                    "end_node_id": end_id,
                    "properties": record["rel_properties"] or {},
                })

            return {
                "root_id": root_id,
                "nodes": list(nodes_map.values()),
                "relationships": relationships,
                "node_depths": node_depths,
                "max_depth": max_depth,
            }
        finally:
            svc.close()
