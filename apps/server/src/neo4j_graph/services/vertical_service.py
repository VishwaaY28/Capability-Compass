from neo4j_graph.services.query_execution_service import Neo4jQueryService


class VerticalService:
    """Service for managing Vertical nodes in Neo4j"""
    
    @staticmethod
    def get_all_verticals():
        """Get all verticals"""
        query = """
        MATCH (v:Vertical)
        RETURN v.uid AS uid, v.name AS name
        ORDER BY v.name
        """
        svc = Neo4jQueryService()
        try:
            results = svc.execute_cypher(query)
            return [{"uid": r["uid"], "name": r["name"]} for r in results]
        finally:
            svc.close()
    
    @staticmethod
    def get_vertical_by_id(vertical_id: int):
        """Get vertical by uid"""
        query = """
        MATCH (v:Vertical {uid: $uid})
        RETURN v.uid AS uid, v.name AS name
        """
        svc = Neo4jQueryService()
        try:
            results = svc.execute_cypher(query, {"uid": vertical_id})
            return results[0] if results else None
        finally:
            svc.close()
    
    @staticmethod
    def create_vertical(name: str, uid: int):
        """Create a new vertical"""
        query = """
        CREATE (v:Vertical {uid: $uid, name: $name})
        RETURN v.uid AS uid, v.name AS name
        """
        svc = Neo4jQueryService()
        try:
            results = svc.execute_cypher(query, {"uid": uid, "name": name})
            return results[0] if results else None
        finally:
            svc.close()
    
    @staticmethod
    def update_vertical(vertical_id: int, name: str):
        """Update vertical name"""
        query = """
        MATCH (v:Vertical {uid: $uid})
        SET v.name = $name
        RETURN v.uid AS uid, v.name AS name
        """
        svc = Neo4jQueryService()
        try:
            results = svc.execute_cypher(query, {"uid": vertical_id, "name": name})
            return results[0] if results else None
        finally:
            svc.close()
    
    @staticmethod
    def delete_vertical(vertical_id: int):
        """Delete vertical and its relationships"""
        query = """
        MATCH (v:Vertical {uid: $uid})
        DETACH DELETE v
        RETURN count(v) AS deleted
        """
        svc = Neo4jQueryService()
        try:
            results = svc.execute_cypher(query, {"uid": vertical_id})
            return results[0]["deleted"] > 0 if results else False
        finally:
            svc.close()
    
    @staticmethod
    def get_all_subverticals():
        """Get all subverticals with their vertical"""
        query = """
        MATCH (sv:SubVertical)
        OPTIONAL MATCH (v:Vertical)-[:HAS_SUBVERTICAL]->(sv)
        RETURN sv.uid AS uid, sv.name AS name, v.uid AS vertical_uid, v.name AS vertical_name
        ORDER BY sv.name
        """
        svc = Neo4jQueryService()
        try:
            results = svc.execute_cypher(query)
            return [{
                "uid": r["uid"],
                "name": r["name"],
                "vertical_uid": r.get("vertical_uid"),
                "vertical_name": r.get("vertical_name")
            } for r in results]
        finally:
            svc.close()
    
    @staticmethod
    def get_subverticals_by_vertical(vertical_id: int):
        """Get all subverticals under a vertical"""
        query = """
        MATCH (v:Vertical {uid: $uid})-[:HAS_SUBVERTICAL]->(sv:SubVertical)
        RETURN sv.uid AS uid, sv.name AS name, v.uid AS vertical_uid
        ORDER BY sv.name
        """
        svc = Neo4jQueryService()
        try:
            results = svc.execute_cypher(query, {"uid": vertical_id})
            return [{"uid": r["uid"], "name": r["name"], "vertical_uid": r["vertical_uid"]} for r in results]
        finally:
            svc.close()
    
    @staticmethod
    def create_subvertical(name: str, uid: int, vertical_id: int):
        """Create a new subvertical under a vertical"""
        query = """
        MATCH (v:Vertical {uid: $vertical_uid})
        CREATE (sv:SubVertical {uid: $uid, name: $name})
        CREATE (v)-[:HAS_SUBVERTICAL]->(sv)
        RETURN sv.uid AS uid, sv.name AS name, v.uid AS vertical_uid, v.name AS vertical_name
        """
        svc = Neo4jQueryService()
        try:
            results = svc.execute_cypher(query, {"uid": uid, "name": name, "vertical_uid": vertical_id})
            return results[0] if results else None
        finally:
            svc.close()
    
    @staticmethod
    def update_subvertical(subvertical_id: int, name: str = None, vertical_id: int = None):
        """Update subvertical"""
        params = {"uid": subvertical_id}
        
        if name and vertical_id:
            query = """
            MATCH (sv:SubVertical {uid: $uid})
            OPTIONAL MATCH (v_old:Vertical)-[r:HAS_SUBVERTICAL]->(sv)
            DELETE r
            WITH sv
            MATCH (v:Vertical {uid: $vertical_uid})
            SET sv.name = $name
            CREATE (v)-[:HAS_SUBVERTICAL]->(sv)
            RETURN sv.uid AS uid, sv.name AS name, v.uid AS vertical_uid, v.name AS vertical_name
            """
            params.update({"name": name, "vertical_uid": vertical_id})
        elif name:
            query = """
            MATCH (sv:SubVertical {uid: $uid})
            SET sv.name = $name
            OPTIONAL MATCH (v:Vertical)-[:HAS_SUBVERTICAL]->(sv)
            RETURN sv.uid AS uid, sv.name AS name, v.uid AS vertical_uid, v.name AS vertical_name
            """
            params["name"] = name
        elif vertical_id:
            query = """
            MATCH (sv:SubVertical {uid: $uid})
            OPTIONAL MATCH (v_old:Vertical)-[r:HAS_SUBVERTICAL]->(sv)
            DELETE r
            WITH sv
            MATCH (v:Vertical {uid: $vertical_uid})
            CREATE (v)-[:HAS_SUBVERTICAL]->(sv)
            RETURN sv.uid AS uid, sv.name AS name, v.uid AS vertical_uid, v.name AS vertical_name
            """
            params["vertical_uid"] = vertical_id
        else:
            return None
        
        svc = Neo4jQueryService()
        try:
            results = svc.execute_cypher(query, params)
            return results[0] if results else None
        finally:
            svc.close()
    
    @staticmethod
    def delete_subvertical(subvertical_id: int):
        """Delete subvertical and its relationships"""
        query = """
        MATCH (sv:SubVertical {uid: $uid})
        DETACH DELETE sv
        RETURN count(sv) AS deleted
        """
        svc = Neo4jQueryService()
        try:
            results = svc.execute_cypher(query, {"uid": subvertical_id})
            return results[0]["deleted"] > 0 if results else False
        finally:
            svc.close()
