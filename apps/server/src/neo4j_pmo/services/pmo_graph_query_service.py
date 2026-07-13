import re
from neo4j.graph import Node, Relationship, Path
from neo4j_pmo.services.pmo_query_service import PmoQueryService

_WRITE_PATTERN = re.compile(
    r"\b(CREATE|DELETE|DETACH|SET|REMOVE|MERGE|DROP|FOREACH|LOAD\s+CSV|CALL\s+\{)\b",
    re.IGNORECASE,
)


class PmoGraphQueryService:

    @staticmethod
    def _ingest_node(node: Node, nodes_map: dict):
        nodes_map[node.element_id] = {
            "internal_id": node.element_id,
            "labels": list(node.labels),
            "properties": dict(node),
        }

    @staticmethod
    def _ingest_relationship(rel: Relationship, nodes_map: dict, rels_map: dict):
        start_id = rel.start_node.element_id
        end_id = rel.end_node.element_id
        rels_map[rel.element_id] = {
            "id": rel.element_id,
            "type": rel.type,
            "start_node_id": start_id,
            "end_node_id": end_id,
            "properties": dict(rel),
        }
        if start_id not in nodes_map:
            PmoGraphQueryService._ingest_node(rel.start_node, nodes_map)
        if end_id not in nodes_map:
            PmoGraphQueryService._ingest_node(rel.end_node, nodes_map)

    @staticmethod
    def _ingest_value(value, nodes_map: dict, rels_map: dict):
        if value is None:
            return
        if isinstance(value, Node):
            PmoGraphQueryService._ingest_node(value, nodes_map)
        elif isinstance(value, Relationship):
            PmoGraphQueryService._ingest_relationship(value, nodes_map, rels_map)
        elif isinstance(value, Path):
            for node in value.nodes:
                PmoGraphQueryService._ingest_node(node, nodes_map)
            for rel in value.relationships:
                PmoGraphQueryService._ingest_relationship(rel, nodes_map, rels_map)
        elif isinstance(value, (list, tuple)):
            for item in value:
                PmoGraphQueryService._ingest_value(item, nodes_map, rels_map)

    @staticmethod
    def execute_visualization_query(query: str):
        normalized = query.strip().rstrip(";")
        if not normalized:
            raise ValueError("Query cannot be empty")
        if _WRITE_PATTERN.search(normalized):
            raise ValueError("Only read-only Cypher queries are allowed")

        svc = PmoQueryService()
        try:
            nodes_map = {}
            rels_map = {}

            with svc.driver.session(database=svc.database) as session:
                result = session.run(normalized)
                for record in result:
                    for value in record.values():
                        PmoGraphQueryService._ingest_value(value, nodes_map, rels_map)

            nodes = list(nodes_map.values())
            relationships = [
                rel for rel in rels_map.values()
                if rel["start_node_id"] in nodes_map and rel["end_node_id"] in nodes_map
            ]

            if not nodes:
                raise ValueError("Query returned no nodes to visualize")

            root_id = nodes[0]["internal_id"]
            node_depths = {node["internal_id"]: 0 for node in nodes}

            return {
                "root_id": root_id,
                "nodes": nodes,
                "relationships": relationships,
                "node_depths": node_depths,
                "max_depth": 0,
            }
        finally:
            svc.close()
