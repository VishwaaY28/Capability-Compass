from neo4j_graph.models import Capability
from neo4j_graph.services.graphsubtree_service import GraphSubtreeService
from neo4j_graph.services.query_execution_service import Neo4jQueryService


class CapabilityService:

    @staticmethod
    def get_subtree_by_id(capability_id, depth=None, direction='outgoing'):
        return GraphSubtreeService.get_subtree_by_property('Capability', 'uid', capability_id, depth, direction)

    @staticmethod
    def get_subtree_by_name(capability_name, depth=None, direction='outgoing'):
        return GraphSubtreeService.get_subtree_by_property('Capability', 'name', capability_name, depth, direction)

    @staticmethod
    def get_all_capabilities():
        """Get all capabilities with their vertical and subvertical"""
        query = """
        MATCH (c:Capability)
        OPTIONAL MATCH (sv:SubVertical)-[:HAS_CAPABILITY]->(c)
        OPTIONAL MATCH (v:Vertical)-[:HAS_SUBVERTICAL]->(sv)
        RETURN c.uid AS uid, c.name AS name, c.description AS description,
               v.name AS vertical, sv.name AS subvertical
        ORDER BY c.name
        """
        svc = Neo4jQueryService()
        try:
            results = svc.execute_cypher(query)
            return [{
                "uid": r["uid"],
                "name": r["name"],
                "description": r.get("description", ""),
                "vertical": r.get("vertical"),
                "subvertical": r.get("subvertical")
            } for r in results]
        finally:
            svc.close()
    
    @staticmethod
    def get_capability_by_id(capability_id):
        """Get single capability with full hierarchy"""
        query = """
        MATCH (c:Capability {uid: $uid})
        OPTIONAL MATCH (sv:SubVertical)-[:HAS_CAPABILITY]->(c)
        OPTIONAL MATCH (v:Vertical)-[:HAS_SUBVERTICAL]->(sv)
        OPTIONAL MATCH (c)-[:REALIZED_BY]->(p:Process)
        OPTIONAL MATCH (p)-[:DECOMPOSES]->(sp:Subprocess)
        OPTIONAL MATCH (sp)-[:USES_DATA]->(de:DataEntity)
        OPTIONAL MATCH (de)-[:HAS_ELEMENT]->(elem:DataElements)
        RETURN c, v.name AS vertical, sv.name AS subvertical,
               collect(DISTINCT {
                   id: p.uid, name: p.name, level: p.level, 
                   description: p.description, category: p.category
               }) AS processes,
               collect(DISTINCT {
                   id: sp.uid, name: sp.name, description: sp.description,
                   category: sp.category, process_id: p.uid
               }) AS subprocesses,
               collect(DISTINCT {
                   id: de.uid, name: de.name, description: de.data_entity_description,
                   subprocess_id: sp.uid
               }) AS data_entities,
               collect(DISTINCT {
                   id: elem.uid, name: elem.name, description: elem.data_element_description,
                   data_entity_id: de.uid
               }) AS data_elements
        """
        svc = Neo4jQueryService()
        try:
            results = svc.execute_cypher(query, {"uid": capability_id})
            if not results:
                return None
            
            r = results[0]
            cap = r["c"]
            
            # Build hierarchy
            processes_map = {}
            for p in r["processes"]:
                if p["id"]:
                    processes_map[p["id"]] = {
                        "id": p["id"],
                        "name": p["name"],
                        "level": p["level"],
                        "description": p["description"],
                        "category": p["category"],
                        "subprocesses": []
                    }
            
            subprocesses_map = {}
            for sp in r["subprocesses"]:
                if sp["id"]:
                    subprocesses_map[sp["id"]] = {
                        "id": sp["id"],
                        "name": sp["name"],
                        "description": sp["description"],
                        "category": sp["category"],
                        "data_entities": []
                    }
                    if sp["process_id"] in processes_map:
                        processes_map[sp["process_id"]]["subprocesses"].append(subprocesses_map[sp["id"]])
            
            data_entities_map = {}
            for de in r["data_entities"]:
                if de["id"]:
                    data_entities_map[de["id"]] = {
                        "data_entity_id": de["id"],
                        "data_entity_name": de["name"],
                        "data_entity_description": de["description"],
                        "data_elements": []
                    }
                    if de["subprocess_id"] in subprocesses_map:
                        subprocesses_map[de["subprocess_id"]]["data_entities"].append(data_entities_map[de["id"]])
            
            for elem in r["data_elements"]:
                if elem["id"] and elem["data_entity_id"] in data_entities_map:
                    data_entities_map[elem["data_entity_id"]]["data_elements"].append({
                        "data_element_id": elem["id"],
                        "data_element_name": elem["name"],
                        "data_element_description": elem["description"]
                    })
            
            return {
                "id": cap["uid"],
                "name": cap["name"],
                "description": cap.get("description", ""),
                "vertical": r.get("vertical"),
                "subvertical": r.get("subvertical"),
                "processes": list(processes_map.values())
            }
        finally:
            svc.close()
    
    @staticmethod
    def create_capability(name: str, description: str, uid: int, subvertical_id: int = None):
        """Create a new capability"""
        if subvertical_id:
            query = """
            MATCH (sv:SubVertical {uid: $subvertical_uid})
            CREATE (c:Capability {uid: $uid, name: $name, description: $description})
            CREATE (sv)-[:HAS_CAPABILITY]->(c)
            WITH c, sv
            OPTIONAL MATCH (v:Vertical)-[:HAS_SUBVERTICAL]->(sv)
            RETURN c.uid AS uid, c.name AS name, c.description AS description,
                   v.name AS vertical, sv.name AS subvertical
            """
            params = {"uid": uid, "name": name, "description": description, "subvertical_uid": subvertical_id}
        else:
            query = """
            CREATE (c:Capability {uid: $uid, name: $name, description: $description})
            RETURN c.uid AS uid, c.name AS name, c.description AS description,
                   null AS vertical, null AS subvertical
            """
            params = {"uid": uid, "name": name, "description": description}
        
        svc = Neo4jQueryService()
        try:
            results = svc.execute_cypher(query, params)
            return results[0] if results else None
        finally:
            svc.close()
    
    @staticmethod
    def update_capability(capability_id: int, name: str = None, description: str = None, subvertical_id: int = None):
        """Update capability"""
        set_clauses = []
        params = {"uid": capability_id}
        
        if name:
            set_clauses.append("c.name = $name")
            params["name"] = name
        if description is not None:
            set_clauses.append("c.description = $description")
            params["description"] = description
        
        if not set_clauses and subvertical_id is None:
            return None
        
        if subvertical_id:
            params["subvertical_uid"] = subvertical_id
            query = f"""
            MATCH (c:Capability {{uid: $uid}})
            OPTIONAL MATCH (sv_old:SubVertical)-[r:HAS_CAPABILITY]->(c)
            DELETE r
            WITH c
            MATCH (sv:SubVertical {{uid: $subvertical_uid}})
            {('SET ' + ', '.join(set_clauses)) if set_clauses else ''}
            CREATE (sv)-[:HAS_CAPABILITY]->(c)
            WITH c, sv
            OPTIONAL MATCH (v:Vertical)-[:HAS_SUBVERTICAL]->(sv)
            RETURN c.uid AS uid, c.name AS name, c.description AS description,
                   v.name AS vertical, sv.name AS subvertical
            """
        else:
            query = f"""
            MATCH (c:Capability {{uid: $uid}})
            {('SET ' + ', '.join(set_clauses)) if set_clauses else ''}
            OPTIONAL MATCH (sv:SubVertical)-[:HAS_CAPABILITY]->(c)
            OPTIONAL MATCH (v:Vertical)-[:HAS_SUBVERTICAL]->(sv)
            RETURN c.uid AS uid, c.name AS name, c.description AS description,
                   v.name AS vertical, sv.name AS subvertical
            """
        
        svc = Neo4jQueryService()
        try:
            results = svc.execute_cypher(query, params)
            return results[0] if results else None
        finally:
            svc.close()

    @staticmethod
    def delete_by_id(capability_id):
        """Delete capability and all its relationships"""
        query = """
        MATCH (c:Capability {uid: $uid})
        DETACH DELETE c
        RETURN count(c) AS deleted
        """
        svc = Neo4jQueryService()
        try:
            results = svc.execute_cypher(query, {"uid": capability_id})
            return results[0]["deleted"] > 0 if results else False
        finally:
            svc.close()

    @staticmethod
    def delete_by_name(capability_name):
        """Delete capability by name"""
        query = """
        MATCH (c:Capability {name: $name})
        DETACH DELETE c
        RETURN count(c) AS deleted
        """
        svc = Neo4jQueryService()
        try:
            results = svc.execute_cypher(query, {"name": capability_name})
            return results[0]["deleted"] > 0 if results else False
        finally:
            svc.close()
    
    @staticmethod
    def search_capabilities_by_keywords(keywords: list):
        """Search capabilities by keywords"""
        if not keywords:
            return []
        
        # Build regex pattern for case-insensitive search
        pattern = "|".join([f"(?i).*{kw}.*" for kw in keywords])
        
        query = """
        MATCH (c:Capability)
        WHERE c.name =~ $pattern OR c.description =~ $pattern
        OPTIONAL MATCH (sv:SubVertical)-[:HAS_CAPABILITY]->(c)
        OPTIONAL MATCH (v:Vertical)-[:HAS_SUBVERTICAL]->(sv)
        RETURN c.uid AS uid, c.name AS name, c.description AS description,
               v.name AS vertical, sv.name AS subvertical
        ORDER BY c.name
        """
        
        svc = Neo4jQueryService()
        try:
            results = svc.execute_cypher(query, {"pattern": pattern})
            return [{
                "uid": r["uid"],
                "name": r["name"],
                "description": r.get("description", ""),
                "vertical": r.get("vertical"),
                "subvertical": r.get("subvertical")
            } for r in results]
        finally:
            svc.close()
    
    @staticmethod
    def search_by_concepts(concepts: list, limit: int = 50):
        """
        Search capabilities by matching concepts anywhere in the full hierarchy:
        Capability → Process → Subprocess → DataEntity → DataElements.
        Returns deduplicated capability UIDs so the caller can fetch full depth.
        """
        import logging
        logger = logging.getLogger(__name__)

        if not concepts:
            return []

        # Build per-concept OR conditions across every relevant text field
        concept_blocks = []
        params: dict = {"limit": limit}

        for i, concept in enumerate(concepts):
            p = f"c{i}"
            params[p] = concept
            concept_blocks.append(f"""(
                toLower(c.name)                    CONTAINS toLower(${p}) OR
                toLower(c.description)             CONTAINS toLower(${p}) OR
                toLower(p.name)                    CONTAINS toLower(${p}) OR
                toLower(p.description)             CONTAINS toLower(${p}) OR
                toLower(sp.name)                   CONTAINS toLower(${p}) OR
                toLower(sp.description)            CONTAINS toLower(${p}) OR
                toLower(de.name)                   CONTAINS toLower(${p}) OR
                toLower(de.data_entity_description) CONTAINS toLower(${p}) OR
                toLower(elem.name)                 CONTAINS toLower(${p}) OR
                toLower(elem.data_element_description) CONTAINS toLower(${p})
            )""")

        where_clause = " OR ".join(concept_blocks)

        # Single traversal — optional matches so capabilities with no children still appear
        query = f"""
        MATCH (c:Capability)
        OPTIONAL MATCH (c)-[:REALIZED_BY]->(p:Process)
        OPTIONAL MATCH (p)-[:DECOMPOSES]->(sp:Subprocess)
        OPTIONAL MATCH (sp)-[:USES_DATA]->(de:DataEntity)
        OPTIONAL MATCH (de)-[:HAS_ELEMENT]->(elem:DataElements)
        WITH c, p, sp, de, elem
        WHERE {where_clause}
        RETURN DISTINCT c.uid AS uid
        LIMIT $limit
        """

        svc = Neo4jQueryService()
        try:
            results = svc.execute_cypher(query, params)
            logger.info(f"[Capability Search] Found {len(results)} capabilities for concepts: {concepts}")

            capabilities = []
            for row in results:
                cap = CapabilityService.get_capability_by_id(row["uid"])
                if cap:
                    capabilities.append(cap)

            return capabilities
        finally:
            svc.close()
