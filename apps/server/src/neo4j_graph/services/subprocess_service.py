from neo4j_graph.models import Subprocess
from neo4j_graph.services.graphsubtree_service import GraphSubtreeService
from neo4j_graph.services.query_execution_service import Neo4jQueryService


class SubprocessService:

    @staticmethod
    def get_subtree_by_id(subprocess_id, depth=None, direction='outgoing'):
        return GraphSubtreeService.get_subtree_by_property('Subprocess', 'uid', subprocess_id, depth, direction)

    @staticmethod
    def get_subtree_by_name(subprocess_name, depth=None, direction='outgoing'):
        return GraphSubtreeService.get_subtree_by_property('Subprocess', 'name', subprocess_name, depth, direction)

    @staticmethod
    def get_all_subprocesses():
        """Get all subprocesses"""
        query = """
        MATCH (sp:Subprocess)
        RETURN sp.uid AS uid, sp.name AS name, sp.description AS description, sp.category AS category
        ORDER BY sp.name
        """
        svc = Neo4jQueryService()
        try:
            results = svc.execute_cypher(query)
            return [{
                "uid": r["uid"],
                "name": r["name"],
                "description": r.get("description", ""),
                "category": r.get("category")
            } for r in results]
        finally:
            svc.close()
    
    @staticmethod
    def create_subprocess(name: str, description: str, uid: int, parent_process_id: int, category: str = None):
        """Create a new subprocess"""
        query = """
        MATCH (p:Process {uid: $process_uid})
        CREATE (sp:Subprocess {uid: $uid, name: $name, description: $description, category: $category})
        CREATE (p)-[:DECOMPOSES]->(sp)
        RETURN sp.uid AS uid, sp.name AS name, sp.description AS description, sp.category AS category
        """
        svc = Neo4jQueryService()
        try:
            params = {
                "process_uid": parent_process_id,
                "uid": uid,
                "name": name,
                "description": description,
                "category": category
            }
            results = svc.execute_cypher(query, params)
            return results[0] if results else None
        finally:
            svc.close()
    
    @staticmethod
    def delete_subprocess(subprocess_id: int):
        """Delete subprocess and all its relationships"""
        query = """
        MATCH (sp:Subprocess {uid: $uid})
        DETACH DELETE sp
        RETURN count(sp) AS deleted
        """
        svc = Neo4jQueryService()
        try:
            results = svc.execute_cypher(query, {"uid": subprocess_id})
            return results[0]["deleted"] > 0 if results else False
        finally:
            svc.close()
    
    @staticmethod
    def search_by_concepts(concepts: list, limit: int = 50):
        """
        Search subprocesses by concepts using case-insensitive text matching.
        
        Args:
            concepts: List of concepts/keywords to search for
            limit: Maximum number of results to return
            
        Returns:
            List of subprocesses with parent process, capability, and data entities
        """
        import logging
        logger = logging.getLogger(__name__)
        
        if not concepts:
            return []
        
        # Build WHERE clause with OR conditions for each concept
        where_conditions = []
        params = {"limit": limit}
        
        for i, concept in enumerate(concepts):
            param_name = f"concept{i}"
            where_conditions.append(f"toLower(sp.name) CONTAINS toLower(${param_name})")
            where_conditions.append(f"toLower(sp.description) CONTAINS toLower(${param_name})")
            params[param_name] = concept
        
        where_clause = " OR ".join(where_conditions)
        
        query = f"""
        MATCH (sp:Subprocess)
        WHERE {where_clause}
        OPTIONAL MATCH (p:Process)-[:DECOMPOSES]->(sp)
        OPTIONAL MATCH (c:Capability)-[:REALIZED_BY]->(p)
        OPTIONAL MATCH (sp)-[:USES_DATA]->(de:DataEntity)
        OPTIONAL MATCH (de)-[:HAS_ELEMENT]->(elem:DataElements)
        OPTIONAL MATCH (sv:SubVertical)-[:HAS_CAPABILITY]->(c)
        OPTIONAL MATCH (v:Vertical)-[:HAS_SUBVERTICAL]->(sv)
        RETURN DISTINCT sp.uid AS uid, sp.name AS name, sp.description AS description, sp.category AS category,
               p.uid AS process_id, p.name AS process_name,
               c.uid AS capability_id, c.name AS capability_name,
               v.name AS vertical, sv.name AS subvertical,
               collect(DISTINCT {{
                   id: de.uid, name: de.name, description: de.data_entity_description
               }}) AS data_entities,
               collect(DISTINCT {{
                   id: elem.uid, name: elem.name, description: elem.data_element_description,
                   data_entity_id: de.uid
               }}) AS data_elements
        LIMIT $limit
        """
        
        svc = Neo4jQueryService()
        try:
            results = svc.execute_cypher(query, params)
            logger.info(f"[Subprocess Search] Found {len(results)} subprocesses for concepts: {concepts}")
            
            # Build subprocess objects with full hierarchy
            subprocesses = []
            for r in results:
                # Build data entities map
                data_entities_map = {}
                for de in r["data_entities"]:
                    if de["id"]:
                        data_entities_map[de["id"]] = {
                            "data_entity_id": de["id"],
                            "data_entity_name": de["name"],
                            "data_entity_description": de["description"],
                            "data_elements": []
                        }
                
                # Add data elements to data entities
                for elem in r["data_elements"]:
                    if elem["id"] and elem["data_entity_id"] in data_entities_map:
                        data_entities_map[elem["data_entity_id"]]["data_elements"].append({
                            "data_element_id": elem["id"],
                            "data_element_name": elem["name"],
                            "data_element_description": elem["description"]
                        })
                
                subprocesses.append({
                    "id": r["uid"],
                    "name": r["name"],
                    "description": r["description"],
                    "category": r["category"],
                    "parent_process": {
                        "id": r["process_id"],
                        "name": r["process_name"]
                    } if r["process_id"] else None,
                    "parent_capability": {
                        "id": r["capability_id"],
                        "name": r["capability_name"],
                        "vertical": r.get("vertical"),
                        "subvertical": r.get("subvertical")
                    } if r["capability_id"] else None,
                    "data_entities": list(data_entities_map.values())
                })
            
            return subprocesses
        finally:
            svc.close()
