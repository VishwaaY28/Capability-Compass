"""
Optimized Batch CSV Import Service for Capability Compass

Uses batch operations and UNWIND for much faster imports.
"""
import csv
import io
import logging
from typing import Dict, List, Set, Tuple

from neo4j_graph.services.query_execution_service import Neo4jQueryService

logger = logging.getLogger(__name__)


class CSVBatchImportService:
    """Optimized batch import service for CSV data"""
    
    @staticmethod
    def import_csv_batch(csv_text: str, clear_existing: bool = False) -> dict:
        """
        Import CSV using optimized batch operations.
        
        Args:
            csv_text: CSV content as string
            clear_existing: Whether to clear existing data first
            
        Returns:
            Dictionary with import statistics
        """
        stats = {
            "verticals_created": 0,
            "subverticals_created": 0,
            "capabilities_created": 0,
            "processes_created": 0,
            "subprocesses_created": 0,
            "data_entities_created": 0,
            "data_elements_created": 0,
            "organization_units_created": 0,
            "applications_created": 0,
            "rows_processed": 0
        }
        
        try:
            # Clear if requested
            if clear_existing:
                svc = Neo4jQueryService()
                try:
                    svc.execute_cypher("MATCH (n) DETACH DELETE n")
                    logger.info("Cleared all existing data")
                finally:
                    svc.close()
            
            # Parse CSV
            csv_reader = csv.DictReader(io.StringIO(csv_text))
            rows = list(csv_reader)
            stats["rows_processed"] = len(rows)
            
            logger.info(f"Processing {len(rows)} rows in batch mode...")
            
            # Collect unique entities
            verticals = set()
            subverticals = set()  # (vertical, subvertical)
            capabilities = set()  # (capability, subvertical)
            processes = set()  # (capability, process, desc)
            subprocesses = set()  # (process, subprocess, desc)
            data_entities = set()  # (subprocess, entity, desc)
            data_elements = set()  # (entity, element, desc)
            org_units = set()
            applications = set()
            
            # Relationships to create
            cap_org_links = set()  # (capability, org_unit)
            subprocess_app_links = set()  # (subprocess, application)
            
            for row in rows:
                vertical = row.get("Vertical", "").strip()
                subvertical = row.get("Sub Vertical", "").strip()
                capability = row.get("Capability Name", "").strip()
                process = row.get("Process", "").strip()
                process_desc = row.get("Process Description", "").strip()
                subprocess = row.get("Sub Process", "").strip()
                subprocess_desc = row.get("Sub-Process Description", "").strip()
                data_entity = row.get("Data Entity", "").strip()
                data_entity_desc = row.get("Data Entity Description", "").strip()
                data_element = row.get("Data Element", "").strip()
                data_element_desc = row.get("Data Element Description", "").strip()
                org_units_str = row.get("Organization Units", "").strip()
                apps_str = row.get("Applications", "").strip()
                
                if not capability:
                    continue
                
                if vertical:
                    verticals.add(vertical)
                if subvertical and vertical:
                    subverticals.add((vertical, subvertical))
                
                capabilities.add((capability, subvertical if subvertical else ""))
                
                if process:
                    processes.add((capability, process, process_desc))
                if subprocess and process:
                    subprocesses.add((process, subprocess, subprocess_desc))
                if data_entity and subprocess:
                    data_entities.add((subprocess, data_entity, data_entity_desc))
                if data_element and data_entity:
                    data_elements.add((data_entity, data_element, data_element_desc))
                
                # Organization units
                if org_units_str:
                    for ou in org_units_str.split(','):
                        ou = ou.strip()
                        if ou:
                            org_units.add(ou)
                            cap_org_links.add((capability, ou))
                
                # Applications
                if apps_str and subprocess:
                    for app in apps_str.split(','):
                        app = app.strip()
                        if app:
                            applications.add(app)
                            subprocess_app_links.add((subprocess, app))
            
            # Import in batches
            svc = Neo4jQueryService()
            try:
                # CRITICAL: fetch the next-available UID per label BEFORE any
                # batch insert so newly-created nodes never collide with
                # pre-existing ones. Without this, a delete-by-UID later
                # would also wipe unrelated nodes that happened to share
                # the same UID, and "max(uid)" reasoning downstream breaks.
                from neo4j_graph.services.csv_import_service import CSVImportService
                uid_counters = CSVImportService.get_max_uids()

                # 1. Create Verticals
                if verticals:
                    stats["verticals_created"] = CSVBatchImportService._batch_create_verticals(
                        svc, list(verticals), uid_counters["vertical"]
                    )
                
                # 2. Create SubVerticals
                if subverticals:
                    stats["subverticals_created"] = CSVBatchImportService._batch_create_subverticals(
                        svc, list(subverticals), uid_counters["subvertical"]
                    )
                
                # 3. Create Capabilities
                if capabilities:
                    stats["capabilities_created"] = CSVBatchImportService._batch_create_capabilities(
                        svc, list(capabilities), uid_counters["capability"]
                    )
                
                # 4. Create Processes
                if processes:
                    stats["processes_created"] = CSVBatchImportService._batch_create_processes(
                        svc, list(processes), uid_counters["process"]
                    )
                
                # 5. Create Subprocesses
                if subprocesses:
                    stats["subprocesses_created"] = CSVBatchImportService._batch_create_subprocesses(
                        svc, list(subprocesses), uid_counters["subprocess"]
                    )
                
                # 6. Create Data Entities
                if data_entities:
                    stats["data_entities_created"] = CSVBatchImportService._batch_create_data_entities(
                        svc, list(data_entities), uid_counters["data_entity"]
                    )
                
                # 7. Create Data Elements
                if data_elements:
                    stats["data_elements_created"] = CSVBatchImportService._batch_create_data_elements(
                        svc, list(data_elements), uid_counters["data_element"]
                    )
                
                # 8. Create Organization Units
                if org_units:
                    stats["organization_units_created"] = CSVBatchImportService._batch_create_org_units(
                        svc, list(org_units), uid_counters["org_unit"]
                    )
                
                # 9. Create Applications
                if applications:
                    stats["applications_created"] = CSVBatchImportService._batch_create_applications(
                        svc, list(applications), uid_counters["application"]
                    )
                
                # 10. Create Capability-OrgUnit links
                if cap_org_links:
                    CSVBatchImportService._batch_link_capability_org_units(
                        svc, list(cap_org_links)
                    )
                
                # 11. Create Subprocess-Application links
                if subprocess_app_links:
                    CSVBatchImportService._batch_link_subprocess_applications(
                        svc, list(subprocess_app_links)
                    )
                
            finally:
                svc.close()
            
            logger.info(f"Batch import completed: {stats}")
            return stats
            
        except Exception as e:
            logger.error(f"Batch import failed: {e}", exc_info=True)
            raise
    
    # ------------------------------------------------------------------
    # NOTE on UIDs:
    # Each `_batch_create_*` accepts a `start_uid` (provided by the caller
    # from `CSVImportService.get_max_uids()`). The Cypher uses
    # `ON CREATE SET n.uid = item.uid` so the UID is only consumed for
    # *newly* created nodes — pre-existing nodes keep their original UID
    # (since MERGE matches them by name). Using `start_uid + idx` instead
    # of `idx + 1` is critical: it prevents collisions with UIDs already
    # in the graph, which previously caused `MATCH (n {uid:$uid})
    # DETACH DELETE n` to remove unrelated nodes that happened to share a
    # UID with the deletion target.
    # ------------------------------------------------------------------

    @staticmethod
    def _batch_create_verticals(
        svc: Neo4jQueryService, verticals: List[str], start_uid: int = 1
    ) -> int:
        """Batch create verticals (idempotent on name)."""
        query = """
        UNWIND $items AS item
        MERGE (v:Vertical {name: item.name})
        ON CREATE SET v.uid = item.uid, v.__newly_created = true
        WITH v
        WHERE v.__newly_created = true
        REMOVE v.__newly_created
        RETURN count(v) AS created
        """
        items = [{"name": v, "uid": start_uid + idx} for idx, v in enumerate(verticals)]
        result = svc.execute_cypher(query, {"items": items})
        count = result[0]["created"] if result else 0
        logger.info(f"Created {count} new verticals (uids starting at {start_uid})")
        return count

    @staticmethod
    def _batch_create_subverticals(
        svc: Neo4jQueryService,
        subverticals: List[Tuple[str, str]],
        start_uid: int = 1,
    ) -> int:
        """Batch create subverticals (idempotent on name)."""
        query = """
        UNWIND $items AS item
        MATCH (v:Vertical {name: item.vertical})
        MERGE (sv:SubVertical {name: item.name})
        ON CREATE SET sv.uid = item.uid, sv.__newly_created = true
        MERGE (v)-[:HAS_SUBVERTICAL]->(sv)
        WITH sv
        WHERE sv.__newly_created = true
        REMOVE sv.__newly_created
        RETURN count(sv) AS created
        """
        items = [
            {"vertical": v, "name": sv, "uid": start_uid + idx}
            for idx, (v, sv) in enumerate(subverticals)
        ]
        result = svc.execute_cypher(query, {"items": items})
        count = result[0]["created"] if result else 0
        logger.info(f"Created {count} new subverticals (uids starting at {start_uid})")
        return count

    @staticmethod
    def _batch_create_capabilities(
        svc: Neo4jQueryService,
        capabilities: List[Tuple[str, str]],
        start_uid: int = 1,
    ) -> int:
        """Batch create capabilities (idempotent on name)."""
        query = """
        UNWIND $items AS item
        MERGE (c:Capability {name: item.name})
        ON CREATE SET c.uid = item.uid, c.description = '', c.__newly_created = true
        WITH c, item
        OPTIONAL MATCH (sv:SubVertical {name: item.subvertical})
        FOREACH (_ IN CASE WHEN sv IS NULL OR item.subvertical = '' THEN [] ELSE [1] END |
            MERGE (sv)-[:HAS_CAPABILITY]->(c)
        )
        WITH c
        WHERE c.__newly_created = true
        REMOVE c.__newly_created
        RETURN count(c) AS created
        """
        items = [
            {"name": cap, "subvertical": sv, "uid": start_uid + idx}
            for idx, (cap, sv) in enumerate(capabilities)
        ]
        result = svc.execute_cypher(query, {"items": items})
        count = result[0]["created"] if result else 0
        logger.info(f"Created {count} new capabilities (uids starting at {start_uid})")
        return count

    @staticmethod
    def _batch_create_processes(
        svc: Neo4jQueryService,
        processes: List[Tuple[str, str, str]],
        start_uid: int = 1,
    ) -> int:
        """Batch create processes (idempotent on name)."""
        query = """
        UNWIND $items AS item
        MATCH (c:Capability {name: item.capability})
        MERGE (p:Process {name: item.name})
        ON CREATE SET p.uid = item.uid, p.level = 1, p.description = item.description,
                      p.category = null, p.__newly_created = true
        MERGE (c)-[:REALIZED_BY]->(p)
        WITH p
        WHERE p.__newly_created = true
        REMOVE p.__newly_created
        RETURN count(p) AS created
        """
        items = [
            {"capability": cap, "name": proc, "description": desc, "uid": start_uid + idx}
            for idx, (cap, proc, desc) in enumerate(processes)
        ]
        result = svc.execute_cypher(query, {"items": items})
        count = result[0]["created"] if result else 0
        logger.info(f"Created {count} new processes (uids starting at {start_uid})")
        return count

    @staticmethod
    def _batch_create_subprocesses(
        svc: Neo4jQueryService,
        subprocesses: List[Tuple[str, str, str]],
        start_uid: int = 1,
    ) -> int:
        """Batch create subprocesses (idempotent on name)."""
        query = """
        UNWIND $items AS item
        MATCH (p:Process {name: item.process})
        MERGE (sp:Subprocess {name: item.name})
        ON CREATE SET sp.uid = item.uid, sp.description = item.description,
                      sp.category = null, sp.__newly_created = true
        MERGE (p)-[:DECOMPOSES]->(sp)
        WITH sp
        WHERE sp.__newly_created = true
        REMOVE sp.__newly_created
        RETURN count(sp) AS created
        """
        items = [
            {"process": proc, "name": subproc, "description": desc, "uid": start_uid + idx}
            for idx, (proc, subproc, desc) in enumerate(subprocesses)
        ]
        result = svc.execute_cypher(query, {"items": items})
        count = result[0]["created"] if result else 0
        logger.info(f"Created {count} new subprocesses (uids starting at {start_uid})")
        return count

    @staticmethod
    def _batch_create_data_entities(
        svc: Neo4jQueryService,
        data_entities: List[Tuple[str, str, str]],
        start_uid: int = 1,
    ) -> int:
        """Batch create data entities (idempotent on name)."""
        query = """
        UNWIND $items AS item
        MATCH (sp:Subprocess {name: item.subprocess})
        MERGE (de:DataEntity {name: item.name})
        ON CREATE SET de.uid = item.uid, de.data_entity_description = item.description,
                      de.__newly_created = true
        MERGE (sp)-[:USES_DATA]->(de)
        WITH de
        WHERE de.__newly_created = true
        REMOVE de.__newly_created
        RETURN count(de) AS created
        """
        items = [
            {"subprocess": subproc, "name": entity, "description": desc, "uid": start_uid + idx}
            for idx, (subproc, entity, desc) in enumerate(data_entities)
        ]
        result = svc.execute_cypher(query, {"items": items})
        count = result[0]["created"] if result else 0
        logger.info(f"Created {count} new data entities (uids starting at {start_uid})")
        return count

    @staticmethod
    def _batch_create_data_elements(
        svc: Neo4jQueryService,
        data_elements: List[Tuple[str, str, str]],
        start_uid: int = 1,
    ) -> int:
        """Batch create data elements (idempotent on name)."""
        query = """
        UNWIND $items AS item
        MATCH (de:DataEntity {name: item.entity})
        MERGE (elem:DataElements {name: item.name})
        ON CREATE SET elem.uid = item.uid, elem.data_element_description = item.description,
                      elem.__newly_created = true
        MERGE (de)-[:HAS_ELEMENT]->(elem)
        WITH elem
        WHERE elem.__newly_created = true
        REMOVE elem.__newly_created
        RETURN count(elem) AS created
        """
        items = [
            {"entity": entity, "name": element, "description": desc, "uid": start_uid + idx}
            for idx, (entity, element, desc) in enumerate(data_elements)
        ]
        result = svc.execute_cypher(query, {"items": items})
        count = result[0]["created"] if result else 0
        logger.info(f"Created {count} new data elements (uids starting at {start_uid})")
        return count

    @staticmethod
    def _batch_create_org_units(
        svc: Neo4jQueryService, org_units: List[str], start_uid: int = 1
    ) -> int:
        """Batch create organization units (idempotent on name)."""
        query = """
        UNWIND $items AS item
        MERGE (ou:OrganizationUnit {name: item.name})
        ON CREATE SET ou.uid = item.uid, ou.__newly_created = true
        WITH ou
        WHERE ou.__newly_created = true
        REMOVE ou.__newly_created
        RETURN count(ou) AS created
        """
        items = [{"name": ou, "uid": start_uid + idx} for idx, ou in enumerate(org_units)]
        result = svc.execute_cypher(query, {"items": items})
        count = result[0]["created"] if result else 0
        logger.info(f"Created {count} new organization units (uids starting at {start_uid})")
        return count

    @staticmethod
    def _batch_create_applications(
        svc: Neo4jQueryService, applications: List[str], start_uid: int = 1
    ) -> int:
        """Batch create applications (idempotent on name)."""
        query = """
        UNWIND $items AS item
        MERGE (app:ApplicationCatalog {name: item.name})
        ON CREATE SET app.uid = item.uid, app.__newly_created = true
        WITH app
        WHERE app.__newly_created = true
        REMOVE app.__newly_created
        RETURN count(app) AS created
        """
        items = [{"name": app, "uid": start_uid + idx} for idx, app in enumerate(applications)]
        result = svc.execute_cypher(query, {"items": items})
        count = result[0]["created"] if result else 0
        logger.info(f"Created {count} new applications (uids starting at {start_uid})")
        return count
    
    @staticmethod
    def _batch_link_capability_org_units(svc: Neo4jQueryService, links: List[Tuple[str, str]]):
        """Batch create capability-org unit relationships"""
        query = """
        UNWIND $items AS item
        MATCH (c:Capability {name: item.capability})
        MATCH (ou:OrganizationUnit {name: item.org_unit})
        MERGE (c)-[:ACCOUNTABLE]->(ou)
        """
        items = [
            {"capability": cap, "org_unit": ou}
            for cap, ou in links
        ]
        svc.execute_cypher(query, {"items": items})
        logger.info(f"Created {len(links)} capability-org unit links")
    
    @staticmethod
    def _batch_link_subprocess_applications(svc: Neo4jQueryService, links: List[Tuple[str, str]]):
        """Batch create subprocess-application relationships"""
        query = """
        UNWIND $items AS item
        MATCH (sp:Subprocess {name: item.subprocess})
        MATCH (app:ApplicationCatalog {name: item.application})
        MERGE (sp)-[:SUPPORTED_BY]->(app)
        """
        items = [
            {"subprocess": subproc, "application": app}
            for subproc, app in links
        ]
        svc.execute_cypher(query, {"items": items})
        logger.info(f"Created {len(links)} subprocess-application links")
