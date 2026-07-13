from neo4j_pmo.schema import PMO_LABELS, DISPLAY_NAME_PROPERTIES
from neo4j_pmo.services.pmo_query_service import PmoQueryService
from neo4j_pmo.services.pmo_subtree_service import PmoSubtreeService


class PmoEntityService:

    @staticmethod
    def get_labels():
        svc = PmoQueryService()
        try:
            db_labels = {
                row["label"]
                for row in svc.execute_cypher("CALL db.labels() YIELD label RETURN label")
            }
            return [label for label in PMO_LABELS if label in db_labels] or list(PMO_LABELS)
        except Exception:
            return list(PMO_LABELS)
        finally:
            svc.close()

    @staticmethod
    def get_all_entities(label: str):
        if label not in PMO_LABELS:
            raise ValueError(f"Unknown PMO label '{label}'")

        coalesce_expr = ", ".join(f"n.{prop}" for prop in DISPLAY_NAME_PROPERTIES)
        query = f"""
MATCH (n:{label})
RETURN n.uri AS uri, coalesce({coalesce_expr}) AS name
ORDER BY name
        """
        svc = PmoQueryService()
        try:
            results = svc.execute_cypher(query)
            return [
                {
                    "uri": row["uri"],
                    "name": row["name"] or row["uri"],
                }
                for row in results
                if row.get("uri")
            ]
        finally:
            svc.close()

    @staticmethod
    def get_subtree_by_uri(label, uri, depth=None, direction="outgoing"):
        if label not in PMO_LABELS:
            raise ValueError(f"Unknown PMO label '{label}'")
        return PmoSubtreeService.get_subtree_by_uri(label, uri, depth=depth, direction=direction)
