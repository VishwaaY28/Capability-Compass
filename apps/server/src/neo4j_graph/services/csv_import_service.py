"""
CSV Import Service for Capability Compass

Handles parsing and importing CSV data into Neo4j graph database.
"""
import csv
import io
import logging
from typing import Dict, List, Tuple

from neo4j_graph.services.query_execution_service import Neo4jQueryService

logger = logging.getLogger(__name__)


class CSVImportService:
    """Service for importing CSV data to Neo4j"""
    
    # Expected CSV columns
    EXPECTED_COLUMNS = [
        "Vertical",
        "Sub Vertical",
        "Capability Name",
        "Process",
        "Process Description",
        "Sub Process",
        "Sub-Process Description",
        "Data Entity",
        "Data Entity Description",
        "Data Element",
        "Data Element Description",
        "Organization Units",
        "Applications"
    ]
    
    @staticmethod
    def validate_csv_structure(csv_text: str) -> Tuple[bool, str]:
        """
        Validate CSV structure and columns.
        
        Args:
            csv_text: CSV content as string
            
        Returns:
            Tuple of (is_valid, error_message)
        """
        try:
            csv_reader = csv.DictReader(io.StringIO(csv_text))
            headers = csv_reader.fieldnames
            
            if not headers:
                return False, "CSV file is empty or has no headers"
            
            # Check for required columns
            missing_columns = []
            for col in CSVImportService.EXPECTED_COLUMNS:
                if col not in headers:
                    missing_columns.append(col)
            
            if missing_columns:
                return False, f"Missing required columns: {', '.join(missing_columns)}"
            
            return True, ""
            
        except Exception as e:
            return False, f"Invalid CSV format: {str(e)}"
    
    @staticmethod
    def get_max_uids() -> Dict[str, int]:
        """
        Get maximum UIDs for all node types in a single query for performance.
        
        Returns:
            Dictionary mapping node type to next available UID
        """
        uid_map = {
            "vertical": 1,
            "subvertical": 1,
            "capability": 1,
            "process": 1,
            "subprocess": 1,
            "data_entity": 1,
            "data_element": 1,
            "org_unit": 1,
            "application": 1
        }
        
        svc = Neo4jQueryService()
        try:
            # Get all max UIDs in a single query for performance
            query = """
            OPTIONAL MATCH (v:Vertical)
            WITH max(v.uid) AS max_vertical
            OPTIONAL MATCH (sv:SubVertical)
            WITH max_vertical, max(sv.uid) AS max_subvertical
            OPTIONAL MATCH (c:Capability)
            WITH max_vertical, max_subvertical, max(c.uid) AS max_capability
            OPTIONAL MATCH (p:Process)
            WITH max_vertical, max_subvertical, max_capability, max(p.uid) AS max_process
            OPTIONAL MATCH (sp:Subprocess)
            WITH max_vertical, max_subvertical, max_capability, max_process, max(sp.uid) AS max_subprocess
            OPTIONAL MATCH (de:DataEntity)
            WITH max_vertical, max_subvertical, max_capability, max_process, max_subprocess, max(de.uid) AS max_data_entity
            OPTIONAL MATCH (elem:DataElements)
            WITH max_vertical, max_subvertical, max_capability, max_process, max_subprocess, max_data_entity, max(elem.uid) AS max_data_element
            OPTIONAL MATCH (ou:OrganizationUnit)
            WITH max_vertical, max_subvertical, max_capability, max_process, max_subprocess, max_data_entity, max_data_element, max(ou.uid) AS max_org_unit
            OPTIONAL MATCH (app:ApplicationCatalog)
            RETURN max_vertical, max_subvertical, max_capability, max_process, max_subprocess, 
                   max_data_entity, max_data_element, max_org_unit, max(app.uid) AS max_application
            """
            results = svc.execute_cypher(query)
            
            if results:
                r = results[0]
                uid_map["vertical"] = (r["max_vertical"] or 0) + 1
                uid_map["subvertical"] = (r["max_subvertical"] or 0) + 1
                uid_map["capability"] = (r["max_capability"] or 0) + 1
                uid_map["process"] = (r["max_process"] or 0) + 1
                uid_map["subprocess"] = (r["max_subprocess"] or 0) + 1
                uid_map["data_entity"] = (r["max_data_entity"] or 0) + 1
                uid_map["data_element"] = (r["max_data_element"] or 0) + 1
                uid_map["org_unit"] = (r["max_org_unit"] or 0) + 1
                uid_map["application"] = (r["max_application"] or 0) + 1
        finally:
            svc.close()
        
        return uid_map
    
    @staticmethod
    def clear_all_data():
        """Clear all data from Neo4j database"""
        logger.info("Clearing all data from Neo4j...")
        svc = Neo4jQueryService()
        try:
            svc.execute_cypher("MATCH (n) DETACH DELETE n")
            logger.info("All data cleared successfully")
        finally:
            svc.close()
    
    @staticmethod
    def create_or_get_vertical(name: str, uid_counter: Dict[str, int], 
                               cache: Dict[str, int]) -> int:
        """Create or get vertical by name"""
        if name in cache:
            return cache[name]
        
        svc = Neo4jQueryService()
        try:
            query = "MATCH (v:Vertical {name: $name}) RETURN v.uid AS uid"
            result = svc.execute_cypher(query, {"name": name})
            
            if result:
                uid = result[0]["uid"]
                cache[name] = uid
                return uid
            
            uid = uid_counter["vertical"]
            query = """
            CREATE (v:Vertical {uid: $uid, name: $name})
            RETURN v.uid AS uid
            """
            svc.execute_cypher(query, {"uid": uid, "name": name})
            
            cache[name] = uid
            uid_counter["vertical"] += 1
            logger.info(f"Created vertical: {name} (UID: {uid})")
            return uid
            
        finally:
            svc.close()
    
    @staticmethod
    def create_or_get_subvertical(name: str, vertical_uid: int, uid_counter: Dict[str, int], 
                                  cache: Dict[Tuple, int]) -> int:
        """Create or get subvertical by name and vertical"""
        key = (vertical_uid, name)
        if key in cache:
            return cache[key]
        
        svc = Neo4jQueryService()
        try:
            query = """
            MATCH (v:Vertical {uid: $v_uid})-[:HAS_SUBVERTICAL]->(sv:SubVertical {name: $name})
            RETURN sv.uid AS uid
            """
            result = svc.execute_cypher(query, {"v_uid": vertical_uid, "name": name})
            
            if result:
                uid = result[0]["uid"]
                cache[key] = uid
                return uid
            
            uid = uid_counter["subvertical"]
            query = """
            MATCH (v:Vertical {uid: $v_uid})
            CREATE (sv:SubVertical {uid: $uid, name: $name})
            CREATE (v)-[:HAS_SUBVERTICAL]->(sv)
            RETURN sv.uid AS uid
            """
            svc.execute_cypher(query, {
                "v_uid": vertical_uid,
                "uid": uid,
                "name": name
            })
            
            cache[key] = uid
            uid_counter["subvertical"] += 1
            logger.info(f"  Created subvertical: {name} (UID: {uid})")
            return uid
            
        finally:
            svc.close()
    
    @staticmethod
    def parse_csv_rows(csv_text: str) -> List[Dict[str, str]]:
        """
        Parse CSV text into list of row dictionaries.
        
        Args:
            csv_text: CSV content as string
            
        Returns:
            List of dictionaries, one per row
        """
        csv_reader = csv.DictReader(io.StringIO(csv_text))
        rows = []
        
        for row in csv_reader:
            # Clean and normalize row data
            cleaned_row = {
                "vertical": row.get("Vertical", "").strip(),
                "subvertical": row.get("Sub Vertical", "").strip(),
                "capability_name": row.get("Capability Name", "").strip(),
                "process_name": row.get("Process", "").strip(),
                "process_desc": row.get("Process Description", "").strip(),
                "subprocess_name": row.get("Sub Process", "").strip(),
                "subprocess_desc": row.get("Sub-Process Description", "").strip(),
                "data_entity_name": row.get("Data Entity", "").strip(),
                "data_entity_desc": row.get("Data Entity Description", "").strip(),
                "data_element_name": row.get("Data Element", "").strip(),
                "data_element_desc": row.get("Data Element Description", "").strip(),
                "org_units": row.get("Organization Units", "").strip(),
                "applications": row.get("Applications", "").strip()
            }
            
            # Skip completely empty rows
            if not any(cleaned_row.values()):
                continue
            
            # Must have at least a capability name
            if not cleaned_row["capability_name"]:
                continue
            
            rows.append(cleaned_row)
        
        return rows
    @staticmethod
    def create_or_get_vertical(name: str, uid_counter: Dict[str, int],
                               cache: Dict[str, int]) -> int:
        """Create or get vertical by name"""
        if name in cache:
            return cache[name]

        svc = Neo4jQueryService()
        try:
            query = "MATCH (v:Vertical {name: $name}) RETURN v.uid AS uid"
            result = svc.execute_cypher(query, {"name": name})

            if result:
                uid = result[0]["uid"]
                cache[name] = uid
                return uid

            uid = uid_counter["vertical"]
            query = """
            CREATE (v:Vertical {uid: $uid, name: $name})
            RETURN v.uid AS uid
            """
            svc.execute_cypher(query, {"uid": uid, "name": name})

            cache[name] = uid
            uid_counter["vertical"] += 1
            logger.info(f"Created vertical: {name} (UID: {uid})")
            return uid

        finally:
            svc.close()

    @staticmethod
    def create_or_get_subvertical(name: str, vertical_uid: int, uid_counter: Dict[str, int],
                                  cache: Dict[Tuple, int]) -> int:
        """Create or get subvertical by name and vertical"""
        key = (vertical_uid, name)
        if key in cache:
            return cache[key]

        svc = Neo4jQueryService()
        try:
            query = """
            MATCH (v:Vertical {uid: $v_uid})-[:HAS_SUBVERTICAL]->(sv:SubVertical {name: $name})
            RETURN sv.uid AS uid
            """
            result = svc.execute_cypher(query, {"v_uid": vertical_uid, "name": name})

            if result:
                uid = result[0]["uid"]
                cache[key] = uid
                return uid

            uid = uid_counter["subvertical"]
            query = """
            MATCH (v:Vertical {uid: $v_uid})
            CREATE (sv:SubVertical {uid: $uid, name: $name})
            CREATE (v)-[:HAS_SUBVERTICAL]->(sv)
            RETURN sv.uid AS uid
            """
            svc.execute_cypher(query, {
                "v_uid": vertical_uid,
                "uid": uid,
                "name": name
            })

            cache[key] = uid
            uid_counter["subvertical"] += 1
            logger.info(f"  Created subvertical: {name} (UID: {uid})")
            return uid

        finally:
            svc.close()

    
    @staticmethod
    def create_or_get_capability(name: str, uid_counter: Dict[str, int], 
                                 cache: Dict[str, int], subvertical_uid: int = None) -> int:
        """
        Create or get capability by name.
        
        Args:
            name: Capability name
            uid_counter: UID counter dictionary
            cache: Cache of name -> uid mappings
            subvertical_uid: Optional subvertical UID to link to
            
        Returns:
            Capability UID
        """
        if name in cache:
            return cache[name]
        
        svc = Neo4jQueryService()
        try:
            # Check if exists
            query = "MATCH (c:Capability {name: $name}) RETURN c.uid AS uid"
            result = svc.execute_cypher(query, {"name": name})
            
            if result:
                uid = result[0]["uid"]
                cache[name] = uid
                
                # Link to subvertical if provided and not already linked
                if subvertical_uid:
                    link_query = """
                    MATCH (c:Capability {uid: $cap_uid})
                    MATCH (sv:SubVertical {uid: $sv_uid})
                    MERGE (sv)-[:HAS_CAPABILITY]->(c)
                    """
                    svc.execute_cypher(link_query, {"cap_uid": uid, "sv_uid": subvertical_uid})
                
                return uid
            
            # Create new
            uid = uid_counter["capability"]
            
            if subvertical_uid:
                query = """
                MATCH (sv:SubVertical {uid: $sv_uid})
                CREATE (c:Capability {uid: $uid, name: $name, description: $description})
                CREATE (sv)-[:HAS_CAPABILITY]->(c)
                RETURN c.uid AS uid
                """
                svc.execute_cypher(query, {
                    "sv_uid": subvertical_uid,
                    "uid": uid,
                    "name": name,
                    "description": ""
                })
            else:
                query = """
                CREATE (c:Capability {uid: $uid, name: $name, description: $description})
                RETURN c.uid AS uid
                """
                svc.execute_cypher(query, {
                    "uid": uid,
                    "name": name,
                    "description": ""
                })
            
            cache[name] = uid
            uid_counter["capability"] += 1
            logger.info(f"Created capability: {name} (UID: {uid})")
            return uid
            
        finally:
            svc.close()
    
    @staticmethod
    def create_or_get_process(name: str, description: str, capability_uid: int,
                             uid_counter: Dict[str, int], cache: Dict[Tuple, int]) -> int:
        """
        Create or get process by name and capability.
        
        Args:
            name: Process name
            description: Process description
            capability_uid: Parent capability UID
            uid_counter: UID counter dictionary
            cache: Cache of (capability_uid, name) -> uid mappings
            
        Returns:
            Process UID
        """
        key = (capability_uid, name)
        if key in cache:
            return cache[key]
        
        svc = Neo4jQueryService()
        try:
            # Check if exists
            query = """
            MATCH (c:Capability {uid: $cap_uid})-[:REALIZED_BY]->(p:Process {name: $name})
            RETURN p.uid AS uid
            """
            result = svc.execute_cypher(query, {"cap_uid": capability_uid, "name": name})
            
            if result:
                uid = result[0]["uid"]
                cache[key] = uid
                return uid
            
            # Create new
            uid = uid_counter["process"]
            query = """
            MATCH (c:Capability {uid: $cap_uid})
            CREATE (p:Process {uid: $uid, name: $name, level: 1, 
                              description: $description, category: $category})
            CREATE (c)-[:REALIZED_BY]->(p)
            RETURN p.uid AS uid
            """
            svc.execute_cypher(query, {
                "cap_uid": capability_uid,
                "uid": uid,
                "name": name,
                "description": description,
                "category": None
            })
            
            cache[key] = uid
            uid_counter["process"] += 1
            logger.info(f"  Created process: {name} (UID: {uid})")
            return uid
            
        finally:
            svc.close()
    
    @staticmethod
    def create_or_get_subprocess(name: str, description: str, process_uid: int,
                                uid_counter: Dict[str, int], cache: Dict[Tuple, int]) -> int:
        """Create or get subprocess"""
        key = (process_uid, name)
        if key in cache:
            return cache[key]
        
        svc = Neo4jQueryService()
        try:
            query = """
            MATCH (p:Process {uid: $proc_uid})-[:DECOMPOSES]->(sp:Subprocess {name: $name})
            RETURN sp.uid AS uid
            """
            result = svc.execute_cypher(query, {"proc_uid": process_uid, "name": name})
            
            if result:
                uid = result[0]["uid"]
                cache[key] = uid
                return uid
            
            uid = uid_counter["subprocess"]
            query = """
            MATCH (p:Process {uid: $proc_uid})
            CREATE (sp:Subprocess {uid: $uid, name: $name, 
                                  description: $description, category: $category})
            CREATE (p)-[:DECOMPOSES]->(sp)
            RETURN sp.uid AS uid
            """
            svc.execute_cypher(query, {
                "proc_uid": process_uid,
                "uid": uid,
                "name": name,
                "description": description,
                "category": None
            })
            
            cache[key] = uid
            uid_counter["subprocess"] += 1
            logger.info(f"    Created subprocess: {name} (UID: {uid})")
            return uid
            
        finally:
            svc.close()
    
    @staticmethod
    def create_or_get_data_entity(name: str, description: str, subprocess_uid: int,
                                 uid_counter: Dict[str, int], cache: Dict[Tuple, int]) -> int:
        """Create or get data entity"""
        key = (subprocess_uid, name)
        if key in cache:
            return cache[key]
        
        svc = Neo4jQueryService()
        try:
            query = """
            MATCH (sp:Subprocess {uid: $sp_uid})-[:USES_DATA]->(de:DataEntity {name: $name})
            RETURN de.uid AS uid
            """
            result = svc.execute_cypher(query, {"sp_uid": subprocess_uid, "name": name})
            
            if result:
                uid = result[0]["uid"]
                cache[key] = uid
                return uid
            
            uid = uid_counter["data_entity"]
            query = """
            MATCH (sp:Subprocess {uid: $sp_uid})
            CREATE (de:DataEntity {uid: $uid, name: $name, 
                                  data_entity_description: $description})
            CREATE (sp)-[:USES_DATA]->(de)
            RETURN de.uid AS uid
            """
            svc.execute_cypher(query, {
                "sp_uid": subprocess_uid,
                "uid": uid,
                "name": name,
                "description": description
            })
            
            cache[key] = uid
            uid_counter["data_entity"] += 1
            logger.info(f"      Created data entity: {name} (UID: {uid})")
            return uid
            
        finally:
            svc.close()
    
    @staticmethod
    def create_or_get_data_element(name: str, description: str, data_entity_uid: int,
                                   uid_counter: Dict[str, int], cache: Dict[Tuple, int]) -> int:
        """Create or get data element"""
        key = (data_entity_uid, name)
        if key in cache:
            return cache[key]
        
        svc = Neo4jQueryService()
        try:
            query = """
            MATCH (de:DataEntity {uid: $de_uid})-[:HAS_ELEMENT]->(elem:DataElements {name: $name})
            RETURN elem.uid AS uid
            """
            result = svc.execute_cypher(query, {"de_uid": data_entity_uid, "name": name})
            
            if result:
                uid = result[0]["uid"]
                cache[key] = uid
                return uid
            
            uid = uid_counter["data_element"]
            query = """
            MATCH (de:DataEntity {uid: $de_uid})
            CREATE (elem:DataElements {uid: $uid, name: $name, 
                                       data_element_description: $description})
            CREATE (de)-[:HAS_ELEMENT]->(elem)
            RETURN elem.uid AS uid
            """
            svc.execute_cypher(query, {
                "de_uid": data_entity_uid,
                "uid": uid,
                "name": name,
                "description": description
            })
            
            cache[key] = uid
            uid_counter["data_element"] += 1
            return uid
            
        finally:
            svc.close()
    
    @staticmethod
    def create_or_get_org_unit(name: str, uid_counter: Dict[str, int], 
                              cache: Dict[str, int]) -> int:
        """Create or get organization unit"""
        if name in cache:
            return cache[name]
        
        svc = Neo4jQueryService()
        try:
            query = "MATCH (ou:OrganizationUnit {name: $name}) RETURN ou.uid AS uid"
            result = svc.execute_cypher(query, {"name": name})
            
            if result:
                uid = result[0]["uid"]
                cache[name] = uid
                return uid
            
            uid = uid_counter["org_unit"]
            query = """
            CREATE (ou:OrganizationUnit {uid: $uid, name: $name})
            RETURN ou.uid AS uid
            """
            svc.execute_cypher(query, {"uid": uid, "name": name})
            
            cache[name] = uid
            uid_counter["org_unit"] += 1
            return uid
            
        finally:
            svc.close()
    
    @staticmethod
    def create_or_get_application(name: str, uid_counter: Dict[str, int], 
                                 cache: Dict[str, int]) -> int:
        """Create or get application"""
        if name in cache:
            return cache[name]
        
        svc = Neo4jQueryService()
        try:
            query = "MATCH (app:ApplicationCatalog {name: $name}) RETURN app.uid AS uid"
            result = svc.execute_cypher(query, {"name": name})
            
            if result:
                uid = result[0]["uid"]
                cache[name] = uid
                return uid
            
            uid = uid_counter["application"]
            query = """
            CREATE (app:ApplicationCatalog {uid: $uid, name: $name})
            RETURN app.uid AS uid
            """
            svc.execute_cypher(query, {"uid": uid, "name": name})
            
            cache[name] = uid
            uid_counter["application"] += 1
            return uid
            
        finally:
            svc.close()
    
    @staticmethod
    def link_capability_to_org_unit(capability_uid: int, org_unit_uid: int):
        """Create ACCOUNTABLE relationship between capability and org unit"""
        svc = Neo4jQueryService()
        try:
            query = """
            MATCH (c:Capability {uid: $cap_uid})
            MATCH (ou:OrganizationUnit {uid: $ou_uid})
            MERGE (c)-[:ACCOUNTABLE]->(ou)
            """
            svc.execute_cypher(query, {"cap_uid": capability_uid, "ou_uid": org_unit_uid})
        finally:
            svc.close()
    
    @staticmethod
    def link_subprocess_to_application(subprocess_uid: int, application_uid: int):
        """Create SUPPORTED_BY relationship between subprocess and application"""
        svc = Neo4jQueryService()
        try:
            query = """
            MATCH (sp:Subprocess {uid: $sp_uid})
            MATCH (app:ApplicationCatalog {uid: $app_uid})
            MERGE (sp)-[:SUPPORTED_BY]->(app)
            """
            svc.execute_cypher(query, {"sp_uid": subprocess_uid, "app_uid": application_uid})
        finally:
            svc.close()
