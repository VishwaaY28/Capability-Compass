from neo4j_graph.models import ApplicationCatalog
from neo4j_graph.services.graphsubtree_service import GraphSubtreeService


class ApplicationCatalogService:

    @staticmethod
    def get_subtree_by_id(app_catalog_id, depth=None, direction='outgoing'):
        return GraphSubtreeService.get_subtree_by_property('ApplicationCatalog', 'uid', app_catalog_id, depth, direction)

    @staticmethod
    def get_subtree_by_name(app_catalog_name, depth=None, direction='outgoing'):
        return GraphSubtreeService.get_subtree_by_property('ApplicationCatalog', 'name', app_catalog_name, depth, direction)

    @staticmethod
    def get_all_application_catalogs():
        return [{"uid": ac.uid, "name": ac.name} for ac in ApplicationCatalog.nodes.all()]
