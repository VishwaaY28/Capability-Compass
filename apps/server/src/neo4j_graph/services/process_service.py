from neo4j_graph.models import Process
from neo4j_graph.services.graphsubtree_service import GraphSubtreeService
from neo4j_graph.services.query_execution_service import Neo4jQueryService


class ProcessService:

    @staticmethod
    def get_subtree_by_id(process_id, depth=None, direction='outgoing'):
        return GraphSubtreeService.get_subtree_by_property('Process', 'uid', process_id, depth, direction)

    @staticmethod
    def get_subtree_by_name(process_name, depth=None, direction='outgoing'):
        return GraphSubtreeService.get_subtree_by_property('Process', 'name', process_name, depth, direction)

    @staticmethod
    def get_all_processes():
        """Get all processes"""
        query = """
        MATCH (p:Process)
        RETURN p.uid AS uid, p.name AS name, p.level AS level, 
               p.description AS description, p.category AS category
        ORDER BY p.name
        """
        svc = Neo4jQueryService()
        try:
            results = svc.execute_cypher(query)
            return [{
                "uid": r["uid"],
                "name": r["name"],
                "level": r.get("level"),
                "description": r.get("description", ""),
                "category": r.get("category")
            } for r in results]
        finally:
            svc.close()
    
    @staticmethod
    def get_processes_by_capability(capability_id: int):
        """Get all processes for a capability with full subprocess hierarchy including data entities and elements"""
        query = """
        MATCH (c:Capability {uid: $capability_uid})-[:REALIZED_BY]->(p:Process)
        OPTIONAL MATCH (p)-[:DECOMPOSES]->(sp:Subprocess)
        OPTIONAL MATCH (sp)-[:USES_DATA]->(de:DataEntity)
        OPTIONAL MATCH (de)-[:HAS_ELEMENT]->(elem:DataElements)
        RETURN p.uid AS uid, p.name AS name, p.level AS level,
               p.description AS description, p.category AS category,
               collect(DISTINCT {
                   id: sp.uid, name: sp.name, description: sp.description,
                   category: sp.category
               }) AS subprocesses,
               collect(DISTINCT {
                   id: de.uid, name: de.name, description: de.data_entity_description,
                   subprocess_id: sp.uid
               }) AS data_entities,
               collect(DISTINCT {
                   id: elem.uid, name: elem.name, description: elem.data_element_description,
                   data_entity_id: de.uid
               }) AS data_elements
        ORDER BY p.name
        """
        svc = Neo4jQueryService()
        try:
            results = svc.execute_cypher(query, {"capability_uid": capability_id})
            
            # Build hierarchy with data entities and elements
            processes = []
            for r in results:
                # Build subprocesses map
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
                        # Add to subprocess
                        if de["subprocess_id"] in subprocesses_map:
                            subprocesses_map[de["subprocess_id"]]["data_entities"].append(data_entities_map[de["id"]])
                
                # Add data elements to data entities
                for elem in r["data_elements"]:
                    if elem["id"] and elem["data_entity_id"] in data_entities_map:
                        data_entities_map[elem["data_entity_id"]]["data_elements"].append({
                            "data_element_id": elem["id"],
                            "data_element_name": elem["name"],
                            "data_element_description": elem["description"]
                        })
                
                processes.append({
                    "id": r["uid"],
                    "name": r["name"],
                    "level": r.get("level"),
                    "description": r.get("description", ""),
                    "category": r.get("category"),
                    "subprocesses": list(subprocesses_map.values())
                })
            
            return processes
        finally:
            svc.close()
    
    @staticmethod
    def create_process(name: str, level: str, description: str, uid: int, 
                      capability_id: int, category: str = None, subprocesses: list = None):
        """Create a new process"""
        query = """
        MATCH (c:Capability {uid: $capability_uid})
        CREATE (p:Process {uid: $uid, name: $name, level: $level, 
                           description: $description, category: $category})
        CREATE (c)-[:REALIZED_BY]->(p)
        RETURN p.uid AS uid, p.name AS name, p.level AS level,
               p.description AS description, p.category AS category
        """
        svc = Neo4jQueryService()
        try:
            params = {
                "capability_uid": capability_id,
                "uid": uid,
                "name": name,
                "level": level,
                "description": description,
                "category": category
            }
            result = svc.execute_cypher(query, params)
            if not result:
                return None
            
            process = result[0]
            
            # Create subprocesses if provided
            if subprocesses:
                for sp_data in subprocesses:
                    sp_query = """
                    MATCH (p:Process {uid: $process_uid})
                    CREATE (sp:Subprocess {uid: $sp_uid, name: $name, 
                                          description: $description, category: $category})
                    CREATE (p)-[:DECOMPOSES]->(sp)
                    RETURN sp.uid AS uid, sp.name AS name
                    """
                    sp_params = {
                        "process_uid": uid,
                        "sp_uid": sp_data.get("uid"),
                        "name": sp_data.get("name"),
                        "description": sp_data.get("description", ""),
                        "category": sp_data.get("category")
                    }
                    svc.execute_cypher(sp_query, sp_params)
            
            return process
        finally:
            svc.close()
    
    @staticmethod
    def delete_process(process_id: int):
        """Delete process and all its relationships"""
        query = """
        MATCH (p:Process {uid: $uid})
        DETACH DELETE p
        RETURN count(p) AS deleted
        """
        svc = Neo4jQueryService()
        try:
            results = svc.execute_cypher(query, {"uid": process_id})
            return results[0]["deleted"] > 0 if results else False
        finally:
            svc.close()
    
    @staticmethod
    def search_by_concepts(concepts: list, limit: int = 50):
        """
        Search processes by concepts using case-insensitive text matching.
        
        Args:
            concepts: List of concepts/keywords to search for
            limit: Maximum number of results to return
            
        Returns:
            List of processes with parent capability and subprocesses
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
            where_conditions.append(f"toLower(p.name) CONTAINS toLower(${param_name})")
            where_conditions.append(f"toLower(p.description) CONTAINS toLower(${param_name})")
            params[param_name] = concept
        
        where_clause = " OR ".join(where_conditions)
        
        query = f"""
        MATCH (p:Process)
        WHERE {where_clause}
        OPTIONAL MATCH (c:Capability)-[:REALIZED_BY]->(p)
        RETURN DISTINCT p.uid AS uid, c.uid AS capability_uid
        LIMIT $limit
        """
        
        svc = Neo4jQueryService()
        try:
            results = svc.execute_cypher(query, params)
            logger.info(f"[Process Search] Found {len(results)} processes for concepts: {concepts}")
            
            # Fetch full details for each process grouped by capability
            processes = []
            for result in results:
                if result["capability_uid"]:
                    # Get processes with full hierarchy
                    cap_processes = ProcessService.get_processes_by_capability(result["capability_uid"])
                    # Find the matching process
                    for proc in cap_processes:
                        if proc["id"] == result["uid"]:
                            processes.append(proc)
                            break
            
            return processes
        finally:
            svc.close()
