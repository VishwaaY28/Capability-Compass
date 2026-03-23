from neo4j_graph.models import OrganizationUnit
from neo4j_graph.services.graphsubtree_service import GraphSubtreeService


class OrganizationUnitService:

    @staticmethod
    def get_subtree_by_id(org_unit_id, depth=None, direction='outgoing'):
        return GraphSubtreeService.get_subtree_by_property('OrganizationUnit', 'uid', org_unit_id, depth, direction)

    @staticmethod
    def get_subtree_by_name(org_unit_name, depth=None, direction='outgoing'):
        return GraphSubtreeService.get_subtree_by_property('OrganizationUnit', 'name', org_unit_name, depth, direction)

    @staticmethod
    def get_all_organization_units():
        return [{"uid": ou.uid, "name": ou.name} for ou in OrganizationUnit.nodes.all()]
